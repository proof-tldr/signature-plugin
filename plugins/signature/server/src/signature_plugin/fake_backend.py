"""A stand-in for Signature, in memory, speaking the API in docs/backend-contract.md. It exists so the plugin can
be developed, tested and rehearsed before Signature-Platform has every endpoint. It does not build models or
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
    catalogs: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    turns: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    questions: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    queries: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    asked_about_documents: bool = False
    canned_queries: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
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
                Route(
                    f'{domain}/conversation/clarifying-questions/{{question_id}}/answer', self.answer, methods=['POST']
                ),
                Route(f'{domain}/review', self.review),
                Route(f'{domain}/publish', self.publish, methods=['POST']),
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
        self.catalogs[body['name']] = body['database']['catalog']
        return JSONResponse({'sourceId': request.path_params['source_id']})

    async def start_turn(self, request: Request) -> Response:
        body = await request.json()
        documents = [source['filename'] for source in body.get('sources', [])]
        parts = [f'{len(self.catalogs)} source(s)'] + ([f'{len(documents)} document(s)'] if documents else [])
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
        return JSONResponse({'turn': self._turn(reply)}, status_code=202)

    async def get_turn(self, request: Request) -> Response:
        turn = self.turns.get(request.path_params['turn_id'])
        return JSONResponse(turn) if turn else _problem(404, 'Unknown turn')

    async def list_questions(self, _request: Request) -> Response:
        return JSONResponse({'questions': list(self.questions.values())})

    async def answer(self, request: Request) -> Response:
        question = self.questions.pop(request.path_params['question_id'], None)
        if question is None:
            return _problem(404, 'That question is not open')
        answer = (await request.json())['answer']
        return JSONResponse({'turn': self._turn(f'Noted: {answer}')}, status_code=202)

    async def review(self, _request: Request) -> Response:
        return JSONResponse(
            {
                'summary': f'{self.domain_name} draws on {len(self.catalogs)} source(s) and '
                f'{len(self.documents)} document(s). (This review comes from the stand-in backend.)',
                'sections': [
                    {
                        'title': name,
                        'points': [f'{table["name"]}: {len(table["columns"])} columns' for table in catalog['tables']],
                    }
                    for name, catalog in self.catalogs.items()
                ],
            }
        )

    async def publish(self, _request: Request) -> Response:
        self.published_at = datetime.now(UTC).isoformat()
        return JSONResponse({'publishedAt': self.published_at})

    async def plan_query(self, request: Request) -> Response:
        body = await request.json()
        query_id = str(uuid.uuid4())
        canned = self.canned_queries.get(body['question'])
        first_table = next((t['sqlName'] for c in self.catalogs.values() for t in c['tables']), None)
        if canned:
            plan = {'state': 'planned', 'reading': canned['reading'], 'sql': canned['sql']}
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

    def _turn(self, reply: str) -> dict[str, Any]:
        turn_id = str(uuid.uuid4())
        self.turns[turn_id] = {'id': turn_id, 'state': 'pending'}

        async def answered() -> None:
            await asyncio.sleep(BUILD_SECONDS)
            self.turns[turn_id] = {'id': turn_id, 'state': 'answered', 'reply': reply}

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
    canned: dict[str, dict[str, str]] = json.loads(Path(canned_path).read_text(encoding='utf-8')) if canned_path else {}
    uvicorn.run(FakeSignature(canned_queries=canned).app(), host='127.0.0.1', port=arguments.port)
