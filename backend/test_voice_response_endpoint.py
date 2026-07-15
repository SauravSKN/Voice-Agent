import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as main_module
from app.services.language_model import (
    BlankModelResponseError,
    LanguageModelTimeoutError,
    ModelServerUnavailableError,
)
from app.services.speech_to_text import TranscriptionError
from app.services.text_to_speech import (
    EmptyTextToSpeechOutputError,
    TextToSpeechGenerationError,
    TextToSpeechModelLoadingError,
    InvalidTextToSpeechInputError,
)


class FakeSpeechService:
    def __init__(self, transcript="भारत की राजधानी क्या है?", error=None):
        self.transcript = transcript
        self.error = error
        self.observed_path = None

    def transcribe_with_details(self, audio_path):
        self.observed_path = Path(audio_path)
        if not self.observed_path.exists():
            raise AssertionError("Temporary audio was not created.")
        if self.error:
            raise self.error
        return SimpleNamespace(
            raw_transcript=self.transcript,
            cleaned_transcript=self.transcript,
        )


class FakeLanguageModelService:
    def __init__(self, response="भारत की राजधानी नई दिल्ली है।", error=None):
        self.response = response
        self.error = error
        self.messages = []

    def generate(self, message, history=None):
        self.messages.append(message)
        if self.error:
            raise self.error
        return SimpleNamespace(
            response=self.response,
            generation_time_ms=10,
        )


class FakeTextToSpeechService:
    def __init__(self, error=None, delay_seconds=0.0):
        self.error = error
        self.delay_seconds = delay_seconds
        self.messages = []
        self.voice_selections = []
        self.settings = SimpleNamespace(timeout_seconds=1.0)

    def generate(self, message, voice_selection=None):
        self.messages.append(message)
        self.voice_selections.append(voice_selection)
        if voice_selection not in {
            None,
            "piper",
            "indic_parler_divya",
            "indic_parler_rohit",
        }:
            raise InvalidTextToSpeechInputError("invalid voice")
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.error:
            raise self.error
        return SimpleNamespace(
            filename="tts-0123456789abcdef0123456789abcdef.wav",
            generation_time_ms=7,
            provider=(
                "indic_parler"
                if voice_selection == "indic_parler_divya"
                else "piper"
            ),
            voice=(
                "Divya"
                if voice_selection == "indic_parler_divya"
                else "Priyamvada"
            ),
        )


class VoiceResponseEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def post_audio(
        self,
        speech_service,
        language_model_service,
        text_to_speech_service=None,
        tts_voice=None,
    ):
        tts_service = text_to_speech_service or FakeTextToSpeechService()
        with (
            patch.object(
                main_module,
                "get_speech_service",
                return_value=speech_service,
            ),
            patch.object(
                main_module,
                "get_language_model_service",
                return_value=language_model_service,
            ),
            patch.object(
                main_module,
                "get_text_to_speech_service",
                return_value=tts_service,
            ),
        ):
            return self.client.post(
                "/api/voice/respond",
                files={
                    "audio": (
                        "recording.webm",
                        b"test-audio",
                        "audio/webm",
                    )
                },
                data=(
                    {"tts_voice": tts_voice}
                    if tts_voice is not None
                    else None
                ),
            )

    def test_successful_combined_response_and_timing_structure(self):
        speech_service = FakeSpeechService()
        language_model_service = FakeLanguageModelService()
        text_to_speech_service = FakeTextToSpeechService()

        response = self.post_audio(
            speech_service,
            language_model_service,
            text_to_speech_service,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["transcript"], speech_service.transcript)
        self.assertEqual(data["response"], language_model_service.response)
        self.assertEqual(
            data["audio_url"],
            "/generated-audio/tts-0123456789abcdef0123456789abcdef.wav",
        )
        self.assertEqual(data["tts_provider"], "piper")
        self.assertEqual(data["tts_voice"], "Priyamvada")
        self.assertEqual(
            text_to_speech_service.messages,
            [language_model_service.response],
        )
        self.assertEqual(
            language_model_service.messages,
            [speech_service.transcript],
        )
        self.assertEqual(
            set(data["timing"]),
            {
                "transcription_ms",
                "language_model_ms",
                "text_to_speech_ms",
                "total_ms",
            },
        )
        self.assertTrue(
            all(value >= 0 for value in data["timing"].values())
        )

    def test_selected_voice_and_actual_provider_are_returned(self):
        tts_service = FakeTextToSpeechService()
        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(),
            tts_service,
            tts_voice="indic_parler_divya",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tts_provider"], "indic_parler")
        self.assertEqual(response.json()["tts_voice"], "Divya")
        self.assertEqual(
            tts_service.voice_selections,
            ["indic_parler_divya"],
        )

    def test_invalid_browser_voice_is_rejected(self):
        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(),
            FakeTextToSpeechService(),
            tts_voice="arbitrary_model",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "The generated response could not be spoken.",
        )

    def test_blank_transcript_is_rejected(self):
        response = self.post_audio(
            FakeSpeechService(transcript="   "),
            FakeLanguageModelService(),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "No speech was detected in the audio.",
        )

    def test_transcription_failure_is_safe(self):
        response = self.post_audio(
            FakeSpeechService(
                error=TranscriptionError("decoder failed at C:\\secret")
            ),
            FakeLanguageModelService(),
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "The audio could not be transcribed.",
        )
        self.assertNotIn("secret", response.text)

    def test_model_unavailable(self):
        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(
                error=ModelServerUnavailableError("connection refused")
            ),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The local language model is unavailable.",
        )

    def test_model_timeout(self):
        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(
                error=LanguageModelTimeoutError("slow")
            ),
        )

        self.assertEqual(response.status_code, 504)

    def test_blank_model_response(self):
        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(
                error=BlankModelResponseError("blank")
            ),
        )

        self.assertEqual(response.status_code, 502)

    def test_tts_model_unavailable_is_safe(self):
        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(),
            FakeTextToSpeechService(
                error=TextToSpeechModelLoadingError("C:\\secret")
            ),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The local text-to-speech model is unavailable.",
        )
        self.assertNotIn("secret", response.text)

    def test_tts_generation_and_empty_output_fail_safely(self):
        generation = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(),
            FakeTextToSpeechService(
                error=TextToSpeechGenerationError("failed")
            ),
        )
        empty = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(),
            FakeTextToSpeechService(
                error=EmptyTextToSpeechOutputError("empty")
            ),
        )

        self.assertEqual(generation.status_code, 502)
        self.assertEqual(empty.status_code, 502)
        self.assertIn("no audio", empty.json()["detail"])

    def test_tts_timeout_is_reported(self):
        text_to_speech_service = FakeTextToSpeechService(
            delay_seconds=0.05
        )
        text_to_speech_service.settings.timeout_seconds = 0.005

        response = self.post_audio(
            FakeSpeechService(),
            FakeLanguageModelService(),
            text_to_speech_service,
        )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(
            response.json()["detail"],
            "The local text-to-speech request timed out.",
        )

    def test_temporary_file_is_removed_after_success(self):
        speech_service = FakeSpeechService()

        response = self.post_audio(
            speech_service,
            FakeLanguageModelService(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(speech_service.observed_path)
        self.assertFalse(speech_service.observed_path.exists())

    def test_upload_validation(self):
        missing = self.client.post("/api/voice/respond")
        empty = self.client.post(
            "/api/voice/respond",
            files={"audio": ("empty.webm", b"", "audio/webm")},
        )
        unsupported = self.client.post(
            "/api/voice/respond",
            files={"audio": ("notes.txt", b"text", "text/plain")},
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(unsupported.status_code, 415)

    def test_all_service_accessors_cache_once(self):
        speech_service = object()
        language_model_service = object()
        text_to_speech_service = object()
        main_module.get_speech_service.cache_clear()
        main_module.get_language_model_service.cache_clear()
        main_module.get_text_to_speech_service.cache_clear()

        try:
            with (
                patch.object(
                    main_module,
                    "SpeechToTextService",
                    return_value=speech_service,
                ) as speech_factory,
                patch.object(
                    main_module,
                    "LanguageModelService",
                    return_value=language_model_service,
                ) as language_model_factory,
                patch.object(
                    main_module,
                    "TextToSpeechService",
                    return_value=text_to_speech_service,
                ) as text_to_speech_factory,
            ):
                self.assertIs(
                    main_module.get_speech_service(),
                    main_module.get_speech_service(),
                )
                self.assertIs(
                    main_module.get_language_model_service(),
                    main_module.get_language_model_service(),
                )
                self.assertIs(
                    main_module.get_text_to_speech_service(),
                    main_module.get_text_to_speech_service(),
                )

            speech_factory.assert_called_once_with()
            language_model_factory.assert_called_once_with()
            text_to_speech_factory.assert_called_once_with()
        finally:
            main_module.get_speech_service.cache_clear()
            main_module.get_language_model_service.cache_clear()
            main_module.get_text_to_speech_service.cache_clear()


if __name__ == "__main__":
    unittest.main()
