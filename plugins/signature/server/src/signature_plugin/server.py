"""Signature's MCP server, run by Claude Code on the customer's machine. Its tools take a domain from sources
and documents to published, and answer questions about it by running Signature's SQL here, on the customer's
own data. Answers go to the customer; Claude only learns that they were shown."""

import asyncio
import functools
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from signature_plugin import handoff, local_data, presentation
from signature_plugin.backend import (
    OpenQuestion,
    Signature,
    SignatureRefused,
    SignatureUnreachable,
    connected,
)
from signature_plugin.local_data import QueryRefused
from signature_plugin.pages import Page, Pages, Refusal
from signature_plugin.settings import NotConfigured, from_environment
from signature_plugin.sources import DatabaseSource, FileSource, Source, SourceRefused, Sources

POLL_SECONDS = 1.0
WAIT_SECONDS = 540.0

INSTRUCTIONS = """Signature turns the customer's data and documents into a domain it can answer questions about
with proven SQL. Your API key opens exactly one domain, so you never choose one.

To set one up, follow the setup skill: ask the customer where their data lives, add those files and databases
as sources, take the documents they give you, build, answer Signature's questions with them, then open the
review so they can publish. Pass documents as they are; do not go looking for more.

Answers to questions are shown to the customer, never to you. Do not guess, restate or summarise them."""


class Waiting(TypedDict):
    state: Literal['waiting']
    note: str


class SourceSummary(TypedDict):
    name: str
    kind: Literal['file', 'database']
    location: str


class QuestionView(TypedDict):
    question_id: str
    question: str
    suggested_answers: list[str]


class Status(TypedDict):
    domain: str
    published_at: str | None
    sources: list[SourceSummary]
    open_questions: list[QuestionView]


class Added(TypedDict):
    source: str
    tables: int
    columns: int


class BuildProgress(TypedDict):
    state: Literal['built', 'questions', 'building', 'failed']
    turn_id: str
    reply: str | None
    open_questions: list[QuestionView]
    note: str


class Answer(TypedDict):
    question_id: str
    answer: str
    from_customer: bool


class Reviewed(TypedDict):
    state: Literal['published', 'changes_requested']
    note: str
    build: BuildProgress | None


class Asked(TypedDict):
    query_id: str
    thread_id: str
    note: str


@dataclass
class PluginState:
    pages: Pages
    waiting_pages: dict[Literal['connect', 'review'], Page[Any]]


@dataclass(frozen=True)
class Session:
    """Signature, bound to the key's one domain, and the sources this machine holds for that domain."""

    signature: Signature
    sources: Sources


@dataclass(frozen=True)
class ReviewDecision:
    publish: bool
    changes: str


@asynccontextmanager
async def _plugin_state(_server: MCPServer[PluginState]) -> AsyncGenerator[PluginState]:
    yield PluginState(pages=Pages(), waiting_pages={})


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
        yield Session(signature=signature, sources=Sources(settings.data_dir / signature.domain_id))


@server.tool(
    description="Where the customer's Signature domain stands: its name, whether it is published, "
    'the sources added so far, and the questions Signature is waiting on.'
)
@_tool_errors
async def get_status(ctx: Context[PluginState]) -> Status:
    async with _session() as session:
        domain = await session.signature.domain()
        return Status(
            domain=domain.name,
            published_at=domain.published_at,
            sources=[_summary(source) for source in session.sources.all()],
            open_questions=_views(await session.signature.open_questions()),
        )


@server.tool(
    description="Adds the customer's data files as sources: CSV, TSV, XLSX, Parquet or JSON files, or "
    'folders of them. Give absolute paths. The files stay on this machine; Signature is told '
    'their structure and a few example values when you build.'
)
@_tool_errors
async def add_data_files(paths: list[str], ctx: Context[PluginState]) -> list[Added]:
    async with _session() as session:
        added = session.sources.add_files(paths)
        try:
            return [await _checked(source) for source in added]
        except SourceRefused:
            for source in added:
                session.sources.remove(source.name)
            raise


@server.tool(
    description="Opens a page in the customer's browser where they connect a PostgreSQL or MySQL "
    'database themselves, so its password never passes through you. Waits until they have '
    'connected it. Call once per database.'
)
@_tool_errors
async def connect_database(ctx: Context[PluginState], suggested_name: str | None = None) -> Added | Waiting:
    async with _session() as session:
        sources = session.sources

    async def connected_from(form: dict[str, str]) -> DatabaseSource | Refusal:
        return await _database_connected(sources, form)

    source = await _decision_on_page(
        ctx,
        'connect',
        lambda pages: pages.show('connect.html', {'suggested_name': suggested_name}, connected_from),
        'Waiting for the customer to connect their database…',
    )
    if source is None:
        return Waiting(state='waiting', note='The page is still open. Call connect_database again to keep waiting.')
    return await _checked(source)


