import asyncio
import json
import logging
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.memory import (
    ConversationConfigurationError,
    ConversationStore,
    InvalidSessionIdError,
)

from app.services.language_model import (
    BlankModelResponseError,
    InvalidLanguageModelInputError,
    LanguageModelConfigurationError,
    LanguageModelSettings,
    LanguageModelService,
    LanguageModelTimeoutError,
    ModelLoadingError,
    ModelServerUnavailableError,
)
from app.services.speech_to_text import (
    EmptyAudioError,
    NoSpeechDetectedError,
    SpeechToTextService,
    TranscriptionError,
    WhisperConfigurationError,
    WhisperSettings,
)
from app.services.text_to_speech import (
    EmptyTextToSpeechOutputError,
    InvalidTextToSpeechInputError,
    TextToSpeechConfigurationError,
    TextToSpeechGenerationError,
    TextToSpeechModelLoadingError,
    TextToSpeechService,
    TextToSpeechSettings,
    TextToSpeechTimeoutError,
    default_generated_audio_directory,
    is_safe_audio_filename,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Hindi Voice Agent API",
    description="Backend API for the Hindi voice-agent project.",
    version="0.7.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@lru_cache(maxsize=1)
def get_speech_service() -> SpeechToTextService:
    """Load the configured model once, on the first transcription request."""
    return SpeechToTextService()


@lru_cache(maxsize=1)
def get_language_model_service() -> LanguageModelService:
    """Load local language-model configuration and prompt once."""
    return LanguageModelService()


@lru_cache(maxsize=1)
def get_text_to_speech_service() -> TextToSpeechService:
    """Cache one lazy local text-to-speech provider service."""
    return TextToSpeechService()


@lru_cache(maxsize=1)
def get_conversation_store() -> ConversationStore:
    """Create one bounded, process-local conversation store."""
    return ConversationStore()


class ChatRequest(BaseModel):
    message: str = Field(max_length=2000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    status: str
    session_id: str
    response: str
    generation_time_ms: int
    memory_turns: int


class VoiceResponseTiming(BaseModel):
    transcription_ms: int
    language_model_ms: int
    text_to_speech_ms: int
    total_ms: int


class VoiceAgentResponse(BaseModel):
    status: str
    session_id: str
    transcript: str
    response: str
    audio_url: str
    tts_provider: str
    tts_voice: str
    memory_turns: int
    timing: VoiceResponseTiming


class ClearConversationRequest(BaseModel):
    session_id: str


class ClearConversationResponse(BaseModel):
    status: str
    cleared: bool


async def _generate_with_memory(
    user_text: str,
    session_id: str | None,
):
    conversation_store = await run_in_threadpool(get_conversation_store)
    resolved_session_id = session_id if session_id is not None else uuid4().hex
    resolved_session_id = await run_in_threadpool(
        conversation_store.validate_session_id,
        resolved_session_id,
    )
    history = await run_in_threadpool(
        conversation_store.get_history,
        resolved_session_id,
    )
    language_model_service = await run_in_threadpool(
        get_language_model_service
    )
    result = await run_in_threadpool(
        language_model_service.generate,
        user_text,
        history=history,
    )
    memory_turns = await run_in_threadpool(
        conversation_store.add_turn,
        resolved_session_id,
        user_text,
        result.response,
    )
    return result, resolved_session_id, memory_turns


async def _read_audio_upload(
    audio: UploadFile,
    *,
    unsupported_status_code: int,
) -> bytes:
    if not audio.content_type:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file has no content type.",
        )

    if not audio.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=unsupported_status_code,
            detail="Only audio files are allowed.",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail="The uploaded audio file is empty.",
        )

    return audio_bytes


