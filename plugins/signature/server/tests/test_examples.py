from pathlib import Path
from typing import Any

from signature_plugin.examples import examples_of
from signature_plugin.sources import FileSource, Sources


def snapshot_for(customers_table: str) -> dict[str, Any]:
    """Orders read from orders.csv, customers from the named table, and each order's customer read from its
    customer_id column, which holds a customer's id. Tables are named as the local DuckDB names them."""
    return {
        'entities': [{'id': 'order', 'name': 'Order'}, {'id': 'customer', 'name': 'Customer'}],
        'fields': [
            {
                'id': 'order.customer',
                'entityId': 'order',
                'name': 'customer',
                'type': {'kind': 'named', 'name': 'Customer'},
            },
            {
                'id': 'customer.name',
                'entityId': 'customer',
                'name': 'name',
                'type': {'kind': 'named', 'name': 'string'},
            },
        ],
        'sources': [{'id': 'local'}],
        'databaseEntities': [
            {'id': 'orders-table', 'sourceId': 'local', 'relation': 'memory.files.orders'},
            {'id': 'customers-table', 'sourceId': 'local', 'relation': customers_table},
        ],
        'columns': [
            {'id': 'orders.id', 'name': 'id', 'storage': {'kind': 'column', 'column': 'id'}},
            {'id': 'orders.customer_id', 'name': 'customer_id', 'storage': {'kind': 'column', 'column': 'customer_id'}},
            {'id': 'customers.id', 'name': 'id', 'storage': {'kind': 'column', 'column': 'id'}},
            {'id': 'customers.name', 'name': 'name', 'storage': {'kind': 'column', 'column': 'name'}},
        ],
        'mappings': [
            {
                'id': 'm-order',
                'entityId': 'order',
                'databaseEntityId': 'orders-table',
                'identity': [{'columnId': 'orders.id', 'name': 'id'}],
            },
            {
                'id': 'm-customer',
                'entityId': 'customer',
                'databaseEntityId': 'customers-table',
                'identity': [{'columnId': 'customers.id', 'name': 'id'}],
            },
        ],
        'mappingFields': [
            {
                'id': 'mf1',
                'mappingId': 'm-order',
                'columnId': 'orders.customer_id',
                'target': {'kind': 'field', 'fieldId': 'order.customer'},
            },
            {
                'id': 'mf2',
                'mappingId': 'm-customer',
                'columnId': 'customers.name',
                'target': {'kind': 'field', 'fieldId': 'customer.name'},
            },
        ],
    }


def test_examples_name_records_and_pair_related_ones(tmp_path: Path, data_files: Path) -> None:
    sources: list[FileSource] = Sources(tmp_path / 'domain').add_files(
        [str(data_files / 'orders.csv'), str(data_files / 'customers.parquet')]
    )

    found = examples_of(snapshot_for('memory.files.customers'), sources)

    assert sorted(found['things']['customer']) == ['Acme', 'Globex']
    assert sorted(found['things']['order']) == ['Order 1', 'Order 2', 'Order 3']
    pairs: list[list[str]] = found['links']['order.customer']
    assert sorted(map(tuple, pairs)) == [
        ('Order 1', 'Acme'),
        ('Order 2', 'Acme'),
        ('Order 3', 'Globex'),
    ]


def test_a_thing_whose_records_are_not_here_has_no_examples(tmp_path: Path, data_files: Path) -> None:
    sources: list[FileSource] = Sources(tmp_path / 'domain').add_files([str(data_files / 'orders.csv')])

    found = examples_of(snapshot_for('memory.files.not_here'), sources)

    assert 'customer' not in found['things']
    assert found['links'] == {}
