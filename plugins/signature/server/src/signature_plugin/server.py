"""Signature's MCP server, run by Claude Code on the customer's machine. Its tools take a domain from sources
and documents to published, and answer questions about it by running Signature's SQL here, on the customer's
own data. Answers go to the customer; Claude only learns that they were shown.

Claude never handles Signature's ids: the server remembers the build it is waiting on and the conversation a
follow-up continues, and numbers Signature's open questions."""

import asyncio
import functools
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version
from typing import Any, Final, Literal, TypedDict
from urllib.parse import unquote, urlsplit

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    InputRequiredResult,
    ToolAnnotations,
)
from pydantic import TypeAdapter

from signature_plugin.backend import (
    BuildStatus,
    DocumentKind,
    OpenQuestion,
    Preparation,
    QueryPlan,
    Signature,
    SignatureRefused,
    SignatureUnreachable,
    connected,
)
from signature_plugin.examples import examples_of
from signature_plugin.local_data import LocalData, QueryRefused, Result
from signature_plugin.pages import Page, Pages, Refusal
from signature_plugin.progress import ActivityBoard, ProgressStore
from signature_plugin.settings import NotConfigured, from_environment
from signature_plugin.sources import DatabaseSource, FileSource, Source, SourceRefused, Sources

POLL_SECONDS = 1.0
# How long Signature may stay unreachable while work is waited on before the wait fails; a busy server misses polls.
UNREACHABLE_SECONDS = 60.0
# How long one call waits on Signature or on the customer before handing back to Claude, under Claude Code's limit
# on a single tool call. Evaluations shorten it.
WAIT_SECONDS = float(os.environ.get('SIGNATURE_WAIT_SECONDS', '540'))
# The rows of an answer Claude reads and the customer is shown; a larger result is cut here and says so.
SHOWN_ROWS = 200

INSTRUCTIONS = """Signature turns the customer's data and documents into a domain it can answer questions about
with proven SQL. Your API key opens exactly one domain, so you never choose one.

To set one up, follow the setup skill: call set_up, which asks the customer for their documents and data itself
and builds, answer Signature's questions, then open the review so they can publish. Pass documents as they are;
do not go looking for more.

Once the domain is published, every question about the customer's data (how many, how much, which, the
highest, the average, any lookup in it) goes to ask_question, even when the files can be read here: Signature
proves its answer, which reading or querying the data yourself does not. Never count, compute or look anything up
in the customer's data yourself, and never offer to: when Signature cannot answer, say so and offer to ask it
differently. You do not know what Signature can answer, so never suggest example questions or say what the data
holds beyond its sources' names: tell the customer to ask in their own words.

Signature's answer is the whole answer. Never add your own comment on it: no observations, comparisons, totals,
rankings or conclusions drawn from its rows, which would be your reasoning presented beside a proven result. A
question about what an answer shows, such as which value is highest, is a new question for ask_question.

Show the customer each result as its note says, unless what follows the result says Signature has drawn it for
them already: then do not restate it."""

type PagePurpose = Literal['connect', 'review']
# The steps set_up asks the customer something at, in order, and the last, which confirms what it gathered.
type AskingStep = Literal['business', 'data', 'data_documents']
type SetupStep = AskingStep | Literal['confirm']
NEXT_STEP: Final[dict[AskingStep, SetupStep]] = {
    'business': 'data',
    'data': 'data_documents',
    'data_documents': 'confirm',
}

# The form set_up shows the customer at each asking step: its message and its fields, each a list of paths separated
# by commas.
SETUP_FORMS: Final[dict[AskingStep, tuple[str, dict[str, Any]]]] = {
    'business': (
        'Which documents explain your business, such as its policies, procedures and memos? Give their files or '
        'folders, separated by commas.',
        {'paths': {'type': 'string', 'title': 'Documents about your business'}},
    ),
    'data': (
        'Where is your data? Give its files or folders, separated by commas, and the file holding a database '
        'connection, if you have one. The data stays on this computer.',
        {
            'paths': {'type': 'string', 'title': 'Data files or folders'},
            'connection_file': {'type': 'string', 'title': 'Database connection file'},
        },
    ),
    'data_documents': (
        "Which documents explain your data's tables and columns, such as data dictionaries? Give their files or "
        'folders, separated by commas, or leave it empty.',
        {'paths': {'type': 'string', 'title': 'Documents about your data'}},
    ),
}

# The URL schemes a connection file may use, and the engine each names.
DATABASE_SCHEMES: Final = {'postgresql': 'postgres', 'postgres': 'postgres', 'mysql': 'mysql', 'mariadb': 'mysql'}

