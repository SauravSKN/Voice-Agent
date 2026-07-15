import os
import re
import sys
import time
import traceback
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import ctranslate2
from faster_whisper import WhisperModel


class SpeechToTextError(RuntimeError):
    """Base error raised by the speech-to-text service."""


class EmptyAudioError(SpeechToTextError):
    """Raised when an audio file has no content."""


class NoSpeechDetectedError(SpeechToTextError):
    """Raised when Whisper finds no spoken words in the audio."""


class TranscriptionError(SpeechToTextError):
    """Raised when Whisper cannot decode or transcribe the audio."""


class WhisperConfigurationError(SpeechToTextError):
    """Raised when the environment contains an invalid Whisper setting."""


class ModelInitializationError(SpeechToTextError):
    """Raised when the requested Whisper model cannot be initialized."""


SUPPORTED_COMPUTE_TYPES = {
    "cpu": {"auto", "float32", "int8", "int8_float32"},
    "cuda": {"auto", "float16", "float32", "int8", "int8_float16"},
}


@dataclass(frozen=True)
class WhisperSettings:
    model_name: str
    requested_device: str
    requested_compute_type: str
    allow_cpu_fallback: bool

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "WhisperSettings":
        values = os.environ if environment is None else environment

        model_name = values.get("WHISPER_MODEL", "medium").strip()
        requested_device = values.get("WHISPER_DEVICE", "cpu").strip().lower()
        requested_compute_type = values.get(
            "WHISPER_COMPUTE_TYPE",
            "int8",
        ).strip().lower()
        fallback_value = values.get(
            "WHISPER_ALLOW_CPU_FALLBACK",
            "true",
        ).strip().lower()

        if not model_name:
            raise WhisperConfigurationError(
                "WHISPER_MODEL must not be empty."
            )

        if requested_device not in SUPPORTED_COMPUTE_TYPES:
            raise WhisperConfigurationError(
                "WHISPER_DEVICE must be either 'cpu' or 'cuda'; "
                f"received {requested_device!r}."
            )

        supported_compute_types = SUPPORTED_COMPUTE_TYPES[requested_device]
        if requested_compute_type not in supported_compute_types:
            supported_values = ", ".join(sorted(supported_compute_types))
            raise WhisperConfigurationError(
                f"WHISPER_COMPUTE_TYPE={requested_compute_type!r} is not "
                f"supported for WHISPER_DEVICE={requested_device!r}. "
                f"Supported values: {supported_values}."
            )

        if fallback_value in {"1", "true", "yes", "on"}:
            allow_cpu_fallback = True
        elif fallback_value in {"0", "false", "no", "off"}:
            allow_cpu_fallback = False
        else:
            raise WhisperConfigurationError(
                "WHISPER_ALLOW_CPU_FALLBACK must be true or false; "
                f"received {fallback_value!r}."
            )

        return cls(
            model_name=model_name,
            requested_device=requested_device,
            requested_compute_type=requested_compute_type,
            allow_cpu_fallback=allow_cpu_fallback,
        )


@dataclass(frozen=True)
class TranscriptionResult:
    raw_transcript: str
    cleaned_transcript: str


