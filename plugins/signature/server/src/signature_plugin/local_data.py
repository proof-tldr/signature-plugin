"""The customer's sources opened together in one embedded DuckDB, on this machine: files as views, databases
attached read-only. It reports their structure and runs Signature's queries, locked so that a query can read
only those sources and change nothing.

Each file is the view `files.<source>`; each database is the catalog `<source>`, its tables at
`<source>.<schema>.<table>`. Signature's SQL names them that way."""

import json
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypedDict, cast

import duckdb

from signature_plugin.sources import DatabaseSource, FileFormat, FileSource, Source, SourceRefused, password_of

# Files are views in this schema of DuckDB's own in-memory database; each database source is attached beside it.
FILES_DATABASE = 'memory'
FILES_SCHEMA = 'files'
SYSTEM_SCHEMAS = {'information_schema', 'pg_catalog', 'mysql', 'performance_schema', 'sys'}
SAMPLE_ROWS = 1000
SAMPLE_VALUES = 5
SAMPLE_TEXT_LENGTH = 80
QUERY_TIMEOUT_SECONDS = 120.0
# Each file format's DuckDB reader, and the extension it needs loaded before the connection is locked.
FILE_READERS: dict[FileFormat, tuple[str, str | None]] = {
    'csv': ('read_csv', None),
    'parquet': ('read_parquet', None),
    'json': ('read_json', 'json'),
    'xlsx': ('read_xlsx', 'excel'),
}
MAX_RESULT_ROWS = 10_000
COLUMNS = 'SELECT schema_name, table_name, column_name, data_type, is_nullable FROM duckdb_columns()'
ORDER = 'ORDER BY schema_name, table_name, column_index'


class QueryRefused(Exception):
    """A query that was not run or did not finish, with the reason."""


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


class Column(TypedDict):
    name: str
    type: str
    nullable: bool
    primaryKey: bool
    examples: list[str]


class Table(TypedDict):
    schema: str
    name: str
    sqlName: str
    columns: list[Column]


class Catalog(TypedDict):
    tables: list[Table]


@dataclass(frozen=True)
class TableSummary:
    name: str
    columns: int


def check(source: Source) -> list[TableSummary]:
    """The tables a source holds, opening it alone: a source that cannot be opened is refused, with why."""
    with _opened([source]) as connection:
        return [TableSummary(table['name'], len(table['columns'])) for table in _tables(connection, source, 0)]


def catalogs(sources: Sequence[Source]) -> dict[str, Catalog]:
    """What Signature is told about each source, by name: its tables, their columns, types and keys, and a few
    example values per column, so it can see what codes and formats the data uses. Never whole rows."""
    with _opened(sources) as connection:
        return {source.name: Catalog(tables=_tables(connection, source, SAMPLE_VALUES)) for source in sources}


def run(sources: Sequence[Source], sql: str) -> Result:
    """Signature's query over the sources, run if it is one SELECT over their tables, within the time and row
    limits."""
    with _opened(sources) as connection:
        return _ran(connection, sql)


def run_each(sources: Sequence[Source], queries: Sequence[str]) -> list[Result | None]:
    """Each query's result over one opening of the sources, None for a query that was refused or failed."""
    results: list[Result | None] = []
    with _opened(sources) as connection:
        for sql in queries:
            try:
                results.append(_ran(connection, sql))
            except QueryRefused:
                results.append(None)
    return results


def _ran(connection: duckdb.DuckDBPyConnection, sql: str) -> Result:
    _refuse_unless_plain_select(connection, sql)
    timer = threading.Timer(QUERY_TIMEOUT_SECONDS, connection.interrupt)
    timer.start()
    try:
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
    except duckdb.InterruptException as stopped:
        raise QueryRefused(f'The query ran past {QUERY_TIMEOUT_SECONDS:.0f} seconds and was stopped.') from stopped
    except duckdb.Error as failure:
        raise QueryRefused(f'The query failed on your data: {failure}') from failure
    finally:
        timer.cancel()
    columns = [description[0] for description in cursor.description or []]
    return Result(columns=columns, rows=rows[:MAX_RESULT_ROWS], truncated=len(rows) > MAX_RESULT_ROWS)


@contextmanager
def _opened(sources: Sequence[Source]) -> Generator[duckdb.DuckDBPyConnection]:
    """All the sources in one DuckDB, locked: no file but theirs can be read, and nothing written anywhere."""
    connection = duckdb.connect(':memory:')
    try:
        connection.execute(f'CREATE SCHEMA {FILES_SCHEMA}')
        for source in sources:
            _attach(connection, source)
        allowed = [source.path for source in sources if isinstance(source, FileSource)]
        connection.execute('SET allowed_paths = ?', [allowed])
        connection.execute('SET enable_external_access = false')
        connection.execute('SET lock_configuration = true')
        yield connection
    finally:
        connection.close()


