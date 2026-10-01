"""A source the plugin cannot read is refused before any connection is made."""

import asyncio
from pathlib import Path

import pytest

from catalog_readers import SourceNotUsable, read_structure


def test_an_adapter_the_plugin_cannot_read_is_refused():
    with pytest.raises(SourceNotUsable, match='mongodb'):
        asyncio.run(read_structure('mongodb', 'logs'))


def test_an_undefined_service_is_refused_naming_only_the_service():
    with pytest.raises(SourceNotUsable, match='nowhere') as refusal:
        asyncio.run(read_structure('postgresql', 'nowhere'))
    assert 'host' not in str(refusal.value).lower().replace('~/.pg_service.conf', '')


FILES = Path(__file__).parent / 'files'


def test_a_folder_of_files_is_read_for_its_structure_alone():
    structure = asyncio.run(read_structure('files', str(FILES)))

    assert structure.tables == 4
    columns = {file['name']: [(column['name'], column['nativeType']) for column in file['columns']]
               for file in structure.database['catalog']['files']}
    assert columns == {
        'customers': [('id', 'BIGINT'), ('name', 'VARCHAR'), ('placed', 'DATE')],
        'events': [('id', 'BIGINT'), ('tags', 'VARCHAR[]'), ('owner', 'STRUCT("name" VARCHAR)')],
        'orders': [('id', 'BIGINT'), ('amount', 'DECIMAL(18,3)')],
        'prices': [('sku', 'VARCHAR'), ('price', 'DOUBLE')]}


def test_no_value_from_a_file_is_in_what_is_read():
    structure = asyncio.run(read_structure('files', str(FILES)))

    for value in ['Ada', 'Grace', 'secret-value', 'Linus', 'A1']:
        assert value not in str(structure.database)


def test_a_glob_reads_only_what_it_matches():
    structure = asyncio.run(read_structure('files', str(FILES / '*.csv')))

    assert [file['name'] for file in structure.database['catalog']['files']] == ['customers']


def test_a_location_with_no_files_is_refused():
    with pytest.raises(SourceNotUsable, match='No .csv'):
        asyncio.run(read_structure('files', str(FILES / 'nothing-here')))


def test_a_file_that_cannot_be_read_is_refused_without_quoting_it(tmp_path):
    (tmp_path / 'broken.parquet').write_text('secret row value')

    with pytest.raises(SourceNotUsable, match='InvalidInputException') as refusal:
        asyncio.run(read_structure('files', str(tmp_path)))
    assert 'secret row value' not in str(refusal.value)


def test_newline_delimited_json_is_read_like_json(tmp_path):
    (tmp_path / 'log.jsonl').write_text('{"id": 1}\n{"id": 2}\n')
    (tmp_path / 'more.ndjson').write_text('{"id": 3}\n')

    structure = asyncio.run(read_structure('files', str(tmp_path)))

    assert [file['name'] for file in structure.database['catalog']['files']] == ['log', 'more']


def test_files_sharing_a_stem_are_reported_under_their_file_names(tmp_path):
    (tmp_path / 'orders.csv').write_text('id\n1\n')
    (tmp_path / 'orders.tsv').write_text('id\n1\n')

    structure = asyncio.run(read_structure('files', str(tmp_path)))

    assert [file['name'] for file in structure.database['catalog']['files']] == ['orders.csv', 'orders.tsv']
