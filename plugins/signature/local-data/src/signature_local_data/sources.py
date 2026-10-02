"""The customer's data sources as plain values: which files and databases they are. No passwords live here; a
database's is supplied by whoever opens it."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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
