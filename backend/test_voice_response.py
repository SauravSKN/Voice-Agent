import io
import json
import os
import sys
import wave
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


TEMP_AUDIO_DIR = Path(__file__).resolve().parent / "temporary_audio"


def find_recording() -> Path:
    recordings = [path for path in TEMP_AUDIO_DIR.glob("*.webm") if path.is_file()]
    if not recordings:
        raise FileNotFoundError("No WebM recording was found in temporary_audio.")
    return max(recordings, key=lambda path: path.stat().st_mtime)


def build_multipart(audio_path: Path) -> tuple[bytes, str]:
    boundary = f"----HindiVoiceAgent{uuid4().hex}"
    header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="audio"; '
        f'filename="{audio_path.name}"\r\n'
        "Content-Type: audio/webm\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("ascii")
    return header + audio_path.read_bytes() + footer, boundary


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    audio_path = find_recording()
    request_body, boundary = build_multipart(audio_path)
    base_url = os.environ.get(
        "VOICE_AGENT_API_URL",
        "http://127.0.0.1:8000",
    ).rstrip("/")

    request = Request(
        f"{base_url}/api/voice/respond",
        data=request_body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    print(f"Using recording: {audio_path.name}")
    with urlopen(request, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))

    print(f"Transcript: {result['transcript']}")
    print(f"Assistant: {result['response']}")
    print(f"Audio URL: {result['audio_url']}")
    print(f"Transcription time: {result['timing']['transcription_ms']} ms")
    print(f"Language-model time: {result['timing']['language_model_ms']} ms")
    print(f"Text-to-speech time: {result['timing']['text_to_speech_ms']} ms")
    print(f"Total backend time: {result['timing']['total_ms']} ms")

    with urlopen(f"{base_url}{result['audio_url']}", timeout=30) as response:
        audio_bytes = response.read()
        content_type = response.headers.get_content_type()

    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        duration_seconds = wav_file.getnframes() / wav_file.getframerate()
        print(f"Generated audio content type: {content_type}")
        print(f"Generated audio size: {len(audio_bytes)} bytes")
        print(f"Generated audio duration: {duration_seconds:.3f} seconds")

    if content_type != "audio/wav" or len(audio_bytes) <= 44:
        raise RuntimeError("Generated response audio is invalid.")
    print("Generated-audio route validation: PASS")


if __name__ == "__main__":
    main()
