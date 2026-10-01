"""The customer's data sources, as this machine keeps them: which files and databases they are, saved between
sessions, with database passwords kept in the system keychain and never in a file or a tool's output."""

import contextlib
import re
from pathlib import Path
from typing import Annotated, Literal

import keyring
import keyring.errors
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

KEYCHAIN_SERVICE = 'signature-plugin'

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

    def all(self) -> list[FileSource | DatabaseSource]:
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
        keyring.set_password(KEYCHAIN_SERVICE, _keychain_account(named), password)
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

    def _save(self, sources: list[FileSource | DatabaseSource]) -> None:
        self._file.write_bytes(SAVED.dump_json(sources, indent=2))
        self._file.chmod(0o600)


def password_of(source: DatabaseSource) -> str:
    password = keyring.get_password(KEYCHAIN_SERVICE, _keychain_account(source))
    if password is None:
        raise SourceRefused(f'The password for {source.name} is no longer in the keychain. Connect it again.')
    return password


def _forget_password(source: DatabaseSource) -> None:
    with contextlib.suppress(keyring.errors.PasswordDeleteError):  # already gone: nothing to forget
        keyring.delete_password(KEYCHAIN_SERVICE, _keychain_account(source))


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