# What Claude tells the customer when a build fails, by the reason Signature gives.
BUILD_FAILURES = {
    'temporarilyUnavailable': 'Signature could not finish this build because it is briefly unavailable. Tell the '
    'customer in one sentence and offer to build again in a few minutes. Do not change what you hand it.',
    'invalidResponse': 'Signature could not finish this build: its work came back unusable this time. Build again '
    'once with the same documents; if it fails again, tell the customer.',
    'sourceUnavailable': 'Signature could not read one of the documents. Ask the customer whether each document '
    'opens, then build again without any that do not.',
    'domainChanged': 'The domain changed while this build ran, so Signature stopped it. Build again.',
    'accessRevoked': "Signature's access to this domain was withdrawn. Tell the customer to check their API key.",
}


class SourceSummary(TypedDict):
    name: str
    kind: Literal['file', 'database']
    location: str


class QuestionView(TypedDict):
    number: int
    question: str
    suggested_answers: list[str]


class Status(TypedDict):
    domain: str
    published: bool
    sources: list[SourceSummary]
    open_questions: list[QuestionView]
    note: str


class Added(TypedDict):
    source: str
    tables: int
    columns: int


class BuildProgress(TypedDict):
    state: Literal['built', 'questions', 'replied', 'building', 'failed']
    reply: str | None
    open_questions: list[QuestionView]
    note: str


class Answer(TypedDict):
    question: int
    answer: str
    from_customer: bool


class NotDecided(TypedDict):
    state: Literal['waiting', 'declined']
    note: str


class Reviewed(TypedDict):
    state: Literal['published', 'changes_requested']
    note: str
    build: BuildProgress | None


type Cell = str | int | float | bool | None


class Asked(TypedDict):
    """An answer as Claude reads it and the plugin's mod draws it under the call: the question, how Signature read it,
    and the rows its proven query found on the customer's data; or why there is no answer."""

    state: Literal['answered', 'unanswerable', 'unproven', 'stale']
    question: str
    reading: str | None
    columns: list[str]
    rows: list[list[Cell]]
    row_count: int
    truncated: bool
    reason: str | None
    note: str


class Gathered(TypedDict):
    """What set_up has gathered from the customer so far, carried from one round to the next: the step it asks
    next, why the last answer to it was refused, and the documents given."""

    step: SetupStep
    problem: str | None
    documents: list[str]
    data_documents: list[str]


GATHERED: Final = TypeAdapter(Gathered)


@dataclass
class PluginState:
    pages: Pages
    waiting_pages: dict[PagePurpose, Page[Any]]
    local: LocalData


@dataclass(frozen=True)
class Session:
    """Signature, bound to the key's one domain, and what this machine holds for that domain."""

    signature: Signature
    sources: Sources
    progress: ProgressStore
    board: ActivityBoard


@dataclass(frozen=True)
class ReviewDecision:
    publish: bool
    changes: str


@dataclass(frozen=True)
class Decided[T]:
    value: T


@asynccontextmanager
async def _plugin_state(_server: MCPServer[PluginState]) -> AsyncGenerator[PluginState]:
    local = LocalData()
    try:
        yield PluginState(pages=Pages(), waiting_pages={}, local=local)
    finally:
        local.close()


server: MCPServer[PluginState] = MCPServer(
    'signature', instructions=INSTRUCTIONS, version=version('signature-plugin'), lifespan=_plugin_state
)


