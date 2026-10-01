"""Shared test setup: an in-memory keychain, the stand-in Signature served on a free port, sample data files, and
the plugin's server wired to them, its browser pages captured instead of opened."""

import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path

import duckdb
import keyring
import pytest
import uvicorn
from keyring.backend import KeyringBackend

from signature_plugin.fake_backend import FakeSignature
from signature_plugin.local_data import LocalData

ORDERS_SQL = 'SELECT status, SUM(amount_cents) AS total FROM files.orders GROUP BY status ORDER BY status'


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.passwords.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring() -> Generator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def local() -> Generator[LocalData]:
    """The sources' DuckDB, kept open between calls as the server keeps it."""
    opened = LocalData()
    yield opened
    opened.close()


@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'


@pytest.fixture
def data_files(tmp_path: Path) -> Path:
    """A folder holding orders as CSV, customers as Parquet and products as XLSX."""
    folder = tmp_path / 'data'
    folder.mkdir()
    (folder / 'orders.csv').write_text(
        'id,customer_id,status,amount_cents\n1,1,paid,1000\n2,1,refunded,500\n3,2,paid,700\n', encoding='utf-8'
    )
    connection = duckdb.connect(':memory:')
    connection.execute(
        f"COPY (SELECT * FROM (VALUES (1, 'Acme'), (2, 'Globex')) AS t(id, name)) "
        f"TO '{folder / 'customers.parquet'}' (FORMAT parquet)"
    )
    connection.execute('INSTALL excel; LOAD excel')
    connection.execute(
        f"COPY (SELECT * FROM (VALUES (1, 'Widget', 250)) AS t(id, title, price_cents)) "
        f"TO '{folder / 'products.xlsx'}' (FORMAT xlsx, HEADER true)"
    )
    connection.close()
    return folder


@pytest.fixture
def fake_signature() -> Generator[tuple[FakeSignature, str]]:
    """The stand-in Signature, running on a free port; it and its address."""
    signature = FakeSignature(
        canned_queries={
            'What did each status bring in?': {
                'reading': 'total amount per order status',
                'sql': ORDERS_SQL,
                'columns': ['order status', 'amount brought in'],
            },
            'Which customers are loyal?': {'state': 'failed', 'reason': 'the checker refuted the program'},
        }
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(signature.app(), host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    yield signature, f'http://127.0.0.1:{port}'
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def opened_pages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The addresses the plugin would have opened in the customer's browser."""
    opened: list[str] = []
    monkeypatch.setattr('webbrowser.open', lambda url, *_args, **_kwargs: opened.append(url) or True)  # type: ignore[misc]
    return opened


@pytest.fixture
def plugin_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_signature: tuple[FakeSignature, str]
) -> FakeSignature:
    signature, address = fake_signature
    monkeypatch.setenv('SIGNATURE_API_URL', address)
    monkeypatch.setenv('SIGNATURE_API_KEY', 'test-key')
    monkeypatch.setenv('SIGNATURE_DATA_DIR', str(tmp_path / 'plugin-data'))
    monkeypatch.setattr('signature_plugin.handoff.FOLDER', tmp_path / 'answers')
    monkeypatch.setattr('signature_plugin.fake_backend.BUILD_SECONDS', 0.05)
    return signature


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]
