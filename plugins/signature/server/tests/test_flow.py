"""The whole setup and asking flow, through a real MCP client, against the stand-in Signature."""

import json
import os
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp_types import ElicitRequestFormParams, ElicitRequestParams, ElicitRequestURLParams, ElicitResult

from signature_plugin.fake_backend import FakeSignature
from signature_plugin.server import server

pytestmark = pytest.mark.anyio


async def called(client: Client, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    with anyio.fail_after(30):
        result = await client.call_tool(tool, arguments or {})
    assert not result.is_error, result.content
    return result.structured_content.get('result', result.structured_content) if result.structured_content else None


async def submitted(opened: list[str], form: dict[str, str]) -> httpx2.Response:
    """The decision the page the plugin opened last sends back, once it has opened one."""
    with anyio.fail_after(30):
        while not opened:
            await anyio.sleep(0.02)
    async with httpx2.AsyncClient() as browser:
        return await browser.post(f'{opened[-1]}/decision', json=form)


async def called_through_page(client: Client, tool: str, opened: list[str], *forms: dict[str, str]) -> Any:
    """The tool's result, while each form is submitted in turn to the page the tool opens."""

    async def submit_each() -> None:
        for form in forms:
            await submitted(opened, form)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(submit_each)
        return await called(client, tool)


async def test_setup_from_files_and_documents_to_published_answers(
    plugin_environment: FakeSignature,
    opened_pages: list[str],
    data_files: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = tmp_path / 'refund-policy.md'
    policy.write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    glossary = tmp_path / 'glossary.md'
    glossary.write_text('Revenue includes refunded orders.', encoding='utf-8')

    async with Client(server, raise_exceptions=True) as client:
        status = await called(client, 'get_status')
        assert status['domain'] == 'Demo domain'
        assert status['sources'] == []

        added = await called(client, 'add_data_files', {'paths': [str(data_files)]})
        assert {entry['source'] for entry in added} == {'orders', 'customers', 'products'}

        built = await called(client, 'build', {'documents': [str(policy), str(glossary)], 'note': 'Amounts are cents.'})
        assert built['state'] == 'questions'
        question, _ = built['open_questions']
        assert 'define the same term differently' in question['question']
        assert plugin_environment.table_names() == {'orders', 'customers', 'products'}
        assert sorted(plugin_environment.documents.values()) == ['glossary.md', 'refund-policy.md']

        answered = await called(
            client,
            'answer_questions',
            {
                'answers': [
                    {
                        'question': question['number'],
                        'answer': 'The refund policy is right.',
                        'from_customer': True,
                    },
                ]
            },
        )
        assert answered['state'] == 'built'

        reviewed = await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
        assert reviewed['state'] == 'published'
        assert 'can now ask questions' in reviewed['note']
        assert plugin_environment.published_at is not None

        asked = await called(client, 'ask_question', {'question': 'What did each status bring in?'})
    assert asked['state'] == 'answered' and asked['reading'] == 'total amount per order status'
    assert sorted(asked['rows']) == [['paid', 1700], ['refunded', 500]]
    assert asked['row_count'] == 2 and not asked['truncated']


async def test_a_change_asked_for_in_review_is_built(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        await called(client, 'build')
        reviewed = await called_through_page(
            client,
            'review',
            opened_pages,
            {'decision': 'change', 'changes': ''},
            {'decision': 'change', 'changes': 'Amounts are in cents.'},
        )
    assert reviewed['state'] == 'changes_requested'
    assert reviewed['build']['state'] == 'built'
    assert plugin_environment.published_at is None


async def test_building_with_nothing_is_refused(plugin_environment: FakeSignature) -> None:
    async with Client(server) as client:
        result = await client.call_tool('build', {})
    assert result.is_error
    assert 'nothing to build from' in str(result.content)


async def test_a_database_that_will_not_connect_keeps_the_page_open(
    plugin_environment: FakeSignature, opened_pages: list[str]
) -> None:
    async with Client(server, raise_exceptions=True) as client, anyio.create_task_group() as tasks:
        tasks.start_soon(called, client, 'connect_database')
        refused = await submitted(
            opened_pages,
            {
                'engine': 'postgres',
                'name': 'sales',
                'host': '127.0.0.1',
                'port': '1',
                'database': 'x',
                'user': 'x',
                'password': 'x',
            },
        )
        assert refused.status_code == 422
        assert 'could not be opened' in refused.text
        tasks.cancel_scope.cancel()
    async with Client(server, raise_exceptions=True) as client:
        assert (await called(client, 'get_status'))['sources'] == []


DATABASES = [
    pytest.param('postgres', 'SIGNATURE_TEST_POSTGRES', '"sales_db"."public"."orders"', id='postgres'),
    pytest.param('mysql', 'SIGNATURE_TEST_MYSQL', '"sales_db"."shop"."products"', id='mysql'),
]


@pytest.mark.parametrize(('engine', 'variable', 'expected_table'), DATABASES)
async def test_a_database_connected_in_the_browser_is_reported(
    plugin_environment: FakeSignature, opened_pages: list[str], engine: str, variable: str, expected_table: str
) -> None:
    """Set SIGNATURE_TEST_POSTGRES or SIGNATURE_TEST_MYSQL to host:port:database:user:password to run."""
    if variable not in os.environ:
        pytest.skip(f'{variable} is not set')
    host, port, database, user, password = os.environ[variable].split(':')
    async with Client(server, raise_exceptions=True) as client:
        login = {
            'engine': engine,
            'name': 'Sales DB',
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password,
        }
        connected = await called_through_page(client, 'connect_database', opened_pages, login)
        assert connected['source'] == 'sales_db'
        assert password not in json.dumps(await called(client, 'get_status'))
        await called(client, 'build')
    assert expected_table in {plugin_environment.sql_name(table) for table in plugin_environment.tables()}


async def test_a_client_that_shows_links_is_asked_to_open_the_review(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    links: list[str] = []

    async def accept(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestURLParams)
        links.append(params.url)
        return ElicitResult(action='accept')

    async with Client(server, raise_exceptions=True, elicitation_callback=accept) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        await called(client, 'build')
        reviewed = await called_through_page(client, 'review', links, {'decision': 'publish'})
    assert reviewed['state'] == 'published'
    assert opened_pages == []


async def test_a_declined_link_is_reported_not_opened(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    async def decline(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action='decline')

    async with Client(server, raise_exceptions=True, elicitation_callback=decline) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        await called(client, 'build')
        reviewed = await called(client, 'review')
    assert reviewed['state'] == 'declined'
    assert opened_pages == []


@pytest.mark.parametrize(
    ('tool', 'arguments', 'told'),
    [
        (
            'answer_questions',
            {'answers': [{'question': 9, 'answer': 'x', 'from_customer': True}]},
            'no open question 9',
        ),
        ('wait_for_build', {}, 'Call build first'),
        ('ask_question', {'question': 'And last year?', 'follow_up': True}, 'no earlier question'),
        ('add_data_files', {'paths': ['/nowhere/orders.csv']}, 'does not exist'),
        ('remove_source', {'name': 'sales'}, 'no source called sales'),
    ],
)
async def test_a_mistake_is_told_with_what_to_do(
    plugin_environment: FakeSignature, tool: str, arguments: dict[str, Any], told: str
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert told in str(result.content)


async def test_a_question_after_the_sources_change_shape_asks_for_a_rebuild(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    orders = data_files / 'orders.csv'
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(orders)]})
        await called(client, 'build')
        await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
        assert (await called(client, 'ask_question', {'question': 'What did each status bring in?'}))[
            'state'
        ] == 'answered'

        orders.write_text('id,customer_id,state,amount_cents\n1,1,paid,1000\n', encoding='utf-8')
        asked = await called(client, 'ask_question', {'question': 'How many orders are there?'})

    assert asked['state'] == 'stale'
    assert 'Call build' in asked['note']


async def test_a_domain_that_cannot_get_ready_for_questions_is_said_to_be_published_but_not_ready(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    plugin_environment.preparation_failure = 'the link of your Domain to the tables stayed invalid'
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files)]})
        await called(client, 'build', {'note': 'Amounts are cents.'})
        reviewed = await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
    assert reviewed['state'] == 'published'
    assert 'could not get ready' in reviewed['note'] and 'stayed invalid' in reviewed['note']


async def test_an_answer_is_shown_under_the_column_names_signature_gives(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files)]})
        await called(client, 'build', {'note': 'Amounts are cents.'})
        await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
        asked = await called(client, 'ask_question', {'question': 'What did each status bring in?'})
    assert asked['columns'] == ['order status', 'amount brought in']


