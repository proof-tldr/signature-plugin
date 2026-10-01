"""A catalog's rows become the exact request body Signature takes, carrying structure only."""

from catalog_report import (FileColumn, FileStructure, PostgresqlCatalogRows, duckdb_type_name, files_database,
                            postgresql_database, table_count)

ROWS = PostgresqlCatalogRows(
    relations=[
        {'schema_name': 'public', 'relation_name': 'customers', 'description': 'People who buy'},
        {'schema_name': 'public', 'relation_name': 'orders', 'description': None},
        {'schema_name': 'sales', 'relation_name': 'refunds', 'description': None},
    ],
    columns=[
        {'schema_name': 'public', 'relation_name': 'customers', 'column_name': 'id', 'native_type': 'bigint',
         'is_nullable': False, 'description': None},
        {'schema_name': 'public', 'relation_name': 'customers', 'column_name': 'email', 'native_type': 'text',
         'is_nullable': True, 'description': 'Contact address'},
        {'schema_name': 'public', 'relation_name': 'orders', 'column_name': 'id', 'native_type': 'bigint',
         'is_nullable': False, 'description': None},
        {'schema_name': 'sales', 'relation_name': 'refunds', 'column_name': 'amount', 'native_type': 'numeric',
         'is_nullable': False, 'description': None},
    ],
    primary_keys=[
        {'schema_name': 'public', 'relation_name': 'customers', 'columns': ['id']},
        {'schema_name': 'public', 'relation_name': 'orders', 'columns': ['id']},
    ])

EXPECTED = {'adapter': 'postgresql', 'catalog': {'schemas': [
    {'name': 'public', 'relations': [
        {'name': 'customers', 'primaryKey': ['id'], 'description': 'People who buy', 'columns': [
            {'name': 'id', 'nativeType': 'bigint', 'nullable': False},
            {'name': 'email', 'nativeType': 'text', 'nullable': True, 'description': 'Contact address'}]},
        {'name': 'orders', 'primaryKey': ['id'], 'columns': [
            {'name': 'id', 'nativeType': 'bigint', 'nullable': False}]}]},
    {'name': 'sales', 'relations': [
        {'name': 'refunds', 'primaryKey': [], 'columns': [
            {'name': 'amount', 'nativeType': 'numeric', 'nullable': False}]}]}]}}


def test_rows_become_the_database_signature_takes():
    assert postgresql_database(ROWS) == EXPECTED


def test_tables_are_counted_across_schemas():
    assert table_count(EXPECTED) == 3



def test_duckdb_types_become_the_names_signature_takes():
    assert [duckdb_type_name(described) for described in
            ['BIGINT', 'DECIMAL(18,3)', 'INTEGER[]', 'INTEGER[3]', 'STRUCT(a INTEGER)', 'TIMESTAMP_MS',
             'TIMESTAMP WITH TIME ZONE', 'BIGNUM']] == [
        'bigint', 'decimal', 'list', 'array', 'struct', 'timestamp', 'timestamp with time zone', 'varchar']


def test_files_become_the_database_signature_takes():
    files = [FileStructure('orders', 'parquet', [FileColumn('id', 'BIGINT', True), FileColumn('amount', 'DECIMAL(18,3)', True)])]

    assert files_database(files) == {'adapter': 'files', 'catalog': {'files': [
        {'name': 'orders', 'format': 'parquet', 'columns': [
            {'name': 'id', 'nativeType': 'bigint', 'nullable': True},
            {'name': 'amount', 'nativeType': 'decimal', 'nullable': True}]}]}}
    assert table_count(files_database(files)) == 1
