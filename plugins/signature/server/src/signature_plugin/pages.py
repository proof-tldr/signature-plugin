"""The pages the plugin shows the customer in their browser: one to connect a database, whose password never
reaches Claude, and one to review the domain before it is published. Both are the web app built from
plugins/signature/web into ./web, fed the page's data and sending back the customer's decision as JSON.

They are served on 127.0.0.1 at an address holding a random token, so nothing else on the machine or the network
can use them, and they answer only requests addressed to 127.0.0.1, so a website the browser has open cannot reach
them by rebinding its own name."""

import asyncio
import secrets
import socket
import webbrowser
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

APP = Path(__file__).parent / 'web'
ASSETS = APP / 'assets'


@dataclass(frozen=True)
class Refusal:
    """Why a submitted decision was not accepted, shown on the page so the customer can try again."""

    reason: str


@dataclass
class Page[T]:
    """One page waiting for the customer: the data it shows, and `accept`, which turns what the customer submits
    into the page's decision or refuses it. The first accepted submission decides the page."""

    id: str
    address: str
    data: Mapping[str, Any]
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
        self, data: Mapping[str, Any], accept: Callable[[dict[str, str]], Awaitable[T | Refusal]]
    ) -> Page[T]:
        """A page waiting for the customer at its address; nothing is opened yet."""
        port = await self._started()
        page_id = secrets.token_urlsafe(8)
        page = Page(id=page_id, address=f'http://127.0.0.1:{port}/{self._token}/{page_id}', data=data, accept=accept)
        self._pages[page_id] = page
        return page

    def open_in_browser(self, page: Page[Any]) -> None:
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
        app = Starlette(
            routes=[
                Route('/{token}/assets/{file:path}', self._asset),
                Route('/{token}/{page_id}', self._app),
                Route('/{token}/{page_id}/data', self._data),
                Route('/{token}/{page_id}/decision', self._decision, methods=['POST']),
            ]
        )
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        self._server_task = asyncio.create_task(server.serve(sockets=[listener]))
        self._port = port
        return port

    def _trusted(self, request: Request) -> bool:
        return request.headers.get('host') == f'127.0.0.1:{self._port}' and secrets.compare_digest(
            request.path_params['token'], self._token
        )

    async def _app(self, request: Request) -> Response:
        if not self._trusted(request):
            return Response('Not found', status_code=404)
        return FileResponse(APP / 'index.html', headers={'cache-control': 'no-store'})

    async def _asset(self, request: Request) -> Response:
        asset = (ASSETS / request.path_params['file']).resolve()
        if not self._trusted(request) or not asset.is_relative_to(ASSETS.resolve()) or not asset.is_file():
            return Response('Not found', status_code=404)
        return FileResponse(asset, headers={'cache-control': 'max-age=31536000, immutable'})

    async def _data(self, request: Request) -> Response:
        page = self._pages.get(request.path_params['page_id'])
        if not self._trusted(request) or page is None or page.decided.done():
            return JSONResponse({'error': 'This page has expired.'}, status_code=404)
        return JSONResponse(dict(page.data), headers={'cache-control': 'no-store'})

    async def _decision(self, request: Request) -> Response:
        page = self._pages.get(request.path_params['page_id'])
        if not self._trusted(request) or page is None or page.decided.done():
            return JSONResponse({'error': 'This page has expired.'}, status_code=404)
        try:
            submitted = await request.json()
        except JSONDecodeError:
            return JSONResponse({'error': 'The page sent something it should not have.'}, status_code=400)
        outcome = await page.accept({str(key): str(value) for key, value in dict(submitted).items()})
        if isinstance(outcome, Refusal):
            return JSONResponse({'error': outcome.reason}, status_code=422)
        page.decided.set_result(outcome)
        return JSONResponse({'done': True})
