"""Reads a local database's structure with the member's own connection. Each adapter is a row of ADAPTERS: how
to read its catalog, and how to shape what was read. Only the catalog is queried, never a table's rows."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from catalog_report import PostgresqlCatalogRows, postgresql_database, table_count
from local_sources import LocalSource, SourceNotUsable

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


async def read_postgresql(connection_string: str) -> dict:
    """The `database` of a reported source, from a read-only look at Postgres's catalog."""
    async with await psycopg.AsyncConnection.connect(connection_string, row_factory=dict_row) as connection:
        await connection.set_read_only(True)
        relations = await fetch_all(connection, RELATIONS)
        columns = await fetch_all(connection, COLUMNS)
        primary_keys = await fetch_all(connection, PRIMARY_KEYS)
    return postgresql_database(PostgresqlCatalogRows(relations, columns, primary_keys))


@dataclass(frozen=True)
class Adapter:
    """How to read one kind of database, and which failures mean it could not be reached or read."""
    read: Callable[[str], Awaitable[dict]]
    failures: tuple[type[Exception], ...]


ADAPTERS = {'postgresql': Adapter(read_postgresql, (psycopg.Error, OSError))}


@dataclass(frozen=True)
class ReadStructure:
    """A source's structure as Signature takes it, and how many tables that holds."""
    database: dict
    tables: int


async def read_structure(source: LocalSource) -> ReadStructure:
    """The structure of a local source, read with its own connection; a source that cannot be read is refused."""
    adapter = ADAPTERS.get(source.adapter)
    if adapter is None:
        raise SourceNotUsable(f'Source {source.name} uses the adapter "{source.adapter}", which the plugin cannot '
                              f'read. It reads: {", ".join(ADAPTERS)}.')
    try:
        database = await adapter.read(source.connection_string)
    except adapter.failures as failure:
        raise SourceNotUsable(f'Could not read the structure of {source.name}: {type(failure).__name__}. '
                              'Check its connection string.') from failure
    return ReadStructure(database, table_count(database))
