"""Which files on the member's machine a location names, and the format each is read as. A location is a path, a folder or a
glob: only where to look, never what is in the files. Nothing here reads a file's contents."""

import glob
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class FileFormat:
    """One format DuckDB reads: the suffixes that name it, the query that describes its columns, and the extension
    DuckDB needs loaded first."""
    suffixes: tuple[str, ...]
    describe: str
    extension: str | None = None


# https://duckdb.org/docs/stable/guides/meta/describe, https://duckdb.org/docs/stable/data/csv/auto_detection,
# https://duckdb.org/docs/stable/data/parquet/overview, https://duckdb.org/docs/stable/data/json/overview,
# https://duckdb.org/docs/stable/core_extensions/excel
FILE_FORMATS = (
    FileFormat(('.csv',), 'DESCRIBE SELECT * FROM read_csv_auto(?)'),
    FileFormat(('.tsv',), "DESCRIBE SELECT * FROM read_csv(?, delim = '\t', header = true)"),
    FileFormat(('.parquet',), 'DESCRIBE SELECT * FROM read_parquet(?)'),
    FileFormat(('.json', '.jsonl', '.ndjson'), 'DESCRIBE SELECT * FROM read_json_auto(?)'),
    FileFormat(('.xlsx',), 'DESCRIBE SELECT * FROM read_xlsx(?)', extension='excel'),
)
FORMAT_OF_SUFFIX = {suffix: file_format for file_format in FILE_FORMATS for suffix in file_format.suffixes}
SUPPORTED_SUFFIXES = ', '.join(sorted(FORMAT_OF_SUFFIX))
GLOB_CHARACTERS = '*?['


def absolute_location(location: str) -> str:
    """The location as an absolute path with `~` expanded, so the same place always names the same source."""
    return str(Path(location).expanduser().absolute())


@dataclass(frozen=True)
class LocalFile:
    """A readable file a location names, and the format its suffix says it is."""
    path: Path
    format: FileFormat


def files_at(absolute: str) -> list[LocalFile]:
    """The readable files a location names, in path order: a folder holds its direct children, a glob what it matches."""
    place = Path(absolute)
    if place.is_dir():
        candidates = list(place.iterdir())
    elif any(character in absolute for character in GLOB_CHARACTERS):
        candidates = [Path(match) for match in glob.glob(absolute, recursive=True)]
    else:
        candidates = [place]
    return [LocalFile(path, FORMAT_OF_SUFFIX[path.suffix.lower()]) for path in sorted(candidates)
            if path.is_file() and path.suffix.lower() in FORMAT_OF_SUFFIX]


def source_name_of(absolute: str) -> str:
    """What a location is reported as: its last path component. Two locations ending alike share a name; the
    location, never the name, is what identifies a source."""
    return Path(absolute).name or absolute


def names_of(files: list[LocalFile]) -> list[str]:
    """Each file's reported name, in the files' order: its stem, else its file name where two share a stem, else its
    whole path where two share a file name (a recursive glob across folders)."""
    stems = [file.path.stem for file in files]
    file_names = [file.path.name for file in files]
    return [str(file.path) if file_names.count(file.path.name) > 1
            else file.path.name if stems.count(file.path.stem) > 1 else file.path.stem for file in files]
