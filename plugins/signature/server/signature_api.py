"""Signature's REST API as this machine reaches it, with the member's API key: the workspace's domains, and a
question asked and followed to its outcome."""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2

KEY_REJECTED = 'Signature did not accept your API key. Run /plugin configure signature@signature to enter a new one.'
POLL_SECONDS = 1.0
WAIT_SECONDS = 570.0
REQUEST_TIMEOUT_SECONDS = 30.0


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


type Signature = httpx2.AsyncClient


async def in_session[T](work: Callable[[Signature], Awaitable[T]]) -> T:
    """The work's result, done with one connection to Signature that presents the member's key."""
    async with httpx2.AsyncClient(base_url=os.environ['SIGNATURE_API_URL'],
                                  headers={'authorization': f'Bearer {os.environ["SIGNATURE_API_KEY"]}'},
                                  timeout=REQUEST_TIMEOUT_SECONDS) as signature:
        return await work(signature)


async def body_of(signature: Signature, method: str, path: str, *, params: dict | None = None,
                  json: dict | None = None) -> dict:
    """The body of a request Signature accepted; a refusal raised with the reason Signature gave."""
    try:
        response = await signature.request(method, path, params=params, json=json)
    except httpx2.HTTPError as failure:
        raise SignatureUnreachable() from failure
    if response.status_code in (401, 403) and not is_problem(response):
        raise SignatureRefused(KEY_REJECTED)
    if response.status_code >= 500 or not response.is_error:
        if response.is_error:
            raise SignatureUnreachable()
        return response.json()
    try:
        problem = response.json() if is_problem(response) else {}
    except ValueError:  # a malformed problem body still refuses, with the status's own words
        problem = {}
    raise SignatureRefused(problem.get('detail') or problem.get('title') or response.reason_phrase)


def is_problem(response: httpx2.Response) -> bool:
    """Whether Signature itself refused: the gateway's refusals carry no problem details."""
    return response.headers.get('content-type', '').startswith('application/problem+json')


async def list_domains(signature: Signature) -> dict:
    return await body_of(signature, 'GET', '/domains')


async def describe_domain(signature: Signature, domain_id: str) -> dict:
    return await body_of(signature, 'GET', f'/domains/{domain_id}/model/snapshot')


async def ask(signature: Signature, domain_id: str, question: str, thread_id: str | None) -> Asked:
    thread_id = thread_id or str(uuid.uuid4())
    accepted = await body_of(signature, 'POST', f'/domains/{domain_id}/conversation/questions',
                             json={'idempotencyKey': str(uuid.uuid4()), 'text': question, 'threadId': thread_id})
    return Asked(thread_id, accepted['turn']['id'])


async def outcome(signature: Signature, domain_id: str, asked: Asked) -> Outcome:
    """The question's outcome, waited for while it is pending, up to WAIT_SECONDS."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_SECONDS
    while loop.time() < deadline:
        turn = await body_of(signature, 'GET', f'/domains/{domain_id}/conversation/turns/{asked.turn_id}')
        if turn['state'] == 'answered':
            return Answered(turn['reply'])
        if turn['state'] == 'failed':
            return Failed()
        await asyncio.sleep(POLL_SECONDS)
    return StillWorking()
