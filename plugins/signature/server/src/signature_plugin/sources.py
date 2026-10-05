"""The customer's data sources, as this machine keeps them: which files and databases they are, saved between
sessions, with database passwords kept in the system keychain and never in a tool's output. A machine with no
keychain this user can open, such as a Linux server without a desktop session, keeps them instead in a file in the
plugin's folder that only this user can read."""

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

import keyring
import keyring.errors
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from signature_plugin.settings import data_folder

KEYCHAIN_SERVICE = 'signature-plugin'
# What keyring raises where there is no keychain this user can open, as on a server without a desktop session: only
# then is a password kept in the file. A keychain that is there but refuses, as when the user dismisses its prompt, is
# told to the customer instead.
NO_KEYCHAIN = (keyring.errors.NoKeyringError, keyring.errors.InitError, keyring.errors.KeyringLocked)
PASSWORDS_FILE = 'passwords.json'

type FileFormat = Literal['csv', 'xlsx', 'parquet', 'json']
type DatabaseEngine = Literal['postgres', 'mysql']

FILE_FORMATS: dict[str, FileFormat] = {
    '.csv': 'csv',
    '.tsv': 'csv',
    '.txt': 'csv',
    '.xlsx': 'xlsx',
    '.parquet': 'parquet',
    '.json': 'json',
    '.jsonl': 'json',
    '.ndjson': 'json',
}


class FileSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal['file'] = 'file'
    name: str
    path: str
    format: FileFormat


class DatabaseSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal['database'] = 'database'
    name: str
    engine: DatabaseEngine
    host: str
    port: int
    database: str
    user: str


type Source = Annotated[FileSource | DatabaseSource, Field(discriminator='kind')]

SAVED = TypeAdapter(list[Source])


class SourceRefused(Exception):
    """A source that cannot be added or opened, with the reason."""


class Sources:
    """The sources registered for one domain, kept in a file next to the plugin's other data."""

    def __init__(self, folder: Path) -> None:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._file = folder / 'sources.json'

    def all(self) -> list[Source]:
        if not self._file.exists():
            return []
        return SAVED.validate_json(self._file.read_bytes())

    def add_files(self, paths: list[str]) -> list[FileSource]:
        """The files at those paths registered, a folder standing for the data files directly inside it. A file
        already registered is not added again."""
        found = [file for path in paths for file in _data_files(Path(path).expanduser())]
        if not found:
            raise SourceRefused('No CSV, TSV, XLSX, Parquet or JSON files were found there.')
        existing = self.all()
        known = {source.path for source in existing if isinstance(source, FileSource)}
        taken = {source.name for source in existing}
        added: list[FileSource] = []
        for file in found:
            if str(file) in known:
                continue
            name = _free_name(_identifier(file.stem), taken)
            taken.add(name)
            added.append(FileSource(name=name, path=str(file), format=FILE_FORMATS[file.suffix.lower()]))
        self._save([*existing, *added])
        return added

    def add_database(self, source: DatabaseSource, password: str) -> DatabaseSource:
        """The database registered under a free name, its password stored in the keychain."""
        existing = self.all()
        named = source.model_copy(update={'name': _free_name(_identifier(source.name), {s.name for s in existing})})
        _keep_password(named, password)
        self._save([*existing, named])
        return named

    def remove(self, name: str) -> None:
        existing = self.all()
        if not any(source.name == name for source in existing):
            raise SourceRefused(f'There is no source called {name}.')
        for source in existing:
            if source.name == name and isinstance(source, DatabaseSource):
                _forget_password(source)
        self._save([source for source in existing if source.name != name])

    def _save(self, sources: list[Source]) -> None:
        self._file.write_bytes(SAVED.dump_json(sources, indent=2))
        self._file.chmod(0o600)


def password_of(source: DatabaseSource) -> str:
    account = _keychain_account(source)
    password = None
    with contextlib.suppress(*NO_KEYCHAIN):  # the password is in the file
        password = keyring.get_password(KEYCHAIN_SERVICE, account)
    if password is None:
        password = _saved_passwords().get(account)
    if password is None:
        raise SourceRefused(f'The password for {source.name} is no longer kept on this machine. Connect it again.')
    return password


def _keep_password(source: DatabaseSource, password: str) -> None:
    account = _keychain_account(source)
    try:
        keyring.set_password(KEYCHAIN_SERVICE, account, password)
    except NO_KEYCHAIN:
        _save_passwords({**_saved_passwords(), account: password})
    except keyring.errors.KeyringError as refused:
        raise SourceRefused(f'The keychain did not keep the password for {source.name}: {refused}') from refused


def _forget_password(source: DatabaseSource) -> None:
    account = _keychain_account(source)
    with contextlib.suppress(keyring.errors.PasswordDeleteError, *NO_KEYCHAIN):  # already gone, or no keychain
        keyring.delete_password(KEYCHAIN_SERVICE, account)
    saved = _saved_passwords()
    if saved.pop(account, None) is not None:
        _save_passwords(saved)


def _saved_passwords() -> dict[str, str]:
    file = data_folder() / PASSWORDS_FILE
    return json.loads(file.read_bytes()) if file.exists() else {}


def _save_passwords(passwords: dict[str, str]) -> None:
    file = data_folder() / PASSWORDS_FILE
    descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as written:
        os.fchmod(written.fileno(), 0o600)
        json.dump(passwords, written)


def _data_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(child.resolve() for child in path.iterdir() if child.suffix.lower() in FILE_FORMATS)
    if not path.exists():
        raise SourceRefused(f'{path} does not exist.')
    if path.suffix.lower() not in FILE_FORMATS:
        raise SourceRefused(f'{path.name} is not a CSV, TSV, XLSX, Parquet or JSON file.')
    return [path.resolve()]


def _identifier(text: str) -> str:
    """A plain name for the source: lower case letters, digits and underscores."""
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_') or 'source'


def _free_name(name: str, taken: set[str]) -> str:
    candidate, suffix = name, 2
    while candidate in taken:
        candidate, suffix = f'{name}_{suffix}', suffix + 1
    return candidate


def _keychain_account(source: DatabaseSource) -> str:
    return f'{source.engine}://{source.user}@{source.host}:{source.port}/{source.database}'
