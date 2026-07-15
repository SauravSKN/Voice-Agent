import json
import logging
import os
import re
import time
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import onnxruntime
from piper import PiperVoice

from app.services.speech_formatting import prepare_text_for_speech


logger = logging.getLogger(__name__)

SAFE_AUDIO_FILENAME = re.compile(r"^tts-[0-9a-f]{32}\.wav$")
INDIC_PARLER_MODEL_NAME = "ai4bharat/indic-parler-tts"
INDIC_PARLER_SPEAKERS = frozenset({"Divya", "Rohit"})
INDIC_PARLER_STYLES = frozenset(
    {
        "configured",
        "neutral",
        "warm_friendly",
        "calm_assistant",
        "slightly_expressive",
        "moderate_pace",
        "slightly_slower",
    }
)
VOICE_SELECTIONS = {
    "piper": ("piper", "Priyamvada"),
    "indic_parler_divya": ("indic_parler", "Divya"),
    "indic_parler_rohit": ("indic_parler", "Rohit"),
}
DEFAULT_INDIC_DESCRIPTION = (
    "Divya speaks in a warm, natural and conversational Hindi voice. "
    "Her pace is moderate, her pitch is balanced, and her speech is "
    "slightly expressive. The recording is clear and close, with "
    "no background noise."
)


class TextToSpeechError(RuntimeError):
    """Base error raised by the local text-to-speech service."""


class TextToSpeechConfigurationError(TextToSpeechError):
    """Raised when text-to-speech configuration is invalid."""


class InvalidTextToSpeechInputError(TextToSpeechError):
    """Raised when synthesis input is blank, invalid, or excessive."""


class TextToSpeechModelLoadingError(TextToSpeechError):
    """Raised when the configured text-to-speech model cannot be loaded."""


class TextToSpeechGenerationError(TextToSpeechError):
    """Raised when a provider cannot generate a valid WAV file."""