def _attach(connection: duckdb.DuckDBPyConnection, source: Source) -> None:
    try:
        match source:
            case FileSource():
                reader, extension = FILE_READERS[source.format]
                if extension:
                    connection.execute(f'INSTALL {extension}; LOAD {extension}')
                view = f'{FILES_SCHEMA}.{_quoted(source.name)}'
                connection.execute(f'CREATE VIEW {view} AS SELECT * FROM {reader}({_literal(source.path)})')
            case DatabaseSource():
                connection.execute(f'INSTALL {source.engine}; LOAD {source.engine}')
                secret = _quoted(f'{source.name}_login')
                connection.execute(
                    f'CREATE TEMPORARY SECRET {secret} (TYPE {source.engine}, HOST {_literal(source.host)}, '
                    f'PORT {source.port}, DATABASE {_literal(source.database)}, USER {_literal(source.user)}, '
                    f'PASSWORD {_literal(password_of(source))})'
                )
                connection.execute(
                    f"ATTACH '' AS {_quoted(source.name)} (TYPE {source.engine}, SECRET {secret}, READ_ONLY)"
                )
    except duckdb.Error as failure:
        raise SourceRefused(f'{source.name} could not be opened: {failure}') from failure


def _tables(connection: duckdb.DuckDBPyConnection, source: Source, examples_per_column: int) -> list[Table]:
    """The source's tables, with up to that many example values for each column."""
    match source:
        case FileSource():
            database = FILES_DATABASE
            columns = connection.execute(
                f'{COLUMNS} WHERE database_name = ? AND schema_name = ? AND table_name = ? {ORDER}',
                [FILES_DATABASE, FILES_SCHEMA, source.name],
            ).fetchall()
        case DatabaseSource():
            database = source.name
            columns = connection.execute(
                f'{COLUMNS} WHERE database_name = ? AND schema_name NOT IN (SELECT unnest(?)) {ORDER}',
                [source.name, sorted(SYSTEM_SCHEMAS)],
            ).fetchall()
    keys = _primary_keys(connection, database)
    tables: dict[tuple[str, str], Table] = {}
    for schema, table, column, data_type, nullable in columns:
        sql_name = _sql_name(database, schema, table)
        entry = tables.setdefault((schema, table), Table(schema=schema, name=table, sqlName=sql_name, columns=[]))
        entry['columns'].append(
            Column(
                name=column,
                type=data_type,
                nullable=nullable,
                primaryKey=column in keys.get((schema, table), set()),
                examples=_examples(connection, sql_name, column, examples_per_column),
            )
        )
    return list(tables.values())


def _primary_keys(connection: duckdb.DuckDBPyConnection, database: str) -> dict[tuple[str, str], set[str]]:
    rows = connection.execute(
        """SELECT schema_name, table_name, constraint_column_names FROM duckdb_constraints()
           WHERE database_name = ? AND constraint_type = 'PRIMARY KEY' """,
        [database],
    ).fetchall()
    return {(schema, table): set(columns) for schema, table, columns in rows}


def _examples(connection: duckdb.DuckDBPyConnection, table: str, column: str, count: int) -> list[str]:
    if count == 0:
        return []
    quoted = _quoted(column)
    values = connection.execute(
        f"""SELECT DISTINCT CAST({quoted} AS VARCHAR) FROM (SELECT {quoted} FROM {table} LIMIT {SAMPLE_ROWS})
            WHERE {quoted} IS NOT NULL LIMIT {count}"""
    ).fetchall()
    return [value[:SAMPLE_TEXT_LENGTH] for (value,) in values]


def _sql_name(database: str, schema: str, table: str) -> str:
    parts = (schema, table) if database == FILES_DATABASE else (database, schema, table)
    return '.'.join(_quoted(part) for part in parts)


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _refuse_unless_plain_select(connection: duckdb.DuckDBPyConnection, sql: str) -> None:
    """Only one SELECT, naming tables and never a table function: a function such as postgres_query would
    reach past the sources' tables into whatever else the database holds."""
    statements = connection.extract_statements(sql)
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise QueryRefused('Signature sent something other than one SELECT; it was not run.')
    serialized = json.loads(connection.execute('SELECT json_serialize_sql(?)', [sql]).fetchone()[0])  # type: ignore[index]
    if serialized.get('error'):
        raise QueryRefused(f'Signature sent SQL that does not parse: {serialized.get("error_message")}')
    if _names_table_function(serialized):
        raise QueryRefused('Signature sent a query that calls a table function; it was not run.')


def _names_table_function(node: object) -> bool:
    if isinstance(node, dict):
        fields = cast(dict[str, object], node)
        return fields.get('type') == 'TABLE_FUNCTION' or any(_names_table_function(v) for v in fields.values())
    if isinstance(node, list):
        return any(_names_table_function(item) for item in cast(list[object], node))
    return False
