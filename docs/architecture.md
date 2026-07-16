# Architecture

## Request flow

```text
Browser (voice, typed chat, or appointment form)
→ FastAPI
→ Faster-Whisper for voice input
→ deterministic appointment intent/safety boundary
  → controlled appointment tools → repositories → SQLite
  OR
  → bounded conversation history → Ollama Qwen3
→ Piper TTS for voice responses
→ browser display/playback
```

The static frontend is served from `127.0.0.1:5500`. Its JavaScript sends microphone audio or structured form/typed input to FastAPI at `127.0.0.1:8000`. Audio uploads use an operating-system temporary file for decoding and are deleted in a `finally` block.

`POST /api/transcribe` returns raw and conservatively cleaned text. `POST /api/voice/respond` uses the cleaned transcript. Typed `POST /api/chat` uses the same random per-tab session ID. General chat reads bounded history and calls local Ollama. A successful user/assistant pair is committed to memory, Piper writes a uniquely named WAV, and the API returns a relative local audio URL.

Appointment requests bypass Ollama for doctor facts and state changes. `AppointmentAssistant` collects one missing field at a time and may invoke only seven allowlisted operations. Those tools call `AppointmentService`, which enforces validation and transaction rules over repositories. REST form operations use the same service. Their optional `session_id` synchronizes the verified result into the same temporary workflow store.

The appointment workflow store is process-local, bounded, expiring, and separate from chat turns. It can exist without opening SQLite; the database initializes lazily only for appointment-relevant input or REST appointment calls. **New Conversation** clears both stores.

SQLite contains synthetic doctors, generated availability, and explicitly created demo appointments. Foreign keys, unique slot keys, indexes, `BEGIN IMMEDIATE`, and conditional slot updates protect integrity. Runtime database files are ignored by Git.

## Service lifetime

- Whisper, language-model configuration, Piper, chat memory, workflow memory, and appointment service accessors use one-entry process caches.
- Large models initialize lazily and are reused.
- Chat and appointment workflow memory are bounded by inactivity TTL and maximum sessions.
- Upload files are deleted after processing; generated WAV cleanup is bounded by age and count.
- Backend restart clears memory. Committed demo appointments remain in the configured SQLite file until that local file is removed.

## Health design

`/api/health` does not instantiate model or appointment factories. It validates configuration, requests only Ollama's model list, and checks Piper files. It returns coarse states without absolute paths, patient data, or private values. Detailed machine checks remain in the local PowerShell script.

## Trust boundary

The model never receives raw SQL and cannot choose an arbitrary callable. Only repository results may be presented as verified doctors, fees, clinics, slots, or confirmations. The deterministic safety layer refuses diagnosis, medication/dosage, and report interpretation; apparent emergencies are directed to local emergency care without diagnosis.

The supplied scripts bind only to loopback. The API has permissive CORS and no authentication, so it must not be exposed to a LAN or the internet without a separate production security design.
