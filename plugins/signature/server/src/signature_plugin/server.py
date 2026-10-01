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
from typing import Any, Literal, TypedDict

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ElicitRequest, ElicitRequestURLParams, ElicitResult, InputRequiredResult, ToolAnnotations

from signature_plugin import handoff, presentation
from signature_plugin.backend import (
    OpenQuestion,
    Preparation,
    Signature,
    SignatureRefused,
    SignatureUnreachable,
    connected,
)
from signature_plugin.examples import examples_of
from signature_plugin.local_data import LocalData, QueryRefused
from signature_plugin.pages import Page, Pages, Refusal
from signature_plugin.progress import ProgressStore
from signature_plugin.settings import NotConfigured, from_environment
from signature_plugin.sources import DatabaseSource, FileSource, Source, SourceRefused, Sources

POLL_SECONDS = 1.0
# How long one call waits on Signature or on the customer before handing back to Claude, under Claude Code's limit
# on a single tool call. Evaluations shorten it.
WAIT_SECONDS = float(os.environ.get('SIGNATURE_WAIT_SECONDS', '540'))

INSTRUCTIONS = """Signature turns the customer's data and documents into a domain it can answer questions about
with proven SQL. Your API key opens exactly one domain, so you never choose one.

To set one up, follow the setup skill: ask the customer where their data lives, add those files and databases
as sources, take the documents they give you, build, answer Signature's questions with them, then open the
review so they can publish. Pass documents as they are; do not go looking for more.

Answers to questions are shown to the customer, never to you. Do not guess, restate or summarise them."""

type PagePurpose = Literal['connect', 'review']


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


class Added(TypedDict):
    source: str
    tables: int
    columns: int


class BuildProgress(TypedDict):
    state: Literal['built', 'questions', 'building', 'failed']
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


class Asked(TypedDict):
    state: Literal['shown', 'unanswerable', 'unproven', 'stale']
    note: str


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
    'signature', instructions=INSTRUCTIONS, version='0.3.0', lifespan=_plugin_state
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
        yield Session(signature=signature, sources=Sources(folder), progress=ProgressStore(folder))


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
    description='Asks the customer to connect a PostgreSQL or MySQL database on a page in their browser, so '
    'its password never passes through you. Waits until they have connected it. Call once per database.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
@_tool_errors
async def connect_database(
    ctx: Context[PluginState], suggested_name: str | None = None
) -> Added | NotDecided | InputRequiredResult:
    local = ctx.request_context.lifespan_context.local
    async with _session() as session:
        sources = session.sources

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
    'the documents at the given absolute paths, exactly as they are. `note` is anything the customer said that '
    'Signature should know. Waits while Signature builds and returns its reply and any questions it has.',
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
@_tool_errors
async def build(
    ctx: Context[PluginState], documents: list[str] | None = None, note: str | None = None
) -> BuildProgress:
    async with _session() as session:
        signature, sources = session.signature, session.sources.all()
        if not sources and not documents:
            raise ToolError(
                "There is nothing to build from yet. Add the customer's data with add_data_files or "
                'connect_database, or pass their documents.'
            )
        contents = [await _document(path) for path in documents or []]
        if sources:
            await ctx.report_progress(0, message='Telling Signature about your data…')
            local = ctx.request_context.lifespan_context.local
            await signature.report_catalog(await anyio.to_thread.run_sync(local.catalog, sources))
        await ctx.report_progress(0, message='Uploading your documents…')
        staged = [await signature.stage_document(name, content) for name, content in contents]
        build_id = await signature.start_build(note, staged)
        return await _followed(session, build_id, ctx)


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
        build_ids = [
            await session.signature.answer_question(question_ids[given['question']], _attributed(given))
            for given in answers
        ]
        return await _followed(session, build_ids[-1], ctx)


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
            return Reviewed(state='published', note=_readiness(await _prepared(signature)), build=None)
        build_id = await signature.start_build(outcome.value.changes, [])
        return Reviewed(
            state='changes_requested',
            note='The customer asked for changes, which were sent to Signature. Call review again once the '
            'build has no open questions.',
            build=await _followed(session, build_id, ctx),
        )


