"""Where the customer's setup stands, kept on this machine so Claude never has to carry Signature's ids: the build
it is waiting on, the conversation follow-up questions continue, and which of Signature's question ids each
question number stands for."""

from pathlib import Path

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
