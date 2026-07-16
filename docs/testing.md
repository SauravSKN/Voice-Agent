# Testing

## Fast suite

```powershell
Set-Location .\hindi-voice-agent
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

This performs Python compile checks; mocked unit/endpoint tests for STT configuration and cleanup, Ollama requests and errors, conversation memory, voice responses, Piper output/cleanup, generated-audio routing, health, appointment repositories/services, concurrency, dialogue, REST APIs, and typed/voice workflow sharing; `pip check`; JavaScript syntax; and all frontend Node tests. It neither starts services nor downloads/loads real models.

## Explicit integration suite

Start Ollama and FastAPI, record a real WebM clip, and leave that clip under `backend/temporary_audio`. Then run:

```powershell
Set-Location .\hindi-voice-agent
New-Item -ItemType Directory -Force .\backend\temporary_audio
# Copy your own WebM fixture into .\backend\temporary_audio\
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1 -Integration
```

The integration extension runs the existing real Whisper transcription, direct Ollama generation, conversation HTTP flow, Piper WAV generation, full voice endpoint/generated-audio validation, and spoken conversation-memory flow. It can be slow and can generate WAV files; automatic cleanup limits still apply. Ordinary tests never download models.

The private WebM fixture is intentionally not included in a shared repository. If it is absent, the integration runner fails early with a clear instruction instead of pretending model coverage passed.

## Manual browser verification

1. Run `start_all.ps1` and open the frontend.
2. Record and replay a Hindi sentence.
3. Transcribe it and verify visible Hindi text.
4. Ask the voice agent, inspect transcript/answer/timings, and hear the WAV.
5. Replay the response.
6. Send a typed follow-up that depends on prior context.
7. Start a new conversation and confirm old context is gone.
8. Check `/api/health` and confirm no paths or private data appear.
9. Search Dermatology + Pune + In person, choose Dr. Neha Sharma, load a future date, select a verified slot, and create a fictional booking.
10. Confirm reference display, lookup, reschedule, cancellation, and UI reset.
11. Attempt a second booking for the occupied slot and verify HTTP 409; request a nonexistent slot and verify HTTP 404.
12. Ask for diagnosis or dosage and verify a refusal; describe an apparent emergency and verify urgent-care guidance without diagnosis.

Appointment tests use temporary SQLite files and synthetic identities. They assert that concurrent booking has one winner, failed rescheduling preserves the original slot, cancellation releases a slot, unsafe references and invalid phone numbers are rejected, the LLM is not called for verified appointment facts, and New Conversation clears both memory stores.
