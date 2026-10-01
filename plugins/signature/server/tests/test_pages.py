import httpx2
import pytest

from signature_plugin.pages import Pages, Refusal

pytestmark = pytest.mark.anyio


async def accept_anything(form: dict[str, str]) -> dict[str, str] | Refusal:
    return form


async def test_a_page_answers_only_requests_addressed_to_127_0_0_1(opened_pages: list[str]) -> None:
    pages = Pages()
    page = await pages.show('done.html', {}, accept_anything)
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
