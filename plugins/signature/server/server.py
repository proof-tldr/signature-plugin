# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.2.0", "psycopg[binary]>=3.2", "duckdb>=1.4"]
# ///
"""Signature's MCP server, run on the member's machine over stdio. It calls Signature's REST API with the
member's key, and leaves each answer for the plugin's hook to show the member: the model learns only that it
was shown."""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Literal, TypedDict

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import answer_handoff
import catalog_readers
import local_files
import signature_api


class AskedResult(TypedDict):
    """What the model learns from ask_question; the hook finds the answer by its turn_id."""
    thread_id: str
    turn_id: str
    note: str


INSTRUCTIONS = '''Answers to questions are shown to the user, never to you.
You build a Signature domain with the user: you already know much of their business and files, so hand Signature
what you can find and explain what it means, and ask the user only what you cannot tell.'''

server = MCPServer('signature', instructions=INSTRUCTIONS)


@server.tool(description='Lists the domains in this workspace. A domain is a business data model you can ask '
                         'questions about.')
async def list_domains() -> str:
    return json.dumps(await through_signature(signature_api.list_domains))


@server.tool(description='Returns a domain’s whole model: its scalars, entities, fields, functions and axioms.')
async def describe_domain(domain_id: str) -> str:
    return json.dumps(await through_signature(lambda signature: signature_api.describe_domain(signature, domain_id)))


@server.tool(description='Asks a question about a published domain’s data and shows the answer to the user. '
                         'Pass a thread_id from an earlier ask_question to ask a follow-up in the same thread.')
async def ask_question(domain_id: str, question: str, ctx: Context, thread_id: str | None = None) -> AskedResult:
    async def asked_and_ended(signature: signature_api.Signature) -> tuple[signature_api.Asked, signature_api.Outcome]:
        asked = await signature_api.ask(signature, domain_id, question, thread_id)
        await ctx.report_progress(0, message='Signature is answering…')
        return asked, await signature_api.outcome(signature, domain_id, asked.turn_id)

    asked, ended = await through_signature(asked_and_ended)
    shown, told = shown_and_told(ended)
    answer_handoff.leave(asked.turn_id, shown)
    return AskedResult(thread_id=asked.thread_id, turn_id=asked.turn_id,
                       note=f'{told} For a follow-up, call ask_question with this thread_id.')


class Built(TypedDict):
    """What the model learns from a build turn Signature finished: its reply, and what it still needs to know."""
    reply: str
    open_questions: list[dict]
    note: str


class StillBuilding(TypedDict):
    """What the model learns from a build turn Signature had not finished by the time the wait ended."""
    note: str


BUILT = 'Tell the user what Signature did.'
BUILT_WITH_QUESTIONS = ('Tell the user what Signature did. Answer the open questions you can from what you know; '
                        'ask the user the rest.')
STILL_BUILDING = 'Signature is still building. Check get_domain_status in a moment.'
BUILD_FAILED = 'Signature could not finish building from this. Try again, or hand it less at once.'


class SourceFile(TypedDict):
    path: str
    kind: Literal['policy', 'spec', 'notes']


class DomainStatus(TypedDict):
    name: str
    description: str | None
    published_at: str | None
    open_questions: list[dict]


@server.tool(description='Creates a new, empty domain in this workspace, and returns it with its id.')
async def create_domain(name: str, description: str | None = None) -> str:
    return json.dumps(await through_signature(
        lambda signature: signature_api.create_domain(signature, name, description)))


@server.tool(description='Hands Signature files that describe the business: policies, specs or notes, up to 12, '
                         '5 MB each. Explain what they mean and how they relate in `explanation`. Signature builds '
                         'the domain from them and replies.')
async def add_documents(domain_id: str, files: list[SourceFile], ctx: Context,
                        explanation: str | None = None) -> Built | StillBuilding:
    async def built(signature: signature_api.Signature) -> Built | StillBuilding:
        uploads = signature_api.uploads_of([(file['path'], file['kind']) for file in files])
        sources = [await signature_api.staged(signature, domain_id, upload) for upload in uploads]
        return await built_from(signature, domain_id, explanation, sources, ctx)

    return await through_signature(built)


@server.tool(description='Tells Signature how the user\'s data relates to the domain\'s concepts: what a table or '
                         'file holds, what its rows mean, what its codes stand for. Say which claims the user made '
                         'and which you inferred. Signature uses it to build and replies.')
async def describe_dataset(domain_id: str, explanation: str, ctx: Context) -> Built | StillBuilding:
    return await through_signature(lambda signature: built_from(signature, domain_id, explanation, [], ctx))


class SourceReported(TypedDict):
    """What the model learns from reporting a local source: which source, and how many tables, never the structure itself."""
    source: str
    tables: int


