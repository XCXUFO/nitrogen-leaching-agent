"""Bounded in-process task state with session files and legacy single-file requests."""
from __future__ import annotations

import time
from contextlib import contextmanager
from collections.abc import Iterator

from src.agent.contracts import TaskState


class ConversationBusy(RuntimeError):
    pass


class StateCapacityError(RuntimeError):
    pass


class StateStore:
    def __init__(self, *, ttl_seconds: float = 1800, max_sessions: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.entries: dict[str, TaskState] = {}
        self._busy: set[str] = set()

    @contextmanager
    def lease(self, conversation_id: str, attachment_id: str | None, *, session_files: bool = False) -> Iterator[TaskState]:
        # No await between lookup and lease acquisition: atomic on the app event loop.
        if conversation_id in self._busy:
            raise ConversationBusy("conversation_busy")
        now = time.monotonic()
        self.entries = {key: value for key, value in self.entries.items()
                        if value.expires_at > now or key in self._busy}
        if conversation_id not in self.entries:
            if len(self.entries) >= self.max_sessions:
                raise StateCapacityError("conversation_capacity")
            self.entries[conversation_id] = TaskState(conversation_id=conversation_id)
        state = self.entries[conversation_id]
        if not (session_files or state.session_files_enabled) and state.current_attachment_id != attachment_id:
            state.current_attachment_id = attachment_id
            self.clear_metric(state)
        self._busy.add(conversation_id)
        try:
            yield state
        finally:
            state.expires_at = time.monotonic() + self.ttl_seconds
            self._busy.discard(conversation_id)

    @staticmethod
    def clear_metric(state: TaskState) -> None:
        state.current_metric = None
        state.current_operation = []
        state.last_tool = None