@server.tool(description='Removes a source the customer no longer wants Signature to use.')
@_tool_errors
async def remove_source(name: str, ctx: Context[PluginState]) -> str:
    async with _session() as session:
        session.sources.remove(name)
    return f'{name} removed. Build again for Signature to drop it.'


@server.tool(
    description='Builds the domain: tells Signature the structure of every source added so far and '
    'hands it the documents at the given absolute paths, exactly as they are. `note` is '
    'anything the customer said that Signature should know. Waits while Signature builds and '
    'returns its reply and any questions it has.'
)
@_tool_errors
async def build(
    ctx: Context[PluginState], documents: list[str] | None = None, note: str | None = None
) -> BuildProgress:
    async with _session() as session:
        signature, sources = session.signature, session.sources.all()
        if not sources and not documents:
            raise ToolError("There is nothing to build from yet: add the customer's data or documents first.")
        await ctx.report_progress(0, message='Telling Signature about your data…')
        catalogs = await anyio.to_thread.run_sync(local_data.catalogs, sources)
        for source in sources:
            await signature.report_source(_source_id(signature, source), source.name, catalogs[source.name])
        await ctx.report_progress(0, message='Uploading your documents…')
        staged = [await signature.stage_document(path) for path in documents or []]
        turn_id = await signature.start_build(note, staged)
        return await _followed(signature, turn_id, ctx)


@server.tool(
    description="Answers Signature's open questions. Set from_customer to false for an answer you "
    'worked out yourself rather than heard from the customer, so Signature knows to treat it '
    'as unconfirmed. Waits while Signature continues building.'
)
@_tool_errors
async def answer_questions(answers: list[Answer], ctx: Context[PluginState]) -> BuildProgress:
    if not answers:
        raise ToolError('Give at least one answer.')
    async with _session() as session:
        turn_ids = [
            await session.signature.answer_question(given['question_id'], _attributed(given)) for given in answers
        ]
        return await _followed(session.signature, turn_ids[-1], ctx)


@server.tool(description='Keeps waiting on a build that was still going when the last call returned.')
@_tool_errors
async def wait_for_build(turn_id: str, ctx: Context[PluginState]) -> BuildProgress:
    async with _session() as session:
        return await _followed(session.signature, turn_id, ctx)


@server.tool(
    description="Opens the review page in the customer's browser: the domain in plain terms, with a "
    'button to publish it or a box to say what is wrong. Waits for their decision. Publishing '
    'happens there; a requested change is sent to Signature and rebuilt.'
)
@_tool_errors
async def review(ctx: Context[PluginState]) -> Reviewed | Waiting:
    async with _session() as session:
        signature = session.signature

        async def review_page(pages: Pages) -> Page[ReviewDecision]:
            domain = await signature.domain()
            context = {'domain_name': domain.name, 'review': await signature.review()}
            return await pages.show('review.html', context, _review_decision)

        decision = await _decision_on_page(ctx, 'review', review_page, 'Waiting for the customer to review…')
        if decision is None:
            return Waiting(state='waiting', note='The review is still open. Call review again to keep waiting.')
        if decision.publish:
            await signature.publish()
            return Reviewed(state='published', note='Published. The customer can now ask questions.', build=None)
        turn_id = await signature.start_build(decision.changes, [])
        return Reviewed(
            state='changes_requested',
            note='The customer asked for changes, which were sent to Signature. Open the review again once the '
            'build has no open questions.',
            build=await _followed(signature, turn_id, ctx),
        )


