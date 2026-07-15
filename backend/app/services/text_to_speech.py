import logging
import os
import re
import time
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

import onnxruntime
from piper import PiperVoice


logger = logging.getLogger(__name__)

SAFE_AUDIO_FILENAME = re.compile(r"^tts-[0-9a-f]{32}\.wav$")


class TextToSpeechError(RuntimeError):
    """Base error raised by the local text-to-speech service."""


class TextToSpeechConfigurationError(TextToSpeechError):
    """Raised when text-to-speech configuration is invalid."""


class InvalidTextToSpeechInputError(TextToSpeechError):
    """Raised when synthesis input is blank, invalid, or excessive."""


class TextToSpeechModelLoadingError(TextToSpeechError):
    """Raised when the configured Piper voice cannot be loaded."""


class TextToSpeechGenerationError(TextToSpeechError):
    """Raised when Piper cannot generate a valid WAV file."""


class EmptyTextToSpeechOutputError(TextToSpeechGenerationError):
    """Raised when synthesis produces no usable audio frames."""


def backend_directory() -> Path:
    return Path(__file__).resolve().parents[2]


def default_generated_audio_directory() -> Path:
    return backend_directory() / "generated_audio"


def is_safe_audio_filename(filename: str) -> bool:
    return bool(SAFE_AUDIO_FILENAME.fullmatch(filename))


