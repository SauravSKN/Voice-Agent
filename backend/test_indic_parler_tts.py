import argparse
import subprocess
import wave
from dataclasses import replace
from pathlib import Path

from app.services.text_to_speech import (
    TextToSpeechService,
    TextToSpeechSettings,
)
from app.indic_parler_service import (
    IndicParlerWorkerSettings,
    _description_for,
)


DEFAULT_TEXT = "नमस्ते, मैं आपका हिंदी एआई सहायक हूँ।"


def verify_wav(path: Path) -> tuple[float, int]:
    with wave.open(str(path), "rb") as wav_file:
        duration = wav_file.getnframes() / wav_file.getframerate()
        if duration <= 0 or wav_file.getnchannels() < 1:
            raise RuntimeError("Python WAV validation found no usable audio.")
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if float(completed.stdout.strip()) <= 0:
        raise RuntimeError("FFprobe found no usable audio duration.")
    return duration, path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speaker", choices=("Divya", "Rohit"), default="Divya")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    arguments = parser.parse_args()

    settings = replace(
        TextToSpeechSettings.from_environment(),
        provider="indic_parler",
        indic_speaker=arguments.speaker,
        allow_piper_fallback=False,
    )
    service = TextToSpeechService(settings)
    selection = f"indic_parler_{arguments.speaker.lower()}"
    result = service.generate(arguments.text, selection)
    duration, file_size = verify_wav(result.file_path)

    print(f"Provider: {result.provider}")
    print(f"Speaker: {result.voice}")
    worker_settings = IndicParlerWorkerSettings.from_environment()
    print(
        "Description: "
        f"{_description_for(arguments.speaker, 'configured', worker_settings)}"
    )
    print(f"Model loading time: {result.model_loading_time_ms} ms")
    print(f"Synthesis time: {result.generation_time_ms} ms")
    print(f"Audio duration: {duration:.3f} s")
    print(f"File size: {file_size} bytes")
    print(f"Peak GPU memory: {result.peak_gpu_memory_mb:.1f} MiB")
    print(
        "Real-time factor: "
        f"{(result.generation_time_ms / 1000) / duration:.3f}"
    )
    print(f"WAV: {result.file_path}")
    print("Python WAV validation: PASS")
    print("FFprobe validation: PASS")


if __name__ == "__main__":
    main()
