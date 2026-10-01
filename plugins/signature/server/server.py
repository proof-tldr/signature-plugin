# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.2.0"]
# ///
"""Signature's MCP server, run on the member's machine over stdio. It reaches Signature's hosted MCP endpoint with
the member's key, and leaves each answer for the plugin's hook to show the member: the model learns only that it
was shown."""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import TypedDict

from mcp.client.session import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import answer_handoff
import signature_api


class AskedResult(TypedDict):
    """What the model learns from ask_question; the hook finds the answer by its turn_id."""
    thread_id: str
    turn_id: str
    note: str


server = MCPServer('signature', instructions='Answers to questions are shown to the user, never to you.')


@server.tool(description='Lists the domains in this workspace. A domain is a business data model you can ask '
                         'questions about.')
async def list_domains() -> str:
    return json.dumps(await through_signature(signature_api.list_domains))


@server.tool(description='Returns a domain’s whole model: its scalars, entities, fields, functions and axioms.')
async def describe_domain(domain_id: str) -> str:
    return json.dumps(await through_signature(lambda session: signature_api.describe_domain(session, domain_id)))


@server.tool(description='Asks a question about a published domain’s data and shows the answer to the user. '
                         'Pass a thread_id from an earlier ask_question to ask a follow-up in the same thread.')
async def ask_question(domain_id: str, question: str, ctx: Context, thread_id: str | None = None) -> AskedResult:
    async def asked_and_ended(session: ClientSession) -> tuple[signature_api.Asked, signature_api.Outcome]:
        asked = await signature_api.ask(session, domain_id, question, thread_id)
        await ctx.report_progress(0, message='Signature is answering…')
        return asked, await signature_api.outcome(session, domain_id, asked)

    asked, ended = await through_signature(asked_and_ended)
    shown, told = shown_and_told(ended)
    answer_handoff.leave(asked.turn_id, shown)
    return AskedResult(thread_id=asked.thread_id, turn_id=asked.turn_id,
                       note=f'{told} For a follow-up, call ask_question with this thread_id.')


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


async def through_signature[T](work: Callable[[ClientSession], Awaitable[T]]) -> T:
    """The work done in a session with Signature, its failures told to the model as tool errors."""
    try:
        return await signature_api.in_session(work)
    except signature_api.SignatureRefused as refused:
        raise ToolError(str(refused)) from refused
    except signature_api.SignatureUnreachable as unreachable:
        raise ToolError('Signature could not be reached. Try again in a moment.') from unreachable


if __name__ == '__main__':
    logging.getLogger('httpx2').setLevel(logging.WARNING)
    server.run()
