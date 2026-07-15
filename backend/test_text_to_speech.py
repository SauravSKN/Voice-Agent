import sys
import wave
from pathlib import Path

from app.services.text_to_speech import TextToSpeechService


TEST_TEXT = "नमस्ते, मैं आपका हिंदी एआई सहायक हूँ।"


def main() -> int:
    service = TextToSpeechService()
    result = service.generate(TEST_TEXT)

    print(f"Output filename: {result.filename}")
    print(
        "Model-loading time: "
        f"{service.model_loading_time_seconds:.3f} seconds"
    )
    print(
        "Generation time: "
        f"{service.last_generation_time_seconds:.3f} seconds"
    )

    if not result.file_path.exists():
        raise RuntimeError("The generated WAV file does not exist.")
    if result.file_path.stat().st_size <= 44:
        raise RuntimeError("The generated WAV file is empty.")

    with wave.open(str(result.file_path), "rb") as wav_file:
        print(f"Channels: {wav_file.getnchannels()}")
        print(f"Sample rate: {wav_file.getframerate()} Hz")
        print(f"Sample width: {wav_file.getsampwidth()} bytes")
        print(f"Frames: {wav_file.getnframes()}")
        if wav_file.getnframes() < 1:
            raise RuntimeError("The WAV file contains no audio frames.")

    print(f"Generated file: {result.file_path}")
    print("Standard WAV validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
