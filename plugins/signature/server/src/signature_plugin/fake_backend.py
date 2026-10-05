"""A stand-in for Signature, in memory, speaking the API in docs/backend-contract.md. It exists so the plugin can
be developed, tested and rehearsed before Signature's backend has every endpoint. It does not build models or
prove anything: builds answer after a short delay, the first build over two or more documents asks one
question, and a question is answered with SQL from the file named by SIGNATURE_FAKE_QUERIES (a JSON object of
question text to {"reading", "sql"}), or else by listing the first reported table.

    signature-fake-backend --port 8790
    SIGNATURE_API_URL=http://127.0.0.1:8790 SIGNATURE_API_KEY=any claude --plugin-dir plugins/signature
"""

import argparse
import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

BUILD_SECONDS = 2.0


@dataclass
class FakeSignature:
    domain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain_name: str = 'Demo domain'
    published_at: str | None = None
    documents: dict[str, str] = field(default_factory=dict[str, str])
    # The kind each document was handed to a build as, by its filename.
    document_kinds: dict[str, str] = field(default_factory=dict[str, str])
    # The customer's local DuckDB as last reported: its source id and catalog, and the catalog's fingerprint as
    # it was when the domain was last published.
    source_id: str | None = None
    catalog: dict[str, Any] | None = None
    published_fingerprint: str | None = None
    # Why getting the published domain ready to answer questions fails, or None when it succeeds.
    preparation_failure: str | None = None
    # How many polls of the preparation find it still running; a question asked meanwhile fails, as Signature's does.
    preparing_polls: int = 0
    # Why every build fails, in Signature's own failure code, or None for builds that succeed.
    build_failure: str | None = None
    # Whether builds only reply, describing what they were given without changing the domain.
    builds_only_reply: bool = False
    # How many build status polls fail as a busy server's do before they answer again.
    busy_polls: int = 0
    turns: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    questions: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    queries: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    asked_about_documents: bool = False
    canned_queries: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    builds: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])

    def app(self) -> Starlette:
        domain = f'/domains/{self.domain_id}'
        return Starlette(
            routes=[
                Route('/domains', self.list_domains),
                Route(domain, self.get_domain),
                Route(f'{domain}/publication', self.publication),
                Route(f'{domain}/documents/presign', self.presign, methods=['POST']),
                Route('/storage/{ref}', self.store, methods=['PUT']),
                Route(f'{domain}/model/sources/{{source_id}}/catalog', self.report_catalog, methods=['PUT']),
                Route(f'{domain}/conversation/turns', self.start_turn, methods=['POST']),
                Route(f'{domain}/conversation/turns/{{turn_id}}', self.get_turn),
                Route(f'{domain}/conversation/clarifying-questions', self.list_questions),
                Route(f'{domain}/model/snapshot', self.model_snapshot),
                Route(f'{domain}/publish', self.publish, methods=['POST']),
                Route(f'{domain}/query-package', self.preparation),
                Route(f'{domain}/queries', self.plan_query, methods=['POST']),
                Route(f'{domain}/queries/{{query_id}}', self.get_query),
            ]
        )

    async def list_domains(self, _request: Request) -> Response:
        return JSONResponse({'domains': [{'id': self.domain_id, 'name': self.domain_name}]})

    async def get_domain(self, _request: Request) -> Response:
        return JSONResponse({'id': self.domain_id, 'name': self.domain_name})

    async def publication(self, _request: Request) -> Response:
        if self.published_at is None:
            return _problem(404, 'Not published yet')
        return JSONResponse({'publishedAt': self.published_at})

    async def presign(self, request: Request) -> Response:
        body = await request.json()
        ref = str(uuid.uuid4())
        self.documents[ref] = body['filename']
        return JSONResponse({'url': str(request.url_for('store', ref=ref)), 'contentRef': ref})

    async def store(self, request: Request) -> Response:
        if request.path_params['ref'] not in self.documents:
            return _problem(404, 'Unknown upload')
        await request.body()
        return Response(status_code=200)

    async def report_catalog(self, request: Request) -> Response:
        body = await request.json()
        self.source_id, self.catalog = request.path_params['source_id'], body['database']['catalog']
        return JSONResponse({'sourceId': request.path_params['source_id']})

    async def start_turn(self, request: Request) -> Response:
        body = await request.json()
        if not body.get('text') and not body.get('sources'):
            return _problem(400, 'Request does not match the declared contract')
        self.questions.clear()  # the customer's next turn closes every open question, as Signature's does
        documents = [source['filename'] for source in body.get('sources', [])]
        self.document_kinds.update({source['filename']: source['kind'] for source in body.get('sources', [])})
        parts = [f'{len(self.tables())} table(s)'] + ([f'{len(documents)} document(s)'] if documents else [])
        reply = f'Built the domain from {" and ".join(parts)}.'
        if len(documents) >= 2 and not self.asked_about_documents:
            self.asked_about_documents = True
            question_id = str(uuid.uuid4())
            self.questions[question_id] = {
                'id': question_id,
                'question': f'{documents[0]} and {documents[1]} seem to define the same term differently. '
                'Which one is right?',
                'suggestedAnswers': [documents[0], documents[1]],
            }
            scope_id = str(uuid.uuid4())
            self.questions[scope_id] = {
                'id': scope_id,
                'question': 'Should refunded orders count as revenue?',
                'suggestedAnswers': ['Yes', 'No'],
            }
        return JSONResponse({'turn': self._turn(reply)}, status_code=202)

    async def get_turn(self, request: Request) -> Response:
        if self.busy_polls > 0:
            self.busy_polls -= 1
            return _problem(503, 'Busy')
        turn = self.turns.get(request.path_params['turn_id'])
        return JSONResponse(turn) if turn else _problem(404, 'Unknown turn')

    async def list_questions(self, _request: Request) -> Response:
        return JSONResponse({'questions': list(self.questions.values())})

    async def model_snapshot(self, _request: Request) -> Response:
        """A model with one entity per reported table, one field per column, each read from that column, and each
        record identified by its primary key or else its first column."""
        model: dict[str, list[dict[str, Any]]] = {
            key: []
            for key in ('entities', 'fields', 'sources', 'databaseEntities', 'columns', 'mappings', 'mappingFields')
        }
        if self.source_id:
            model['sources'].append({'id': self.source_id, 'kind': 'duckdb', 'connection': 'Your data'})
        for table in self.tables():
            entity_id, table_id, mapping_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            model['entities'].append({'id': entity_id, 'name': table['name'].title(), 'invariants': []})
            relation = f'{table["catalog"]}.{table["schema"]}.{table["name"]}'
            model['databaseEntities'].append({'id': table_id, 'sourceId': self.source_id, 'relation': relation})
            identity: list[dict[str, str]] = []
            for column in table['columns']:
                field_id, column_id = str(uuid.uuid4()), str(uuid.uuid4())
                model['fields'].append(
                    {
                        'id': field_id,
                        'entityId': entity_id,
                        'name': column['name'],
                        'type': {'kind': 'named', 'name': column['nativeType'].lower()},
                    }
                )
                model['columns'].append(
                    {
                        'id': column_id,
                        'databaseEntityId': table_id,
                        'name': column['name'],
                        'storage': {'kind': 'column', 'column': column['name']},
                    }
                )
                model['mappingFields'].append(
                    {
                        'id': str(uuid.uuid4()),
                        'mappingId': mapping_id,
                        'columnId': column_id,
                        'target': {'kind': 'field', 'fieldId': field_id},
                    }
                )
                if column['name'] in table['primaryKey'] or not identity:
                    identity = [{'columnId': column_id, 'name': column['name']}]
            model['mappings'].append(
                {'id': mapping_id, 'entityId': entity_id, 'databaseEntityId': table_id, 'identity': identity}
            )
        return JSONResponse(model | {'functions': [], 'axioms': []})

    async def publish(self, _request: Request) -> Response:
        self.published_at = datetime.now(UTC).isoformat()
        self.published_fingerprint = self.catalog['fingerprint'] if self.catalog else None
        return JSONResponse({'publishedAt': self.published_at})

    async def preparation(self, _request: Request) -> Response:
        """The query package a publication of reported local data is built into: built at once, here."""
        if self.published_fingerprint is None:
            return _problem(404, 'No query package')
        status = 'failed' if self.preparation_failure else 'succeeded'
        if self.preparing_polls > 0:
            self.preparing_polls -= 1
            status = 'running'
        return JSONResponse(
            {'status': status, 'reason': self.preparation_failure, 'fingerprint': self.published_fingerprint}
        )

    async def plan_query(self, request: Request) -> Response:
        body = await request.json()
        query_id = str(uuid.uuid4())
        canned = self.canned_queries.get(body['question'])
        first_table = next((self.sql_name(table) for table in self.tables()), None)
        plan: dict[str, Any]
        if self.preparing_polls > 0:
            plan = {'state': 'failed', 'reason': 'The query package is not built yet'}
        elif self.published_fingerprint and body.get('fingerprint') != self.published_fingerprint:
            plan = {'state': 'stale', 'reason': 'the sources changed shape after publishing'}
        elif canned:
            plan = {'state': 'planned', 'columns': list[str]()} | canned
        elif first_table:
            plan = {
                'state': 'planned',
                'reading': f'the first rows of {first_table} (stand-in backend)',
                'sql': f'SELECT * FROM {first_table} LIMIT 10',
            }
        else:
            plan = {'state': 'unanswerable', 'reason': 'no sources have been reported yet'}
        self.queries[query_id] = {'id': query_id, 'threadId': body['threadId']} | plan
        return JSONResponse({'id': query_id}, status_code=202)

    async def get_query(self, request: Request) -> Response:
        query = self.queries.get(request.path_params['query_id'])
        return JSONResponse(query) if query else _problem(404, 'Unknown query')

    def tables(self) -> list[dict[str, Any]]:
        return self.catalog['tables'] if self.catalog else []

    def table_names(self) -> set[str]:
        return {table['name'] for table in self.tables()}

    @staticmethod
    def sql_name(table: dict[str, Any]) -> str:
        return '.'.join(f'"{part}"' for part in (table['catalog'], table['schema'], table['name']))

    def _turn(self, reply: str) -> dict[str, Any]:
        turn_id = str(uuid.uuid4())
        started = datetime.now(UTC).isoformat()
        self.turns[turn_id] = {
            'id': turn_id,
            'state': 'pending',
            'progress': {'stages': [{'stage': 'updating', 'label': 'Updating your model', 'startedAt': started}]},
        }

        async def answered() -> None:
            await asyncio.sleep(BUILD_SECONDS)
            if self.build_failure is None:
                self.turns[turn_id] = {
                    'id': turn_id,
                    'state': 'answered',
                    'reply': 'Shall I go ahead and build it?' if self.builds_only_reply else reply,
                    'modelChanged': not self.builds_only_reply,
                }
            else:
                self.turns[turn_id] = {'id': turn_id, 'state': 'failed', 'failure': {'code': self.build_failure}}

        task = asyncio.get_running_loop().create_task(answered())
        self.builds.add(task)
        task.add_done_callback(self.builds.discard)
        return {'id': turn_id, 'state': 'pending'}


def _problem(status: int, title: str) -> Response:
    return JSONResponse({'title': title}, status_code=status, media_type='application/problem+json')


def main() -> None:
    parser = argparse.ArgumentParser(description='Run the stand-in Signature backend.')
    parser.add_argument('--port', type=int, default=8790)
    arguments = parser.parse_args()
    canned_path = os.environ.get('SIGNATURE_FAKE_QUERIES')
    canned: dict[str, dict[str, Any]] = json.loads(Path(canned_path).read_text(encoding='utf-8')) if canned_path else {}
    uvicorn.run(FakeSignature(canned_queries=canned).app(), host='127.0.0.1', port=arguments.port)
