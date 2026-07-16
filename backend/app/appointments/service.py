import secrets
import sqlite3
from datetime import date, datetime
from typing import Any, Callable

from app.appointments.models import (
    AppointmentCreateRequest,
    AppointmentRescheduleRequest,
    normalize_phone,
    normalize_reference,
)
from app.database import Database
from app.database.repositories import (
    AppointmentRepository,
    AvailabilityRepository,
    DoctorRepository,
)


class AppointmentError(RuntimeError):
    """Base error for verified appointment operations."""


class AppointmentValidationError(AppointmentError):
    pass


class DoctorNotFoundError(AppointmentError):
    pass


class SlotNotFoundError(AppointmentError):
    pass


class SlotUnavailableError(AppointmentError):
    pass


class AppointmentNotFoundError(AppointmentError):
    pass


class InvalidAppointmentStateError(AppointmentError):
    pass


REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class AppointmentService:
    """Enforce appointment rules over structured SQLite data."""

    def __init__(
        self,
        database: Database | None = None,
        *,
        clock: Callable[[], datetime] = datetime.now,
        reference_factory: Callable[[], str] | None = None,
    ) -> None:
        self.database = database or Database()
        self._clock = clock
        self._reference_factory = reference_factory or self._new_reference
        self.doctors = DoctorRepository()
        self.availability = AvailabilityRepository()
        self.appointments = AppointmentRepository()
        self.database.initialize()

    @staticmethod
    def _new_reference() -> str:
        return "APT-" + "".join(
            secrets.choice(REFERENCE_ALPHABET) for _ in range(6)
        )

    def list_specialities(self) -> list[str]:
        with self.database.connect() as connection:
            return self.doctors.specialities(connection)

    def search_doctors(
        self,
        *,
        speciality: str | None = None,
        location: str | None = None,
        consultation_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        if consultation_mode not in {None, "clinic", "video"}:
            raise AppointmentValidationError("Consultation mode is invalid.")
        for value, label in ((speciality, "Speciality"), (location, "Location")):
            if value is not None and (not value.strip() or len(value) > 80):
                raise AppointmentValidationError(f"{label} is invalid.")
        with self.database.connect() as connection:
            return self.doctors.search(
                connection,
                speciality=speciality.strip() if speciality else None,
                location=location.strip() if location else None,
                consultation_mode=consultation_mode,
            )

    def get_doctor(self, doctor_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            doctor = self.doctors.get_active(connection, doctor_id.strip().upper())
        if doctor is None:
            raise DoctorNotFoundError("The requested active doctor was not found.")
        return doctor

    def get_available_slots(
        self,
        doctor_id: str,
        appointment_date: date,
    ) -> list[dict[str, Any]]:
        doctor = self.get_doctor(doctor_id)
        if appointment_date < self._clock().date():
            raise AppointmentValidationError("Past availability cannot be requested.")
        with self.database.connect() as connection:
            return self.availability.list_available(
                connection,
                doctor["doctor_id"],
                appointment_date.isoformat(),
            )

    def book(self, request: AppointmentCreateRequest) -> dict[str, Any]:
        now = self._clock()
        self._ensure_future(request.appointment_date, request.start_time, now)
        with self.database.transaction(immediate=True) as connection:
            doctor = self.doctors.get_active(connection, request.doctor_id)
            if doctor is None:
                raise DoctorNotFoundError("The requested active doctor was not found.")
            if request.consultation_mode not in doctor["consultation_modes"]:
                raise AppointmentValidationError(
                    "The selected consultation mode is not offered by this doctor."
                )
            slot = self.availability.get_slot(
                connection,
                request.doctor_id,
                request.appointment_date.isoformat(),
                request.start_time,
            )
            if slot is None:
                raise SlotNotFoundError("The requested slot does not exist.")
            if slot["status"] != "available" or not self.appointments.claim_slot(
                connection, slot["id"]
            ):
                raise SlotUnavailableError("The requested slot is no longer available.")

            reference = self._unique_reference(connection)
            timestamp = now.isoformat(timespec="seconds")
            self.appointments.insert(
                connection,
                {
                    "public_reference": reference,
                    "doctor_id": request.doctor_id,
                    "patient_name": request.patient_name,
                    "patient_phone": request.patient_phone,
                    "patient_age": request.patient_age,
                    "appointment_date": request.appointment_date.isoformat(),
                    "start_time": request.start_time,
                    "end_time": slot["end_time"],
                    "consultation_mode": request.consultation_mode,
                    "reason": request.reason,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            row = self.appointments.find_verified(
                connection, reference, request.patient_phone
            )
            if row is None:
                raise AppointmentError("The appointment could not be verified after booking.")
            return self._serialize_appointment(row)

    def lookup(self, reference: str, patient_phone: str) -> dict[str, Any]:
        verified_reference = normalize_reference(reference)
        verified_phone = normalize_phone(patient_phone)
        with self.database.connect() as connection:
            row = self.appointments.find_verified(
                connection, verified_reference, verified_phone
            )
        if row is None:
            raise AppointmentNotFoundError(
                "No appointment matched that reference and phone number."
            )
        return self._serialize_appointment(row)

    def cancel(self, reference: str, patient_phone: str) -> dict[str, Any]:
        verified_reference = normalize_reference(reference)
        verified_phone = normalize_phone(patient_phone)
        with self.database.transaction(immediate=True) as connection:
            row = self.appointments.find_verified(
                connection, verified_reference, verified_phone
            )
            if row is None:
                raise AppointmentNotFoundError(
                    "No appointment matched that reference and phone number."
                )
            if row["status"] != "confirmed":
                raise InvalidAppointmentStateError(
                    "Only a confirmed appointment can be cancelled."
                )
            updated_at = self._clock().isoformat(timespec="seconds")
            if not self.appointments.set_cancelled(
                connection, row["id"], updated_at
            ):
                raise InvalidAppointmentStateError(
                    "The appointment is no longer confirmed."
                )
            self.appointments.release_slot(
                connection,
                row["doctor_id"],
                row["appointment_date"],
                row["start_time"],
            )
            updated = self.appointments.find_verified(
                connection, verified_reference, verified_phone
            )
            return self._serialize_appointment(updated)

    def reschedule(
        self,
        reference: str,
        request: AppointmentRescheduleRequest,
    ) -> dict[str, Any]:
        verified_reference = normalize_reference(reference)
        now = self._clock()
        self._ensure_future(request.appointment_date, request.start_time, now)
        with self.database.transaction(immediate=True) as connection:
            row = self.appointments.find_verified(
                connection, verified_reference, request.patient_phone
            )
            if row is None:
                raise AppointmentNotFoundError(
                    "No appointment matched that reference and phone number."
                )
            if row["status"] != "confirmed":
                raise InvalidAppointmentStateError(
                    "Only a confirmed appointment can be rescheduled."
                )
            if (
                row["appointment_date"] == request.appointment_date.isoformat()
                and row["start_time"] == request.start_time
            ):
                raise AppointmentValidationError(
                    "The new slot must be different from the current slot."
                )
            destination = self.availability.get_slot(
                connection,
                row["doctor_id"],
                request.appointment_date.isoformat(),
                request.start_time,
            )
            if destination is None:
                raise SlotNotFoundError("The destination slot does not exist.")
            if destination["status"] != "available" or not self.appointments.claim_slot(
                connection, destination["id"]
            ):
                raise SlotUnavailableError(
                    "The destination slot is no longer available."
                )
            updated_at = now.isoformat(timespec="seconds")
            if not self.appointments.move(
                connection,
                row["id"],
                request.appointment_date.isoformat(),
                request.start_time,
                destination["end_time"],
                updated_at,
            ):
                raise InvalidAppointmentStateError(
                    "The appointment could not be rescheduled."
                )
            self.appointments.release_slot(
                connection,
                row["doctor_id"],
                row["appointment_date"],
                row["start_time"],
            )
            updated = self.appointments.find_verified(
                connection, verified_reference, request.patient_phone
            )
            return self._serialize_appointment(updated)

    def _unique_reference(self, connection: sqlite3.Connection) -> str:
        for _ in range(20):
            try:
                reference = normalize_reference(self._reference_factory())
            except (AttributeError, ValueError):
                continue
            exists = connection.execute(
                "SELECT 1 FROM appointments WHERE public_reference = ?",
                (reference,),
            ).fetchone()
            if exists is None:
                return reference
        raise AppointmentError("A unique appointment reference could not be created.")

    @staticmethod
    def _ensure_future(
        appointment_date: date,
        start_time: str,
        now: datetime,
    ) -> None:
        scheduled = datetime.combine(
            appointment_date,
            datetime.strptime(start_time, "%H:%M").time(),
        )
        if scheduled <= now:
            raise AppointmentValidationError("The appointment slot must be in the future.")

    @staticmethod
    def _serialize_appointment(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "status": row["status"],
            "appointment_reference": row["public_reference"],
            "doctor_id": row["doctor_id"],
            "doctor": row["doctor_name"],
            "speciality": row["speciality"],
            "date": row["appointment_date"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "consultation_mode": row["consultation_mode"],
            "clinic": row["clinic"],
            "location": row["location"],
            "patient_name": row["patient_name"],
            "demonstration_data": True,
        }
