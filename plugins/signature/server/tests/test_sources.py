import stat
from collections.abc import Iterator
from pathlib import Path

import keyring
import keyring.errors
import pytest
from keyring.backend import KeyringBackend

from signature_plugin.sources import DatabaseSource, SourceRefused, Sources, password_of

SALES = DatabaseSource(name='sales', engine='postgres', host='127.0.0.1', port=5432, database='sales', user='me')


class NoKeychain(KeyringBackend):
    """The keychain of a Linux server without a desktop session: there, but nothing can open it."""

    priority = 1  # type: ignore[assignment]

    def get_password(self, service: str, username: str) -> str | None:
        raise keyring.errors.InitError('Failed to create the collection: Prompt dismissed..')

    def set_password(self, service: str, username: str, password: str) -> None:
        raise keyring.errors.InitError('Failed to create the collection: Prompt dismissed..')

    def delete_password(self, service: str, username: str) -> None:
        raise keyring.errors.InitError('Failed to create the collection: Prompt dismissed..')


class MemoryKeychain(KeyringBackend):
    """A keychain that keeps passwords for the test alone, never in the developer's own."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.kept: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.kept.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.kept[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.kept.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError(username)


class RefusingKeychain(MemoryKeychain):
    """A keychain that is there but refuses, as when the user dismisses its prompt."""

    def set_password(self, service: str, username: str, password: str) -> None:
        raise keyring.errors.PasswordSetError('User canceled the operation.')


@pytest.fixture
def keychain() -> Iterator[None]:
    """Restores whatever keychain keyring used before the test, which sets its own."""
    before = keyring.get_keyring()
    yield
    keyring.set_keyring(before)


@pytest.fixture
def plugin_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keychain: None) -> Path:
    monkeypatch.setenv('SIGNATURE_DATA_DIR', str(tmp_path / 'plugin'))
    return tmp_path / 'plugin'


def test_a_password_goes_to_the_keychain_and_never_to_a_file(plugin_folder: Path) -> None:
    keyring.set_keyring(MemoryKeychain())
    sales = Sources(plugin_folder / 'domain').add_database(SALES, 'secret')
    assert password_of(sales) == 'secret'
    assert not (plugin_folder / 'passwords.json').exists()


def test_without_a_keychain_a_password_is_kept_in_a_file_only_this_user_can_read(plugin_folder: Path) -> None:
    keyring.set_keyring(NoKeychain())
    registry = Sources(plugin_folder / 'domain')
    sales = registry.add_database(SALES, 'secret')
    saved = plugin_folder / 'passwords.json'
    assert password_of(sales) == 'secret'
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    registry.remove(sales.name)
    with pytest.raises(SourceRefused, match='no longer kept on this machine'):
        password_of(sales)


def test_a_keychain_that_refuses_is_told_and_nothing_is_written_to_a_file(plugin_folder: Path) -> None:
    keyring.set_keyring(RefusingKeychain())
    with pytest.raises(SourceRefused, match='did not keep the password for sales'):
        Sources(plugin_folder / 'domain').add_database(SALES, 'secret')
    assert not (plugin_folder / 'passwords.json').exists()
