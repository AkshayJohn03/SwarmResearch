"""Human-in-the-loop support.

A node that needs an external decision calls :func:`require_input`.  When
no input is queued the node raises :class:`HumanInterrupt`, the runtime
pauses the whole run (checkpointing state), and ``run(resume=True,
human_input=...)`` later injects the answer.  Offline the answer comes
from a :class:`HumanInputQueue` or a JSON file -- no network required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class HumanInterrupt(Exception):
    """Raised by a node to pause the run until an external answer arrives."""

    def __init__(self, prompt: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(prompt)
        self.prompt = prompt
        self.payload = payload or {}


class HumanInputSource(Protocol):
    def take(self) -> str:
        """Return the next queued answer; raise LookupError when empty."""
        ...


class HumanInputQueue:
    """Simple FIFO of preloaded answers (offline mode / tests)."""

    def __init__(self, answers: list[str] | None = None) -> None:
        self._answers = list(answers or [])

    def push(self, answer: str) -> None:
        self._answers.append(answer)

    def take(self) -> str:
        if not self._answers:
            raise LookupError("no human input queued")
        return self._answers.pop(0)


class FileHumanInput:
    """Reads answers lazily from a JSON array file, one per take."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._index = 0

    def _answers(self) -> list[str]:
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{self._path} must contain a JSON array of answers")
        return data

    def take(self) -> str:
        answers = self._answers()
        if self._index >= len(answers):
            raise LookupError("no human input left in file")
        answer = answers[self._index]
        self._index += 1
        return answer


def require_input(source: HumanInputSource, prompt: str, payload: dict | None = None) -> str:
    """Node-facing helper: return the queued answer or pause the run."""
    try:
        return source.take()
    except LookupError as exc:
        raise HumanInterrupt(prompt, payload) from exc
