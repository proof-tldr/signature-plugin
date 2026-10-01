"""Signature's REST API, reached with the customer's domain-scoped key. docs/backend-contract.md lists every
operation used here and marks the ones Signature-Platform does not have yet."""

import base64
import hashlib
import mimetypes
import uuid
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx2

from signature_plugin.settings import Settings

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
# What the customer's local DuckDB is called as a source in Signature.
LOCAL_SOURCE_NAME = 'Your data'
# Signature asks what kind of document each is; the plugin hands documents over as they are, unclassified.
DOCUMENT_KIND = 'notes'


class SignatureRefused(Exception):
    """A request Signature refused, with the reason it gave."""


class SignatureUnreachable(Exception):
    """Signature could not be reached, or failed on its side."""


@dataclass(frozen=True)
class Domain:
    name: str
    published_at: str | None


@dataclass(frozen=True)
class StagedDocument:
    filename: str
    content_ref: str


type BuildState = Literal['pending', 'answered', 'failed']


@dataclass(frozen=True)
class BuildStatus:
    """Where a build stands; Signature's API calls a build a conversation turn."""

    state: BuildState
    reply: str | None


@dataclass(frozen=True)
class OpenQuestion:
    id: str
    question: str
    suggested_answers: list[str]


type QueryState = Literal['pending', 'planned', 'unanswerable', 'stale', 'failed']


@dataclass(frozen=True)
class QueryPlan:
    state: QueryState
    thread_id: str
    reading: str | None
    sql: str | None
    reason: str | None


class Signature:
    """One open connection to Signature, bound to the customer's one domain."""

    def __init__(self, client: httpx2.AsyncClient, domain_id: str) -> None:
        self._client = client
        self.domain_id = domain_id

    async def domain(self) -> Domain:
        found = await _body(self._client, 'GET', f'/domains/{self.domain_id}')
        publication = await _body(self._client, 'GET', f'/domains/{self.domain_id}/publication', absent_ok=True)
        return Domain(name=found['name'], published_at=publication['publishedAt'] if publication else None)

    async def stage_document(self, filename: str, content: bytes) -> StagedDocument:
        """The document stored with Signature as it is, ready for a build to read."""
        if len(content) > MAX_DOCUMENT_BYTES:
            raise SignatureRefused(f'{filename} is over {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.')
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
        promised = await _body(
            self._client,
            'POST',
            f'/domains/{self.domain_id}/documents/presign',
            json={
                'kind': DOCUMENT_KIND,
                'filename': filename,
                'contentType': content_type,
                'size': len(content),
                'checksumSha256': checksum,
            },
        )
        try:
            async with httpx2.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as storage:
                stored = await storage.put(
                    promised['url'],
                    content=content,
                    headers={'content-type': content_type, 'x-amz-checksum-sha256': checksum},
                )
        except httpx2.HTTPError as failure:
            raise SignatureUnreachable() from failure
        if stored.is_error:
            raise SignatureRefused(f'Signature could not store {filename}.')
        return StagedDocument(filename=filename, content_ref=promised['contentRef'])

    async def report_catalog(self, catalog: Mapping[str, object]) -> None:
        """The structure of the customer's whole local DuckDB, replacing what Signature held for it before. It is
        one source, under an id fixed for the domain, so each build replaces the last report."""
        source_id = uuid.uuid5(uuid.NAMESPACE_URL, f'signature-plugin:{self.domain_id}:local-duckdb')
        await _body(
            self._client,
            'PUT',
            f'/domains/{self.domain_id}/model/sources/{source_id}/catalog',
            json={'name': LOCAL_SOURCE_NAME, 'database': {'adapter': 'duckdb', 'catalog': catalog}},
        )

    async def start_build(self, text: str | None, documents: list[StagedDocument]) -> str:
        """A build over what was handed over; its id."""
        body: dict[str, Any] = {'idempotencyKey': str(uuid.uuid4())}
        if text:
            body['text'] = text
        if documents:
            body['sources'] = [
                {'kind': DOCUMENT_KIND, 'filename': document.filename, 'contentRef': document.content_ref}
                for document in documents
            ]
        accepted = await _body(self._client, 'POST', f'/domains/{self.domain_id}/conversation/turns', json=body)
        return accepted['turn']['id']

    async def build_status(self, build_id: str) -> BuildStatus:
        found = await _body(self._client, 'GET', f'/domains/{self.domain_id}/conversation/turns/{build_id}')
        return BuildStatus(state=found['state'], reply=found.get('reply'))

    async def open_questions(self) -> list[OpenQuestion]:
        found = await _body(self._client, 'GET', f'/domains/{self.domain_id}/conversation/clarifying-questions')
        return [
            OpenQuestion(
                id=question['id'], question=question['question'], suggested_answers=question.get('suggestedAnswers', [])
            )
            for question in found['questions']
        ]

    async def answer_question(self, question_id: str, answer: str) -> str:
        """The answer given; the id of the build Signature continues with."""
        accepted = await _body(
            self._client,
            'POST',
            f'/domains/{self.domain_id}/conversation/clarifying-questions/{question_id}/answer',
            json={'answer': answer},
        )
        return accepted['turn']['id']

    async def model_snapshot(self) -> dict[str, Any]:
        """The domain's whole model as Signature holds it: entities, fields, rules and where each comes from."""
        return await _body(self._client, 'GET', f'/domains/{self.domain_id}/model/snapshot')

    async def publish(self) -> None:
        await _body(self._client, 'POST', f'/domains/{self.domain_id}/publish', json={})

    async def plan_query(self, question: str, thread_id: str | None, fingerprint: str) -> str:
        """The question handed to Signature to plan, with the fingerprint of the customer's sources as they are
        now, so Signature can tell they have changed since publishing; the id of its query."""
        accepted = await _body(
            self._client,
            'POST',
            f'/domains/{self.domain_id}/queries',
            json={
                'idempotencyKey': str(uuid.uuid4()),
                'question': question,
                'threadId': thread_id or str(uuid.uuid4()),
                'fingerprint': fingerprint,
            },
        )
        return accepted['id']

    async def query(self, query_id: str) -> QueryPlan:
        found = await _body(self._client, 'GET', f'/domains/{self.domain_id}/queries/{query_id}')
        return QueryPlan(
            state=found['state'],
            thread_id=found['threadId'],
            reading=found.get('reading'),
            sql=found.get('sql'),
            reason=found.get('reason'),
        )


