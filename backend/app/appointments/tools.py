from datetime import date
from typing import Any, Callable

from app.appointments.models import (
    AppointmentCreateRequest,
    AppointmentRescheduleRequest,
)
from app.appointments.service import AppointmentService


class UnknownAppointmentToolError(ValueError):
    pass


class AppointmentTools:
    """Strict tool allowlist; no raw SQL or arbitrary callable is accepted."""

    timeout_seconds = 10.0

    def __init__(self, service: AppointmentService | None = None) -> None:
        self.service = service or AppointmentService()
        self._tools: dict[str, Callable[..., Any]] = {
            "search_doctors": self.search_doctors,
            "get_doctor_details": self.get_doctor_details,
            "get_available_slots": self.get_available_slots,
            "book_appointment": self.book_appointment,
            "lookup_appointment": self.lookup_appointment,
            "reschedule_appointment": self.reschedule_appointment,
            "cancel_appointment": self.cancel_appointment,
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownAppointmentToolError("The requested appointment tool is not allowed.")
        if not isinstance(arguments, dict):
            raise ValueError("Appointment tool arguments must be an object.")
        return tool(**arguments)

    def search_doctors(self, **filters: Any) -> list[dict[str, Any]]:
        return self.service.search_doctors(**filters)

    def get_doctor_details(self, doctor_id: str) -> dict[str, Any]:
        return self.service.get_doctor(doctor_id)

    def get_available_slots(
        self,
        doctor_id: str,
        appointment_date: str,
    ) -> list[dict[str, Any]]:
        return self.service.get_available_slots(
            doctor_id,
            date.fromisoformat(appointment_date),
        )

    def book_appointment(self, **values: Any) -> dict[str, Any]:
        return self.service.book(AppointmentCreateRequest(**values))

    def lookup_appointment(
        self,
        appointment_reference: str,
        patient_phone: str,
    ) -> dict[str, Any]:
        return self.service.lookup(appointment_reference, patient_phone)

    def reschedule_appointment(
        self,
        appointment_reference: str,
        **values: Any,
    ) -> dict[str, Any]:
        return self.service.reschedule(
            appointment_reference,
            AppointmentRescheduleRequest(**values),
        )

    def cancel_appointment(
        self,
        appointment_reference: str,
        patient_phone: str,
    ) -> dict[str, Any]:
        return self.service.cancel(appointment_reference, patient_phone)
