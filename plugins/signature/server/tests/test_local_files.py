"""A location names files by path, folder or glob, and each is reported under a name that is its own."""

from pathlib import Path

from local_files import FILE_FORMATS, LocalFile, absolute_location, files_at, names_of

FILES = Path(__file__).parent / 'files'


def test_a_folder_holds_its_readable_files():
    assert [file.path.name for file in files_at(str(FILES))] == ['customers.csv', 'events.json', 'orders.parquet', 'prices.tsv']


def test_a_glob_holds_what_it_matches():
    assert [file.path.name for file in files_at(str(FILES / '*.tsv'))] == ['prices.tsv']


def test_one_file_is_itself():
    assert [file.path.name for file in files_at(str(FILES / 'orders.parquet'))] == ['orders.parquet']


def test_a_file_of_another_kind_is_not_readable(tmp_path):
    (tmp_path / 'notes.txt').write_text('x')

    assert files_at(str(tmp_path)) == []


def test_files_sharing_a_stem_keep_their_extension():
    files = [LocalFile(Path('a/orders.csv'), FILE_FORMATS[0]), LocalFile(Path('a/orders.parquet'), FILE_FORMATS[2]),
             LocalFile(Path('a/prices.csv'), FILE_FORMATS[0])]

    assert names_of(files) == ['orders.csv', 'orders.parquet', 'prices']


def test_a_home_relative_location_is_absolute():
    assert absolute_location('~/data').startswith('/')


def test_files_sharing_a_file_name_in_different_folders_are_named_by_path():
    files = [LocalFile(Path('/a/orders.csv'), FILE_FORMATS[0]), LocalFile(Path('/b/orders.csv'), FILE_FORMATS[0])]

    assert names_of(files) == ['/a/orders.csv', '/b/orders.csv']
