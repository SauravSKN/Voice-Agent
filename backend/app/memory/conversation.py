import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


class ConversationMemoryError(RuntimeError):
    """Base error for temporary conversation memory."""


class ConversationConfigurationError(ConversationMemoryError):
    """Raised when conversation-memory configuration is invalid."""


class InvalidSessionIdError(ConversationMemoryError):
    """Raised when a session identifier is unsafe or invalid."""


SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class ConversationSettings:
    max_turns: int
    ttl_seconds: float
    max_sessions: int

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ConversationSettings":
        values = os.environ if environment is None else environment
        max_turns = cls._parse_int(
            values,
            "CONVERSATION_MAX_TURNS",
            default=6,
            minimum=1,
            maximum=50,
        )
        ttl_minutes = cls._parse_int(
            values,
            "CONVERSATION_TTL_MINUTES",
            default=30,
            minimum=1,
            maximum=1440,
        )
        max_sessions = cls._parse_int(
            values,
            "CONVERSATION_MAX_SESSIONS",
            default=100,
            minimum=1,
            maximum=10000,
        )
        return cls(
            max_turns=max_turns,
            ttl_seconds=float(ttl_minutes * 60),
            max_sessions=max_sessions,
        )

    @staticmethod
    def _parse_int(
        values: Mapping[str, str],
        name: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = values.get(name, str(default)).strip()
        try:
            value = int(raw_value)
        except ValueError as error:
            raise ConversationConfigurationError(
                f"{name} must be an integer."
            ) from error
        if value < minimum or value > maximum:
            raise ConversationConfigurationError(
                f"{name} must be between {minimum} and {maximum}."
            )
        return value


@dataclass
class _ConversationState:
    messages: list[dict[str, str]] = field(default_factory=list)
    last_access: float = 0.0


class ConversationStore:
    """Thread-safe, bounded, process-local conversation storage."""

    def __init__(
        self,
        settings: ConversationSettings | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or ConversationSettings.from_environment()
        self._clock = clock
        self._sessions: dict[str, _ConversationState] = {}
        self._lock = threading.RLock()

    @staticmethod
    def validate_session_id(session_id: str) -> str:
        if not isinstance(session_id, str):
            raise InvalidSessionIdError("The session ID must be text.")
        if not session_id:
            raise InvalidSessionIdError("The session ID must not be blank.")
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise InvalidSessionIdError(
                "The session ID may contain only letters, numbers, "
                "underscores, and hyphens, with a maximum length of 128."
            )
        return session_id

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        validated_id = self.validate_session_id(session_id)
        now = self._clock()
        with self._lock:
            self._remove_expired_locked(now)
            state = self._sessions.get(validated_id)
            if state is None:
                return []
            state.last_access = now
            return [dict(message) for message in state.messages]

    def add_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> int:
        validated_id = self.validate_session_id(session_id)
        user_text = self._validate_message(user_message, "user")
        assistant_text = self._validate_message(
            assistant_message,
            "assistant",
        )
        now = self._clock()

        with self._lock:
            self._remove_expired_locked(now)
            state = self._sessions.get(validated_id)
            if state is None:
                self._make_session_space_locked()
                state = _ConversationState(last_access=now)
                self._sessions[validated_id] = state

            state.messages.extend(
                [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text},
                ]
            )
            maximum_messages = self.settings.max_turns * 2
            if len(state.messages) > maximum_messages:
                state.messages = state.messages[-maximum_messages:]
            state.last_access = now
            return len(state.messages) // 2

    def clear(self, session_id: str) -> bool:
        validated_id = self.validate_session_id(session_id)
        now = self._clock()
        with self._lock:
            self._remove_expired_locked(now)
            return self._sessions.pop(validated_id, None) is not None

    def turn_count(self, session_id: str) -> int:
        return len(self.get_history(session_id)) // 2

    def session_count(self) -> int:
        now = self._clock()
        with self._lock:
            self._remove_expired_locked(now)
            return len(self._sessions)

    @staticmethod
    def _validate_message(message: str, role: str) -> str:
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"The {role} message must not be blank.")
        return message.strip()

    def _remove_expired_locked(self, now: float) -> None:
        expired_ids = [
            session_id
            for session_id, state in self._sessions.items()
            if now - state.last_access >= self.settings.ttl_seconds
        ]
        for session_id in expired_ids:
            del self._sessions[session_id]

    def _make_session_space_locked(self) -> None:
        while len(self._sessions) >= self.settings.max_sessions:
            least_recent_session = min(
                self._sessions,
                key=lambda session_id: self._sessions[session_id].last_access,
            )
            del self._sessions[least_recent_session]
