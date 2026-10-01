"""The whole setup and asking flow, through a real MCP client, against the stand-in Signature."""

import io
import json
import os
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp_types import ElicitRequestParams, ElicitRequestURLParams, ElicitResult

from signature_plugin import show_answer
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
        [question] = built['open_questions']
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
        assert 'cannot see it' in asked['note']
        assert 'paid' not in json.dumps(asked)

    hook_input = {'tool_input': {'question': 'What did each status bring in?'}, 'tool_response': json.dumps(asked)}
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(hook_input)))
    shown = io.StringIO()
    monkeypatch.setattr('sys.stdout', shown)
    show_answer.main()
    message = json.loads(shown.getvalue())['systemMessage']
    assert 'total amount per order status' in message
    assert 'paid     │ 1700' in message
    assert 'refunded │ 500' in message


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
        ] == 'shown'

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