async def report_local_source(domain_id: str, adapter: str, location: str, name: str) -> SourceReported:
    """Reads the structure of what a location names on this machine and reports it to the domain under `name`."""
    try:
        structure = await catalog_readers.read_structure(adapter, location)
    except catalog_readers.SourceNotUsable as unusable:
        raise ToolError(str(unusable)) from unusable
    await through_signature(lambda signature: signature_api.report_source(
        signature, domain_id, structure.database, location=location, name=name))
    return SourceReported(source=name, tables=structure.tables)


@server.tool(description='Reports the structure (tables, columns, keys; never rows) of one of the user\'s local '
                         'Postgres databases to a domain. `service` is a connection service name the user defined '
                         'in their ~/.pg_service.conf; the plugin reads and sends the structure itself, and you '
                         'never see or write it.')
async def report_source(domain_id: str, service: str) -> SourceReported:
    return await report_local_source(domain_id, 'postgresql', service, service)


@server.tool(description='Reports the structure (files, their columns and inferred types; never rows) of csv, tsv, parquet, '
                         'json or xlsx files on the user\'s machine to a domain. `path` is one file, a folder of files '
                         'or a glob such as ~/data/*.csv: only where to look. The plugin reads and sends the structure '
                         'itself, and you never see or write it; the user confirms the inferred types in the review.')
async def report_files(domain_id: str, path: str) -> SourceReported:
    location = local_files.absolute_location(path)
    return await report_local_source(domain_id, 'files', location, local_files.source_name_of(location))


@server.tool(description='Lists the questions Signature has asked about the domain and not yet had answered.')
async def list_clarifications(domain_id: str) -> str:
    return json.dumps(await through_signature(
        lambda signature: signature_api.clarifying_questions(signature, domain_id)))


@server.tool(description='Answers one open question Signature asked about the domain, by its id from '
                         'list_clarifications, with the answer the user gave or you know to be true. '
                         'Signature takes the answer, continues building and replies.')
async def answer_clarification(domain_id: str, question_id: str, answer: str, ctx: Context) -> Built | StillBuilding:
    async def built(signature: signature_api.Signature) -> Built | StillBuilding:
        turn_id = await signature_api.answer_clarification(signature, domain_id, question_id, answer)
        return await followed(signature, domain_id, turn_id, ctx)

    return await through_signature(built)


@server.tool(description='Returns where a domain stands: its name, when it was last published (null if never), '
                         'and the questions Signature still has about it.')
async def get_domain_status(domain_id: str) -> DomainStatus:
    async def status(signature: signature_api.Signature) -> DomainStatus:
        found = await signature_api.domain(signature, domain_id)
        return DomainStatus(name=found['name'], description=found['description'],
                            published_at=await signature_api.published_at(signature, domain_id),
                            open_questions=await signature_api.clarifying_questions(signature, domain_id))

    return await through_signature(status)


async def built_from(signature: signature_api.Signature, domain_id: str, text: str | None,
                     sources: list[signature_api.StagedSource], ctx: Context) -> Built | StillBuilding:
    """One build turn sent and followed to its end."""
    turn_id = await signature_api.build(signature, domain_id, text, sources)
    return await followed(signature, domain_id, turn_id, ctx)


async def followed(signature: signature_api.Signature, domain_id: str, turn_id: str,
                   ctx: Context) -> Built | StillBuilding:
    """A build turn followed to its end, with the questions it leaves open."""
    await ctx.report_progress(0, message='Signature is building…')
    match await signature_api.outcome(signature, domain_id, turn_id):
        case signature_api.Answered(reply):
            questions = await signature_api.clarifying_questions(signature, domain_id)
            return Built(reply=reply, open_questions=questions, note=BUILT_WITH_QUESTIONS if questions else BUILT)
        case signature_api.Failed():
            raise ToolError(BUILD_FAILED)
        case signature_api.StillWorking():
            return StillBuilding(note=STILL_BUILDING)


def shown_and_told(ended: signature_api.Outcome) -> tuple[str, str]:
    """What the member is shown, and what the model is told, for the way the question ended."""
    match ended:
        case signature_api.Answered(text):
            return text, ('The answer was shown directly to the user. You cannot see it and must not guess, '
                          'restate or summarise it.')
        case signature_api.Failed():
            return ('Signature couldn’t answer this question.',
                    'Signature couldn’t answer this question, and the user was told.')
        case signature_api.StillWorking():
            return ('Signature is still working on this answer. Ask again in a moment.',
                    'Signature did not answer in time, and the user was told.')


async def through_signature[T](work: Callable[[signature_api.Signature], Awaitable[T]]) -> T:
    """The work done with Signature's API, its failures told to the model as tool errors."""
    try:
        return await signature_api.with_signature(work)
    except signature_api.SignatureRefused as refused:
        raise ToolError(str(refused)) from refused
    except signature_api.DocumentRefused as refused:
        raise ToolError(str(refused)) from refused
    except signature_api.SignatureUnreachable as unreachable:
        raise ToolError('Signature could not be reached. Try again in a moment.') from unreachable


if __name__ == '__main__':
    logging.getLogger('httpx2').setLevel(logging.WARNING)
    server.run()
