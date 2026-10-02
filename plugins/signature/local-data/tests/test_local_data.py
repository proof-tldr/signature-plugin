from pathlib import Path

import pytest

from signature_local_data import DatabaseSource, DuckDbFolders, FileSource, LocalData, QueryRefused, SourceRefused


def no_password(source: DatabaseSource) -> str:
    raise SourceRefused(f'No password for {source.name}.')


@pytest.fixture
def orders(tmp_path: Path) -> FileSource:
    path = tmp_path / 'orders.csv'
    path.write_text('id,status,amount_cents\n1,paid,1000\n2,open,500\n3,paid,250\n', encoding='utf-8')
    return FileSource(name='orders', path=str(path), format='csv')


@pytest.fixture
def local() -> LocalData:
    return LocalData(no_password)


def test_the_catalog_names_the_table_and_its_columns_but_no_values(local: LocalData, orders: FileSource) -> None:
    catalog = local.catalog([orders])

    [table] = catalog['tables']
    assert (table['catalog'], table['schema'], table['name']) == ('memory', 'files', 'orders')
    assert [column['name'] for column in table['columns']] == ['id', 'status', 'amount_cents']
    assert 'paid' not in str(catalog)


def test_the_fingerprint_changes_only_when_the_structure_does(local: LocalData, orders: FileSource) -> None:
    before = local.fingerprint([orders])
    Path(orders.path).write_text('id,status,amount_cents\n1,paid,9\n', encoding='utf-8')
    assert local.fingerprint([orders]) == before
    Path(orders.path).write_text('id,state\n1,paid\n', encoding='utf-8')
    assert local.fingerprint([orders]) != before


def test_a_select_over_a_csv_runs(local: LocalData, orders: FileSource) -> None:
    result = local.run(
        [orders], 'SELECT status, SUM(amount_cents) AS total FROM files.orders GROUP BY status ORDER BY status'
    )

    assert result.columns == ['status', 'total']
    assert result.rows == [('open', 500), ('paid', 1250)]
    assert not result.truncated


@pytest.mark.parametrize(
    'sql', ['DROP TABLE files.orders', "SELECT * FROM read_csv('/etc/hosts')", 'SELECT 1; SELECT 2']
)
def test_anything_but_one_plain_select_is_refused(local: LocalData, orders: FileSource, sql: str) -> None:
    with pytest.raises(QueryRefused):
        local.run([orders], sql)


def test_run_each_gives_none_for_a_refused_query(local: LocalData, orders: FileSource) -> None:
    results = local.run_each([orders], ['SELECT count(*) FROM files.orders', 'DELETE FROM files.orders'])
    assert results[0] is not None
    assert results[0].rows == [(3,)]
    assert results[1] is None


def test_the_duckdb_folders_are_the_callers_to_set(tmp_path: Path, orders: FileSource) -> None:
    folders = DuckDbFolders(extensions=tmp_path / 'ext', temp=tmp_path / 'tmp', home=tmp_path / 'home')
    local = LocalData(no_password, folders)

    result = local.run(
        [orders],
        "SELECT current_setting('extension_directory'), current_setting('temp_directory'), "
        "current_setting('home_directory')",
    )
    assert result.rows == [(str(tmp_path / 'ext'), str(tmp_path / 'tmp'), str(tmp_path / 'home'))]
