"""Signature's REST calls: a source keeps its id across reports, and an answered clarification is one call."""

import asyncio

import httpx2

import signature_api
from signature_api import source_id_of


def test_a_source_keeps_its_id_across_reports():
    assert source_id_of('d1', 'shop') == source_id_of('d1', 'shop')


def test_the_same_service_in_another_domain_is_another_source():
    assert source_id_of('d1', 'shop') != source_id_of('d2', 'shop')


def test_two_services_in_one_domain_are_two_sources():
    assert source_id_of('d1', 'shop') != source_id_of('d1', 'billing')


def test_an_answer_is_one_post_to_the_questions_answer_endpoint():
    requests: list[httpx2.Request] = []

    def accepting(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(202, json={'turn': {'id': 't1'}, 'statusUrl': '/x'})

    async def answered() -> str:
        async with httpx2.AsyncClient(base_url='http://signature.test',
                                      transport=httpx2.MockTransport(accepting)) as signature:
            return await signature_api.answer_clarification(signature, 'd1', 'q1', 'Weekly')

    assert asyncio.run(answered()) == 't1'
    assert [(request.method, request.url.path, request.read()) for request in requests] == [
        ('POST', '/domains/d1/conversation/clarifying-questions/q1/answer', b'{"answer":"Weekly"}')]
