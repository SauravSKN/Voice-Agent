import json
import os
import re
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class LanguageModelError(RuntimeError):
    """Base error for local language-model operations."""


class LanguageModelConfigurationError(LanguageModelError):
    """Raised when local language-model configuration is invalid."""


class InvalidLanguageModelInputError(LanguageModelError):
    """Raised when a user message is blank or too long."""


class ModelServerUnavailableError(LanguageModelError):
    """Raised when the local Ollama server cannot be reached."""


class ModelLoadingError(LanguageModelError):
    """Raised when Ollama cannot load or use the configured model."""


class LanguageModelTimeoutError(LanguageModelError):
    """Raised when local generation exceeds the configured timeout."""


class BlankModelResponseError(LanguageModelError):
    """Raised when the local model returns no usable text."""


@dataclass(frozen=True)
class LanguageModelSettings:
    provider: str
    model: str
    base_url: str
    max_tokens: int
    temperature: float
    timeout_seconds: float
    max_input_chars: int
    max_response_chars: int
    context_tokens: int
    keep_alive: str
    max_history_messages: int

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "LanguageModelSettings":
        values = os.environ if environment is None else environment
        provider = values.get("LLM_PROVIDER", "ollama").strip().lower()
        model = values.get("LLM_MODEL", "qwen3:4b-instruct").strip()
        base_url = values.get(
            "LLM_BASE_URL",
            "http://127.0.0.1:11434",
        ).strip().rstrip("/")

        if provider != "ollama":
            raise LanguageModelConfigurationError(
                "LLM_PROVIDER must be 'ollama'."
            )
        if not model:
            raise LanguageModelConfigurationError(
                "LLM_MODEL must not be empty."
            )

        parsed_url = urlparse(base_url)
        if (
            parsed_url.scheme != "http"
            or parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise LanguageModelConfigurationError(
                "LLM_BASE_URL must be a local HTTP URL on "
                "127.0.0.1, localhost, or ::1."
            )

        max_tokens = cls._parse_int(values, "LLM_MAX_TOKENS", 160, 1, 1024)
        max_input_chars = cls._parse_int(
            values,
            "LLM_MAX_INPUT_CHARS",
            2000,
            1,
            20000,
        )
        max_response_chars = cls._parse_int(
            values,
            "LLM_MAX_RESPONSE_CHARS",
            1200,
            1,
            10000,
        )
        context_tokens = cls._parse_int(
            values,
            "LLM_CONTEXT_TOKENS",
            4096,
            512,
            32768,
        )
        max_history_messages = cls._parse_int(
            values,
            "LLM_MAX_HISTORY_MESSAGES",
            12,
            0,
            100,
        )
        if max_history_messages % 2 != 0:
            raise LanguageModelConfigurationError(
                "LLM_MAX_HISTORY_MESSAGES must be an even number."
            )
        temperature = cls._parse_float(
            values,
            "LLM_TEMPERATURE",
            0.4,
            0.0,
            2.0,
        )
        timeout_seconds = cls._parse_float(
            values,
            "LLM_TIMEOUT_SECONDS",
            60.0,
            1.0,
            600.0,
        )
        keep_alive = values.get("LLM_KEEP_ALIVE", "5m").strip()
        if not keep_alive or len(keep_alive) > 20:
            raise LanguageModelConfigurationError(
                "LLM_KEEP_ALIVE must be a short Ollama duration such as '5m'."
            )

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            max_input_chars=max_input_chars,
            max_response_chars=max_response_chars,
            context_tokens=context_tokens,
            keep_alive=keep_alive,
            max_history_messages=max_history_messages,
        )

    @staticmethod
    def _parse_int(
        values: Mapping[str, str],
        name: str,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = values.get(name, str(default)).strip()
        try:
            value = int(raw_value)
        except ValueError as error:
            raise LanguageModelConfigurationError(
                f"{name} must be an integer."
            ) from error
        if value < minimum or value > maximum:
            raise LanguageModelConfigurationError(
                f"{name} must be between {minimum} and {maximum}."
            )
        return value

    @staticmethod
    def _parse_float(
        values: Mapping[str, str],
        name: str,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        raw_value = values.get(name, str(default)).strip()
        try:
            value = float(raw_value)
        except ValueError as error:
            raise LanguageModelConfigurationError(
                f"{name} must be a number."
            ) from error
        if value < minimum or value > maximum:
            raise LanguageModelConfigurationError(
                f"{name} must be between {minimum} and {maximum}."
            )
        return value


@dataclass(frozen=True)
class LanguageModelResult:
    response: str
    generation_time_ms: int


JsonTransport = Callable[[str, dict[str, Any], float], dict[str, Any]]


class LanguageModelService:
    """Generate short Hindi replies through a loopback-only Ollama server."""

    def __init__(
        self,
        settings: LanguageModelSettings | None = None,
        transport: JsonTransport | None = None,
        prompt_path: Path | None = None,
    ) -> None:
        self.settings = settings or LanguageModelSettings.from_environment()
        self._transport = transport or self._post_json
        self._prompt_path = prompt_path or (
            Path(__file__).resolve().parent.parent
            / "prompts"
            / "hindi_assistant.txt"
        )
        self._system_prompt = self._load_system_prompt()

        print(f"LLM provider: {self.settings.provider}")
        print(f"LLM model: {self.settings.model}")
        print(f"LLM base URL: {self.settings.base_url}")

    def _load_system_prompt(self) -> str:
        try:
            prompt = self._prompt_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ModelLoadingError(
                "The Hindi assistant system prompt could not be loaded."
            ) from error
        if not prompt:
            raise ModelLoadingError(
                "The Hindi assistant system prompt is empty."
            )
        return prompt

    def generate(
        self,
        user_text: str,
        history: Sequence[Mapping[str, str]] | None = None,
    ) -> LanguageModelResult:
        if not isinstance(user_text, str):
            raise InvalidLanguageModelInputError(
                "The message must be text."
            )

        message = user_text.strip()
        if not message:
            raise InvalidLanguageModelInputError(
                "The message must not be blank."
            )
        if len(message) > self.settings.max_input_chars:
            raise InvalidLanguageModelInputError(
                "The message is too long. Maximum length is "
                f"{self.settings.max_input_chars} characters."
            )

        recent_history = self._prepare_history(history)
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                *recent_history,
                {"role": "user", "content": message},
            ],
            "stream": False,
            "think": False,
            "keep_alive": self.settings.keep_alive,
            "options": {
                "temperature": self.settings.temperature,
                "num_predict": self.settings.max_tokens,
                "num_ctx": self.settings.context_tokens,
            },
        }

        started = time.perf_counter()
        try:
            response_data = self._transport(
                f"{self.settings.base_url}/api/chat",
                payload,
                self.settings.timeout_seconds,
            )
        except LanguageModelError:
            raise
        except HTTPError as error:
            if error.code == 404:
                raise ModelLoadingError(
                    "The configured local Ollama model is unavailable."
                ) from error
            raise ModelLoadingError(
                f"The local Ollama server returned HTTP {error.code}."
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise LanguageModelTimeoutError(
                "The local model request timed out."
            ) from error
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise LanguageModelTimeoutError(
                    "The local model request timed out."
                ) from error
            raise ModelServerUnavailableError(
                "The local Ollama server is unavailable."
            ) from error
        except (ConnectionError, OSError) as error:
            raise ModelServerUnavailableError(
                "The local Ollama server is unavailable."
            ) from error
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            print(
                "LLM generation time: "
                f"{elapsed_ms} ms for {len(message)} input characters"
            )

        try:
            raw_response = response_data["message"]["content"]
        except (KeyError, TypeError) as error:
            raise ModelLoadingError(
                "The local model returned an invalid response."
            ) from error

        cleaned_response = self.clean_response(str(raw_response))
        if not cleaned_response:
            raise BlankModelResponseError(
                "The local model returned a blank response."
            )

        return LanguageModelResult(
            response=cleaned_response,
            generation_time_ms=elapsed_ms,
        )

    def _prepare_history(
        self,
        history: Sequence[Mapping[str, str]] | None,
    ) -> list[dict[str, str]]:
        if not history or self.settings.max_history_messages == 0:
            return []

        prepared_messages: list[dict[str, str]] = []
        for item in history:
            if not isinstance(item, Mapping):
                raise InvalidLanguageModelInputError(
                    "The conversation history is invalid."
                )
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(
                content,
                str,
            ):
                raise InvalidLanguageModelInputError(
                    "The conversation history is invalid."
                )
            cleaned_content = content.strip()
            if not cleaned_content:
                continue
            if len(cleaned_content) > self.settings.max_input_chars:
                raise InvalidLanguageModelInputError(
                    "A conversation-history message is too long."
                )
            prepared_messages.append(
                {"role": role, "content": cleaned_content}
            )

        return prepared_messages[-self.settings.max_history_messages :]

    def clean_response(self, response: str) -> str:
        text = response.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        text = re.sub(r"^```(?:text|markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = text.replace("**", "").replace("__", "").replace("`", "")
        text = re.sub(
            r"^(?:assistant|सहायक|उत्तर)\s*:\s*",
            "",
            text,
            flags=re.I,
        )

        cleaned_lines = []
        for line in text.splitlines():
            cleaned_line = re.sub(
                r"^\s*(?:#{1,6}\s+|[-*•]\s+)",
                "",
                line,
            ).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        text = " ".join(cleaned_lines)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) <= self.settings.max_response_chars:
            return text

        shortened = text[: self.settings.max_response_chars].rstrip()
        sentence_end = max(
            shortened.rfind("।"),
            shortened.rfind("."),
            shortened.rfind("!"),
            shortened.rfind("?"),
        )
        if sentence_end >= self.settings.max_response_chars // 2:
            return shortened[: sentence_end + 1]
        return f"{shortened.rstrip(' ,;:')}…"

    @staticmethod
    def _post_json(
        url: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            response_bytes = response.read()
        try:
            parsed_response = json.loads(response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelLoadingError(
                "The local model returned invalid JSON."
            ) from error
        if not isinstance(parsed_response, dict):
            raise ModelLoadingError(
                "The local model returned an invalid response object."
            )
        return parsed_response
