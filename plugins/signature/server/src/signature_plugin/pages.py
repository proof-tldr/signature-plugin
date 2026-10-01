"""The pages the plugin shows the customer in their browser: one to connect a database, whose password never
reaches Claude, and one to review the domain before it is published. They are served on 127.0.0.1 at an
address holding a random token, so nothing else on the machine or the network can use them."""

import asyncio
import secrets
import socket
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent / 'templates'), autoescape=select_autoescape())


@dataclass(frozen=True)
class Refusal:
    """Why a submitted form was not accepted, shown on the page so the customer can try again."""

    reason: str


@dataclass
class Page[T]:
    """One page waiting for the customer. `accept` turns a submitted form into the page's decision, or refuses
    it; the first accepted form decides the page."""

    id: str
    address: str
    template: str
    context: dict[str, Any]
    accept: Callable[[dict[str, str]], Awaitable[T | Refusal]]
    decided: asyncio.Future[T] = field(default_factory=lambda: asyncio.get_running_loop().create_future())


class Pages:
    """The plugin's local web server, started the first time a page is shown."""

    def __init__(self) -> None:
        self._token = secrets.token_urlsafe(24)
        self._pages: dict[str, Page[Any]] = {}
        self._port: int | None = None
        self._server_task: asyncio.Task[None] | None = None

    async def show[T](
        self, template: str, context: dict[str, Any], accept: Callable[[dict[str, str]], Awaitable[T | Refusal]]
    ) -> Page[T]:
        """The page opened in the customer's browser."""
        port = await self._started()
        page_id = secrets.token_urlsafe(8)
        page = Page(
            id=page_id,
            address=f'http://127.0.0.1:{port}/{self._token}/{page_id}',
            template=template,
            context=context,
            accept=accept,
        )
        self._pages[page_id] = page
        webbrowser.open(page.address)
        return page

    def reopen(self, page: Page[Any]) -> None:
        """A page still waiting, brought up in the browser again."""
        webbrowser.open(page.address)

    def close(self, page: Page[Any]) -> None:
        self._pages.pop(page.id, None)

    async def _started(self) -> int:
        """The port the server listens on, starting it if this is the first page."""
        if self._port is not None:
            return self._port
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        port: int = listener.getsockname()[1]
        app = Starlette(routes=[Route('/{token}/{page_id}', self._serve, methods=['GET', 'POST'])])
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        self._server_task = asyncio.create_task(server.serve(sockets=[listener]))
        self._port = port
        return port

    async def _serve(self, request: Request) -> Response:
        page = self._pages.get(request.path_params['page_id'])
        if page is None or not secrets.compare_digest(request.path_params['token'], self._token):
            return _rendered('gone.html', status_code=404)
        if page.decided.done():
            return _rendered('done.html')
        if request.method == 'GET':
            return _rendered(page.template, **page.context)
        form = {key: str(value) for key, value in (await request.form()).items()}
        outcome = await page.accept(form)
        if isinstance(outcome, Refusal):
            entered = {key: value for key, value in form.items() if key != 'password'}
            return _rendered(page.template, status_code=422, error=outcome.reason, form=entered, **page.context)
        page.decided.set_result(outcome)
        return _rendered('done.html')


def _rendered(template: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    return HTMLResponse(TEMPLATES.get_template(template).render(**context), status_code=status_code)
