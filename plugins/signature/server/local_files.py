"""Which files on the member's machine a location names, and in which format. A location is a path, a folder or a
glob: only where to look, never what is in the files. Nothing here opens a file."""

import glob
from dataclasses import dataclass
from pathlib import Path

FORMAT_OF_SUFFIX = {'.csv': 'csv', '.tsv': 'tsv', '.parquet': 'parquet', '.json': 'json', '.jsonl': 'json',
                    '.ndjson': 'json', '.xlsx': 'excel'}
GLOB_CHARACTERS = '*?['


def absolute_location(location: str) -> str:
    """The location as an absolute path with `~` expanded, so the same place always names the same source."""
    return str(Path(location).expanduser().absolute())


@dataclass(frozen=True)
class LocalFile:
    """A readable file a location names, and the format its suffix says it is."""
    path: Path
    format: str


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


def names_of(files: list[LocalFile]) -> dict[Path, str]:
    """Each file's reported name: its stem, or the whole file name where two share a stem."""
    stems = [file.path.stem for file in files]
    return {file.path: file.path.name if stems.count(file.path.stem) > 1 else file.path.stem for file in files}
