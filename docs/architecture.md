# Architecture

## Request flow

```text
Browser
→ MediaRecorder
→ FastAPI
→ Faster-Whisper
→ Conversation Memory
→ Ollama Qwen3
→ Piper TTS
→ WAV response
→ Browser playback
```

The static frontend is served from `127.0.0.1:5500`. Its JavaScript sends a multipart WebM upload to FastAPI at `127.0.0.1:8000`. FastAPI writes the upload to an operating-system temporary file only for decoding, calls the cached Faster-Whisper service, and deletes the file in a `finally` block.

`POST /api/transcribe` returns both the raw and conservatively cleaned transcript. `POST /api/voice/respond` uses the cleaned transcript as the user turn, reads the bounded history for that tab session, and calls Ollama's local `/api/chat` endpoint at `127.0.0.1:11434`. A successful user/assistant pair is committed to memory. Piper then writes a uniquely named WAV under `backend/generated_audio`, and the API returns a relative `/generated-audio/...` URL.

Typed `POST /api/chat` requests share the same random session ID. `POST /api/conversation/clear` removes that one memory entry. The browser then creates a new session ID.

## Service lifetime

- Whisper, language-model configuration, Piper, and conversation store accessors use a one-entry process cache.
- Large models are initialized lazily on first use and reused.
- Conversation memory exists only in the backend process and is bounded by turns, inactivity TTL, and maximum sessions.
- Upload files are deleted after request processing.
- Generated WAV cleanup is bounded by age and count.
- Backend restart clears all conversation memory and model caches.

## Health design

`/api/health` does not instantiate service factories. It validates Whisper settings, requests only Ollama's lightweight model list, and checks that the configured Piper model/config files exist. It returns coarse states without absolute paths or private values. Detailed machine checks stay in the local PowerShell script.

## Trust boundary

The supplied start scripts bind only to loopback. The API has permissive CORS for this local prototype and no authentication, so it must not be bound to a public or LAN interface without a separate security design.
