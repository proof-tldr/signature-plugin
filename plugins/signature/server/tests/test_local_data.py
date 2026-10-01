from pathlib import Path

import pytest

from signature_plugin import local_data
from signature_plugin.local_data import QueryRefused
from signature_plugin.sources import FileSource, SourceRefused, Sources


@pytest.fixture
def sources(tmp_path: Path, data_files: Path) -> list[FileSource]:
    registry = Sources(tmp_path / 'domain')
    return registry.add_files([str(data_files)])


def test_a_folder_adds_each_data_file_in_it(sources: list[FileSource]) -> None:
    assert sorted((source.name, source.format) for source in sources) == [
        ('customers', 'parquet'),
        ('orders', 'csv'),
        ('products', 'xlsx'),
    ]


def test_adding_the_same_file_again_adds_nothing(tmp_path: Path, data_files: Path) -> None:
    registry = Sources(tmp_path / 'domain')
    registry.add_files([str(data_files / 'orders.csv')])
    assert registry.add_files([str(data_files / 'orders.csv')]) == []
    assert len(registry.all()) == 1


def test_a_file_that_is_not_data_is_refused(tmp_path: Path) -> None:
    notes = tmp_path / 'notes.md'
    notes.write_text('hello', encoding='utf-8')
    with pytest.raises(SourceRefused, match='not a CSV'):
        Sources(tmp_path / 'domain').add_files([str(notes)])


def test_one_catalog_describes_every_source_by_its_duckdb_name_and_no_values(sources: list[FileSource]) -> None:
    catalog = local_data.catalog(sources)

    names = {(table['catalog'], table['schema'], table['name']) for table in catalog['tables']}
    assert names == {('memory', 'files', 'orders'), ('memory', 'files', 'customers'), ('memory', 'files', 'products')}
    orders = next(table for table in catalog['tables'] if table['name'] == 'orders')
    assert {'name': 'status', 'nativeType': 'VARCHAR', 'nullable': True} in orders['columns']
    assert 'paid' not in str(catalog)
    assert local_data.run(sources, 'SELECT count(*) FROM "memory"."files"."orders"').rows == [(3,)]


def test_the_fingerprint_follows_the_structure_not_the_rows(tmp_path: Path, data_files: Path) -> None:
    orders = data_files / 'orders.csv'
    sources = Sources(tmp_path / 'domain').add_files([str(orders)])
    before = local_data.fingerprint(sources)

    orders.write_text(orders.read_text(encoding='utf-8') + '4,2,paid,900\n', encoding='utf-8')
    assert local_data.fingerprint(sources) == before

    orders.write_text('id,customer_id,state,amount_cents\n1,1,paid,1000\n', encoding='utf-8')
    assert local_data.fingerprint(sources) != before


def test_every_format_can_be_queried(sources: list[FileSource]) -> None:
    for source in sources:
        assert local_data.run(sources, f'SELECT * FROM files."{source.name}"').rows


def test_a_select_runs(sources: list[FileSource]) -> None:
    result = local_data.run(
        sources,
        'SELECT c.name, SUM(o.amount_cents) FROM files.orders o JOIN files.customers c '
        'ON c.id = o.customer_id GROUP BY 1 ORDER BY 1',
    )
    assert result.rows == [('Acme', 1500), ('Globex', 700)]


def test_each_row_of_a_file_has_its_own_rowid(sources: list[FileSource]) -> None:
    """Signature keys a file's rows by their rowid, as a file has no key."""
    result = local_data.run(sources, 'SELECT count(DISTINCT rowid), count(*) FROM memory.files.orders')
    assert result.rows == [(3, 3)]


@pytest.mark.parametrize(
    ('sql', 'reason'),
    [
        ("SELECT * FROM read_csv('/etc/hosts')", 'table function'),
        ('SELECT 1; SELECT 2', 'one SELECT'),
        ('DELETE FROM files.orders', 'one SELECT'),
        ("COPY (SELECT 1) TO '/tmp/out.csv'", 'one SELECT'),
        ("ATTACH 'other.db'", 'one SELECT'),
        ('SELECT * FROM nowhere', 'failed on your data'),
    ],
)
def test_anything_but_a_select_over_the_sources_is_refused(sources: list[FileSource], sql: str, reason: str) -> None:
    with pytest.raises(QueryRefused, match=reason):
        local_data.run(sources, sql)


def test_a_scalar_function_cannot_read_files_outside_the_sources(sources: list[FileSource]) -> None:
    with pytest.raises(QueryRefused):
        local_data.run(sources, "SELECT content FROM read_text('/etc/hosts')")
    with pytest.raises(QueryRefused):
        local_data.run(sources, "SELECT getenv('HOME')")


def test_a_missing_file_is_refused_when_opened(tmp_path: Path, data_files: Path) -> None:
    registry = Sources(tmp_path / 'domain')
    [orders] = registry.add_files([str(data_files / 'orders.csv')])
    (data_files / 'orders.csv').unlink()
    with pytest.raises(SourceRefused, match='could not be opened'):
        local_data.check(orders)
