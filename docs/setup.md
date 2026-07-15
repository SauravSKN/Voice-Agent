# Setup and sharing

## New developer checklist

1. Install 64-bit Python 3.11, FFmpeg, Ollama, and a current browser. Install Node.js if frontend tests will be run.
2. Create `.venv` and install `backend/requirements.txt`.
3. Copy `.env.example` to the ignored `.env` file.
4. Pull `qwen3:4b-instruct` with Ollama.
5. Download both Piper voice files with the provided module command.
6. Run `scripts/check_setup.ps1` until it has no `FAIL` result.
7. Run `scripts/start_all.ps1` and open `http://127.0.0.1:5500/`.
8. Run fast tests; enable integrations only with local services and a real WebM fixture.
9. Stop only windows started for the project with `Ctrl+C`.

Exact commands:

```powershell
Set-Location .\hindi-voice-agent
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
Copy-Item .\.env.example .\.env
ollama pull qwen3:4b-instruct
.\.venv\Scripts\python.exe -m piper.download_voices hi_IN-priyamvada-medium --download-dir .\backend\models\piper
powershell -ExecutionPolicy Bypass -File .\scripts\check_setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

No script installs software or models. The model commands are explicit setup steps.

## Optional GPU STT

CPU `int8` works without NVIDIA libraries and is the shareable default. For CUDA `float16`, current Faster-Whisper/CTranslate2 guidance requires a supported NVIDIA driver, CUDA 12 cuBLAS, and cuDNN 9. Configure the three Whisper variables, run the checker, and perform a real transcription while observing `nvidia-smi`. If initialization fails, restore CPU values; do not change or hardcode DLL search paths in project source.

## Clean-room sharing review

The README identifies software, Python version, environment creation, pinned direct dependencies, both model commands, configuration, start/stop instructions, testing, and CPU/GPU switching. Machine-specific items that remain are:

- the recipient's chosen clone/extraction path;
- microphone/browser permissions;
- NVIDIA driver and CUDA runtime installation if GPU STT is requested;
- a user-provided real WebM fixture for model-dependent integration tests;
- the owner must choose a project source-code licence before public redistribution.

Do not share `.venv`, `.env`, Piper model files, Ollama blobs, audio files, generated WAVs, caches, or logs. The root `.gitignore` covers project-local instances, but review any archive manually before sending it.
