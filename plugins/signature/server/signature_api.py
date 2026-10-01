"""Signature's REST API as this machine reaches it, with the member's API key: the workspace's domains, and a
question asked and followed to its outcome."""

import asyncio
import base64
import hashlib
import mimetypes
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx2

KEY_REJECTED = 'Signature did not accept your API key. Run /plugin configure signature@signature to enter a new one.'
POLL_SECONDS = 1.0
WAIT_SECONDS = 570.0
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_DOCUMENTS = 12
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class SignatureRefused(Exception):
    """A request Signature refused, with the reason it gave."""


class NotFound(SignatureRefused):
    """Signature has nothing at that address."""


class DocumentRefused(Exception):
    """A file that cannot be handed to Signature, with the reason."""


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
    reason = problem.get('detail') or problem.get('title') or response.reason_phrase
    raise NotFound(reason) if response.status_code == 404 else SignatureRefused(reason)


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


async def outcome(signature: Signature, domain_id: str, turn_id: str) -> Outcome:
    """A turn's outcome, waited for while it is pending, up to WAIT_SECONDS."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_SECONDS
    while loop.time() < deadline:
        turn = await body_of(signature, 'GET', f'/domains/{domain_id}/conversation/turns/{turn_id}')
        if turn['state'] == 'answered':
            return Answered(turn['reply'])
        if turn['state'] == 'failed':
            return Failed()
        await asyncio.sleep(POLL_SECONDS)
    return StillWorking()


@dataclass(frozen=True)
class Upload:
    """A document's bytes, and what Signature's storage checks them against."""
    kind: str
    filename: str
    content: bytes
    content_type: str
    checksum: str


@dataclass(frozen=True)
class StagedSource:
    """A document stored with Signature, ready for a build turn to read."""
    kind: str
    filename: str
    content_ref: str


async def create_domain(signature: Signature, name: str, description: str | None) -> dict:
    return await body_of(signature, 'POST', '/domains',
                         json={'name': name} | ({'description': description} if description else {}))


def uploads_of(files: list[tuple[str, str]]) -> list[Upload]:
    """The (path, kind) files read and checked against Signature's limits; a file it would refuse raised."""
    if len(files) > MAX_DOCUMENTS:
        raise DocumentRefused(f'Signature takes at most {MAX_DOCUMENTS} documents at once.')
    return [upload_of(Path(path).expanduser(), kind) for path, kind in files]


def upload_of(path: Path, kind: str) -> Upload:
    try:
        content = path.read_bytes()
    except OSError as failure:
        raise DocumentRefused(f'Could not read {path}: {failure.strerror}.') from failure
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentRefused(f'{path.name} is over {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.')
    return Upload(kind=kind, filename=path.name, content=content,
                  content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                  checksum=base64.b64encode(hashlib.sha256(content).digest()).decode())


async def staged(signature: Signature, domain_id: str, upload: Upload) -> StagedSource:
    """The upload stored with Signature. Storage is reached at a presigned address, without the member's key."""
    promised = await body_of(signature, 'POST', f'/domains/{domain_id}/documents/presign',
                             json={'kind': upload.kind, 'filename': upload.filename,
                                   'contentType': upload.content_type, 'size': len(upload.content),
                                   'checksumSha256': upload.checksum})
    try:
        async with httpx2.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as storage:
            stored = await storage.put(promised['url'], content=upload.content,
                                       headers={'content-type': upload.content_type,
                                                'x-amz-checksum-sha256': upload.checksum})
    except httpx2.HTTPError as failure:
        raise SignatureUnreachable() from failure
    if stored.is_error:
        raise SignatureRefused(f'Signature could not store {upload.filename}.')
    return StagedSource(kind=upload.kind, filename=upload.filename, content_ref=promised['contentRef'])


async def build(signature: Signature, domain_id: str, text: str | None, sources: list[StagedSource]) -> str:
    """One build turn: what the member's Claude says and hands over. Its id, to follow with `outcome`."""
    accepted = await body_of(signature, 'POST', f'/domains/{domain_id}/conversation/turns',
                             json={'idempotencyKey': str(uuid.uuid4())} | ({'text': text} if text else {})
                             | ({'sources': [{'kind': source.kind, 'filename': source.filename,
                                                 'contentRef': source.content_ref} for source in sources]}
                                if sources else {}))
    return accepted['turn']['id']


async def clarifying_questions(signature: Signature, domain_id: str) -> list[dict]:
    return (await body_of(signature, 'GET', f'/domains/{domain_id}/conversation/clarifying-questions'))['questions']


async def answer_clarification(signature: Signature, domain_id: str, question_id: str, answer: str) -> str:
    """One open question answered; the id of the turn Signature builds from it."""
    accepted = await body_of(signature, 'POST',
                             f'/domains/{domain_id}/conversation/clarifying-questions/{question_id}/answer',
                             json={'answer': answer})
    return accepted['turn']['id']


async def domain(signature: Signature, domain_id: str) -> dict:
    return await body_of(signature, 'GET', f'/domains/{domain_id}')


async def published_at(signature: Signature, domain_id: str) -> str | None:
    """When the domain was last published, or None while it never has been."""
    try:
        return (await body_of(signature, 'GET', f'/domains/{domain_id}/publication'))['publishedAt']
    except NotFound:
        return None


def source_id_of(domain_id: str, service: str) -> str:
    """The id Signature knows a local source by, the same on every report so a re-report replaces the last."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'signature-plugin:source:{domain_id}:{service}'))


async def report_source(signature: Signature, domain_id: str, service: str, database: dict) -> dict:
    """A source's structure, read on the member's machine, replacing what Signature held for that service."""
    source_id = source_id_of(domain_id, service)
    return await body_of(signature, 'PUT', f'/domains/{domain_id}/model/sources/{source_id}/catalog',
                         json={'name': service, 'database': database})