async def test_a_question_signature_cannot_prove_an_answer_to_is_told_with_why_and_nothing_runs(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files)]})
        await called(client, 'build', {'note': 'Amounts are cents.'})
        await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
        asked = await called(client, 'ask_question', {'question': 'Which customers are loyal?'})
    assert asked['state'] == 'unproven' and 'refuted' in (asked['reason'] or '') and asked['rows'] == []


async def test_a_build_leaves_how_it_ended_for_the_hooks(
    plugin_environment: FakeSignature, data_files: Path, tmp_path: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        with anyio.fail_after(30):
            result = await client.call_tool('build', {})
    assert result.structured_content is not None and result.structured_content['state'] == 'built'
    board = json.loads((tmp_path / 'plugin-data' / 'activity.json').read_text(encoding='utf-8'))
    assert board['state'] == 'built'


async def test_a_build_with_nothing_new_to_hand_over_rebuilds_from_the_data(
    plugin_environment: FakeSignature, data_files: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        built = await called(client, 'build')
    assert built['state'] == 'built'


async def test_a_failed_build_says_why_in_terms_claude_can_act_on(
    plugin_environment: FakeSignature, data_files: Path
) -> None:
    plugin_environment.build_failure = 'temporarilyUnavailable'
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        built = await called(client, 'build')
    assert built['state'] == 'failed'
    assert 'briefly unavailable' in built['note']


async def test_a_question_leaves_that_it_is_over_for_the_hooks(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path, tmp_path: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files)]})
        await called(client, 'build', {'note': 'Amounts are cents.'})
        await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
        with anyio.fail_after(30):
            result = await client.call_tool('ask_question', {'question': 'What did each status bring in?'})
    assert result.structured_content is not None and result.structured_content['state'] == 'answered'
    board = json.loads((tmp_path / 'plugin-data' / 'activity.json').read_text(encoding='utf-8'))
    assert board['state'] == 'asked'


