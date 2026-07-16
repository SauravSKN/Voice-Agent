import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.appointments.dialogue import AppointmentAssistant
from app.appointments.service import AppointmentService, SlotUnavailableError
from app.appointments.tools import AppointmentTools, UnknownAppointmentToolError
from app.database import Database, DatabaseSettings
from app.memory.appointment import AppointmentWorkflowStore


class FailingBookTools(AppointmentTools):
    def book_appointment(self, **values):
        raise SlotUnavailableError("The requested slot is no longer available.")


class AppointmentDialogueTests(unittest.TestCase):
    def test_iso_date_does_not_override_explicit_time(self):
        self.assertEqual(
            self.assistant._extract_time("2026-07-20 16:00"),
            "16:00",
        )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database = Database(
            DatabaseSettings(Path(self.temporary_directory.name) / "dialogue.sqlite3")
        )
        today = date.today()
        self.appointment_date = today + timedelta(days=1)
        while self.appointment_date.weekday() == 6:
            self.appointment_date += timedelta(days=1)
        service = AppointmentService(
            database,
            clock=lambda: datetime.combine(today, time(8, 0)),
            reference_factory=lambda: "APT-ZYXW98",
        )
        self.tools = AppointmentTools(service)
        self.assistant = AppointmentAssistant(
            self.tools,
            AppointmentWorkflowStore(),
            today=lambda: today,
        )
        self.session_id = "dialogue-session"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def say(self, text: str):
        result = self.assistant.handle(text, self.session_id)
        self.assertIsNotNone(result)
        return result

    def advance_to_confirmation(self) -> None:
        self.assertIn(
            "स्थान",
            self.say(
                f"मुझे {self.appointment_date.isoformat()} को किसी त्वचा रोग विशेषज्ञ से अपॉइंटमेंट चाहिए।"
            ).response,
        )
        self.assertIn("क्लिनिक", self.say("पुणे").response)
        self.assertIn("DOC-", self.say("क्लिनिक विज़िट").response)
        self.assertIn("उपलब्ध समय", self.say("DOC-001").response)
        self.assertIn("नाम", self.say("शाम 4 बजे").response)
        self.assertIn("मोबाइल", self.say("मेरा नाम सौरव है").response)
        self.assertIn("पुष्टि", self.say("9876543210").response)

    def test_full_booking_flow_confirms_only_after_database_success(self) -> None:
        self.advance_to_confirmation()
        confirmed = self.say("हाँ, बुक कर दीजिए")
        self.assertIn("बुक हो गई", confirmed.response)
        self.assertEqual(confirmed.appointment["appointment_reference"], "APT-ZYXW98")
        self.assertEqual(confirmed.appointment_state["phase"], "confirmed")

    def test_completed_workflow_releases_general_chat_and_can_switch_intent(self) -> None:
        self.advance_to_confirmation()
        confirmed = self.say("हाँ, बुक कर दीजिए")
        reference = confirmed.appointment["appointment_reference"]
        switched = self.say("मेरी अपॉइंटमेंट रद्द कर दीजिए")
        self.assertEqual(switched.appointment_state["intent"], "cancel_appointment")
        self.assertEqual(switched.appointment_state["appointment_reference"], reference)
        self.assertEqual(switched.appointment_state["awaiting"], "patient_phone")

        self.assistant.store.replace(
            self.session_id,
            {
                "intent": "manage_appointment",
                "phase": "confirmed",
                "appointment_reference": reference,
            },
        )
        self.assertIsNone(self.assistant.handle("नमस्ते", self.session_id))
        self.assertEqual(self.assistant.store.get(self.session_id), {})

    def test_medical_safety_response_does_not_discard_active_workflow(self) -> None:
        first = self.say("मुझे डॉक्टर की अपॉइंटमेंट चाहिए")
        before = first.appointment_state
        refused = self.say("मुझे कौन सी दवा और खुराक लेनी चाहिए?")
        self.assertIn("निदान", refused.response)
        self.assertEqual(refused.appointment_state, before)

    def test_missing_fields_are_requested_one_at_a_time(self) -> None:
        first = self.say("मुझे डॉक्टर से अपॉइंटमेंट चाहिए")
        self.assertEqual(first.appointment_state["awaiting"], "speciality")
        self.assertNotIn("patient_phone", first.appointment_state)

    def test_no_doctor_is_invented(self) -> None:
        self.say("मुझे कल हृदय के डॉक्टर की अपॉइंटमेंट चाहिए")
        self.say("पुणे")
        result = self.say("क्लिनिक")
        self.assertIn("कोई सक्रिय डेमो डॉक्टर", result.response)
        self.assertEqual(result.appointment_state["doctor_options"], [])

    def test_medical_advice_and_emergency_are_safely_refused(self) -> None:
        advice = self.say("मेरी दवा की खुराक कितनी होनी चाहिए?")
        self.assertIn("निदान", advice.response)
        emergency = self.assistant.handle("मुझे सीने में दर्द है और सांस नहीं आ रही", "emergency")
        self.assertIn("आपात", emergency.response)
        self.assertIn("अस्पताल", emergency.response)

    def test_failed_tool_does_not_claim_booking_success(self) -> None:
        failing = AppointmentAssistant(
            FailingBookTools(self.tools.service),
            AppointmentWorkflowStore(),
            today=date.today,
        )
        self.assistant = failing
        self.advance_to_confirmation()
        failed = self.say("हाँ")
        self.assertNotIn("बुक हो गई", failed.response)
        self.assertIn("पूरी नहीं हुई", failed.response)

    def test_clear_removes_workflow_state(self) -> None:
        self.say("मुझे डॉक्टर की अपॉइंटमेंट चाहिए")
        self.assertTrue(self.assistant.clear(self.session_id))
        self.assertEqual(self.assistant.store.get(self.session_id), {})

    def test_unknown_tool_and_raw_query_are_rejected(self) -> None:
        with self.assertRaises(UnknownAppointmentToolError):
            self.tools.execute("run_sql", {"query": "SELECT * FROM doctors"})


if __name__ == "__main__":
    unittest.main()