class SpeechToTextService:
    """Convert recorded Hindi speech into cleaned text using Faster-Whisper."""

    def __init__(
        self,
        settings: WhisperSettings | None = None,
        model_factory: Callable[..., object] = WhisperModel,
        cuda_device_count_getter: Callable[[], int] = (
            ctranslate2.get_cuda_device_count
        ),
    ) -> None:
        self.settings = settings or WhisperSettings.from_environment()
        self.actual_device = "uninitialized"
        self.actual_compute_type = "uninitialized"
        self.model_loading_time_seconds = 0.0
        self.last_transcription_time_seconds = 0.0

        print(f"Requested device: {self.settings.requested_device}")
        print(f"Model name: {self.settings.model_name}")
        print(
            "Requested compute type: "
            f"{self.settings.requested_compute_type}"
        )
        print(
            "CPU fallback allowed: "
            f"{self.settings.allow_cpu_fallback}"
        )

        initialization_started = time.perf_counter()
        cuda_device_count = self._get_cuda_device_count(
            cuda_device_count_getter
        )
        print(f"CUDA device count: {cuda_device_count}")

        if self.settings.requested_device == "cuda":
            self.model = self._initialize_cuda_or_fallback(
                model_factory,
                cuda_device_count,
            )
        else:
            self.model = self._initialize_model(
                model_factory,
                device="cpu",
                compute_type=self.settings.requested_compute_type,
            )

        self.model_loading_time_seconds = (
            time.perf_counter() - initialization_started
        )
        print(f"Actual selected device: {self.actual_device}")
        print(f"Actual compute type: {self.actual_compute_type}")
        print(
            "Model-loading time: "
            f"{self.model_loading_time_seconds:.3f} seconds"
        )
        print("Faster-Whisper model loaded.")

    @staticmethod
    def _get_cuda_device_count(
        cuda_device_count_getter: Callable[[], int],
    ) -> int:
        try:
            return max(0, int(cuda_device_count_getter()))
        except Exception as error:
            print(
                "CUDA device detection failed: "
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )
            return 0

    def _initialize_model(
        self,
        model_factory: Callable[..., object],
        *,
        device: str,
        compute_type: str,
    ) -> object:
        print(
            "Initializing Faster-Whisper with "
            f"device={device!r}, compute_type={compute_type!r}..."
        )
        attempt_started = time.perf_counter()

        try:
            model = model_factory(
                self.settings.model_name,
                device=device,
                compute_type=compute_type,
            )
        except Exception:
            attempt_time = time.perf_counter() - attempt_started
            print(
                f"Failed {device} model-loading time: "
                f"{attempt_time:.3f} seconds",
                file=sys.stderr,
            )
            raise

        self.actual_device = device
        self.actual_compute_type = compute_type
        return model

    def _initialize_cuda_or_fallback(
        self,
        model_factory: Callable[..., object],
        cuda_device_count: int,
    ) -> object:
        if cuda_device_count < 1:
            error = ModelInitializationError(
                "CUDA was requested, but CTranslate2 detected no CUDA devices."
            )
            print(f"CUDA initialization error: {error}", file=sys.stderr)
            return self._fallback_or_raise(model_factory, error)

        try:
            return self._initialize_model(
                model_factory,
                device="cuda",
                compute_type=self.settings.requested_compute_type,
            )
        except Exception as error:
            print(
                "CUDA model initialization failed with the full error:",
                file=sys.stderr,
            )
            traceback.print_exception(
                type(error),
                error,
                error.__traceback__,
                file=sys.stderr,
            )
            initialization_error = ModelInitializationError(
                "Faster-Whisper could not initialize on CUDA: "
                f"{type(error).__name__}: {error}"
            )
            return self._fallback_or_raise(
                model_factory,
                initialization_error,
            )

    def _fallback_or_raise(
        self,
        model_factory: Callable[..., object],
        error: ModelInitializationError,
    ) -> object:
        if not self.settings.allow_cpu_fallback:
            raise error

        print(
            "CUDA is unavailable; falling back to "
            "device='cpu', compute_type='int8'.",
            file=sys.stderr,
        )

        try:
            return self._initialize_model(
                model_factory,
                device="cpu",
                compute_type="int8",
            )
        except Exception as fallback_error:
            print(
                "CPU fallback initialization failed with the full error:",
                file=sys.stderr,
            )
            traceback.print_exception(
                type(fallback_error),
                fallback_error,
                fallback_error.__traceback__,
                file=sys.stderr,
            )
            raise ModelInitializationError(
                "CUDA initialization failed and the CPU fallback also failed: "
                f"{type(fallback_error).__name__}: {fallback_error}"
            ) from fallback_error

    @staticmethod
    def _print_transcript(label: str, transcript: str) -> None:
        """Log Unicode text without failing on a legacy Windows console."""
        message = f"{label}: {transcript}"

        try:
            print(message)
        except UnicodeEncodeError:
            encoding = sys.stdout.encoding or "ascii"
            safe_message = message.encode(
                encoding,
                errors="backslashreplace",
            ).decode(encoding)
            print(safe_message)

    @staticmethod
    def correct_common_errors(transcript: str) -> str:
        """Correct only high-confidence ASR errors without changing valid Hindi."""
        corrected_text = unicodedata.normalize("NFC", transcript)
        corrected_text = re.sub(r"\s+", " ", corrected_text).strip()

        # At an utterance boundary or after a conjunction, this is commonly a
        # misheard "मैं एक". It is not changed in phrases such as "घर में एक".
        corrected_text = re.sub(
            r"(^|[।!?]\s*|,\s*|\bऔर\s+)में\s+एक\b",
            r"\1मैं एक",
            corrected_text,
        )

        # "एजेंड" is not the intended technical term in this project domain.
        corrected_text = re.sub(
            r"(?<!\w)हिंदी\s+एजेंड(?!\w)",
            "हिंदी वॉइस एजेंट",
            corrected_text,
        )

        # Expand the shortened phrase only when it is the complete utterance.
        # This avoids altering a valid phrase embedded in a longer sentence.
        match = re.fullmatch(r"हिंदी\s+एजेंट([।.!?]?)", corrected_text)
        if match:
            corrected_text = f"हिंदी वॉइस एजेंट{match.group(1)}"

        # "मेरो" can be valid Nepali. Correct the self-introduction only when
        # its clause uses the Hindi copula "है" (Nepali normally uses "हो").
        corrected_text = re.sub(
            r"(^|[\s,।!?])मेरो(?=\s+नाम[^।!?\n]{0,80}\sहै(?:[\s,।!?]|$))",
            r"\1मेरा",
            corrected_text,
        )

        return corrected_text

    def transcribe_with_details(self, audio_path: Path) -> TranscriptionResult:
        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio file was not found: {audio_path}"
            )

        if not audio_path.is_file():
            raise TranscriptionError(
                f"Audio path is not a file: {audio_path}"
            )

        if audio_path.stat().st_size == 0:
            raise EmptyAudioError("The audio file is empty.")

        transcription_started = time.perf_counter()

        try:
            segments, information = self.model.transcribe(
                str(audio_path),
                language="hi",
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 500,
                },
                condition_on_previous_text=False,
                initial_prompt=(
                    "यह हिंदी और हिंग्लिश बातचीत है। "
                    "तकनीकी शब्द: वॉइस एजेंट, एआई, वेबसाइट, माइक्रोफोन, "
                    "रिकॉर्डिंग, बैकएंड और फ्रंटएंड। "
                    "शब्दों को देवनागरी में सही लिखें।"
                ),
            )

            transcript_parts = [
                segment.text.strip()
                for segment in segments
                if segment.text.strip()
            ]
        except Exception as error:
            raise TranscriptionError(
                f"Whisper could not transcribe the audio: {error}"
            ) from error
        finally:
            self.last_transcription_time_seconds = (
                time.perf_counter() - transcription_started
            )
            print(
                "Transcription time: "
                f"{self.last_transcription_time_seconds:.3f} seconds"
            )

        raw_transcript = " ".join(transcript_parts).strip()

        if not raw_transcript:
            raise NoSpeechDetectedError(
                "No speech was detected in the audio."
            )

        cleaned_transcript = self.correct_common_errors(raw_transcript)

        print(f"Detected language: {getattr(information, 'language', 'unknown')}")
        probability = getattr(information, "language_probability", None)
        if probability is not None:
            print(f"Language probability: {probability:.2f}")
        self._print_transcript("Raw transcript", raw_transcript)
        self._print_transcript("Cleaned transcript", cleaned_transcript)

        return TranscriptionResult(
            raw_transcript=raw_transcript,
            cleaned_transcript=cleaned_transcript,
        )

    def transcribe(self, audio_path: Path) -> str:
        """Return cleaned text while preserving the existing public API."""
        return self.transcribe_with_details(audio_path).cleaned_transcript