def _tool_errors[**P, T](tool: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Failures the customer or Claude can act on, told to Claude as tool errors in plain words."""

    @functools.wraps(tool)
    async def told(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await tool(*args, **kwargs)
        except (SignatureRefused, SourceRefused, QueryRefused, NotConfigured) as refused:
            raise ToolError(str(refused)) from refused
        except SignatureUnreachable as unreachable:
            raise ToolError('Signature could not be reached. Try again in a moment.') from unreachable

    return told


@asynccontextmanager
async def _session() -> AsyncGenerator[Session]:
    settings = from_environment()
    async with connected(settings) as signature:
        folder = settings.data_dir / signature.domain_id
        yield Session(
            signature=signature,
            sources=Sources(folder),
            progress=ProgressStore(folder),
            board=ActivityBoard(settings.data_dir),
        )


@server.tool(
    title='Signature status',
    description="Where the customer's Signature domain stands: its name, whether it is published, "
    'the sources added so far, and the questions Signature is waiting on.',
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@_tool_errors
async def get_status() -> Status:
    async with _session() as session:
        domain = await session.signature.domain()
        return Status(
            domain=domain.name,
            published=domain.published_at is not None,
            sources=[_summary(source) for source in session.sources.all()],
            open_questions=await _numbered_questions(session),
            note='Tell the customer, in a sentence or two, where their domain stands and what they can do next.',
        )


@server.tool(
    title='Add data files',
    description="Adds the customer's data files as sources: CSV, TSV, XLSX, Parquet or JSON files, or "
    'folders of them, by absolute path, for example ["/Users/ana/exports/orders.csv", "/Users/ana/exports"]. '
    'The files stay on this machine; Signature is told their structure and a few example values when you '
    'build. Adding a file again does nothing.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    ),
)
@_tool_errors
async def add_data_files(paths: list[str], ctx: Context[PluginState]) -> list[Added]:
    local = ctx.request_context.lifespan_context.local
    async with _session() as session:
        added = session.sources.add_files(paths)
        try:
            return [await _checked(local, session.sources, source) for source in added]
        except SourceRefused:
            for source in added:
                session.sources.remove(source.name)
            raise


@server.tool(
    title='Connect a database',
    description='Connects a PostgreSQL or MySQL database. When the customer names a file holding its connection '
    '(a URL such as postgresql://user:password@host:port/database), pass that path as connection_file, exactly as '
    'the customer wrote it: a relative path is read from the folder Claude Code runs in. The server reads it, so '
    'never open, read or print the file yourself, nor look for it. Otherwise the customer connects it on a page in '
    'their browser. Either way its password never passes through you. Call once per database.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
@_tool_errors
async def connect_database(
    ctx: Context[PluginState], suggested_name: str | None = None, connection_file: str | None = None
) -> Added | NotDecided | InputRequiredResult:
    local = ctx.request_context.lifespan_context.local
    async with _session() as session:
        sources = session.sources
    if connection_file is not None:
        connected = await _database_connected(local, sources, await _connection_form(connection_file, suggested_name))
        if isinstance(connected, Refusal):
            raise ToolError(connected.reason)
        return await _checked(local, sources, connected)

    async def connected_from(form: dict[str, str]) -> DatabaseSource | Refusal:
        return await _database_connected(local, sources, form)

    outcome = await _decision_on_page(
        ctx,
        'connect',
        lambda pages: pages.show({'page': 'connect', 'suggestedName': suggested_name}, connected_from),
        'Connect your database to Signature. The password stays on this computer.',
    )
    if not isinstance(outcome, Decided):
        return outcome
    return await _checked(local, sources, outcome.value)


@server.tool(
    title='Remove a source',
    description='Removes a source, by the name add_data_files, connect_database or get_status gave it. '
    'Build again for Signature to drop it.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
@_tool_errors
async def remove_source(name: str) -> str:
    async with _session() as session:
        session.sources.remove(name)
    return f'{name} removed. Build again for Signature to drop it.'


@server.tool(
    title='Build the domain',
    description='Builds the domain: tells Signature the structure of every source added so far and hands it '
    'the documents at the given absolute paths, exactly as they are: `documents` explain the business, '
    "`data_documents` explain the data's tables and columns in the business's terms, such as data "
    'dictionaries. `note` is anything the customer said that Signature should know. Waits while Signature '
    'builds and returns its reply and any questions it has.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
@_tool_errors
async def build(
    ctx: Context[PluginState],
    documents: list[str] | None = None,
    data_documents: list[str] | None = None,
    note: str | None = None,
) -> BuildProgress:
    async with _session() as session:
        if not session.sources.all() and not documents and not data_documents:
            raise ToolError(
                "There is nothing to build from yet. Add the customer's data with add_data_files or "
                'connect_database, or pass their documents.'
            )
        return await _built(session, ctx, documents or [], data_documents or [], note)


@server.tool(
    title='Set up Signature',
    description='Walks the customer through setting up their domain: asks them in turn, in forms Claude Code shows '
    'them, for the documents explaining their business, their data, and the documents explaining it, then builds. '
    'Call it as soon as the customer wants to set up Signature, without asking them anything first: it asks them '
    'itself. Returns as build does.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
@_tool_errors
async def set_up(ctx: Context[PluginState]) -> BuildProgress | NotDecided | InputRequiredResult:
    if not _takes_forms(ctx):
        raise ToolError(
            "This Claude Code cannot show Signature's setup forms. Ask the customer for the documents explaining "
            'their business, their data and the documents explaining it, then use add_data_files, '
            'connect_database and build.'
        )
    gathered = _gathered(ctx.request_state)
    step = gathered['step']
    response = (ctx.input_responses or {}).get(step)
    async with _session() as session:
        if isinstance(response, ElicitResult):
            if response.action != 'accept':
                return NotDecided(
                    state='declined',
                    note='The customer stopped setting up. Ask whether they want to go on, and call set_up again '
                    'when they do.',
                )
            if step == 'confirm':
                return await _built(session, ctx, gathered['documents'], gathered['data_documents'], None)
            gathered = await _gathered_with(session, ctx, gathered, step, response.content or {})
        return _form_for(gathered, session.sources.all())


@server.tool(
    title="Answer Signature's questions",
    description="Answers Signature's open questions, by their numbers. Set from_customer to false for an "
    'answer you worked out yourself rather than heard from the customer, so Signature treats it as '
    'unconfirmed. Waits while Signature continues building.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
@_tool_errors
async def answer_questions(answers: list[Answer], ctx: Context[PluginState]) -> BuildProgress:
    if not answers:
        raise ToolError(
            'Give at least one answer, for example [{"question": 1, "answer": "…", "from_customer": true}].'
        )
    async with _session() as session:
        question_ids = session.progress.load().question_ids
        unknown = [given['question'] for given in answers if given['question'] not in question_ids]
        if unknown:
            open_numbers = ', '.join(str(number) for number in question_ids) or 'none'
            raise ToolError(
                f'There is no open question {", ".join(map(str, unknown))}. Open questions: {open_numbers}. '
                'Call get_status to see them.'
            )
        # The customer's next turn closes every open question, so all the answers go to Signature in one turn,
        # each under the question it settles, as Signature words a single answer itself.
        still_open = {question.id: question.question for question in await session.signature.open_questions()}
        closed = [given['question'] for given in answers if question_ids[given['question']] not in still_open]
        if closed:
            raise ToolError(
                f'Question {", ".join(map(str, closed))} is no longer open. Call get_status to see what is.'
            )
        settled = '\n\n'.join(
            f'Q: {still_open[question_ids[given["question"]]]}\nA: {_attributed(given)}' for given in answers
        )
        build_id = await session.signature.start_build(settled, [])
        return await _followed(session, build_id, ctx)


@server.tool(
    title='Wait for the build',
    description='Keeps waiting on the build that was still going when the last call returned.',
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@_tool_errors
async def wait_for_build(ctx: Context[PluginState]) -> BuildProgress:
    async with _session() as session:
        build_id = session.progress.load().build_id
        if build_id is None:
            raise ToolError('No build has been started. Call build first.')
        return await _followed(session, build_id, ctx)


@server.tool(
    title='Review and publish',
    description='Shows the customer the domain in plain terms on a page in their browser, with a button to '
    'publish it or a box to say what is wrong. Waits for their decision. A requested change is sent to '
    'Signature and rebuilt.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
@_tool_errors
async def review(ctx: Context[PluginState]) -> Reviewed | NotDecided | InputRequiredResult:
    async with _session() as session:
        signature = session.signature

        async def review_page(pages: Pages) -> Page[ReviewDecision]:
            domain = await signature.domain()
            snapshot = await signature.model_snapshot()
            local = ctx.request_context.lifespan_context.local
            cases = await anyio.to_thread.run_sync(examples_of, snapshot, local, session.sources.all())
            data = {'page': 'review', 'domain': domain.name, 'snapshot': snapshot, 'examples': cases}
            return await pages.show(data, _review_decision)

        outcome = await _decision_on_page(
            ctx, 'review', review_page, 'Review what Signature understood, then publish it or say what is wrong.'
        )
        if not isinstance(outcome, Decided):
            return outcome
        if outcome.value.publish:
            await signature.publish()
            await ctx.report_progress(0, message='Getting ready to answer questions about your data…')
            return Reviewed(state='published', note=_readiness(await _prepared(session)), build=None)
        build_id = await signature.start_build(outcome.value.changes, [])
        return Reviewed(
            state='changes_requested',
            note='The customer asked for changes, which were sent to Signature. Call review again once the '
            'build has no open questions.',
            build=await _followed(session, build_id, ctx),
        )


@server.tool(
    title='Ask Signature',
    description="Asks Signature a question about the customer's data. Use it for every such question, rather than "
    'reading or querying the data yourself: Signature proves a SQL query that answers it, the query runs here on '
    "the customer's data, and its rows come back to show the customer. Set follow_up to true to continue from the "
    'previous question.',
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@_tool_errors
async def ask_question(question: str, ctx: Context[PluginState], follow_up: bool = False) -> Asked:
    async with _session() as session:
        signature, progress = session.signature, session.progress.load()
        if follow_up and progress.thread_id is None:
            raise ToolError('There is no earlier question to follow up on. Ask it with follow_up false.')
        local = ctx.request_context.lifespan_context.local
        fingerprint = await anyio.to_thread.run_sync(local.fingerprint, session.sources.all())
        await _prepared(session)
        query_id = await signature.plan_query(question, progress.thread_id if follow_up else None, fingerprint)
        try:
            plan = await _planned(session, query_id, ctx)
            if plan is None:
                raise ToolError('Signature took too long to work out the query. Ask again.')
            session.progress.save(progress.model_copy(update={'thread_id': plan.thread_id}))
            return await _asked(session, ctx, question, plan)
        finally:
            session.board.ended('asked')


async def _asked(session: Session, ctx: Context[PluginState], question: str, plan: QueryPlan) -> Asked:
    """What came of a question Signature has planned: its answer, run here on the customer's data, or why there is
    none."""
    match plan.state:
        case 'planned' if plan.sql:
            await _show_stage(session, 'Running it on your data', datetime.now(UTC).isoformat())
            local = ctx.request_context.lifespan_context.local
            result = await anyio.to_thread.run_sync(local.run, session.sources.all(), plan.sql)
            return _answered(question, plan.reading, plan.columns, result)
        case 'unanswerable':
            return _unanswered(
                question,
                'unanswerable',
                plan.reason,
                'Tell the customer why Signature cannot answer this, and suggest, in a sentence, how they could '
                'ask it in terms the domain has.',
            )
        case 'stale':
            return _unanswered(
                question,
                'stale',
                'Your data has changed shape since the domain was published.',
                "The customer's tables or columns changed after publishing. Call build, then review so they can "
                'publish again, then ask again.',
            )
        case 'failed':
            return _unanswered(
                question,
                'unproven',
                plan.reason,
                'Tell the customer Signature could not prove an answer, so nothing ran, and offer to ask it more '
                'simply, one part at a time.',
            )
        case _:
            raise ToolError('Signature could not work out a query for this question.')


ANSWERED_NOTE = (
    'Show the customer this answer and nothing else: the rows as a Markdown table under readable headers (the '
    'first 20 when there are more, saying how many there are), or the value alone when there is one. Do not show '
    'or paraphrase `reading`, describe how the answer was computed, or comment on the rows. A question about '
    'them, or anything needing other numbers, goes to Signature again (with follow_up for a refinement of this '
    'question).'
)


def _answered(question: str, reading: str | None, names: list[str], result: Result) -> Asked:
    """The rows of a proven query, under the names Signature gave its columns, or the query's own."""
    columns = names if len(names) == len(result.columns) else result.columns
    rows = [[_cell(value) for value in row] for row in result.rows[:SHOWN_ROWS]]
    return Asked(
        state='answered',
        question=question,
        reading=reading,
        columns=columns,
        rows=rows,
        row_count=len(result.rows),
        truncated=result.truncated or len(result.rows) > SHOWN_ROWS,
        reason=None,
        note=ANSWERED_NOTE,
    )


def _unanswered(
    question: str, state: Literal['unanswerable', 'unproven', 'stale'], reason: str | None, note: str
) -> Asked:
    return Asked(
        state=state,
        question=question,
        reading=None,
        columns=[],
        rows=[],
        row_count=0,
        truncated=False,
        reason=reason,
        note=note,
    )


def _cell(value: object) -> Cell:
    """A value as JSON carries it: a number or text as it is, a decimal as a number, anything else, such as a date,
    as its text."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _gathered(state: str | None) -> Gathered:
    if state is None:
        return Gathered(step='business', problem=None, documents=[], data_documents=[])
    return GATHERED.validate_json(state)


def _form_for(gathered: Gathered, sources: list[Source]) -> InputRequiredResult:
    """The form for the step set_up asks next, with why the last answer to it was refused."""
    step = gathered['step']
    if step == 'confirm':
        message = _everything(gathered, sources)
        schema: dict[str, Any] = {'type': 'object', 'properties': {}}
    else:
        message, fields = SETUP_FORMS[step]
        schema = {'type': 'object', 'properties': fields}
    if gathered['problem'] is not None:
        message = f'{gathered["problem"]}\n\n{message}'
    form = ElicitRequestFormParams(message=message, requested_schema=schema)
    return InputRequiredResult(
        input_requests={step: ElicitRequest(params=form)}, request_state=GATHERED.dump_json(gathered).decode()
    )


async def _gathered_with(
    session: Session, ctx: Context[PluginState], gathered: Gathered, step: AskingStep, answer: dict[str, Any]
) -> Gathered:
    """What set_up has gathered once the customer answers the step, and the step it asks next: the same one, saying
    why, when the answer cannot be used. Data is added as a source as soon as it is given."""
    documents, data_documents = gathered['documents'], gathered['data_documents']
    try:
        match step:
            case 'business':
                documents = await _documents_at(_paths(answer.get('paths')))
            case 'data':
                connection_file = str(answer.get('connection_file') or '').strip()
                await _added(session, ctx, _paths(answer.get('paths')), connection_file)
            case 'data_documents':
                data_documents = await _documents_at(_paths(answer.get('paths')), required=False)
    except (ToolError, SourceRefused) as refused:
        return Gathered(step=step, problem=str(refused), documents=documents, data_documents=data_documents)
    return Gathered(step=NEXT_STEP[step], problem=None, documents=documents, data_documents=data_documents)


async def _added(session: Session, ctx: Context[PluginState], paths: list[str], connection_file: str) -> None:
    """The customer's data files and database added as sources and checked; at least one must be given."""
    if not paths and not connection_file:
        raise ToolError('Give at least one data file or folder, or a database connection file.')
    local = ctx.request_context.lifespan_context.local
    for source in session.sources.add_files(paths) if paths else []:
        await _checked(local, session.sources, source)
    if connection_file:
        connected = await _database_connected(local, session.sources, await _connection_form(connection_file, None))
        if isinstance(connected, Refusal):
            raise ToolError(connected.reason)


def _paths(answer: object) -> list[str]:
    """The paths a customer typed into one field, separated by commas or lines."""
    return [path.strip() for path in str(answer or '').replace('\n', ',').split(',') if path.strip()]


async def _documents_at(paths: list[str], *, required: bool = True) -> list[str]:
    """The documents at the paths the customer gave, a folder standing for the files directly inside it, as data
    folders do; each must exist."""
    if required and not paths:
        raise ToolError('Give at least one document or folder.')
    found: list[str] = []
    for given in paths:
        path = await anyio.Path(given).expanduser()
        if await path.is_dir():
            found.extend(await _files_in(path))
        elif await path.is_file():
            found.append(str(path))
        else:
            raise ToolError(f'There is nothing at {given}.')
    return found


async def _files_in(folder: anyio.Path) -> list[str]:
    """The files directly inside the folder, by name, leaving out hidden ones."""
    files = [file async for file in folder.iterdir() if await file.is_file() and not file.name.startswith('.')]
    return sorted(str(file) for file in files)


def _everything(gathered: Gathered, sources: list[Source]) -> str:
    """What set_up will build from, for the customer to confirm."""
    data = ', '.join(source.name for source in sources) or 'none'
    return (
        f'Signature will build from {_counted(len(gathered["documents"]), "document")} about your business, your '
        f'data ({data}) and {_counted(len(gathered["data_documents"]), "document")} explaining it. Is that '
        'everything? Accept to build now.'
    )


def _counted(count: int, noun: str) -> str:
    return f'{count} {noun}' if count == 1 else f'{count} {noun}s'


async def _built(
    session: Session, ctx: Context[PluginState], documents: list[str], data_documents: list[str], note: str | None
) -> BuildProgress:
    """The domain built from every source and the documents, followed until it ends or the wait runs out."""
    signature, sources = session.signature, session.sources.all()
    kinds: list[tuple[str, DocumentKind]] = [
        *((path, 'notes') for path in documents),
        *((path, 'data') for path in data_documents),
    ]
    contents: list[tuple[tuple[str, bytes], DocumentKind]] = [(await _document(path), kind) for path, kind in kinds]
    if sources:
        await ctx.report_progress(0, message='Telling Signature about your data…')
        local = ctx.request_context.lifespan_context.local
        await signature.report_catalog(await anyio.to_thread.run_sync(local.catalog, sources))
    await ctx.report_progress(0, message='Uploading your documents…')
    staged = [await signature.stage_document(name, content, kind) for (name, content), kind in contents]
    build_id = await signature.start_build(note, staged)
    return await _followed(session, build_id, ctx)


async def _document(location: str) -> tuple[str, bytes]:
    """The document's file name and its bytes, exactly as the customer gave it."""
    path = await anyio.Path(location).expanduser()
    try:
        return path.name, await path.read_bytes()
    except OSError as failure:
        raise ToolError(f'Could not read {location}: {failure.strerror}. Give an absolute path.') from failure


async def _checked(local: LocalData, sources: Sources, source: Source) -> Added:
    tables = await anyio.to_thread.run_sync(local.check, sources.all(), source)
    return Added(source=source.name, tables=len(tables), columns=sum(table.columns for table in tables))


async def _database_connected(local: LocalData, sources: Sources, form: dict[str, str]) -> DatabaseSource | Refusal:
    """The database the form describes, connected and kept; or why it could not be, for the page to show."""
    engine = 'mysql' if form.get('engine') == 'mysql' else 'postgres'
    try:
        port = int(form.get('port') or (3306 if engine == 'mysql' else 5432))
    except ValueError:
        return Refusal('The port must be a number, such as 5432.')
    source = sources.add_database(
        DatabaseSource(
            name=form.get('name') or engine,
            engine=engine,
            host=form.get('host', ''),
            port=port,
            database=form.get('database', ''),
            user=form.get('user', ''),
        ),
        password=form.get('password', ''),
    )
    try:
        await anyio.to_thread.run_sync(local.check, sources.all(), source)
    except SourceRefused as refused:
        sources.remove(source.name)
        return Refusal(str(refused))
    return source


async def _connection_form(location: str, name: str | None) -> dict[str, str]:
    """The connection a file names as a URL, in the fields the browser page sends. Errors never quote the file, since
    it holds a password."""
    path = await anyio.Path(location).expanduser()
    try:
        url = urlsplit((await path.read_text(encoding='utf-8')).strip())
    except OSError as failure:
        raise ToolError(f'Could not read {location}: {failure.strerror}. Ask the customer where it is.') from failure
    engine = DATABASE_SCHEMES.get(url.scheme)
    database = url.path.removeprefix('/')
    if engine is None or not url.hostname or not database:
        raise ToolError(
            f'{location} does not hold a database URL. It should be one line such as '
            'postgresql://user:password@host:5432/database, or mysql://… for MySQL.'
        )
    return {
        'engine': engine,
        'name': name or database,
        'host': url.hostname,
        'port': str(url.port or ''),
        'database': database,
        'user': unquote(url.username or ''),
        'password': unquote(url.password or ''),
    }


async def _review_decision(form: dict[str, str]) -> ReviewDecision | Refusal:
    changes = form.get('changes', '').strip()
    if form.get('decision') == 'change' and not changes:
        return Refusal('Say what should change.')
    return ReviewDecision(publish=form.get('decision') == 'publish', changes=changes)


async def _decision_on_page[T](
    ctx: Context[PluginState],
    purpose: PagePurpose,
    opened: Callable[[Pages], Awaitable[Page[T]]],
    invitation: str,
) -> Decided[T] | NotDecided | InputRequiredResult:
    """The customer's decision on the page for that purpose: the one still waiting from an earlier call, or a new
    one. A client that can show the customer a link is asked to, in a first round; otherwise, or if the customer
    dismissed the link, the page opens in their browser directly."""
    state = ctx.request_context.lifespan_context
    page: Page[T] | None = state.waiting_pages.get(purpose)
    if page is None:
        page = await opened(state.pages)
        state.waiting_pages[purpose] = page
    response = (ctx.input_responses or {}).get(purpose)
    if response is None and _shows_links(ctx):
        link = ElicitRequestURLParams(message=invitation, url=page.address, elicitation_id=page.id)
        return InputRequiredResult(input_requests={purpose: ElicitRequest(params=link)}, request_state=purpose)
    action = response.action if isinstance(response, ElicitResult) else None
    if action == 'decline':
        _forget(state, purpose, page)
        return NotDecided(state='declined', note='The customer chose not to open the page.')
    if action != 'accept':
        state.pages.open_in_browser(page)
    await ctx.report_progress(0, message='Waiting for the customer on the page in their browser…')
    try:
        decision = await asyncio.wait_for(asyncio.shield(page.decided), WAIT_SECONDS)
    except TimeoutError:
        return NotDecided(
            state='waiting',
            note="The page is still open in the customer's browser and nobody has used it yet. Tell the customer it "
            'is waiting for them and stop; call this tool again only after they say they are done with it.',
        )
    _forget(state, purpose, page)
    return Decided(decision)


def _takes_forms(ctx: Context[PluginState]) -> bool:
    """Whether the client shows the customer forms: it says so, or declares elicitation with no modes, which means
    forms alone."""
    capabilities = ctx.client_capabilities
    elicitation = capabilities.elicitation if capabilities is not None else None
    return elicitation is not None and (elicitation.form is not None or elicitation.url is None)


def _shows_links(ctx: Context[PluginState]) -> bool:
    capabilities = ctx.client_capabilities
    return (
        capabilities is not None and capabilities.elicitation is not None and capabilities.elicitation.url is not None
    )


def _forget(state: PluginState, purpose: PagePurpose, page: Page[Any]) -> None:
    del state.waiting_pages[purpose]
    state.pages.close(page)


async def _followed(session: Session, build_id: str, ctx: Context[PluginState]) -> BuildProgress:
    """The build followed until it ends, or until the wait runs out, with what Claude should do next."""
    session.progress.save(session.progress.load().model_copy(update={'build_id': build_id}))
    started = datetime.now(UTC).isoformat()

    async def show(found: BuildStatus) -> None:
        await _show_stage(session, found.stage or 'Building your domain', found.started_at or started, found.stages)

    status = await _waited(
        lambda: session.signature.build_status(build_id), lambda found: found.state == 'pending', show
    )
    if status is None:
        return BuildProgress(
            state='building',
            reply=None,
            open_questions=[],
            note='Signature is still building. Call wait_for_build.',
        )
    if status.state == 'failed':
        session.board.ended('failed')
        return BuildProgress(
            state='failed',
            reply=None,
            open_questions=[],
            note=BUILD_FAILURES.get(status.failure or '', 'Signature could not finish this build. Try again.'),
        )
    questions = await _numbered_questions(session)
    if not questions and not status.model_changed:
        session.board.ended('replied')
        return BuildProgress(
            state='replied',
            reply=status.reply,
            open_questions=[],
            note='Signature replied without building anything yet, so there is nothing to review. If its reply asks '
            'whether to go ahead, call build with a note telling it to go ahead and build the whole domain. Otherwise '
            'tell the customer what it said in a sentence or two. Do not call review until a build has built '
            'something.',
        )
    session.board.ended('questions' if questions else 'built')
    if questions:
        return BuildProgress(
            state='questions',
            reply=status.reply,
            open_questions=questions,
            note='Answer what you can from what the customer told you or gave you; ask the customer the rest '
            'together, then call answer_questions with the question numbers.',
        )
    return BuildProgress(
        state='built',
        reply=status.reply,
        open_questions=[],
        note='Nothing is open. Tell the customer in one sentence what Signature built, naming at most the main '
        'kinds of things, never each detail: the review page shows those. Then call review.',
    )


async def _planned(session: Session, query_id: str, ctx: Context[PluginState]) -> QueryPlan | None:
    """Signature's plan for a question, once it is no longer pending or the wait runs out."""
    started = datetime.now(UTC).isoformat()

    async def show(_pending: QueryPlan) -> None:
        await _show_stage(session, 'Working out the query', started)

    return await _waited(lambda: session.signature.query(query_id), lambda found: found.state == 'pending', show)


async def _show_stage(session: Session, stage: str, started_at: str, stages: list[str] | None = None) -> None:
    """Shows the customer what Signature is doing, in the plugin's band above their prompt."""
    session.board.running(stage, started_at, stages)


async def _numbered_questions(session: Session) -> list[QuestionView]:
    """Signature's open questions, numbered from 1; the numbers are remembered for answer_questions."""
    questions = await session.signature.open_questions()
    numbered = dict(enumerate(questions, start=1))
    progress = session.progress.load()
    session.progress.save(progress.model_copy(update={'question_ids': {n: q.id for n, q in numbered.items()}}))
    return [_view(number, question) for number, question in numbered.items()]


async def _prepared(session: Session) -> Preparation | None:
    """Signature's preparation of the published domain to answer questions, once it is no longer underway or the
    wait runs out, the customer shown that Signature is getting ready meanwhile: a question asked before then would
    find nothing to answer from."""
    started = datetime.now(UTC).isoformat()

    async def show(_underway: Preparation | None) -> None:
        await _show_stage(session, 'Getting ready to answer questions', started)

    found = await _waited(session.signature.preparation, lambda found: found is not None and found.underway, show)
    return found if found is not None else await session.signature.preparation()


def _readiness(preparation: Preparation | None) -> str:
    """What to tell Claude about asking questions once the domain is published."""
    if preparation is None:
        # Publishing asks for the package questions are answered from, so a publication without one has nothing
        # to answer from and never will.
        return (
            'Published, but Signature has nothing to answer questions from: it built no query package for this '
            'publication. Tell the customer, and do not ask questions until it is fixed.'
        )
    if preparation.state == 'succeeded':
        return (
            'Published. The customer can now ask questions. Do not suggest example questions of your own; let '
            'the customer ask theirs.'
        )
    if preparation.underway:
        return (
            'Published. Signature is still getting ready to answer questions; a question asked now waits for '
            'it, so it may take a few minutes.'
        )
    return (
        f'Published, but Signature could not get ready to answer questions: {preparation.reason}. Tell the '
        'customer, and do not ask questions until it is fixed.'
    )


async def _waited[T](
    fetch: Callable[[], Awaitable[T]],
    pending: Callable[[T], bool],
    observe: Callable[[T], Awaitable[None]] | None = None,
) -> T | None:
    """What fetch returns once it is no longer pending, or None if that takes longer than the wait. Each pending
    value is given to observe, when there is one. Signature busy with the work being waited on may miss a poll; only
    being unreachable for UNREACHABLE_SECONDS on end fails the wait."""
    with anyio.move_on_after(WAIT_SECONDS):
        while pending(found := await _polled(fetch)):
            if observe is not None:
                await observe(found)
            await anyio.sleep(POLL_SECONDS)
        return found
    return None


async def _polled[T](fetch: Callable[[], Awaitable[T]]) -> T:
    """What fetch returns, asked again while Signature cannot be reached, until it has been unreachable for
    UNREACHABLE_SECONDS."""
    give_up = anyio.current_time() + UNREACHABLE_SECONDS
    while True:
        try:
            return await fetch()
        except SignatureUnreachable:
            if anyio.current_time() >= give_up:
                raise
            await anyio.sleep(POLL_SECONDS)


def _attributed(given: Answer) -> str:
    """The answer as Signature receives it, marked when Claude inferred it rather than heard it."""
    if given['from_customer']:
        return given['answer']
    return f'(Inferred, not confirmed by the customer) {given["answer"]}'


def _summary(source: Source) -> SourceSummary:
    if isinstance(source, FileSource):
        return SourceSummary(name=source.name, kind='file', location=source.path)
    return SourceSummary(
        name=source.name, kind='database', location=f'{source.engine}://{source.host}:{source.port}/{source.database}'
    )


def _view(number: int, question: OpenQuestion) -> QuestionView:
    return QuestionView(number=number, question=question.question, suggested_answers=question.suggested_answers)


def main() -> None:
    server.run()