@contextmanager
def _temporary_audio_file(
    audio_bytes: bytes,
    filename: str | None,
) -> Iterator[Path]:
    allowed_extensions = {
        ".flac",
        ".m4a",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpga",
        ".ogg",
        ".wav",
        ".webm",
    }
    requested_extension = Path(filename or "").suffix.lower()
    file_extension = (
        requested_extension
        if requested_extension in allowed_extensions
        else ".webm"
    )
    saved_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="wb",
            suffix=f"-{uuid4().hex}{file_extension}",
            delete=False,
        ) as temporary_audio:
            temporary_audio.write(audio_bytes)
            saved_path = Path(temporary_audio.name)

        yield saved_path
    finally:
        if saved_path is not None:
            try:
                saved_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Temporary audio cleanup failed.")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    missing_audio = any(
        item.get("type") == "missing"
        and tuple(item.get("loc", ())) == ("body", "audio")
        for item in error.errors()
    )

    if request.url.path in {
        "/api/transcribe",
        "/api/voice/respond",
    } and missing_audio:
        return JSONResponse(
            status_code=400,
            content={"detail": "An audio file is required."},
        )

    return JSONResponse(
        status_code=422,
        content={"detail": error.errors()},
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Hindi Voice Agent backend is running."
    }


def _language_model_health() -> str:
    """Check Ollama without asking it to load or run a model."""
    try:
        settings = LanguageModelSettings.from_environment()
        with urlopen(f"{settings.base_url}/api/tags", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        model_names = {
            model.get("name") or model.get("model")
            for model in payload.get("models", [])
            if isinstance(model, dict)
        }
        if settings.model not in model_names:
            return "model_missing"
        return "reachable"
    except LanguageModelConfigurationError:
        return "misconfigured"
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return "unreachable"


def _speech_to_text_health() -> str:
    """Validate settings without constructing the large Whisper model."""
    try:
        WhisperSettings.from_environment()
    except WhisperConfigurationError:
        return "misconfigured"
    return "ready"


def _text_to_speech_health() -> str:
    """Validate settings and provider readiness without loading a model."""
    try:
        settings = TextToSpeechSettings.from_environment()
    except TextToSpeechConfigurationError:
        return "misconfigured"
    if settings.provider == "piper":
        if not settings.model_path.is_file():
            return "model_missing"
        if not Path(f"{settings.model_path}.json").is_file():
            return "config_missing"
        return "ready"
    try:
        with urlopen(
            f"{settings.indic_service_url}/health",
            timeout=1.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return "ready" if payload.get("status") == "ready" else "unavailable"
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return "unreachable"


@app.get("/api/health")
def health_check() -> dict[str, str | dict[str, str]]:
    services = {
        "speech_to_text": _speech_to_text_health(),
        "language_model": _language_model_health(),
        "text_to_speech": _text_to_speech_health(),
    }
    is_healthy = services == {
        "speech_to_text": "ready",
        "language_model": "reachable",
        "text_to_speech": "ready",
    }
    return {
        "status": "ok" if is_healthy else "degraded",
        "services": services,
    }


@app.get("/generated-audio/{filename}")
async def generated_audio(filename: str) -> FileResponse:
    audio_directory = default_generated_audio_directory().resolve()
    if not is_safe_audio_filename(filename):
        raise HTTPException(
            status_code=404,
            detail="Generated audio was not found.",
        )

    audio_path = (audio_directory / filename).resolve()
    if (
        audio_path.parent != audio_directory
        or not audio_path.is_file()
    ):
        raise HTTPException(
            status_code=404,
            detail="Generated audio was not found.",
        )

    return FileResponse(
        path=audio_path,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        result, session_id, memory_turns = await _generate_with_memory(
            request.message,
            request.session_id,
        )
    except InvalidSessionIdError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ConversationConfigurationError as error:
        logger.exception("Conversation memory is misconfigured.")
        raise HTTPException(
            status_code=500,
            detail="Conversation memory is misconfigured.",
        ) from error
    except InvalidLanguageModelInputError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LanguageModelConfigurationError as error:
        raise HTTPException(
            status_code=500,
            detail="The local language model is misconfigured.",
        ) from error
    except ModelServerUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail="The local language-model server is unavailable.",
        ) from error
    except ModelLoadingError as error:
        raise HTTPException(
            status_code=503,
            detail="The configured local language model is unavailable.",
        ) from error
    except LanguageModelTimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail="The local language-model request timed out.",
        ) from error
    except BlankModelResponseError as error:
        raise HTTPException(
            status_code=502,
            detail="The local language model returned a blank response.",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="The language-model request failed.",
        ) from error

    return ChatResponse(
        status="success",
        session_id=session_id,
        response=result.response,
        generation_time_ms=result.generation_time_ms,
        memory_turns=memory_turns,
    )


@app.post(
    "/api/conversation/clear",
    response_model=ClearConversationResponse,
)
async def clear_conversation(
    request: ClearConversationRequest,
) -> ClearConversationResponse:
    try:
        store = await run_in_threadpool(get_conversation_store)
        cleared = await run_in_threadpool(store.clear, request.session_id)
    except InvalidSessionIdError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ConversationConfigurationError as error:
        logger.exception("Conversation memory is misconfigured.")
        raise HTTPException(
            status_code=500,
            detail="Conversation memory is misconfigured.",
        ) from error
    return ClearConversationResponse(status="success", cleared=cleared)


@app.post("/api/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
) -> dict[str, str | int]:
    audio_bytes = await _read_audio_upload(
        audio,
        unsupported_status_code=400,
    )

    try:
        with _temporary_audio_file(audio_bytes, audio.filename) as saved_path:
            service = await run_in_threadpool(get_speech_service)
            result = await run_in_threadpool(
                service.transcribe_with_details,
                saved_path,
            )
    except EmptyAudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except NoSpeechDetectedError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TranscriptionError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"The audio file could not be processed: {error}",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"The transcription service failed: {error}",
        ) from error
    return {
        "status": "transcribed",
        "raw_transcript": result.raw_transcript,
        "transcript": result.cleaned_transcript,
        "size_bytes": len(audio_bytes),
    }


