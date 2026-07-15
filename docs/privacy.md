# Privacy and data lifecycle

This local architecture reduces the need to send content to an application cloud service, but it is not an absolute privacy guarantee. Operating-system, browser, installed software, model source, backups, malware, logging configuration, or future code changes can alter the risk.

## Browser

- Microphone audio is held in a browser `Blob` for preview and upload during the page session.
- `sessionStorage` contains a random conversation session ID, not messages or audio.
- The browser sends recordings, typed text, and the session ID to FastAPI over loopback HTTP.

## Backend memory

- Conversation memory stores only completed user/assistant text turns, timestamps, and session association.
- Audio bytes and file paths are not stored in conversation memory.
- Sessions expire after inactivity, can be evicted by the maximum-session cap, can be cleared by the endpoint, and all disappear on backend restart.

## Disk

- Each upload is written to an operating-system temporary file for decoding and deleted in a `finally` block after success or failure.
- A source recording placed manually in `backend/temporary_audio` for integration testing remains until the developer deletes it; Git ignores it.
- Piper response WAV files are written to `backend/generated_audio`. Cleanup removes expired files and enforces a maximum count (60 minutes and 50 files by default).
- Model files, `.env`, the virtual environment, and normal software/model caches remain on disk until manually removed.
- Ollama stores its model blobs outside this repository according to its installation settings.

## Network

- Browser → FastAPI: `127.0.0.1:8000`.
- Browser static files: `127.0.0.1:5500`.
- FastAPI → Ollama: configured loopback URL, normally `127.0.0.1:11434`.
- Piper and Faster-Whisper inference run in the backend process. First-time Whisper/model tooling may access model sources when a model is not already cached; ordinary requests do not intentionally call a cloud API.

The supplied scripts do not bind public interfaces. Because the prototype has no authentication and permissive CORS, do not expose it to a LAN or the internet.
