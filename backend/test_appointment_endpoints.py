import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.appointments.service import AppointmentService
from app.appointments.dialogue import AppointmentAssistant
from app.appointments.tools import AppointmentTools
from app.database import Database, DatabaseSettings
from app.memory.appointment import AppointmentWorkflowStore
from app.main import app


class AppointmentEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.tomorrow = date.today() + timedelta(days=1)
        while self.tomorrow.weekday() == 6:
            self.tomorrow += timedelta(days=1)
        references = iter(["APT-QWERT2", "APT-ASDFG3"])
        self.service = AppointmentService(
            Database(
                DatabaseSettings(Path(self.temporary_directory.name) / "api.sqlite3")
            ),
            clock=lambda: datetime.combine(date.today(), time(8, 0)),
            reference_factory=lambda: next(references),
        )
        self.service_patch = patch(
            "app.main.get_appointment_service",
            return_value=self.service,
        )
        self.service_patch.start()
        self.assistant = AppointmentAssistant(
            AppointmentTools(self.service),
            AppointmentWorkflowStore(),
            today=date.today,
        )
        self.assistant_patch = patch(
            "app.main.get_appointment_assistant",
            return_value=self.assistant,
        )
        self.assistant_patch.start()
        self.workflow_store_patch = patch(
            "app.main.get_appointment_workflow_store",
            return_value=self.assistant.store,
        )
        self.workflow_store_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.workflow_store_patch.stop()
        self.assistant_patch.stop()
        self.service_patch.stop()
        self.temporary_directory.cleanup()

    def payload(self, **overrides):
        values = {
            "doctor_id": "DOC-001",
            "patient_name": "Saurav Kumar",
            "patient_phone": "9876543210",
            "appointment_date": self.tomorrow.isoformat(),
            "start_time": "10:00",
            "consultation_mode": "clinic",
        }
        values.update(overrides)
        return values

    def test_directory_specialities_details_and_availability(self) -> None:
        specialities = self.client.get("/api/specialities")
        self.assertEqual(specialities.status_code, 200)
        self.assertIn("Dermatology", specialities.json()["specialities"])
        doctors = self.client.get(
            "/api/doctors",
            params={"speciality": "Dermatology", "location": "Pune"},
        )
        self.assertEqual(doctors.status_code, 200)
        self.assertEqual(len(doctors.json()["doctors"]), 2)
        details = self.client.get("/api/doctors/DOC-001")
        self.assertNotIn("id", details.json())
        availability = self.client.get(
            "/api/doctors/DOC-001/availability",
            params={"date": self.tomorrow.isoformat()},
        )
        self.assertEqual(len(availability.json()["slots"]), 4)

    def test_booking_lookup_reschedule_and_cancel(self) -> None:
        created = self.client.post(
            "/api/appointments",
            json=self.payload(session_id="form-session"),
        )
        self.assertEqual(created.status_code, 200)
        reference = created.json()["appointment_reference"]
        self.assertNotIn("patient_phone", created.json())
        looked_up = self.client.get(
            f"/api/appointments/{reference}", params={"phone": "9876543210"}
        )
        self.assertEqual(looked_up.json()["status"], "confirmed")
        moved = self.client.post(
            f"/api/appointments/{reference}/reschedule",
            json={
                "patient_phone": "9876543210",
                "appointment_date": self.tomorrow.isoformat(),
                "start_time": "11:00",
                "session_id": "form-session",
            },
        )
        self.assertEqual(moved.json()["start_time"], "11:00")
        cancelled = self.client.post(
            f"/api/appointments/{reference}/cancel",
            json={
                "patient_phone": "9876543210",
                "session_id": "form-session",
            },
        )
        self.assertEqual(cancelled.json()["status"], "cancelled")
        state = self.assistant.store.get("form-session")
        self.assertEqual(state["phase"], "cancelled")
        self.assertEqual(state["appointment"]["status"], "cancelled")

    def test_double_booking_and_unknown_reference_are_safe(self) -> None:
        self.assertEqual(self.client.post("/api/appointments", json=self.payload()).status_code, 200)
        conflict = self.client.post(
            "/api/appointments",
            json=self.payload(patient_name="Anita Rao", patient_phone="9876501234"),
        )
        self.assertEqual(conflict.status_code, 409)
        missing = self.client.get(
            "/api/appointments/APT-NONE22", params={"phone": "9876543210"}
        )
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn(str(self.service.database.settings.path), missing.text)

    def test_invalid_phone_and_past_slot_are_rejected(self) -> None:
        invalid_phone = self.client.post(
            "/api/appointments", json=self.payload(patient_phone="123")
        )
        self.assertEqual(invalid_phone.status_code, 422)
        past = self.client.post(
            "/api/appointments",
            json=self.payload(appointment_date=(date.today() - timedelta(days=1)).isoformat()),
        )
        self.assertIn(past.status_code, {400, 404})


if __name__ == "__main__":
    unittest.main()
