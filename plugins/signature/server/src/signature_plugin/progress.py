"""Where the customer's setup stands, kept on this machine so Claude never has to carry Signature's ids: the build
it is waiting on, the conversation follow-up questions continue, and which of Signature's question ids each
question number stands for."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Progress(BaseModel):
    build_id: str | None = None
    thread_id: str | None = None
    question_ids: dict[int, str] = {}


class ProgressStore:
    """The progress for one domain, in a file next to its sources."""

    def __init__(self, folder: Path) -> None:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._file = folder / 'progress.json'

    def load(self) -> Progress:
        if not self._file.exists():
            return Progress()
        return Progress.model_validate_json(self._file.read_bytes())

    def save(self, progress: Progress) -> None:
        self._file.write_text(progress.model_dump_json(indent=2), encoding='utf-8')
        self._file.chmod(0o600)


# How a build ended, or that a question is over; the hooks announce a build's ending, while a question's shows itself.
type Outcome = Literal['built', 'questions', 'replied', 'failed', 'asked']


class ActivityBoard:
    """What Signature is doing for the customer now, a build or a question, as the plugin's hooks show it under the
    customer's prompt: a file at the top of the plugin's folder, rewritten while the work runs so the hooks can tell
    live work from a stale record, then left holding how it ended so the hooks can announce a build once."""

    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / 'activity.json'

    def running(self, stage: str | None, started_at: str | None, stages: list[str] | None = None) -> None:
        """Work under way: its current stage, when it started, and every stage it has entered, when it has stages."""
        self._write({'state': 'running', 'stage': stage, 'started_at': started_at, 'stages': stages or []})

    def ended(self, outcome: Outcome) -> None:
        self._write({'state': outcome, 'ended_at': datetime.now(UTC).isoformat()})

    def _write(self, board: dict[str, str | list[str] | None]) -> None:
        self._file.write_text(json.dumps(board), encoding='utf-8')
        self._file.chmod(0o600)