class TextToSpeechTimeoutError(TextToSpeechError):
    """Raised when a provider request exceeds its configured timeout."""


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
    indic_model_name: str = INDIC_PARLER_MODEL_NAME
    indic_service_url: str = "http://127.0.0.1:8002"
    indic_device: str = "cuda"
    indic_dtype: str = "float16"
    indic_speaker: str = "Divya"
    indic_description: str = DEFAULT_INDIC_DESCRIPTION
    indic_max_input_chars: int = 500
    indic_timeout_seconds: float = 90.0
    indic_allow_cpu_fallback: bool = False
    allow_piper_fallback: bool = True

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

        if provider not in {"piper", "indic_parler"}:
            raise TextToSpeechConfigurationError(
                "TTS_PROVIDER must be 'piper' or 'indic_parler'."
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

        indic_model_name = values.get(
            "INDIC_PARLER_MODEL",
            INDIC_PARLER_MODEL_NAME,
        ).strip()
        if indic_model_name != INDIC_PARLER_MODEL_NAME:
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_MODEL must be ai4bharat/indic-parler-tts."
            )
        indic_service_url = values.get(
            "INDIC_PARLER_SERVICE_URL",
            "http://127.0.0.1:8002",
        ).strip().rstrip("/")
        parsed_service_url = urlsplit(indic_service_url)
        if (
            parsed_service_url.scheme != "http"
            or parsed_service_url.hostname not in {"127.0.0.1", "localhost"}
            or not parsed_service_url.port
            or parsed_service_url.path not in {"", "/"}
            or parsed_service_url.query
            or parsed_service_url.fragment
            or parsed_service_url.username
            or parsed_service_url.password
        ):
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_SERVICE_URL must be a loopback HTTP URL with "
                "an explicit port."
            )
        indic_device = values.get(
            "INDIC_PARLER_DEVICE", "cuda"
        ).strip().lower()
        if indic_device not in {"cpu", "cuda"}:
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_DEVICE must be 'cpu' or 'cuda'."
            )
        indic_dtype = values.get(
            "INDIC_PARLER_DTYPE", "float16"
        ).strip().lower()
        if indic_dtype not in {"float16", "float32"}:
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_DTYPE must be 'float16' or 'float32'."
            )
        if indic_device == "cpu" and indic_dtype != "float32":
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_DTYPE must be float32 when using CPU."
            )
        indic_speaker = values.get(
            "INDIC_PARLER_SPEAKER", "Divya"
        ).strip().title()
        if indic_speaker not in INDIC_PARLER_SPEAKERS:
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_SPEAKER must be 'Divya' or 'Rohit'."
            )
        indic_description = values.get(
            "INDIC_PARLER_DESCRIPTION",
            DEFAULT_INDIC_DESCRIPTION,
        ).strip()
        if not indic_description or len(indic_description) > 1000:
            raise TextToSpeechConfigurationError(
                "INDIC_PARLER_DESCRIPTION must contain 1 to 1000 characters."
            )

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
            indic_model_name=indic_model_name,
            indic_service_url=indic_service_url,
            indic_device=indic_device,
            indic_dtype=indic_dtype,
            indic_speaker=indic_speaker,
            indic_description=indic_description,
            indic_max_input_chars=cls._parse_int(
                values,
                "INDIC_PARLER_MAX_INPUT_CHARS",
                500,
                1,
                2000,
            ),
            indic_timeout_seconds=cls._parse_float(
                values,
                "INDIC_PARLER_TIMEOUT_SECONDS",
                90.0,
                1.0,
                600.0,
            ),
            indic_allow_cpu_fallback=cls._parse_bool(
                values,
                "INDIC_PARLER_ALLOW_CPU_FALLBACK",
                False,
            ),
            allow_piper_fallback=cls._parse_bool(
                values,
                "TTS_ALLOW_PIPER_FALLBACK",
                True,
            ),
        )

    @staticmethod
    def _parse_bool(
        values: Mapping[str, str],
        name: str,
        default: bool,
    ) -> bool:
        raw_value = values.get(
            name, "true" if default else "false"
        ).strip().lower()
        if raw_value in {"1", "true", "yes", "on"}:
            return True
        if raw_value in {"0", "false", "no", "off"}:
            return False
        raise TextToSpeechConfigurationError(
            f"{name} must be true or false."
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
    duration_seconds: float = 0.0
    provider: str = "piper"
    voice: str = "Priyamvada"
    model_loading_time_ms: int = 0
    peak_gpu_memory_mb: float = 0.0


@dataclass(frozen=True)
class IndicParlerResponse:
    audio_bytes: bytes
    model_loading_time_ms: int
    synthesis_time_ms: int
    peak_gpu_memory_mb: float
    actual_device: str


UrlOpener = Callable[..., object]


class IndicParlerClient:
    """Small loopback client for the isolated Indic Parler process."""

    def __init__(
        self,
        service_url: str,
        timeout_seconds: float,
        *,
        opener: UrlOpener = urlopen,
    ) -> None:
        self.service_url = service_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def synthesize(
        self,
        text: str,
        *,
        speaker: str,
        style: str = "configured",
    ) -> IndicParlerResponse:
        if speaker not in INDIC_PARLER_SPEAKERS:
            raise InvalidTextToSpeechInputError(
                "Indic Parler speaker must be Divya or Rohit."
            )
        if style not in INDIC_PARLER_STYLES:
            raise InvalidTextToSpeechInputError(
                "The Indic Parler speaking style is invalid."
            )
        payload = json.dumps(
            {
                "text": text,
                "speaker": speaker,
                "style": style,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.service_url}/synthesize",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                audio_bytes = response.read()
                headers = response.headers
        except HTTPError as error:
            if error.code == 504:
                raise TextToSpeechTimeoutError(
                    "The Indic Parler request timed out."
                ) from error
            if error.code == 503:
                raise TextToSpeechModelLoadingError(
                    "The Indic Parler model is unavailable."
                ) from error
            raise TextToSpeechGenerationError(
                "The Indic Parler service rejected synthesis."
            ) from error
        except TimeoutError as error:
            raise TextToSpeechTimeoutError(
                "The Indic Parler request timed out."
            ) from error
        except (URLError, OSError) as error:
            raise TextToSpeechModelLoadingError(
                "The local Indic Parler service is unavailable."
            ) from error

        if not audio_bytes:
            raise EmptyTextToSpeechOutputError(
                "Indic Parler generated no audio."
            )
        try:
            return IndicParlerResponse(
                audio_bytes=audio_bytes,
                model_loading_time_ms=int(
                    headers.get("X-Model-Loading-Ms", "0")
                ),
                synthesis_time_ms=int(
                    headers.get("X-Synthesis-Ms", "0")
                ),
                peak_gpu_memory_mb=float(
                    headers.get("X-Peak-GPU-Memory-MB", "0")
                ),
                actual_device=headers.get("X-Actual-Device", "unknown"),
            )
        except (TypeError, ValueError) as error:
            raise TextToSpeechGenerationError(
                "The Indic Parler service returned invalid metadata."
            ) from error


VoiceFactory = Callable[..., object]
ProviderGetter = Callable[[], Sequence[str]]


class TextToSpeechService:
    """Generate Hindi WAV responses through lazy, validated providers."""

    def __init__(
        self,
        settings: TextToSpeechSettings | None = None,
        *,
        voice_factory: VoiceFactory = PiperVoice.load,
        provider_getter: ProviderGetter = onnxruntime.get_available_providers,
        indic_client: IndicParlerClient | None = None,
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
        self._voice_factory = voice_factory
        self._provider_getter = provider_getter
        self._indic_client = indic_client or IndicParlerClient(
            self.settings.indic_service_url,
            self.settings.indic_timeout_seconds,
        )

        try:
            self.output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise TextToSpeechConfigurationError(
                "The generated-audio directory could not be created."
            ) from error

        print(f"TTS provider: {self.settings.provider}")
        if self.settings.provider == "piper":
            print(f"TTS model: {self.settings.model_path.name}")
            print(f"Requested TTS device: {self.settings.requested_device}")
        else:
            print(f"TTS model: {self.settings.indic_model_name}")
            print(f"Requested TTS device: {self.settings.indic_device}")
        print(f"TTS output format: {self.settings.output_format}")

        self.voice = None
        if self.settings.provider == "piper":
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

    def timeout_for_voice(self, voice_selection: str | None = None) -> float:
        provider, _ = self.resolve_voice_selection(voice_selection)
        if provider == "indic_parler":
            return self.settings.indic_timeout_seconds
        return self.settings.timeout_seconds

    def resolve_voice_selection(
        self,
        voice_selection: str | None,
    ) -> tuple[str, str]:
        if voice_selection is None or not voice_selection.strip():
            if self.settings.provider == "indic_parler":
                return "indic_parler", self.settings.indic_speaker
            return "piper", "Priyamvada"
        normalized = voice_selection.strip().lower()
        if normalized not in VOICE_SELECTIONS:
            raise InvalidTextToSpeechInputError(
                "The selected text-to-speech voice is invalid."
            )
        return VOICE_SELECTIONS[normalized]

    def generate(
        self,
        text: str,
        voice_selection: str | None = None,
    ) -> TextToSpeechResult:
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

        provider, speaker = self.resolve_voice_selection(voice_selection)
        max_spoken_chars = (
            self.settings.indic_max_input_chars
            if provider == "indic_parler"
            else self.settings.max_input_chars
        )
        spoken_text = prepare_text_for_speech(
            cleaned_text,
            max_chars=max_spoken_chars,
        )
        if provider == "indic_parler":
            try:
                return self._generate_indic(spoken_text, speaker)
            except TextToSpeechError:
                if not self.settings.allow_piper_fallback:
                    raise
                logger.exception(
                    "Indic Parler synthesis failed; using explicit Piper "
                    "fallback."
                )
                return self._generate_piper(spoken_text)
        return self._generate_piper(spoken_text)

    def _ensure_piper_voice(self) -> object:
        if self.voice is None:
            self.voice = self._load_voice(
                self._voice_factory,
                self._provider_getter,
            )
        return self.voice

    def _new_output_paths(self) -> tuple[str, Path, Path]:

        filename = f"tts-{uuid4().hex}.wav"
        if not is_safe_audio_filename(filename):
            raise TextToSpeechGenerationError(
                "A safe output filename could not be generated."
            )
        output_path = self.output_directory / filename
        temporary_path = self.output_directory / f".{filename}.tmp"
        return filename, output_path, temporary_path

    def _generate_piper(self, spoken_text: str) -> TextToSpeechResult:
        voice = self._ensure_piper_voice()
        filename, output_path, temporary_path = self._new_output_paths()

        generation_started = time.perf_counter()
        with self._lock:
            self.cleanup_generated_audio()
            try:
                with wave.open(str(temporary_path), "wb") as wav_file:
                    voice.synthesize_wav(spoken_text, wav_file)
                temporary_path.replace(output_path)
                duration_seconds = self._validate_wav(output_path)
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
            duration_seconds=duration_seconds,
            provider="piper",
            voice="Priyamvada",
            model_loading_time_ms=round(
                self.model_loading_time_seconds * 1000
            ),
        )

    def _generate_indic(
        self,
        spoken_text: str,
        speaker: str,
    ) -> TextToSpeechResult:
        filename, output_path, temporary_path = self._new_output_paths()
        generation_started = time.perf_counter()
        with self._lock:
            self.cleanup_generated_audio()
            try:
                result = self._indic_client.synthesize(
                    spoken_text,
                    speaker=speaker,
                )
                temporary_path.write_bytes(result.audio_bytes)
                temporary_path.replace(output_path)
                duration_seconds = self._validate_wav(output_path)
            except TextToSpeechError:
                output_path.unlink(missing_ok=True)
                temporary_path.unlink(missing_ok=True)
                raise
            except Exception as error:
                output_path.unlink(missing_ok=True)
                temporary_path.unlink(missing_ok=True)
                raise TextToSpeechGenerationError(
                    "Indic Parler could not generate response audio."
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

        print(f"Actual TTS provider: indic_parler ({speaker})")
        print(f"Actual TTS device: {result.actual_device}")
        return TextToSpeechResult(
            file_path=output_path,
            filename=filename,
            generation_time_ms=result.synthesis_time_ms or round(
                self.last_generation_time_seconds * 1000
            ),
            duration_seconds=duration_seconds,
            provider="indic_parler",
            voice=speaker,
            model_loading_time_ms=result.model_loading_time_ms,
            peak_gpu_memory_mb=result.peak_gpu_memory_mb,
        )

    @staticmethod
    def _validate_wav(output_path: Path) -> float:
        if not output_path.is_file() or output_path.stat().st_size <= 44:
            raise EmptyTextToSpeechOutputError(
                "TTS generated an empty audio file."
            )
        try:
            with wave.open(str(output_path), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                frame_rate = wav_file.getframerate()
                valid_audio = (
                    frame_count > 0
                    and frame_rate > 0
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
        return frame_count / frame_rate

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
