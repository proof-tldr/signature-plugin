"""Where the server leaves an answer for the hook that shows it to the member: one file per question, readable
only by this user, removed once shown. Answers pass through here and never through the model."""

import os
import tempfile
import uuid
from pathlib import Path

FOLDER = Path(tempfile.gettempdir()) / 'signature-answers'


def _path_of(turn_id: str) -> Path:
    return FOLDER / str(uuid.UUID(turn_id))


def leave(turn_id: str, text: str) -> None:
    FOLDER.mkdir(mode=0o700, exist_ok=True)
    folder = FOLDER.lstat()
    if folder.st_uid != os.getuid() or folder.st_mode & 0o077:
        raise PermissionError(f'{FOLDER} is not private to this user')
    path = _path_of(turn_id)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as file:
        file.write(text)


def take(turn_id: str) -> str | None:
    """The text left for that question, removed as it is read; None when there is none."""
    path = _path_of(turn_id)
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    path.unlink(missing_ok=True)
    return text