@server.tool(
    description="Asks Signature a question about the customer's published domain. Signature writes the "
    "SQL; it runs here on the customer's data, and the answer is shown to the customer, not to "
    'you. Pass the thread_id from an earlier answer for a follow-up.'
)
@_tool_errors
async def ask_question(question: str, ctx: Context[PluginState], thread_id: str | None = None) -> Asked:
    async with _session() as session:
        signature = session.signature
        query_id = await signature.plan_query(question, thread_id)
        await ctx.report_progress(0, message='Signature is working out the query…')
        plan = await _waited(lambda: signature.query(query_id), lambda found: found.state == 'pending')
        if plan is None:
            raise ToolError('Signature took too long to work out the query. Ask again.')
        match plan.state:
            case 'planned' if plan.sql:
                await ctx.report_progress(0, message='Running it on your data…')
                result = await anyio.to_thread.run_sync(local_data.run, session.sources.all(), plan.sql)
                handoff.leave(query_id, presentation.rendered(plan.reading, result))
                told = 'The answer was shown to the customer.'
            case 'unanswerable':
                handoff.leave(query_id, f"Signature can't answer this from your domain: {plan.reason}")
                told = 'Signature could not answer this from the domain, and the customer was told why.'
            case _:
                raise ToolError('Signature could not work out a query for this question.')
        return Asked(
            query_id=query_id,
            thread_id=plan.thread_id,
            note=f'{told} You cannot see it. For a follow-up, pass this thread_id.',
        )


async def _checked(source: Source) -> Added:
    tables = await anyio.to_thread.run_sync(local_data.check, source)
    return Added(source=source.name, tables=len(tables), columns=sum(table.columns for table in tables))


async def _database_connected(sources: Sources, form: dict[str, str]) -> DatabaseSource | Refusal:
    """The database the form describes, connected and kept; or why it could not be, for the page to show."""
    engine = 'mysql' if form.get('engine') == 'mysql' else 'postgres'
    try:
        port = int(form.get('port') or (3306 if engine == 'mysql' else 5432))
    except ValueError:
        return Refusal('The port must be a number.')
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
        await anyio.to_thread.run_sync(local_data.check, source)
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
    purpose: Literal['connect', 'review'],
    opened: Callable[[Pages], Awaitable[Page[T]]],
    waiting_message: str,
) -> T | None:
    """The customer's decision on the page for that purpose: the one still waiting from an earlier call,
    brought up again, or a new one. None if they have not decided within the wait; the page stays open."""
    state = ctx.request_context.lifespan_context
    page: Page[T] | None = state.waiting_pages.get(purpose)
    if page is None:
        page = await opened(state.pages)
        state.waiting_pages[purpose] = page
    else:
        state.pages.reopen(page)
    await ctx.report_progress(0, message=waiting_message)
    try:
        decision = await asyncio.wait_for(asyncio.shield(page.decided), WAIT_SECONDS)
    except TimeoutError:
        return None
    del state.waiting_pages[purpose]
    state.pages.close(page)
    return decision


async def _followed(signature: Signature, turn_id: str, ctx: Context[PluginState]) -> BuildProgress:
    """The build turn followed until it ends, or until the wait runs out, with what Claude should do next."""
    await ctx.report_progress(0, message='Signature is building your domain…')
    turn = await _waited(lambda: signature.turn(turn_id), lambda found: found.state == 'pending')
    if turn is None:
        return BuildProgress(
            state='building',
            turn_id=turn_id,
            reply=None,
            open_questions=[],
            note='Signature is still building. Call wait_for_build with this turn_id.',
        )
    if turn.state == 'failed':
        return BuildProgress(
            state='failed',
            turn_id=turn_id,
            reply=None,
            open_questions=[],
            note='Signature could not finish this build. Try again, or hand it less at once.',
        )
    questions = _views(await signature.open_questions())
    if questions:
        return BuildProgress(
            state='questions',
            turn_id=turn_id,
            reply=turn.reply,
            open_questions=questions,
            note='Answer what you can from what the customer told you or gave you; ask the '
            'customer the rest together, then call answer_questions.',
        )
    return BuildProgress(
        state='built',
        turn_id=turn_id,
        reply=turn.reply,
        open_questions=[],
        note='Nothing is open. Tell the customer what Signature did, then call review.',
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


def _source_id(signature: Signature, source: Source) -> str:
    """The id Signature knows a source by, the same on every build so a new report replaces the last."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'signature-plugin:{signature.domain_id}:{source.name}'))


def _summary(source: Source) -> SourceSummary:
    if isinstance(source, FileSource):
        return SourceSummary(name=source.name, kind='file', location=source.path)
    return SourceSummary(
        name=source.name, kind='database', location=f'{source.engine}://{source.host}:{source.port}/{source.database}'
    )


def _views(questions: list[OpenQuestion]) -> list[QuestionView]:
    return [
        QuestionView(question_id=question.id, question=question.question, suggested_answers=question.suggested_answers)
        for question in questions
    ]


def main() -> None:
    server.run()
