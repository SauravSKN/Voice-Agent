# Project progress

Last reviewed: 2026-07-15.

## Completed milestones

- Browser microphone recording and source-audio playback.
- Faster-Whisper medium Hindi STT with conservative cleanup, CPU `int8`, optional CUDA `float16`, explicit fallback behavior, timings, and cached model loading.
- Local Ollama `qwen3:4b-instruct` integration.
- Bounded, temporary, process-local per-tab conversation memory and clear action.
- Piper `hi_IN-priyamvada-medium` CPU TTS, safe generated-audio serving, replay, TTL cleanup, and file-count cap.
- Mocked backend endpoint/service tests and frontend Node tests.
- Stabilization package: environment template, pinned direct dependencies, Git exclusions, setup/start/test scripts, lightweight health diagnostics, and documentation.

## Intentionally not included

No additional AI models, TTS engines, streaming, WebSockets, database, authentication, phone integration, cloud deployment, or external agent tools were added during stabilization.

## Remaining manual decisions

- The project owner must select a source-code licence before public sharing.
- Each developer must install system prerequisites and download Ollama, Whisper cache, and Piper voice assets under their respective terms.
- GPU users must maintain their own compatible NVIDIA driver/CUDA 12 cuBLAS/cuDNN 9 setup.
- Integration users must provide a real WebM recording; private audio is not distributed.

## Final verification

- The setup checker and fast test suite are rerun before publication; current results are reported with the release or pull request rather than stored as machine-specific timing claims.
- Model-dependent Whisper, Ollama, conversation, Piper, voice-response, and spoken-memory integrations have passed locally with a developer-supplied fixture.
- The private recording, its transcript, generated audio, downloaded models, and machine-specific benchmark timings are intentionally excluded from the public repository.
- Frontend DOM flows and live local HTTP integrations have passed; no browser screenshot or browser-profile data is included.
