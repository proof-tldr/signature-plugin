"""Reads a local source's structure: a Postgres database through a libpq connection service the member defined
(~/.pg_service.conf, passwords from ~/.pgpass), so no credential passes through the plugin's own code; or files
through DuckDB. Each adapter is a row of ADAPTERS: how to read its structure, and how to shape what was read. Only
structure is asked for, never a table's rows, and none is sent."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import duckdb
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

import local_files
from local_files import LocalFile
from catalog_report import (FileColumn, FileStructure, PostgresqlCatalogRows, files_database, postgresql_database)

USER_RELATIONS = '''
    relation.relkind IN ('r', 'p', 'v')
    AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    AND namespace.nspname !~ '^pg_temp_'
    AND has_table_privilege(relation.oid, 'SELECT')'''

RELATIONS = f'''
    SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
           obj_description(relation.oid, 'pg_class') AS description
    FROM pg_class AS relation JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE {USER_RELATIONS}
    ORDER BY namespace.nspname, relation.relname'''

COLUMNS = f'''
    SELECT namespace.nspname AS schema_name, relation.relname AS relation_name, attribute.attname AS column_name,
           format_type(attribute.atttypid, NULL) AS native_type, NOT attribute.attnotnull AS is_nullable,
           col_description(attribute.attrelid, attribute.attnum) AS description
    FROM pg_attribute AS attribute
    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped AND {USER_RELATIONS}
    ORDER BY namespace.nspname, relation.relname, attribute.attnum'''

PRIMARY_KEYS = f'''
    SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
           array_agg(attribute.attname::text ORDER BY key_column.position) AS columns
    FROM pg_constraint AS constraint_record
    JOIN pg_class AS relation ON relation.oid = constraint_record.conrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN LATERAL unnest(constraint_record.conkey) WITH ORDINALITY AS key_column(number, position) ON true
    JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid AND attribute.attnum = key_column.number
    WHERE constraint_record.contype = 'p' AND {USER_RELATIONS}
    GROUP BY namespace.nspname, relation.relname'''


async def fetch_all(connection: psycopg.AsyncConnection, query: str) -> list[dict]:
    return await (await connection.execute(query)).fetchall()


@dataclass(frozen=True)
class ReadStructure:
    """A source's structure as Signature takes it, and how many tables that holds."""
    database: dict
    tables: int


async def read_postgresql(service: str) -> ReadStructure:
    """The structure of a reported source, from a read-only look at Postgres's catalog."""
    async with await psycopg.AsyncConnection.connect(make_conninfo(service=service), row_factory=dict_row) as connection:
        await connection.set_read_only(True)
        relations = await fetch_all(connection, RELATIONS)
        columns = await fetch_all(connection, COLUMNS)
        primary_keys = await fetch_all(connection, PRIMARY_KEYS)
    return ReadStructure(postgresql_database(PostgresqlCatalogRows(relations, columns, primary_keys)), len(relations))


def load_extensions(connection: duckdb.DuckDBPyConnection, files: list[LocalFile]) -> None:
    extensions = {file.format.extension for file in files if file.format.extension}
    for extension in sorted(extensions):
        connection.execute(f'INSTALL {extension}')
        connection.execute(f'LOAD {extension}')


def describe_file(connection: duckdb.DuckDBPyConnection, name: str, file: LocalFile) -> FileStructure:
    """One file's columns, from DuckDB's DESCRIBE of it: types are inferred from a sample of the file; no row leaves."""
    described = connection.execute(file.format.describe, [str(file.path)]).fetchall()
    return FileStructure(name, [FileColumn(column, duckdb_type, nullable == 'YES')
                                for column, duckdb_type, nullable, *_ in described])


def describe_files(files: list[LocalFile]) -> list[FileStructure]:
    connection = duckdb.connect()
    try:
        load_extensions(connection, files)
        return [describe_file(connection, name, file) for name, file in zip(local_files.names_of(files), files)]
    finally:
        connection.close()


async def read_files(location: str) -> ReadStructure:
    """The structure of a reported source, from DuckDB's look at the structure of the files a location names."""
    files = local_files.files_at(location)
    if not files:
        raise SourceNotUsable(f'No {local_files.SUPPORTED_SUFFIXES} file found at {location}.')
    described = await asyncio.to_thread(describe_files, files)
    return ReadStructure(files_database(described), len(described))


@dataclass(frozen=True)
class Adapter:
    """How to read one kind of source, what its location is called, and which failures mean it could not be read."""
    read: Callable[[str], Awaitable[ReadStructure]]
    failures: tuple[type[Exception], ...]
    subject: str
    hint: str


ADAPTERS = {
    'postgresql': Adapter(read_postgresql, (psycopg.Error, OSError), 'service',
                          'Check it is in ~/.pg_service.conf and its password in ~/.pgpass.'),
    'files': Adapter(read_files, (duckdb.Error, OSError), 'the files at',
                     'Check the files are readable; Excel files also need DuckDB\'s excel extension, which it '
                     'downloads once.'),
}


class SourceNotUsable(Exception):
    """A local source that cannot be reported, with a reason that names no secret."""


async def read_structure(adapter_name: str, location: str) -> ReadStructure:
    """The structure of the source a location names (a connection service, or where files are); one that cannot be read
    is refused."""
    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        raise SourceNotUsable(f'The plugin cannot read {adapter_name} databases. It reads: {", ".join(ADAPTERS)}.')
    try:
        return await adapter.read(location)
    except adapter.failures as failure:
        raise SourceNotUsable(f'Could not read the structure of {adapter.subject} {location}: '
                              f'{type(failure).__name__}. {adapter.hint}') from failure
