"""Reads a local source's structure: a Postgres database through a libpq connection service the member defined
(~/.pg_service.conf, passwords from ~/.pgpass), so no credential passes through the plugin's own code; or files
through DuckDB. Each adapter is a row of ADAPTERS: how to read its structure, and how to shape what was read. Only
structure is asked for, never a table's rows, and none is sent."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

import local_files
from catalog_report import (FileColumn, FileStructure, PostgresqlCatalogRows, files_database, postgresql_database,
                            table_count)

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


async def read_postgresql(service: str) -> dict:
    """The `database` of a reported source, from a read-only look at Postgres's catalog."""
    async with await psycopg.AsyncConnection.connect(make_conninfo(service=service), row_factory=dict_row) as connection:
        await connection.set_read_only(True)
        relations = await fetch_all(connection, RELATIONS)
        columns = await fetch_all(connection, COLUMNS)
        primary_keys = await fetch_all(connection, PRIMARY_KEYS)
    return postgresql_database(PostgresqlCatalogRows(relations, columns, primary_keys))


# How DuckDB describes each format's columns: the table function that reads it, and what it needs loaded first.
# https://duckdb.org/docs/stable/guides/meta/describe, https://duckdb.org/docs/stable/data/csv/auto_detection,
# https://duckdb.org/docs/stable/data/parquet/overview, https://duckdb.org/docs/stable/data/json/overview,
# https://duckdb.org/docs/stable/core_extensions/excel
DESCRIBE_FILE = {
    'csv': 'DESCRIBE SELECT * FROM read_csv_auto(?)',
    'tsv': "DESCRIBE SELECT * FROM read_csv(?, delim = '\t', header = true)",
    'parquet': 'DESCRIBE SELECT * FROM read_parquet(?)',
    'json': 'DESCRIBE SELECT * FROM read_json_auto(?)',
    'excel': 'DESCRIBE SELECT * FROM read_xlsx(?)',
}


def describe_files(paths: list[Path]) -> list[FileStructure]:
    """Each file's columns, from DuckDB's DESCRIBE of it: its types are inferred from a sample of the file, and no row
    leaves this function."""
    names = local_files.names_of(paths)
    connection = duckdb.connect()
    try:
        if any(local_files.format_of(path) == 'excel' for path in paths):
            connection.execute('INSTALL excel')
            connection.execute('LOAD excel')
        return [FileStructure(names[path], local_files.format_of(path), [
            FileColumn(name, duckdb_type, nullable == 'YES') for name, duckdb_type, nullable, *_ in connection.execute(
                DESCRIBE_FILE[local_files.format_of(path)], [str(path)]).fetchall()]) for path in paths]
    finally:
        connection.close()


async def read_files(location: str) -> dict:
    """The `database` of a reported source, from DuckDB's look at the structure of the files a location names."""
    paths = local_files.files_at(location)
    if not paths:
        raise SourceNotUsable(f'No csv, tsv, parquet, json or xlsx file found at {location}.')
    return files_database(await asyncio.to_thread(describe_files, paths))


@dataclass(frozen=True)
class Adapter:
    """How to read one kind of source, what its location is called, and which failures mean it could not be read."""
    read: Callable[[str], Awaitable[dict]]
    failures: tuple[type[Exception], ...]
    subject: str
    hint: str


ADAPTERS = {
    'postgresql': Adapter(read_postgresql, (psycopg.Error, OSError), 'service',
                          'Check it is in ~/.pg_service.conf and its password in ~/.pgpass.'),
    'files': Adapter(read_files, (duckdb.Error, OSError), 'files at',
                     'Check the files are readable; Excel files also need DuckDB\'s excel extension, which it '
                     'downloads once.'),
}


@dataclass(frozen=True)
class ReadStructure:
    """A source's structure as Signature takes it, and how many tables that holds."""
    database: dict
    tables: int


class SourceNotUsable(Exception):
    """A local source that cannot be reported, with a reason that names no secret."""


async def read_structure(adapter_name: str, location: str) -> ReadStructure:
    """The structure of the source a location names (a connection service, or where files are); one that cannot be read
    is refused."""
    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        raise SourceNotUsable(f'The plugin cannot read {adapter_name} databases. It reads: {", ".join(ADAPTERS)}.')
    try:
        database = await adapter.read(location)
    except adapter.failures as failure:
        raise SourceNotUsable(f'Could not read the structure of {adapter.subject} {location}: '
                              f'{type(failure).__name__}. {adapter.hint}') from failure
    return ReadStructure(database, table_count(database))
