import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.memory.conversation import ConversationSettings, ConversationStore


@dataclass
class _AppointmentSession:
    values: dict[str, Any] = field(default_factory=dict)
    last_access: float = 0.0


class AppointmentWorkflowStore:
    """Bounded, expiring, process-local state separate from chat history."""

    def __init__(
        self,
        settings: ConversationSettings | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or ConversationSettings.from_environment()
        self._clock = clock
        self._sessions: dict[str, _AppointmentSession] = {}
        self._lock = threading.RLock()

    def get(self, session_id: str) -> dict[str, Any]:
        validated = ConversationStore.validate_session_id(session_id)
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            session = self._sessions.get(validated)
            if session is None:
                return {}
            session.last_access = now
            return self._copy(session.values)

    def replace(self, session_id: str, values: dict[str, Any]) -> dict[str, Any]:
        validated = ConversationStore.validate_session_id(session_id)
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            if validated not in self._sessions:
                self._make_space()
            copied = self._copy(values)
            self._sessions[validated] = _AppointmentSession(copied, now)
            return self._copy(copied)

    def clear(self, session_id: str) -> bool:
        validated = ConversationStore.validate_session_id(session_id)
        with self._lock:
            self._remove_expired(self._clock())
            return self._sessions.pop(validated, None) is not None

    def _remove_expired(self, now: float) -> None:
        for session_id in [
            key
            for key, value in self._sessions.items()
            if now - value.last_access >= self.settings.ttl_seconds
        ]:
            del self._sessions[session_id]

    def _make_space(self) -> None:
        while len(self._sessions) >= self.settings.max_sessions:
            oldest = min(
                self._sessions,
                key=lambda key: self._sessions[key].last_access,
            )
            del self._sessions[oldest]

    @staticmethod
    def _copy(values: dict[str, Any]) -> dict[str, Any]:
        copied: dict[str, Any] = {}
        for key, value in values.items():
            if isinstance(value, list):
                copied[key] = [dict(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, dict):
                copied[key] = dict(value)
            else:
                copied[key] = value
        return copied
