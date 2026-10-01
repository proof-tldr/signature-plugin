"""A source's structure (a Postgres catalog's rows, or the columns DuckDB found in files), shaped into the request
Signature takes. Pure: what is read and where it is sent are not this module's concern, and no row of data ever
enters it."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

type Row = dict[str, Any]


@dataclass(frozen=True)
class PostgresqlCatalogRows:
    """What Postgres's catalog says: its tables and views, their columns in order, and their primary keys."""
    relations: list[Row]
    columns: list[Row]
    primary_keys: list[Row]


def described(fields: Row, description: str | None) -> Row:
    return fields | ({'description': description} if description else {})


def postgresql_database(rows: PostgresqlCatalogRows) -> Row:
    """The `database` of a reported source: schemas, their relations, and each relation's columns."""
    columns_of = defaultdict(list)
    for column in rows.columns:
        columns_of[column['schema_name'], column['relation_name']].append(described(
            {'name': column['column_name'], 'nativeType': column['native_type'],
             'nullable': column['is_nullable']}, column['description']))
    primary_key_of = {(key['schema_name'], key['relation_name']): key['columns'] for key in rows.primary_keys}
    schemas = defaultdict(list)
    for relation in rows.relations:
        key = relation['schema_name'], relation['relation_name']
        schemas[relation['schema_name']].append(described(
            {'name': relation['relation_name'], 'primaryKey': primary_key_of.get(key, []),
             'columns': columns_of[key]}, relation['description']))
    return {'adapter': 'postgresql',
            'catalog': {'schemas': [{'name': name, 'relations': relations} for name, relations in schemas.items()]}}


@dataclass(frozen=True)
class FileColumn:
    """One column DuckDB found in a file, its type as DuckDB's `DESCRIBE` printed it."""
    name: str
    duckdb_type: str
    nullable: bool


@dataclass(frozen=True)
class FileStructure:
    """What DuckDB found in one file: the name it is reported under, its format, and its columns in order."""
    name: str
    format: str
    columns: list[FileColumn]


# The type names Signature takes for a file's column: DuckDB's own, lowercase, without parameters.
# https://duckdb.org/docs/stable/sql/data_types/overview
DUCKDB_TYPES = frozenset({
    'boolean', 'tinyint', 'smallint', 'integer', 'bigint', 'hugeint', 'utinyint', 'usmallint', 'uinteger', 'ubigint',
    'uhugeint', 'float', 'double', 'decimal', 'varchar', 'blob', 'bit', 'uuid', 'json', 'date', 'time',
    'time with time zone', 'timestamp', 'timestamp with time zone', 'interval', 'enum', 'list', 'array', 'struct',
    'map', 'union'})
TIMESTAMP_PRECISIONS = {'timestamp_s', 'timestamp_ms', 'timestamp_ns'}
LIST_SUFFIX = re.compile(r'\[(\d*)\]$')
PARAMETERS = re.compile(r'\(.*\)$')


def duckdb_type_name(described: str) -> str:
    """The name Signature takes for a type `DESCRIBE` printed: `DECIMAL(18,3)` is `decimal`, `INTEGER[]` is `list`,
    `INTEGER[3]` is `array`, `TIMESTAMP_MS` is `timestamp`. A type Signature has no name for is reported as `varchar`."""
    suffix = LIST_SUFFIX.search(described)
    if suffix:
        return 'array' if suffix.group(1) else 'list'
    name = PARAMETERS.sub('', described).lower()
    name = 'timestamp' if name in TIMESTAMP_PRECISIONS else name
    return name if name in DUCKDB_TYPES else 'varchar'


def files_database(files: list[FileStructure]) -> Row:
    """The `database` of a reported source: each file with its format and columns."""
    return {'adapter': 'files', 'catalog': {'files': [
        {'name': file.name, 'format': file.format,
         'columns': [{'name': column.name, 'nativeType': duckdb_type_name(column.duckdb_type),
                      'nullable': column.nullable} for column in file.columns]}
        for file in files]}}


TABLES_OF = {
    'postgresql': lambda catalog: sum(len(schema['relations']) for schema in catalog['schemas']),
    'files': lambda catalog: len(catalog['files']),
}


def table_count(database: Row) -> int:
    return TABLES_OF[database['adapter']](database['catalog'])