async def test_a_build_that_only_replies_is_not_taken_for_a_built_domain(
    plugin_environment: FakeSignature, data_files: Path
) -> None:
    plugin_environment.builds_only_reply = True
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        built = await called(client, 'build')
    assert built['state'] == 'replied'
    assert built['reply'] == 'Shall I go ahead and build it?'
    assert 'Do not call review' in built['note']


async def test_every_open_question_can_be_answered_at_once(
    plugin_environment: FakeSignature, data_files: Path, tmp_path: Path
) -> None:
    policy = tmp_path / 'refund-policy.md'
    policy.write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    glossary = tmp_path / 'glossary.md'
    glossary.write_text('Revenue includes refunded orders.', encoding='utf-8')
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files)]})
        built = await called(client, 'build', {'documents': [str(policy), str(glossary)]})
        assert len(built['open_questions']) == 2
        answers = [
            {'question': question['number'], 'answer': 'The refund policy is right.', 'from_customer': True}
            for question in built['open_questions']
        ]
        answered = await called(client, 'answer_questions', {'answers': answers})
    assert answered['state'] == 'built'


async def test_a_publication_with_no_query_package_is_not_called_ready(
    plugin_environment: FakeSignature, opened_pages: list[str], tmp_path: Path
) -> None:
    policy = tmp_path / 'refund-policy.md'
    policy.write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'build', {'documents': [str(policy)]})
        reviewed = await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
    assert reviewed['state'] == 'published'
    assert 'nothing to answer questions from' in reviewed['note']


async def test_a_build_outlasts_a_server_too_busy_to_answer_a_few_polls(
    plugin_environment: FakeSignature, data_files: Path
) -> None:
    plugin_environment.busy_polls = 3
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        built = await called(client, 'build')
    assert built['state'] == 'built'


async def test_a_database_named_in_a_file_that_will_not_connect_says_why_without_its_password(
    plugin_environment: FakeSignature, tmp_path: Path
) -> None:
    connection = tmp_path / 'sales.conn'
    connection.write_text('postgresql://sales:s3cret-pass@127.0.0.1:1/sales\n', encoding='utf-8')
    async with Client(server) as client:
        result = await client.call_tool('connect_database', {'connection_file': str(connection)})
        assert result.is_error
        assert 'could not be opened' in str(result.content)
        assert 's3cret-pass' not in str(result.content)
        assert (await called(client, 'get_status'))['sources'] == []


async def test_a_file_that_holds_no_database_url_is_refused(plugin_environment: FakeSignature, tmp_path: Path) -> None:
    connection = tmp_path / 'notes.txt'
    connection.write_text('host is the usual one, password on the wiki', encoding='utf-8')
    async with Client(server) as client:
        result = await client.call_tool('connect_database', {'connection_file': str(connection)})
    assert result.is_error
    assert 'does not hold a database URL' in str(result.content)


@pytest.mark.parametrize(('engine', 'variable', 'expected_table'), DATABASES)
async def test_a_database_named_in_a_file_is_connected_and_reported(
    plugin_environment: FakeSignature, tmp_path: Path, engine: str, variable: str, expected_table: str
) -> None:
    """Set SIGNATURE_TEST_POSTGRES or SIGNATURE_TEST_MYSQL to host:port:database:user:password to run."""
    if variable not in os.environ:
        pytest.skip(f'{variable} is not set')
    host, port, database, user, password = os.environ[variable].split(':')
    connection = tmp_path / 'sales.conn'
    scheme = 'postgresql' if engine == 'postgres' else 'mysql'
    connection.write_text(f'{scheme}://{user}:{password}@{host}:{port}/{database}', encoding='utf-8')
    async with Client(server, raise_exceptions=True) as client:
        connected = await called(
            client, 'connect_database', {'connection_file': str(connection), 'suggested_name': 'Sales DB'}
        )
        assert connected['source'] == 'sales_db'
        assert password not in json.dumps(await called(client, 'get_status'))
        await called(client, 'build')
    assert expected_table in {plugin_environment.sql_name(table) for table in plugin_environment.tables()}