@asynccontextmanager
async def connected(settings: Settings) -> AsyncGenerator[Signature]:
    """Signature, reached with the customer's key, bound to the one domain that key opens."""
    async with httpx2.AsyncClient(
        base_url=settings.api_url,
        headers={'authorization': f'Bearer {settings.api_key}'},
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        domains = (await _body(client, 'GET', '/domains'))['domains']
        if len(domains) != 1:
            raise SignatureRefused(
                'This API key reaches more than one domain. Ask Signature for a key issued for one domain.'
                if domains
                else 'This API key reaches no domain.'
            )
        yield Signature(client, domains[0]['id'])


async def _body(
    client: httpx2.AsyncClient,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    absent_ok: bool = False,
) -> Any:
    """The JSON body of a request Signature accepted; None for a 404 when absence is an answer."""
    try:
        response = await client.request(method, path, json=json)
    except httpx2.HTTPError as failure:
        raise SignatureUnreachable() from failure
    if response.status_code == 404 and absent_ok:
        return None
    if response.status_code in (401, 403):
        raise SignatureRefused(
            'Signature did not accept the API key. Run /plugin configure signature@signature to enter a new one.'
        )
    if response.status_code >= 500:
        raise SignatureUnreachable()
    if response.is_error:
        raise SignatureRefused(_reason(response))
    return response.json() if response.content else None


def _reason(response: httpx2.Response) -> str:
    try:
        problem = response.json()
    except ValueError:
        return response.reason_phrase
    return problem.get('detail') or problem.get('title') or response.reason_phrase
