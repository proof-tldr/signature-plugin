"""Signature's hosted MCP endpoint as this machine reaches it, with the member's API key: the workspace's
domains, and a question asked and followed to its outcome."""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

KEY_REJECTED = 'Signature did not accept your API key. Run /plugin configure signature@signature to enter a new one.'
POLL_SECONDS = 1.0
WAIT_SECONDS = 570.0


class SignatureRefused(Exception):
    """A request Signature refused, with the reason it gave."""


class SignatureUnreachable(Exception):
    """Signature could not be reached."""


@dataclass(frozen=True)
class Asked:
    thread_id: str
    turn_id: str


@dataclass(frozen=True)
class Answered:
    text: str


@dataclass(frozen=True)
class Failed:
    """Signature could not answer the question."""


@dataclass(frozen=True)
class StillWorking:
    """Signature had not answered by the time the wait ended."""


type Outcome = Answered | Failed | StillWorking


async def in_session[T](work: Callable[[ClientSession], Awaitable[T]]) -> T:
    """The work's result in one session with Signature. Failures are raised once the session has closed, so they
    are not wrapped in the connection's task group; the SDK reports a refused key only as a failed request, so the
    responses' statuses tell it apart."""
    statuses: list[int] = []

    async def remember(response: httpx2.Response) -> None:
        statuses.append(response.status_code)

    headers = {'authorization': f'Bearer {os.environ["SIGNATURE_API_KEY"]}'}
    try:
        async with httpx2.AsyncClient(headers=headers, event_hooks={'response': [remember]}) as http, \
                streamable_http_client(os.environ['SIGNATURE_MCP_URL'], http_client=http) as (read, write), \
                ClientSession(read, write) as session:
            await session.initialize()
            try:
                return await work(session)
            except SignatureRefused as refused:
                refusal = refused
    except (httpx2.HTTPError, MCPError, ExceptionGroup) as failure:
        if {401, 403} & set(statuses):
            raise SignatureRefused(KEY_REJECTED) from failure
        raise SignatureUnreachable() from failure
    raise refusal


async def call(session: ClientSession, tool: str, arguments: dict[str, str]) -> dict:
    result = await session.call_tool(tool, arguments)
    text = next((part.text for part in result.content if part.type == 'text'), '')
    if result.is_error:
        raise SignatureRefused(text)
    return json.loads(text)


async def list_domains(session: ClientSession) -> dict:
    return await call(session, 'list_domains', {})


async def describe_domain(session: ClientSession, domain_id: str) -> dict:
    return await call(session, 'describe_domain', {'domainId': domain_id})


async def ask(session: ClientSession, domain_id: str, question: str, thread_id: str | None) -> Asked:
    arguments = {'domainId': domain_id, 'question': question} | ({'threadId': thread_id} if thread_id else {})
    accepted = await call(session, 'ask_question', arguments)
    return Asked(accepted['threadId'], accepted['turnId'])


async def outcome(session: ClientSession, domain_id: str, asked: Asked) -> Outcome:
    """The question's outcome, waited for while it is pending, up to WAIT_SECONDS."""
    arguments = {'domainId': domain_id, 'threadId': asked.thread_id, 'turnId': asked.turn_id}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_SECONDS
    while loop.time() < deadline:
        turn = await call(session, 'get_answer', arguments)
        if turn['state'] == 'answered':
            return Answered(turn['answer'])
        if turn['state'] == 'failed':
            return Failed()
        await asyncio.sleep(POLL_SECONDS)
    return StillWorking()