async def test_documents_explaining_the_data_are_handed_over_apart_from_those_explaining_the_business(
    plugin_environment: FakeSignature, data_files: Path, tmp_path: Path
) -> None:
    policy = tmp_path / 'refund-policy.md'
    policy.write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    dictionary = tmp_path / 'data-dictionary.md'
    dictionary.write_text('orders.amount is the order total, in cents.', encoding='utf-8')

    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files)]})
        await called(client, 'build', {'documents': [str(policy)], 'data_documents': [str(dictionary)]})

    assert plugin_environment.document_kinds == {'refund-policy.md': 'notes', 'data-dictionary.md': 'data'}


# What a filled-in form returns, as ElicitResult's content takes it.
type FormAnswer = dict[str, str | int | float | bool | list[str] | None]


def answering(*answers: FormAnswer | None) -> tuple[list[str], Any]:
    """The messages of the forms set_up shows, and a client callback filling each in turn with the next answer:
    None declines it."""
    shown: list[str] = []
    remaining = list(answers)

    async def fill(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        shown.append(params.message)
        answer = remaining.pop(0)
        return ElicitResult(action='decline') if answer is None else ElicitResult(action='accept', content=answer)

    return shown, fill


async def test_set_up_asks_for_each_part_in_turn_then_builds(
    plugin_environment: FakeSignature, data_files: Path, tmp_path: Path
) -> None:
    business = tmp_path / 'business'
    (business / 'src').mkdir(parents=True)
    (business / 'refund-policy.pdf').write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    (business / 'src' / 'refund-policy.md').write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    dictionary = tmp_path / 'data-dictionary.md'
    dictionary.write_text('orders.amount is the order total, in cents.', encoding='utf-8')
    shown, fill = answering(
        {'paths': str(business)}, {'paths': str(data_files / 'orders.csv')}, {'paths': str(dictionary)}, {}
    )

    async with Client(server, raise_exceptions=True, elicitation_callback=fill) as client:
        built = await called(client, 'set_up')

    assert built['state'] == 'questions'  # the stand-in asks whether two documents agree
    asked = ['explain your business', 'Where is your data', 'tables and columns', 'Is that everything']
    assert all(part in message for part, message in zip(asked, shown, strict=True))
    assert '1 document about your business, your data (orders) and 1 document explaining it' in shown[3]
    assert plugin_environment.document_kinds == {'refund-policy.pdf': 'notes', 'data-dictionary.md': 'data'}


async def test_set_up_asks_again_saying_why_when_a_path_holds_nothing(
    plugin_environment: FakeSignature, data_files: Path, tmp_path: Path
) -> None:
    policy = tmp_path / 'refund-policy.md'
    policy.write_text('Refunded orders do not count as revenue.', encoding='utf-8')
    shown, fill = answering(
        {'paths': str(tmp_path / 'nowhere')}, {'paths': str(policy)}, {'paths': str(data_files)}, {'paths': ''}, {}
    )

    async with Client(server, raise_exceptions=True, elicitation_callback=fill) as client:
        built = await called(client, 'set_up')

    assert built['state'] == 'built'
    assert shown[1].startswith(f'There is nothing at {tmp_path / "nowhere"}.')
    assert 'Which documents explain your business' in shown[1]


async def test_set_up_stops_when_the_customer_declines(plugin_environment: FakeSignature) -> None:
    _, fill = answering(None)
    async with Client(server, raise_exceptions=True, elicitation_callback=fill) as client:
        stopped = await called(client, 'set_up')
    assert stopped['state'] == 'declined'
    assert plugin_environment.document_kinds == {}


async def test_a_question_asked_while_signature_gets_ready_waits_for_it(
    plugin_environment: FakeSignature, opened_pages: list[str], data_files: Path
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await called(client, 'add_data_files', {'paths': [str(data_files / 'orders.csv')]})
        await called(client, 'build')
        await called_through_page(client, 'review', opened_pages, {'decision': 'publish'})
        plugin_environment.preparing_polls = 2
        asked = await called(client, 'ask_question', {'question': 'Which orders are there?'})
    assert asked['state'] == 'answered'
    assert plugin_environment.preparing_polls == 0
