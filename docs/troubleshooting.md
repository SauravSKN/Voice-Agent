# Troubleshooting

Always begin with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_setup.ps1
```

## PowerShell blocks scripts

Use the one-process form shown above with `-ExecutionPolicy Bypass`; it does not change the machine-wide policy.

## Virtual environment or imports fail

Confirm `.venv\Scripts\python.exe` exists, reports Python 3.11, and reinstall the pinned direct dependencies with that exact executable. Run `.\.venv\Scripts\python.exe -m pip check`.

## FFmpeg missing

Install a Windows FFmpeg build and add its `bin` directory to `PATH`, then open a new PowerShell and run `ffmpeg -version`.

## Ollama unreachable or model missing

Run `ollama serve` in a terminal and `ollama list`. If needed, run `ollama pull qwen3:4b-instruct`. Do not change `LLM_BASE_URL` to a non-loopback URL; the backend rejects it.

## Piper model missing

Run the exact download command in the README. Both `.onnx` and `.onnx.json` must exist. Keep `TTS_MODEL` relative to the `backend` directory unless there is a specific local reason not to.

## CUDA fails

Current Faster-Whisper/CTranslate2 GPU execution needs CUDA 12 cuBLAS and cuDNN 9. `ctranslate2.get_cuda_device_count()` is only a preliminary check; prove operation with a real transcript. Close the backend before changing device settings. Restore `cpu`/`int8` if GPU initialization is unreliable.

## Port already occupied

The scripts accept a port only when the expected local HTTP service answers. They never kill an unexpected process. Use `Get-NetTCPConnection -LocalPort 8000,5500,11434` and inspect the owning PID before deciding what to stop.

## Microphone or autoplay problems

Use the loopback frontend URL, grant microphone permission, and check Windows privacy settings. Browser autoplay may require selecting **Play Response**; this is expected and covered by tests.

## Silence or bad transcription

Speak close to the microphone, use a short Hindi sentence, and confirm the recorded preview contains speech. Silence returns a clear 422 response. Transcript cleanup intentionally changes only narrowly matched phrases and cannot fix arbitrary recognition errors.