@dataclass(frozen=True)
class TextToSpeechSettings:
    provider: str
    model_path: Path
    requested_device: str
    output_format: str
    max_input_chars: int
    allow_cpu_fallback: bool
    timeout_seconds: float
    output_ttl_minutes: int
    max_output_files: int

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        base_directory: Path | None = None,
    ) -> "TextToSpeechSettings":
        values = os.environ if environment is None else environment
        base_path = (base_directory or backend_directory()).resolve()

        provider = values.get("TTS_PROVIDER", "piper").strip().lower()
        raw_model = values.get(
            "TTS_MODEL",
            "models/piper/hi_IN-priyamvada-medium.onnx",
        ).strip()
        requested_device = values.get("TTS_DEVICE", "cpu").strip().lower()
        output_format = values.get("TTS_OUTPUT_FORMAT", "wav").strip().lower()
        fallback_value = values.get(
            "TTS_ALLOW_CPU_FALLBACK",
            "true",
        ).strip().lower()

        if provider != "piper":
            raise TextToSpeechConfigurationError(
                "TTS_PROVIDER must be 'piper'."
            )
        if not raw_model:
            raise TextToSpeechConfigurationError(
                "TTS_MODEL must be a local Piper ONNX model path."
            )
        if requested_device not in {"cpu", "cuda"}:
            raise TextToSpeechConfigurationError(
                "TTS_DEVICE must be either 'cpu' or 'cuda'."
            )
        if output_format != "wav":
            raise TextToSpeechConfigurationError(
                "TTS_OUTPUT_FORMAT must be 'wav'."
            )
        if fallback_value in {"1", "true", "yes", "on"}:
            allow_cpu_fallback = True
        elif fallback_value in {"0", "false", "no", "off"}:
            allow_cpu_fallback = False
        else:
            raise TextToSpeechConfigurationError(
                "TTS_ALLOW_CPU_FALLBACK must be true or false."
            )

        model_path = Path(raw_model).expanduser()
        if not model_path.is_absolute():
            model_path = base_path / model_path

        return cls(
            provider=provider,
            model_path=model_path.resolve(),
            requested_device=requested_device,
            output_format=output_format,
            max_input_chars=cls._parse_int(
                values,
                "TTS_MAX_INPUT_CHARS",
                500,
                1,
                5000,
            ),
            allow_cpu_fallback=allow_cpu_fallback,
            timeout_seconds=cls._parse_float(
                values,
                "TTS_TIMEOUT_SECONDS",
                60.0,
                1.0,
                300.0,
            ),
            output_ttl_minutes=cls._parse_int(
                values,
                "TTS_OUTPUT_TTL_MINUTES",
                60,
                1,
                10080,
            ),
            max_output_files=cls._parse_int(
                values,
                "TTS_MAX_OUTPUT_FILES",
                50,
                1,
                10000,
            ),
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
            raise TextToSpeechConfigurationError(
                f"{name} must be an integer."
            ) from error
        if value < minimum or value > maximum:
            raise TextToSpeechConfigurationError(
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
            raise TextToSpeechConfigurationError(
                f"{name} must be a number."
            ) from error
        if value < minimum or value > maximum:
            raise TextToSpeechConfigurationError(
                f"{name} must be between {minimum} and {maximum}."
            )
        return value


@dataclass(frozen=True)
class TextToSpeechResult:
    file_path: Path
    filename: str
    generation_time_ms: int


VoiceFactory = Callable[..., object]
ProviderGetter = Callable[[], Sequence[str]]


class TextToSpeechService:
    """Generate short Hindi WAV responses through one cached Piper voice."""

    def __init__(
        self,
        settings: TextToSpeechSettings | None = None,
        *,
        voice_factory: VoiceFactory = PiperVoice.load,
        provider_getter: ProviderGetter = onnxruntime.get_available_providers,
        output_directory: Path | None = None,
    ) -> None:
        self.settings = settings or TextToSpeechSettings.from_environment()
        self.output_directory = (
            output_directory or default_generated_audio_directory()
        ).resolve()
        self.actual_device = "uninitialized"
        self.model_loading_time_seconds = 0.0
        self.last_generation_time_seconds = 0.0
        self._lock = RLock()

        try:
            self.output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise TextToSpeechConfigurationError(
                "The generated-audio directory could not be created."
            ) from error

        print(f"TTS provider: {self.settings.provider}")
        print(f"TTS model: {self.settings.model_path.name}")
        print(f"Requested TTS device: {self.settings.requested_device}")
        print(f"TTS output format: {self.settings.output_format}")

        self.voice = self._load_voice(voice_factory, provider_getter)
        self.cleanup_generated_audio()

    @property
    def model_config_path(self) -> Path:
        return Path(f"{self.settings.model_path}.json")

    def _load_voice(
        self,
        voice_factory: VoiceFactory,
        provider_getter: ProviderGetter,
    ) -> object:
        if not self.settings.model_path.is_file():
            raise TextToSpeechModelLoadingError(
                "The configured Piper model file is unavailable."
            )
        if not self.model_config_path.is_file():
            raise TextToSpeechModelLoadingError(
                "The configured Piper model JSON file is unavailable."
            )

        try:
            providers = set(provider_getter())
        except Exception as error:
            raise TextToSpeechModelLoadingError(
                "ONNX Runtime providers could not be inspected."
            ) from error

        print(f"ONNX Runtime providers: {sorted(providers)}")
        requested_cuda = self.settings.requested_device == "cuda"
        cuda_available = "CUDAExecutionProvider" in providers

        if requested_cuda and not cuda_available:
            if not self.settings.allow_cpu_fallback:
                raise TextToSpeechModelLoadingError(
                    "CUDA was requested for TTS, but ONNX Runtime does not "
                    "provide CUDAExecutionProvider."
                )
            logger.warning(
                "CUDA TTS was requested but unavailable; using CPU."
            )
            requested_cuda = False

        load_started = time.perf_counter()
        try:
            voice = voice_factory(
                self.settings.model_path,
                config_path=self.model_config_path,
                use_cuda=requested_cuda,
            )
            self.actual_device = "cuda" if requested_cuda else "cpu"
        except Exception as error:
            if requested_cuda and self.settings.allow_cpu_fallback:
                logger.exception(
                    "CUDA Piper initialization failed; retrying on CPU."
                )
                try:
                    voice = voice_factory(
                        self.settings.model_path,
                        config_path=self.model_config_path,
                        use_cuda=False,
                    )
                    self.actual_device = "cpu"
                except Exception as fallback_error:
                    raise TextToSpeechModelLoadingError(
                        "Piper failed to load on CUDA and CPU fallback."
                    ) from fallback_error
            else:
                raise TextToSpeechModelLoadingError(
                    "The configured Piper voice could not be loaded."
                ) from error
        finally:
            self.model_loading_time_seconds = (
                time.perf_counter() - load_started
            )
            print(
                "TTS model-loading time: "
                f"{self.model_loading_time_seconds:.3f} seconds"
            )

        print(f"Actual TTS device: {self.actual_device}")
        return voice

    def generate(self, text: str) -> TextToSpeechResult:
        if not isinstance(text, str):
            raise InvalidTextToSpeechInputError(
                "TTS input must be text."
            )

        cleaned_text = re.sub(r"\s+", " ", text).strip()
        if not cleaned_text:
            raise InvalidTextToSpeechInputError(
                "TTS input must not be blank."
            )
        if len(cleaned_text) > self.settings.max_input_chars:
            raise InvalidTextToSpeechInputError(
                "TTS input is too long. Maximum length is "
                f"{self.settings.max_input_chars} characters."
            )

        filename = f"tts-{uuid4().hex}.wav"
        if not is_safe_audio_filename(filename):
            raise TextToSpeechGenerationError(
                "A safe output filename could not be generated."
            )
        output_path = self.output_directory / filename
        temporary_path = self.output_directory / f".{filename}.tmp"

        generation_started = time.perf_counter()
        with self._lock:
            self.cleanup_generated_audio()
            try:
                with wave.open(str(temporary_path), "wb") as wav_file:
                    self.voice.synthesize_wav(cleaned_text, wav_file)
                temporary_path.replace(output_path)
                self._validate_wav(output_path)
            except EmptyTextToSpeechOutputError:
                output_path.unlink(missing_ok=True)
                temporary_path.unlink(missing_ok=True)
                raise
            except Exception as error:
                output_path.unlink(missing_ok=True)
                temporary_path.unlink(missing_ok=True)
                raise TextToSpeechGenerationError(
                    "Piper could not generate response audio."
                ) from error
            finally:
                self.last_generation_time_seconds = (
                    time.perf_counter() - generation_started
                )
                print(
                    "TTS generation time: "
                    f"{self.last_generation_time_seconds:.3f} seconds"
                )

            self.cleanup_generated_audio(protected_path=output_path)

        return TextToSpeechResult(
            file_path=output_path,
            filename=filename,
            generation_time_ms=round(
                self.last_generation_time_seconds * 1000
            ),
        )

    @staticmethod
    def _validate_wav(output_path: Path) -> None:
        if not output_path.is_file() or output_path.stat().st_size <= 44:
            raise EmptyTextToSpeechOutputError(
                "TTS generated an empty audio file."
            )
        try:
            with wave.open(str(output_path), "rb") as wav_file:
                valid_audio = (
                    wav_file.getnframes() > 0
                    and wav_file.getframerate() > 0
                    and wav_file.getnchannels() > 0
                    and wav_file.getsampwidth() > 0
                )
        except (OSError, EOFError, wave.Error) as error:
            raise TextToSpeechGenerationError(
                "TTS output is not a valid WAV file."
            ) from error
        if not valid_audio:
            raise EmptyTextToSpeechOutputError(
                "TTS generated no usable audio frames."
            )

    def cleanup_generated_audio(
        self,
        *,
        protected_path: Path | None = None,
        current_time: float | None = None,
    ) -> int:
        """Remove expired WAVs, then enforce the configured file-count cap."""
        now = time.time() if current_time is None else current_time
        cutoff = now - (self.settings.output_ttl_minutes * 60)
        removed = 0

        with self._lock:
            candidates: list[Path] = []
            try:
                entries = list(self.output_directory.iterdir())
            except OSError:
                logger.exception("Generated-audio cleanup could not list files.")
                return 0

            for path in entries:
                if (
                    not path.is_file()
                    or not is_safe_audio_filename(path.name)
                    or path == protected_path
                ):
                    continue
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                    else:
                        candidates.append(path)
                except OSError:
                    logger.warning(
                        "Generated-audio cleanup skipped one file."
                    )

            candidates.sort(key=lambda item: item.stat().st_mtime)
            excess = max(
                0,
                len(candidates)
                + (1 if protected_path and protected_path.exists() else 0)
                - self.settings.max_output_files,
            )
            for path in candidates[:excess]:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    logger.warning(
                        "Generated-audio cleanup skipped one excess file."
                    )

        return removed
