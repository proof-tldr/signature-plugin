"""Answers go to the customer, never to Claude. The server leaves each answer in a file only this user can read,
named after the question asked; the plugin's hook, which sees the same question, shows the answer in the
terminal right after ask_question and deletes it."""

import hashlib
import os
import tempfile
from pathlib import Path

FOLDER = Path(tempfile.gettempdir()) / f'signature-answers-{os.getuid()}'


def leave(question: str, text: str) -> None:
    FOLDER.mkdir(mode=0o700, exist_ok=True)
    folder = FOLDER.lstat()
    if folder.st_uid != os.getuid() or folder.st_mode & 0o077:
        raise PermissionError(f'{FOLDER} is not private to this user')
    descriptor = os.open(_path_of(question), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
        file.write(text)


def take(question: str) -> str | None:
    """The answer left for that question, deleted as it is read; None when there is none."""
    path = _path_of(question)
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    path.unlink(missing_ok=True)
    return text


def _path_of(question: str) -> Path:
    return FOLDER / hashlib.sha256(question.strip().encode()).hexdigest()
