"""In-memory CLI session state (lives only for one process; nothing is persisted)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    """One chat session: LangGraph thread id, turn counter and a readable transcript."""

    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    turns: int = 0
    transcript: list[tuple[str, str]] = field(default_factory=list)

    def record(self, speaker: str, text: str) -> None:
        """Append one transcript line; user turns increase the turn counter."""
        if speaker == "user":
            self.turns += 1
        self.transcript.append((speaker, text))
