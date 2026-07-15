import json
import os
import sys
from urllib.request import Request, urlopen
from uuid import uuid4


def post_json(path: str, payload: dict) -> dict:
    base_url = os.environ.get(
        "VOICE_AGENT_API_URL",
        "http://127.0.0.1:8000",
    ).rstrip("/")
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    session_id = f"manual-{uuid4().hex}"
    other_session_id = f"other-{uuid4().hex}"

    introduction = post_json(
        "/api/chat",
        {"session_id": session_id, "message": "मेरा नाम सौरव है।"},
    )
    remembered = post_json(
        "/api/chat",
        {"session_id": session_id, "message": "मेरा नाम क्या है?"},
    )
    isolated = post_json(
        "/api/chat",
        {"session_id": other_session_id, "message": "मेरा नाम क्या है?"},
    )
    cleared = post_json(
        "/api/conversation/clear",
        {"session_id": session_id},
    )
    after_clear = post_json(
        "/api/chat",
        {"session_id": session_id, "message": "मेरा नाम क्या है?"},
    )

    print(f"Introduction: {introduction['response']}")
    print(f"Remembered follow-up: {remembered['response']}")
    print(f"Other session: {isolated['response']}")
    print(f"Clear response: {json.dumps(cleared, ensure_ascii=False)}")
    print(f"After clear: {after_clear['response']}")


if __name__ == "__main__":
    main()
