import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as main_module
from app.memory.conversation import ConversationSettings, ConversationStore
from app.services.language_model import (
    BlankModelResponseError,
    ModelServerUnavailableError,
)
from app.services.text_to_speech import TextToSpeechGenerationError


class FakeLanguageModelService:
    def __init__(self):
        self.calls = []
        self.error = None

    def generate(self, message, history=None):
        self.calls.append(
            {
                "message": message,
                "history": list(history or []),
            }
        )
        if self.error:
            raise self.error
        if message == "मेरा नाम सौरव है।":
            response = "नमस्ते सौरव।"
        elif message == "मेरा नाम क्या है?" and history:
            response = "आपका नाम सौरव है।"
        else:
            response = "मुझे आपका नाम नहीं पता।"
        return SimpleNamespace(response=response, generation_time_ms=5)


class FakeSpeechService:
    def __init__(self, transcript="मेरा नाम क्या है?"):
        self.transcript = transcript

    def transcribe_with_details(self, _audio_path):
        return SimpleNamespace(
            raw_transcript=self.transcript,
            cleaned_transcript=self.transcript,
        )


class FakeTextToSpeechService:
    def __init__(self):
        self.error = None
        self.settings = SimpleNamespace(timeout_seconds=1.0)

    def generate(self, _message):
        if self.error:
            raise self.error
        return SimpleNamespace(
            filename="tts-0123456789abcdef0123456789abcdef.wav",
            generation_time_ms=1,
        )


class ConversationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)
        self.store = ConversationStore(
            ConversationSettings(
                max_turns=6,
                ttl_seconds=1800,
                max_sessions=100,
            )
        )
        self.language_model = FakeLanguageModelService()
        self.speech_service = FakeSpeechService()
        self.text_to_speech_service = FakeTextToSpeechService()

    def services(self):
        return (
            patch.object(
                main_module,
                "get_conversation_store",
                return_value=self.store,
            ),
            patch.object(
                main_module,
                "get_language_model_service",
                return_value=self.language_model,
            ),
            patch.object(
                main_module,
                "get_speech_service",
                return_value=self.speech_service,
            ),
            patch.object(
                main_module,
                "get_text_to_speech_service",
                return_value=self.text_to_speech_service,
            ),
        )

    def test_successful_chat_stores_history(self):
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        with store_patch, model_patch, speech_patch, tts_patch:
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": "chat-session",
                    "message": "मेरा नाम सौरव है।",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["memory_turns"], 1)
        self.assertEqual(self.store.turn_count("chat-session"), 1)

    def test_voice_and_typed_chat_share_one_session(self):
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        with store_patch, model_patch, speech_patch, tts_patch:
            first = self.client.post(
                "/api/chat",
                json={
                    "session_id": "shared-session",
                    "message": "मेरा नाम सौरव है।",
                },
            )
            second = self.client.post(
                "/api/voice/respond",
                data={"session_id": "shared-session"},
                files={
                    "audio": ("recording.webm", b"audio", "audio/webm")
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["memory_turns"], 2)
        self.assertEqual(second.json()["response"], "आपका नाम सौरव है।")
        self.assertEqual(
            self.language_model.calls[1]["history"],
            [
                {"role": "user", "content": "मेरा नाम सौरव है।"},
                {"role": "assistant", "content": "नमस्ते सौरव।"},
            ],
        )

    def test_failed_or_blank_generation_is_not_stored(self):
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        with store_patch, model_patch, speech_patch, tts_patch:
            self.language_model.error = ModelServerUnavailableError("offline")
            failed = self.client.post(
                "/api/chat",
                json={"session_id": "failed-session", "message": "नमस्ते"},
            )
            self.language_model.error = BlankModelResponseError("blank")
            blank = self.client.post(
                "/api/chat",
                json={"session_id": "blank-session", "message": "नमस्ते"},
            )

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(blank.status_code, 502)
        self.assertEqual(self.store.turn_count("failed-session"), 0)
        self.assertEqual(self.store.turn_count("blank-session"), 0)

    def test_tts_failure_does_not_discard_valid_text_turn(self):
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        self.text_to_speech_service.error = TextToSpeechGenerationError(
            "synthesis failed"
        )
        with store_patch, model_patch, speech_patch, tts_patch:
            response = self.client.post(
                "/api/voice/respond",
                data={"session_id": "tts-failed-session"},
                files={
                    "audio": ("recording.webm", b"audio", "audio/webm")
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.store.turn_count("tts-failed-session"), 1)

    def test_different_sessions_are_isolated(self):
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        with store_patch, model_patch, speech_patch, tts_patch:
            self.client.post(
                "/api/chat",
                json={
                    "session_id": "first-session",
                    "message": "मेरा नाम सौरव है।",
                },
            )
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": "second-session",
                    "message": "मेरा नाम क्या है?",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"], "मुझे आपका नाम नहीं पता।")
        self.assertEqual(self.language_model.calls[1]["history"], [])

    def test_clear_endpoint_removes_history_and_is_idempotent(self):
        self.store.add_turn("clear-session", "user", "assistant")
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        with store_patch, model_patch, speech_patch, tts_patch:
            first = self.client.post(
                "/api/conversation/clear",
                json={"session_id": "clear-session"},
            )
            second = self.client.post(
                "/api/conversation/clear",
                json={"session_id": "clear-session"},
            )

        self.assertEqual(first.json(), {"status": "success", "cleared": True})
        self.assertEqual(second.json(), {"status": "success", "cleared": False})

    def test_invalid_session_id_is_rejected_by_all_memory_endpoints(self):
        store_patch, model_patch, speech_patch, tts_patch = self.services()
        with store_patch, model_patch, speech_patch, tts_patch:
            chat = self.client.post(
                "/api/chat",
                json={"session_id": "../unsafe", "message": "नमस्ते"},
            )
            voice = self.client.post(
                "/api/voice/respond",
                data={"session_id": "../unsafe"},
                files={
                    "audio": ("recording.webm", b"audio", "audio/webm")
                },
            )
            clear = self.client.post(
                "/api/conversation/clear",
                json={"session_id": "../unsafe"},
            )

        self.assertEqual(chat.status_code, 400)
        self.assertEqual(voice.status_code, 400)
        self.assertEqual(clear.status_code, 400)

    def test_conversation_store_accessor_is_cached(self):
        cached_store = object()
        main_module.get_conversation_store.cache_clear()
        try:
            with patch.object(
                main_module,
                "ConversationStore",
                return_value=cached_store,
            ) as store_factory:
                self.assertIs(
                    main_module.get_conversation_store(),
                    main_module.get_conversation_store(),
                )
            store_factory.assert_called_once_with()
        finally:
            main_module.get_conversation_store.cache_clear()


if __name__ == "__main__":
    unittest.main()
