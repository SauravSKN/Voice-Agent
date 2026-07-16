import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.appointments.models import (
    AppointmentCreateRequest,
    AppointmentRescheduleRequest,
)
from app.appointments.service import (
    AppointmentService,
    DoctorNotFoundError,
    InvalidAppointmentStateError,
    SlotUnavailableError,
)
from app.database import Database, DatabaseSettings


class AppointmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "appointments.sqlite3"
        self.now = datetime.combine(date.today(), time(8, 0))
        self.references = iter(
            ["APT-AAAAA2", "APT-BBBBB3", "APT-CCCCC4", "APT-DDDDD5"]
        )
        self.service = self.make_service()
        self.tomorrow = date.today() + timedelta(days=1)
        while self.tomorrow.weekday() == 6:
            self.tomorrow += timedelta(days=1)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_service(self, reference_factory=None) -> AppointmentService:
        database = Database(DatabaseSettings(self.database_path))
        return AppointmentService(
            database,
            clock=lambda: self.now,
            reference_factory=reference_factory or (lambda: next(self.references)),
        )

    def request(self, **overrides) -> AppointmentCreateRequest:
        values = {
            "doctor_id": "DOC-001",
            "patient_name": "Saurav Kumar",
            "patient_phone": "9876543210",
            "appointment_date": self.tomorrow,
            "start_time": "10:00",
            "consultation_mode": "clinic",
        }
        values.update(overrides)
        return AppointmentCreateRequest(**values)

    def test_doctor_search_and_inactive_exclusion(self) -> None:
        dermatologists = self.service.search_doctors(
            speciality="Dermatology", location="Pune"
        )
        self.assertEqual([item["doctor_id"] for item in dermatologists], ["DOC-002", "DOC-001"])
        self.assertNotIn("DOC-010", [item["doctor_id"] for item in self.service.search_doctors()])
        self.assertTrue(all(item["demonstration_data"] for item in dermatologists))

    def test_availability_is_future_and_filtered(self) -> None:
        slots = self.service.get_available_slots("DOC-001", self.tomorrow)
        self.assertEqual([slot["start_time"] for slot in slots], ["10:00", "11:00", "14:00", "16:00"])
        with self.assertRaisesRegex(Exception, "Past availability"):
            self.service.get_available_slots("DOC-001", date.today() - timedelta(days=1))
        with self.assertRaises(DoctorNotFoundError):
            self.service.get_available_slots("DOC-999", self.tomorrow)

    def test_successful_booking_and_lookup(self) -> None:
        booked = self.service.book(self.request())
        self.assertEqual(booked["status"], "confirmed")
        self.assertEqual(booked["appointment_reference"], "APT-AAAAA2")
        looked_up = self.service.lookup("apt-aaaaa2", "+91 98765 43210")
        self.assertEqual(looked_up, booked)

    def test_reference_factory_rejects_invalid_and_retries_duplicates(self) -> None:
        first = self.make_service(reference_factory=lambda: "APT-QQQQQ2")
        first.book(self.request())
        candidates = iter(["unsafe", "APT-QQQQQ2", "APT-WWWWW3"])
        second = self.make_service(reference_factory=lambda: next(candidates))
        booked = second.book(self.request(start_time="11:00"))
        self.assertEqual(booked["appointment_reference"], "APT-WWWWW3")

    def test_double_booking_is_prevented(self) -> None:
        self.service.book(self.request())
        with self.assertRaises(SlotUnavailableError):
            self.service.book(
                self.request(patient_name="Anita Rao", patient_phone="9876501234")
            )

    def test_concurrent_booking_has_one_winner(self) -> None:
        barrier = threading.Barrier(2)

        def attempt(reference: str, phone: str) -> str:
            service = self.make_service(reference_factory=lambda: reference)
            barrier.wait()
            try:
                service.book(self.request(patient_phone=phone))
                return "confirmed"
            except SlotUnavailableError:
                return "unavailable"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda values: attempt(*values),
                    [("APT-EEEEE6", "9876543210"), ("APT-FFFFF7", "9876501234")],
                )
            )
        self.assertCountEqual(results, ["confirmed", "unavailable"])

    def test_cancellation_releases_slot_and_repeated_cancel_fails(self) -> None:
        booked = self.service.book(self.request())
        cancelled = self.service.cancel(booked["appointment_reference"], "9876543210")
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(InvalidAppointmentStateError):
            self.service.cancel(booked["appointment_reference"], "9876543210")
        replacement = self.service.book(
            self.request(patient_name="Anita Rao", patient_phone="9876501234")
        )
        self.assertEqual(replacement["status"], "confirmed")

    def test_failed_reschedule_preserves_original(self) -> None:
        original = self.service.book(self.request())
        self.service.book(
            self.request(
                patient_name="Anita Rao",
                patient_phone="9876501234",
                start_time="11:00",
            )
        )
        with self.assertRaises(SlotUnavailableError):
            self.service.reschedule(
                original["appointment_reference"],
                AppointmentRescheduleRequest(
                    patient_phone="9876543210",
                    appointment_date=self.tomorrow,
                    start_time="11:00",
                ),
            )
        unchanged = self.service.lookup(original["appointment_reference"], "9876543210")
        self.assertEqual(unchanged["start_time"], "10:00")

    def test_successful_reschedule_releases_original(self) -> None:
        original = self.service.book(self.request())
        moved = self.service.reschedule(
            original["appointment_reference"],
            AppointmentRescheduleRequest(
                patient_phone="9876543210",
                appointment_date=self.tomorrow,
                start_time="11:00",
            ),
        )
        self.assertEqual(moved["start_time"], "11:00")
        replacement = self.service.book(
            self.request(patient_name="Anita Rao", patient_phone="9876501234")
        )
        self.assertEqual(replacement["start_time"], "10:00")

    def test_phone_and_required_field_validation(self) -> None:
        with self.assertRaises(ValidationError):
            self.request(patient_phone="123")
        with self.assertRaises(ValidationError):
            AppointmentCreateRequest(
                doctor_id="DOC-001",
                patient_name="Saurav2",
                patient_phone="9876543210",
                appointment_date=self.tomorrow,
                start_time="10:00",
                consultation_mode="clinic",
            )


if __name__ == "__main__":
    unittest.main()