@server.tool(
    title='Ask Signature',
    description="Asks Signature a question about the customer's published domain. Signature writes the SQL; it "
    "runs here on the customer's data, and the answer is shown to the customer, not to you. Set follow_up to "
    'true to continue from the previous question.',
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
        query_id = await signature.plan_query(question, progress.thread_id if follow_up else None, fingerprint)
        await ctx.report_progress(0, message='Signature is working out the query…')
        plan = await _waited(lambda: signature.query(query_id), lambda found: found.state == 'pending')
        if plan is None:
            raise ToolError('Signature took too long to work out the query. Ask again.')
        session.progress.save(progress.model_copy(update={'thread_id': plan.thread_id}))
        match plan.state:
            case 'planned' if plan.sql:
                await ctx.report_progress(0, message='Running it on your data…')
                result = await anyio.to_thread.run_sync(local.run, session.sources.all(), plan.sql)
                handoff.leave(question, presentation.answer_text(plan.reading, plan.columns, result))
                return Asked(state='shown', note='The answer was shown to the customer. You cannot see it.')
            case 'unanswerable':
                handoff.leave(question, f"Signature can't answer this from your domain: {plan.reason}")
                return Asked(
                    state='unanswerable',
                    note='Signature could not answer this from the domain, and the customer was told why.',
                )
            case 'stale':
                handoff.leave(
                    question, 'Your data has changed shape since Signature was published, so it needs updating.'
                )
                return Asked(
                    state='stale',
                    note="The customer's tables or columns changed after publishing. Call build, then review so "
                    'they can publish again, then ask again.',
                )
            case 'failed':
                handoff.leave(question, f'Signature could not prove a query that answers this: {plan.reason}')
                return Asked(
                    state='unproven',
                    note='Signature could not prove an answer, so nothing was run, and the customer was told why. '
                    'Offer to ask it more simply, one part at a time.',
                )
            case _:
                raise ToolError('Signature could not work out a query for this question.')


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
    await ctx.report_progress(0, message='Signature is building your domain…')
    status = await _waited(lambda: session.signature.build_status(build_id), lambda found: found.state == 'pending')
    if status is None:
        return BuildProgress(
            state='building',
            reply=None,
            open_questions=[],
            note='Signature is still building. Call wait_for_build.',
        )
    if status.state == 'failed':
        return BuildProgress(
            state='failed',
            reply=None,
            open_questions=[],
            note='Signature could not finish this build. Try again, or hand it less at once.',
        )
    questions = await _numbered_questions(session)
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
        note='Nothing is open. Tell the customer what Signature did, then call review.',
    )


async def _numbered_questions(session: Session) -> list[QuestionView]:
    """Signature's open questions, numbered from 1; the numbers are remembered for answer_questions."""
    questions = await session.signature.open_questions()
    numbered = dict(enumerate(questions, start=1))
    progress = session.progress.load()
    session.progress.save(progress.model_copy(update={'question_ids': {n: q.id for n, q in numbered.items()}}))
    return [_view(number, question) for number, question in numbered.items()]


async def _prepared(signature: Signature) -> Preparation | None:
    """Signature's preparation of the published domain, once it is no longer underway or the wait runs out."""
    with anyio.move_on_after(WAIT_SECONDS):
        while (found := await signature.preparation()) is not None and found.underway:
            await anyio.sleep(POLL_SECONDS)
        return found
    return await signature.preparation()


def _readiness(preparation: Preparation | None) -> str:
    """What to tell Claude about asking questions once the domain is published."""
    if preparation is None or preparation.state == 'succeeded':
        return 'Published. The customer can now ask questions.'
    if preparation.underway:
        return (
            'Published. Signature is still getting ready to answer questions; a question asked now waits for '
            'it, so it may take a few minutes.'
        )
    return (
        f'Published, but Signature could not get ready to answer questions: {preparation.reason}. Tell the '
        'customer, and do not ask questions until it is fixed.'
    )


async def _waited[T](fetch: Callable[[], Awaitable[T]], pending: Callable[[T], bool]) -> T | None:
    """What fetch returns once it is no longer pending, or None if that takes longer than the wait."""
    with anyio.move_on_after(WAIT_SECONDS):
        while pending(found := await fetch()):
            await anyio.sleep(POLL_SECONDS)
        return found
    return None


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
