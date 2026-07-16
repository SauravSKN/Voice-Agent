import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as main_module
from app.appointments.dialogue import AppointmentAssistant
from app.appointments.service import AppointmentService
from app.appointments.tools import AppointmentTools
from app.database import Database, DatabaseSettings
from app.memory.appointment import AppointmentWorkflowStore
from app.memory.conversation import ConversationStore


class UnusedLanguageModel:
    def generate(self, *_args, **_kwargs):
        raise AssertionError("Appointment dialogue must not invent facts through the LLM.")


class FakeSpeechService:
    def transcribe_with_details(self, _audio_path):
        return SimpleNamespace(
            raw_transcript="हाँ, बुक कर दीजिए",
            cleaned_transcript="हाँ, बुक कर दीजिए",
        )


class FakeTextToSpeechService:
    settings = SimpleNamespace(timeout_seconds=1.0)

    def __init__(self):
        self.messages = []

    def generate(self, message):
        self.messages.append(message)
        return SimpleNamespace(
            filename="tts-0123456789abcdef0123456789abcdef.wav",
            generation_time_ms=1,
        )


class AppointmentConversationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        today = date.today()
        appointment_date = today + timedelta(days=1)
        while appointment_date.weekday() == 6:
            appointment_date += timedelta(days=1)
        self.appointment_date = appointment_date
        service = AppointmentService(
            Database(
                DatabaseSettings(
                    Path(self.temporary_directory.name) / "conversation.sqlite3"
                )
            ),
            clock=lambda: datetime.combine(today, time(8, 0)),
            reference_factory=lambda: "APT-VOICE2",
        )
        self.assistant = AppointmentAssistant(
            AppointmentTools(service),
            AppointmentWorkflowStore(),
            today=lambda: today,
        )
        self.conversation_store = ConversationStore()
        self.tts = FakeTextToSpeechService()
        self.patches = [
            patch.object(
                main_module,
                "get_appointment_assistant",
                return_value=self.assistant,
            ),
            patch.object(
                main_module,
                "get_appointment_workflow_store",
                return_value=self.assistant.store,
            ),
            patch.object(
                main_module,
                "get_conversation_store",
                return_value=self.conversation_store,
            ),
            patch.object(
                main_module,
                "get_language_model_service",
                return_value=UnusedLanguageModel(),
            ),
            patch.object(
                main_module,
                "get_speech_service",
                return_value=FakeSpeechService(),
            ),
            patch.object(
                main_module,
                "get_text_to_speech_service",
                return_value=self.tts,
            ),
        ]
        for active_patch in self.patches:
            active_patch.start()
        self.client = TestClient(main_module.app)

    def tearDown(self):
        self.client.close()
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temporary_directory.cleanup()

    def post_chat(self, message):
        return self.client.post(
            "/api/chat",
            json={"session_id": "voice-form-session", "message": message},
        )

    def test_typed_collection_and_voice_confirmation_share_workflow(self):
        messages = [
            f"मुझे {self.appointment_date.isoformat()} को त्वचा रोग विशेषज्ञ से अपॉइंटमेंट चाहिए",
            "पुणे",
            "क्लिनिक विज़िट",
            "DOC-001",
            "शाम 4 बजे",
            "मेरा नाम सौरव कुमार है",
            "9876543210",
        ]
        for message in messages:
            response = self.post_chat(message)
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.json()["appointment_state"])

        voice = self.client.post(
            "/api/voice/respond",
            data={"session_id": "voice-form-session"},
            files={"audio": ("recording.webm", b"audio", "audio/webm")},
        )
        self.assertEqual(voice.status_code, 200)
        payload = voice.json()
        self.assertEqual(payload["appointment"]["status"], "confirmed")
        self.assertEqual(
            payload["appointment"]["appointment_reference"],
            "APT-VOICE2",
        )
        self.assertIn("बुक हो गई", payload["response"])
        self.assertEqual(self.tts.messages, [payload["response"]])

    def test_new_conversation_clears_both_workflow_and_chat_history(self):
        started = self.post_chat("मुझे डॉक्टर की अपॉइंटमेंट चाहिए")
        self.assertEqual(started.status_code, 200)
        self.assertTrue(self.assistant.store.get("voice-form-session"))
        cleared = self.client.post(
            "/api/conversation/clear",
            json={"session_id": "voice-form-session"},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertTrue(cleared.json()["cleared"])
        self.assertEqual(self.assistant.store.get("voice-form-session"), {})
        self.assertEqual(self.conversation_store.turn_count("voice-form-session"), 0)


if __name__ == "__main__":
    unittest.main()
