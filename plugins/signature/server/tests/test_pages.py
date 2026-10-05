import socket

import httpx2
import pytest

from signature_plugin.pages import Pages, Refusal

pytestmark = pytest.mark.anyio


async def accept_anything(form: dict[str, str]) -> dict[str, str] | Refusal:
    return form


async def test_a_page_answers_only_requests_addressed_to_127_0_0_1(opened_pages: list[str]) -> None:
    pages = Pages()
    page = await pages.show({'page': 'review'}, accept_anything)
    origin, token, page_id = page.address.rsplit('/', 2)
    port = origin.rsplit(':', 1)[1]
    async with httpx2.AsyncClient() as browser:
        direct = await browser.get(page.address)
        rebound = await browser.get(page.address, headers={'host': f'attacker.example:{port}'})
        wrong_token = await browser.get(f'{origin}/not-{token}/{page_id}')
    assert direct.status_code == 200
    assert rebound.status_code == 404
    assert wrong_token.status_code == 404
    assert opened_pages == []


async def test_the_page_serves_the_app_its_data_and_takes_a_decision(opened_pages: list[str]) -> None:
    pages = Pages()
    page = await pages.show({'page': 'review', 'domain': 'Acme'}, accept_anything)
    async with httpx2.AsyncClient() as browser:
        app = await browser.get(page.address)
        data = await browser.get(f'{page.address}/data')
        decided = await browser.post(f'{page.address}/decision', json={'decision': 'publish'})
        again = await browser.post(f'{page.address}/decision', json={'decision': 'publish'})
        escape = await browser.get(page.address.rsplit('/', 1)[0] + '/assets/../../pages.py')
    assert '<div id="root">' in app.text
    assert data.json() == {'page': 'review', 'domain': 'Acme'}
    assert decided.json() == {'done': True}
    assert await page.decided == {'decision': 'publish'}
    assert again.status_code == 404
    assert escape.status_code == 404


async def test_a_chosen_port_serves_the_pages_there_so_a_tunnel_can_reach_them(
    opened_pages: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        free = probe.getsockname()[1]
    monkeypatch.setenv('SIGNATURE_PAGES_PORT', str(free))
    page = await Pages().show({'page': 'review'}, accept_anything)
    assert page.address.startswith(f'http://127.0.0.1:{free}/')
    taken = await Pages().show({'page': 'review'}, accept_anything)
    assert not taken.address.startswith(f'http://127.0.0.1:{free}/')
