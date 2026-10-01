"""A location names files by path, folder or glob, and each is reported under a name that is its own."""

from pathlib import Path

from local_files import absolute_location, files_at, names_of

FILES = Path(__file__).parent / 'files'


def test_a_folder_holds_its_readable_files():
    assert [path.name for path in files_at(str(FILES))] == ['customers.csv', 'events.json', 'orders.parquet', 'prices.tsv']


def test_a_glob_holds_what_it_matches():
    assert [path.name for path in files_at(str(FILES / '*.tsv'))] == ['prices.tsv']


def test_one_file_is_itself():
    assert [path.name for path in files_at(str(FILES / 'orders.parquet'))] == ['orders.parquet']


def test_a_file_of_another_kind_is_not_readable(tmp_path):
    (tmp_path / 'notes.txt').write_text('x')

    assert files_at(str(tmp_path)) == []


def test_files_sharing_a_stem_keep_their_extension():
    paths = [Path('a/orders.csv'), Path('a/orders.parquet'), Path('a/prices.csv')]

    assert list(names_of(paths).values()) == ['orders.csv', 'orders.parquet', 'prices']


def test_a_home_relative_location_is_absolute():
    assert absolute_location('~/data').startswith('/')
