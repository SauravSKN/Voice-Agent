import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as main_module


class GeneratedAudioEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.audio_directory = Path(self.temporary_directory.name)
        self.client = TestClient(main_module.app)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def get(self, filename: str):
        with patch.object(
            main_module,
            "default_generated_audio_directory",
            return_value=self.audio_directory,
        ):
            return self.client.get(f"/generated-audio/{filename}")

    def test_safe_generated_audio_is_served_without_path_disclosure(self):
        filename = "tts-0123456789abcdef0123456789abcdef.wav"
        (self.audio_directory / filename).write_bytes(
            b"RIFF" + (b"\x00" * 100)
        )

        response = self.get(filename)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(str(self.audio_directory), response.text)

    def test_missing_and_unsafe_names_return_404(self):
        missing = self.get(
            "tts-ffffffffffffffffffffffffffffffff.wav"
        )
        unsafe = self.get("notes.wav")
        traversal = self.client.get(
            "/generated-audio/../models/secret.wav"
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unsafe.status_code, 404)
        self.assertEqual(traversal.status_code, 404)


if __name__ == "__main__":
    unittest.main()
