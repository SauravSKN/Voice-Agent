import gc
import io
import logging
import os
import time
import wave
from dataclasses import dataclass
from threading import RLock

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

MODEL_NAME = "ai4bharat/indic-parler-tts"
SPEAKERS = frozenset({"Divya", "Rohit"})
STYLES = frozenset(
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
DEFAULT_DESCRIPTION = (
    "Divya speaks in a warm, natural and conversational Hindi voice. "
    "Her pace is moderate, her pitch is balanced, and her speech is "
    "slightly expressive. The recording is clear and close, with "
    "no background noise."
)


class WorkerConfigurationError(RuntimeError):
    pass


class WorkerModelError(RuntimeError):
    pass


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise WorkerConfigurationError(f"{name} must be true or false.")


@dataclass(frozen=True)
class IndicParlerWorkerSettings:
    model_name: str
    requested_device: str
    dtype: str
    configured_speaker: str
    description: str
    max_input_chars: int
    allow_cpu_fallback: bool

    @classmethod
    def from_environment(cls) -> "IndicParlerWorkerSettings":
        model_name = os.getenv("INDIC_PARLER_MODEL", MODEL_NAME).strip()
        requested_device = os.getenv(
            "INDIC_PARLER_DEVICE", "cuda"
        ).strip().lower()
        dtype = os.getenv(
            "INDIC_PARLER_DTYPE", "float16"
        ).strip().lower()
        speaker = os.getenv(
            "INDIC_PARLER_SPEAKER", "Divya"
        ).strip().title()
        description = os.getenv(
            "INDIC_PARLER_DESCRIPTION", DEFAULT_DESCRIPTION
        ).strip()
        try:
            max_input_chars = int(
                os.getenv("INDIC_PARLER_MAX_INPUT_CHARS", "500")
            )
        except ValueError as error:
            raise WorkerConfigurationError(
                "INDIC_PARLER_MAX_INPUT_CHARS must be an integer."
            ) from error
        allow_cpu_fallback = _parse_bool(
            "INDIC_PARLER_ALLOW_CPU_FALLBACK",
            os.getenv("INDIC_PARLER_ALLOW_CPU_FALLBACK", "false"),
        )

        if model_name != MODEL_NAME:
            raise WorkerConfigurationError(
                "INDIC_PARLER_MODEL must be ai4bharat/indic-parler-tts."
            )
        if requested_device not in {"cpu", "cuda"}:
            raise WorkerConfigurationError(
                "INDIC_PARLER_DEVICE must be cpu or cuda."
            )
        if dtype not in {"float16", "float32"}:
            raise WorkerConfigurationError(
                "INDIC_PARLER_DTYPE must be float16 or float32."
            )
        if requested_device == "cpu" and dtype != "float32":
            raise WorkerConfigurationError(
                "INDIC_PARLER_DTYPE must be float32 on CPU."
            )
        if speaker not in SPEAKERS:
            raise WorkerConfigurationError(
                "INDIC_PARLER_SPEAKER must be Divya or Rohit."
            )
        if not description or len(description) > 1000:
            raise WorkerConfigurationError(
                "INDIC_PARLER_DESCRIPTION must contain 1 to 1000 characters."
            )
        if max_input_chars < 1 or max_input_chars > 2000:
            raise WorkerConfigurationError(
                "INDIC_PARLER_MAX_INPUT_CHARS must be between 1 and 2000."
            )
        return cls(
            model_name=model_name,
            requested_device=requested_device,
            dtype=dtype,
            configured_speaker=speaker,
            description=description,
            max_input_chars=max_input_chars,
            allow_cpu_fallback=allow_cpu_fallback,
        )


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speaker: str
    style: str = "configured"


@dataclass
class ModelBundle:
    model: object
    prompt_tokenizer: object
    description_tokenizer: object
    torch: object
    numpy: object
    actual_device: str
    sample_rate: int
    model_loading_ms: int


def _description_for(
    speaker: str,
    style: str,
    settings: IndicParlerWorkerSettings,
) -> str:
    if style == "configured" and speaker == settings.configured_speaker:
        return settings.description

    if style == "configured" and speaker == "Rohit":
        return (
            "Rohit speaks in a calm, friendly and natural Hindi voice. His "
            "pace is moderate, his pronunciation is clear, and he uses "
            "small natural pauses. The recording is clear and close, with "
            "no background noise."
        )

    descriptions = {
        "configured": settings.description,
        "neutral": (
            f"{speaker} speaks in a natural, neutral and conversational "
            "Hindi voice. The pace and pitch are balanced. The recording is "
            "very clear and close, with no background noise."
        ),
        "warm_friendly": (
            f"{speaker} speaks in a warm and friendly Hindi voice. The pace "
            "is moderate and the speech is natural. The recording is very "
            "clear and close, with no background noise."
        ),
        "calm_assistant": (
            f"{speaker} speaks in a calm, helpful Hindi assistant voice. The "
            "pace is moderate, articulation is clear, and the recording has "
            "no background noise."
        ),
        "slightly_expressive": (
            f"{speaker} speaks in a natural and slightly expressive Hindi "
            "voice. The pace is moderate and the pitch is balanced. The "
            "recording is very clear and close, with no background noise."
        ),
        "moderate_pace": (
            f"{speaker} speaks in a clear, conversational Hindi voice at a "
            "moderate pace. The pitch is balanced and there is no background "
            "noise."
        ),
        "slightly_slower": (
            f"{speaker} speaks in a clear, natural Hindi voice at a slightly "
            "slower pace. The pitch is balanced and there is no background "
            "noise."
        ),
    }
    return descriptions[style]


class IndicParlerRuntime:
    def __init__(self) -> None:
        self.settings = IndicParlerWorkerSettings.from_environment()
        self._bundle: ModelBundle | None = None
        self._lock = RLock()

    @property
    def loaded(self) -> bool:
        return self._bundle is not None

    def _load_on_device(self, device: str) -> ModelBundle:
        import numpy
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        dtype_name = self.settings.dtype
        if device == "cpu":
            dtype_name = "float32"
        torch_dtype = getattr(torch, dtype_name)
        started = time.perf_counter()
        model = ParlerTTSForConditionalGeneration.from_pretrained(
            self.settings.model_name,
            torch_dtype=torch_dtype,
        ).to(device)
        model.eval()
        prompt_tokenizer = AutoTokenizer.from_pretrained(
            self.settings.model_name
        )
        description_tokenizer = AutoTokenizer.from_pretrained(
            model.config.text_encoder._name_or_path
        )
        loading_ms = round((time.perf_counter() - started) * 1000)
        sample_rate = int(model.config.sampling_rate)
        return ModelBundle(
            model=model,
            prompt_tokenizer=prompt_tokenizer,
            description_tokenizer=description_tokenizer,
            torch=torch,
            numpy=numpy,
            actual_device=device,
            sample_rate=sample_rate,
            model_loading_ms=loading_ms,
        )

    def get_model(self) -> tuple[ModelBundle, bool]:
        with self._lock:
            if self._bundle is not None:
                return self._bundle, False

            print(f"Indic Parler model: {self.settings.model_name}")
            print(
                "Indic Parler requested device/dtype: "
                f"{self.settings.requested_device}/{self.settings.dtype}"
            )
            try:
                import torch
            except Exception as error:
                logger.exception("PyTorch could not be imported.")
                raise WorkerModelError(
                    "PyTorch is unavailable in the Indic Parler environment."
                ) from error

            selected_device = self.settings.requested_device
            if selected_device == "cuda" and not torch.cuda.is_available():
                if not self.settings.allow_cpu_fallback:
                    raise WorkerModelError(
                        "CUDA was requested, but PyTorch detects no CUDA device."
                    )
                logger.warning(
                    "CUDA is unavailable; falling back to CPU/float32."
                )
                selected_device = "cpu"

            try:
                self._bundle = self._load_on_device(selected_device)
            except Exception as error:
                logger.exception(
                    "Full Indic Parler initialization error on %s:",
                    selected_device,
                )
                if (
                    selected_device != "cuda"
                    or not self.settings.allow_cpu_fallback
                ):
                    raise WorkerModelError(
                        "Indic Parler could not be initialized on the "
                        f"requested {selected_device} device."
                    ) from error
                self._bundle = None
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                try:
                    self._bundle = self._load_on_device("cpu")
                except Exception as fallback_error:
                    logger.exception(
                        "Full Indic Parler CPU fallback initialization error:"
                    )
                    raise WorkerModelError(
                        "Indic Parler failed on CUDA and CPU fallback."
                    ) from fallback_error

            print(
                "Indic Parler actual device: "
                f"{self._bundle.actual_device}"
            )
            print(
                "Indic Parler model-loading time: "
                f"{self._bundle.model_loading_ms / 1000:.3f} seconds"
            )
            return self._bundle, True

    def synthesize(
        self,
        text: str,
        speaker: str,
        style: str,
    ) -> tuple[bytes, dict[str, str]]:
        cleaned = " ".join(text.split())
        if not cleaned:
            raise ValueError("Text must not be blank.")
        if len(cleaned) > self.settings.max_input_chars:
            raise ValueError(
                "Text exceeds INDIC_PARLER_MAX_INPUT_CHARS."
            )
        if speaker not in SPEAKERS:
            raise ValueError("Speaker must be Divya or Rohit.")
        if style not in STYLES:
            raise ValueError("The requested speaking style is invalid.")

        bundle, loaded_now = self.get_model()
        description = _description_for(speaker, style, self.settings)
        torch = bundle.torch
        if bundle.actual_device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        try:
            description_inputs = bundle.description_tokenizer(
                description,
                return_tensors="pt",
            )
            prompt_inputs = bundle.prompt_tokenizer(
                cleaned,
                return_tensors="pt",
            )
            with torch.inference_mode():
                generation = bundle.model.generate(
                    input_ids=description_inputs.input_ids.to(
                        bundle.actual_device
                    ),
                    attention_mask=description_inputs.attention_mask.to(
                        bundle.actual_device
                    ),
                    prompt_input_ids=prompt_inputs.input_ids.to(
                        bundle.actual_device
                    ),
                    prompt_attention_mask=prompt_inputs.attention_mask.to(
                        bundle.actual_device
                    ),
                )
            audio = generation.detach().to("cpu").float().numpy().squeeze()
        except Exception as error:
            logger.exception("Full Indic Parler synthesis error:")
            raise WorkerModelError(
                "Indic Parler synthesis failed."
            ) from error
        synthesis_ms = round((time.perf_counter() - started) * 1000)

        audio = bundle.numpy.asarray(audio, dtype=bundle.numpy.float32)
        if audio.size == 0:
            raise WorkerModelError("Indic Parler generated blank audio.")
        pcm = (
            bundle.numpy.clip(audio, -1.0, 1.0) * 32767.0
        ).astype(bundle.numpy.int16)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(bundle.sample_rate)
            wav_file.writeframes(pcm.tobytes())

        peak_memory_mb = 0.0
        if bundle.actual_device == "cuda":
            peak_memory_mb = torch.cuda.max_memory_allocated() / (1024**2)
        print(
            f"Indic Parler synthesis: speaker={speaker}, style={style}, "
            f"time={synthesis_ms / 1000:.3f}s, "
            f"peak_gpu_memory={peak_memory_mb:.1f} MiB"
        )
        return output.getvalue(), {
            "X-Model-Loading-Ms": str(
                bundle.model_loading_ms if loaded_now else 0
            ),
            "X-Synthesis-Ms": str(synthesis_ms),
            "X-Peak-GPU-Memory-MB": f"{peak_memory_mb:.1f}",
            "X-Actual-Device": bundle.actual_device,
            "X-Speaker": speaker,
            "X-Style": style,
        }


app = FastAPI(
    title="Hindi Voice Agent Indic Parler Service",
    version="0.1.0",
)
runtime: IndicParlerRuntime | None = None
runtime_lock = RLock()


def get_runtime() -> IndicParlerRuntime:
    global runtime
    with runtime_lock:
        if runtime is None:
            runtime = IndicParlerRuntime()
        return runtime


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Hindi Voice Agent Indic Parler service is running."}


@app.get("/health")
def health() -> dict[str, str | bool]:
    try:
        selected_runtime = get_runtime()
    except WorkerConfigurationError:
        return {"status": "misconfigured", "model_loaded": False}
    return {
        "status": "ready",
        "model_loaded": selected_runtime.loaded,
        "requested_device": selected_runtime.settings.requested_device,
        "model": selected_runtime.settings.model_name,
    }


@app.post("/synthesize")
def synthesize(request: SynthesisRequest) -> Response:
    try:
        audio, headers = get_runtime().synthesize(
            request.text,
            request.speaker,
            request.style,
        )
    except (WorkerConfigurationError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except WorkerModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return Response(
        content=audio,
        media_type="audio/wav",
        headers=headers,
    )
