"""Signature's REST calls: a source keeps its id across reports, and an answered clarification is one call."""

import asyncio

import httpx2
import pytest

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


def test_a_folder_is_one_source_by_its_absolute_path():
    assert source_id_of('d1', '/data/exports') == source_id_of('d1', '/data/exports')
    assert source_id_of('d1', '/data/exports') != source_id_of('d1', '/data/other')


def answered_with(response: httpx2.Response) -> dict:
    async def listed() -> dict:
        async with httpx2.AsyncClient(base_url='http://signature.test',
                                      transport=httpx2.MockTransport(lambda request: response)) as signature:
            return await signature_api.list_domains(signature)

    return asyncio.run(listed())


def problem(status: int, **fields) -> httpx2.Response:
    return httpx2.Response(status, json=fields, headers={'content-type': 'application/problem+json'})


def test_a_gateway_refusal_without_problem_details_says_the_key_was_rejected():
    with pytest.raises(signature_api.SignatureRefused, match='API key'):
        answered_with(httpx2.Response(403, text='forbidden'))


def test_a_refusal_carries_the_reason_signature_gave():
    with pytest.raises(signature_api.SignatureRefused, match='Name taken'):
        answered_with(problem(409, detail='Name taken'))


def test_nothing_at_the_address_is_not_found():
    with pytest.raises(signature_api.NotFound):
        answered_with(problem(404, title='Not Found'))


def test_a_server_failure_is_signature_being_unreachable():
    with pytest.raises(signature_api.SignatureUnreachable):
        answered_with(httpx2.Response(503))


def test_an_accepted_request_returns_its_body():
    assert answered_with(httpx2.Response(200, json={'domains': []})) == {'domains': []}
