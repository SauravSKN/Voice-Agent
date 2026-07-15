import io
import json
import os
import re
import sys
import wave
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from app.services.text_to_speech import TextToSpeechService


def build_multipart(audio_path: Path, session_id: str) -> tuple[bytes, str]:
    boundary = f"----HindiVoiceAgent{uuid4().hex}"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("ascii"))
    body.extend(
        b'Content-Disposition: form-data; name="session_id"\r\n\r\n'
    )
    body.extend(session_id.encode("ascii"))
    body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode("ascii"))
    body.extend(
        (
            'Content-Disposition: form-data; name="audio"; '
            f'filename="{audio_path.name}"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(audio_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return bytes(body), boundary


def post_voice(base_url: str, audio_path: Path, session_id: str) -> dict:
    body, boundary = build_multipart(audio_path, session_id)
    request = Request(
        f"{base_url}/api/voice/respond",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, payload: dict) -> dict:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def validate_response_audio(base_url: str, audio_url: str) -> None:
    with urlopen(f"{base_url}{audio_url}", timeout=30) as response:
        audio_bytes = response.read()
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        if wav_file.getnframes() < 1:
            raise RuntimeError("A response WAV contains no audio frames.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    base_url = os.environ.get(
        "VOICE_AGENT_API_URL",
        "http://127.0.0.1:8000",
    ).rstrip("/")
    session_id = f"voice-memory-{uuid4().hex}"
    service = TextToSpeechService()
    introduction_audio = service.generate("मेरा नाम सौरव है।").file_path
    question_audio = service.generate("मेरा नाम क्या है?").file_path

    introduction = post_voice(base_url, introduction_audio, session_id)
    remembered = post_voice(base_url, question_audio, session_id)
    validate_response_audio(base_url, introduction["audio_url"])
    validate_response_audio(base_url, remembered["audio_url"])

    print(f"Introduction transcript: {introduction['transcript']}")
    print(f"Introduction response: {introduction['response']}")
    print(f"Remembered transcript: {remembered['transcript']}")
    print(f"Remembered response: {remembered['response']}")
    print(f"Remembered turns: {remembered['memory_turns']}")

    name_match = re.search(
        r"मेरा नाम\s+([^\s।,.!?]+)",
        introduction["transcript"],
    )
    if not name_match:
        raise RuntimeError("The introduction name was not transcribed.")
    recognized_name = name_match.group(1)
    if recognized_name not in remembered["response"]:
        raise RuntimeError("The spoken response did not remember the name.")

    cleared = post_json(
        base_url,
        "/api/conversation/clear",
        {"session_id": session_id},
    )
    after_clear = post_voice(base_url, question_audio, session_id)
    print(f"Clear response: {cleared}")
    print(f"After-clear response: {after_clear['response']}")
    if recognized_name in after_clear["response"]:
        raise RuntimeError("The name remained after clearing the session.")

    print("Spoken conversation memory and clear: PASS")


if __name__ == "__main__":
    main()