@app.post(
    "/api/voice/respond",
    response_model=VoiceAgentResponse,
)
async def respond_to_voice(
    audio: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    tts_voice: str | None = Form(default=None, max_length=32),
) -> VoiceAgentResponse:
    total_started = time.perf_counter()
    audio_bytes = await _read_audio_upload(
        audio,
        unsupported_status_code=415,
    )

    try:
        conversation_store = await run_in_threadpool(get_conversation_store)
        resolved_session_id = (
            session_id if session_id is not None else uuid4().hex
        )
        resolved_session_id = await run_in_threadpool(
            conversation_store.validate_session_id,
            resolved_session_id,
        )

        with _temporary_audio_file(audio_bytes, audio.filename) as saved_path:
            transcription_started = time.perf_counter()
            speech_service = await run_in_threadpool(get_speech_service)
            transcription = await run_in_threadpool(
                speech_service.transcribe_with_details,
                saved_path,
            )
            transcription_ms = round(
                (time.perf_counter() - transcription_started) * 1000
            )

            transcript = transcription.cleaned_transcript.strip()
            if not transcript:
                raise NoSpeechDetectedError(
                    "No speech was detected in the audio."
                )

            language_model_started = time.perf_counter()
            (
                language_model_result,
                resolved_session_id,
                memory_turns,
            ) = await _generate_with_memory(
                transcript,
                resolved_session_id,
            )
            language_model_ms = round(
                (time.perf_counter() - language_model_started) * 1000
            )

            text_to_speech_started = time.perf_counter()
            text_to_speech_service = await run_in_threadpool(
                get_text_to_speech_service
            )
            timeout_seconds = (
                text_to_speech_service.timeout_for_voice(tts_voice)
                if hasattr(text_to_speech_service, "timeout_for_voice")
                else text_to_speech_service.settings.timeout_seconds
            )
            text_to_speech_result = await asyncio.wait_for(
                asyncio.to_thread(
                    text_to_speech_service.generate,
                    language_model_result.response,
                    tts_voice,
                ),
                timeout=timeout_seconds,
            )
            text_to_speech_ms = round(
                (time.perf_counter() - text_to_speech_started) * 1000
            )
    except EmptyAudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except NoSpeechDetectedError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except InvalidSessionIdError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ConversationConfigurationError as error:
        logger.exception("Conversation memory is misconfigured.")
        raise HTTPException(
            status_code=500,
            detail="Conversation memory is misconfigured.",
        ) from error
    except TranscriptionError as error:
        logger.exception("Voice-response transcription failed.")
        raise HTTPException(
            status_code=500,
            detail="The audio could not be transcribed.",
        ) from error
    except InvalidLanguageModelInputError as error:
        logger.exception("Voice transcript was rejected by the language model.")
        raise HTTPException(
            status_code=422,
            detail="The transcript could not be used as a model request.",
        ) from error
    except LanguageModelConfigurationError as error:
        logger.exception("The local language model is misconfigured.")
        raise HTTPException(
            status_code=500,
            detail="The local language model is misconfigured.",
        ) from error
    except (ModelServerUnavailableError, ModelLoadingError) as error:
        logger.exception("The local language model is unavailable.")
        raise HTTPException(
            status_code=503,
            detail="The local language model is unavailable.",
        ) from error
    except LanguageModelTimeoutError as error:
        logger.exception("The local language-model request timed out.")
        raise HTTPException(
            status_code=504,
            detail="The local language-model request timed out.",
        ) from error
    except BlankModelResponseError as error:
        logger.exception("The local language model returned a blank response.")
        raise HTTPException(
            status_code=502,
            detail="The local language model returned a blank response.",
        ) from error
    except InvalidTextToSpeechInputError as error:
        logger.exception("The generated response was rejected by TTS.")
        raise HTTPException(
            status_code=422,
            detail="The generated response could not be spoken.",
        ) from error
    except TextToSpeechConfigurationError as error:
        logger.exception("The local text-to-speech service is misconfigured.")
        raise HTTPException(
            status_code=500,
            detail="The local text-to-speech service is misconfigured.",
        ) from error
    except TextToSpeechModelLoadingError as error:
        logger.exception("The local text-to-speech model is unavailable.")
        raise HTTPException(
            status_code=503,
            detail="The local text-to-speech model is unavailable.",
        ) from error
    except EmptyTextToSpeechOutputError as error:
        logger.exception("The local text-to-speech model produced no audio.")
        raise HTTPException(
            status_code=502,
            detail="The local text-to-speech model produced no audio.",
        ) from error
    except TextToSpeechGenerationError as error:
        logger.exception("Local response-audio generation failed.")
        raise HTTPException(
            status_code=502,
            detail="The response audio could not be generated.",
        ) from error
    except TextToSpeechTimeoutError as error:
        logger.exception("The local text-to-speech request timed out.")
        raise HTTPException(
            status_code=504,
            detail="The local text-to-speech request timed out.",
        ) from error
    except asyncio.TimeoutError as error:
        logger.exception("The local text-to-speech request timed out.")
        raise HTTPException(
            status_code=504,
            detail="The local text-to-speech request timed out.",
        ) from error
    except OSError as error:
        logger.exception("Temporary audio processing failed.")
        raise HTTPException(
            status_code=500,
            detail="The audio file could not be processed.",
        ) from error
    except Exception as error:
        logger.exception("Unexpected voice-response failure.")
        raise HTTPException(
            status_code=500,
            detail="The voice-agent request failed.",
        ) from error

    total_ms = round((time.perf_counter() - total_started) * 1000)

    return VoiceAgentResponse(
        status="success",
        session_id=resolved_session_id,
        transcript=transcript,
        response=language_model_result.response,
        audio_url=(
            f"/generated-audio/{text_to_speech_result.filename}"
        ),
        tts_provider=text_to_speech_result.provider,
        tts_voice=text_to_speech_result.voice,
        memory_turns=memory_turns,
        timing=VoiceResponseTiming(
            transcription_ms=transcription_ms,
            language_model_ms=language_model_ms,
            text_to_speech_ms=text_to_speech_ms,
            total_ms=total_ms,
        ),
    )
