from pathlib import Path

from app.services.speech_to_text import SpeechToTextService


TEMP_AUDIO_DIR = Path(__file__).resolve().parent / "temporary_audio"


def find_latest_recording() -> Path:
    recordings = list(TEMP_AUDIO_DIR.glob("*"))

    if not recordings:
        raise FileNotFoundError(
            "No recordings were found in temporary_audio."
        )

    audio_files = [
        path
        for path in recordings
        if path.is_file()
    ]

    if not audio_files:
        raise FileNotFoundError(
            "The temporary_audio folder contains no audio files."
        )

    return max(
        audio_files,
        key=lambda path: path.stat().st_mtime,
    )


def main() -> None:
    audio_path = find_latest_recording()

    print(f"Using recording: {audio_path.name}")

    speech_service = SpeechToTextService()

    transcript = speech_service.transcribe(audio_path)

    print("\nHindi transcript:")
    print(transcript or "[No speech recognized]")


if __name__ == "__main__":
    main()