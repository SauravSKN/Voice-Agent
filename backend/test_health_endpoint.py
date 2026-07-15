import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as main_module


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_health_checks_configuration_without_loading_models(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "voice.onnx"
            model_path.write_bytes(b"model")
            Path(f"{model_path}.json").write_text("{}", encoding="utf-8")
            environment = {
                "WHISPER_MODEL": "medium",
                "WHISPER_DEVICE": "cpu",
                "WHISPER_COMPUTE_TYPE": "int8",
                "WHISPER_ALLOW_CPU_FALLBACK": "true",
                "LLM_MODEL": "qwen3:4b-instruct",
                "LLM_BASE_URL": "http://127.0.0.1:11434",
                "TTS_MODEL": str(model_path),
            }

            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(
                    main_module,
                    "urlopen",
                    return_value=FakeResponse(
                        {"models": [{"name": "qwen3:4b-instruct"}]}
                    ),
                ),
                patch.object(
                    main_module,
                    "get_speech_service",
                    side_effect=AssertionError("Whisper must not load"),
                ),
                patch.object(
                    main_module,
                    "get_language_model_service",
                    side_effect=AssertionError("Qwen must not load"),
                ),
                patch.object(
                    main_module,
                    "get_text_to_speech_service",
                    side_effect=AssertionError("Piper must not load"),
                ),
            ):
                response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "services": {
                    "speech_to_text": "ready",
                    "language_model": "reachable",
                    "text_to_speech": "ready",
                },
            },
        )

    def test_health_reports_degraded_without_leaking_paths(self):
        private_model_path = Path(tempfile.gettempdir()) / "private-voice.onnx"
        environment = {
            "WHISPER_DEVICE": "gpu",
            "TTS_MODEL": str(private_model_path),
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(
                main_module,
                "urlopen",
                side_effect=URLError("offline"),
            ),
        ):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(
            response.json()["services"],
            {
                "speech_to_text": "misconfigured",
                "language_model": "unreachable",
                "text_to_speech": "model_missing",
            },
        )
        self.assertNotIn(str(private_model_path), response.text)


if __name__ == "__main__":
    unittest.main()
