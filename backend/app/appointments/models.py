import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


DOCTOR_ID_PATTERN = re.compile(r"^DOC-[0-9]{3}$")
REFERENCE_PATTERN = re.compile(r"^APT-[A-Z0-9]{6}$")
TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def normalize_phone(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Patient phone must be text.")
    digits = re.sub(r"[\s()-]", "", value.strip())
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if not re.fullmatch(r"[6-9][0-9]{9}", digits):
        raise ValueError("Patient phone must be a valid 10-digit Indian mobile number.")
    return digits


def normalize_reference(value: str) -> str:
    reference = value.strip().upper()
    if not REFERENCE_PATTERN.fullmatch(reference):
        raise ValueError("Appointment reference must look like APT-8H2K5M.")
    return reference


def normalize_time(value: str) -> str:
    candidate = value.strip()
    if not TIME_PATTERN.fullmatch(candidate):
        raise ValueError("Time must use 24-hour HH:MM format.")
    datetime.strptime(candidate, "%H:%M")
    return candidate


def normalize_session_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not SESSION_ID_PATTERN.fullmatch(candidate):
        raise ValueError("Session ID is invalid.")
    return candidate


class AppointmentCreateRequest(BaseModel):
    doctor_id: str
    patient_name: str = Field(min_length=2, max_length=80)
    patient_phone: str
    patient_age: int | None = Field(default=None, ge=0, le=120)
    appointment_date: date
    start_time: str
    consultation_mode: Literal["clinic", "video"]
    reason: str | None = Field(default=None, max_length=300)
    session_id: str | None = None

    @field_validator("doctor_id")
    @classmethod
    def validate_doctor_id(cls, value: str) -> str:
        candidate = value.strip().upper()
        if not DOCTOR_ID_PATTERN.fullmatch(candidate):
            raise ValueError("Doctor ID is invalid.")
        return candidate

    @field_validator("patient_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        candidate = " ".join(value.split())
        if any(character.isdigit() for character in candidate):
            raise ValueError("Patient name must not contain numbers.")
        return candidate

    @field_validator("patient_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, value: str) -> str:
        return normalize_time(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = " ".join(value.split())
        return candidate or None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        return normalize_session_id(value)


class AppointmentRescheduleRequest(BaseModel):
    patient_phone: str
    appointment_date: date
    start_time: str
    session_id: str | None = None

    @field_validator("patient_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, value: str) -> str:
        return normalize_time(value)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        return normalize_session_id(value)


class AppointmentCancelRequest(BaseModel):
    patient_phone: str
    session_id: str | None = None

    @field_validator("patient_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        return normalize_session_id(value)


class DoctorResponse(BaseModel):
    doctor_id: str
    name: str
    speciality: str
    qualifications: str
    languages: list[str]
    experience_years: int
    clinic: str
    location: str
    consultation_fee: int
    slot_duration_minutes: int
    consultation_modes: list[str]
    demonstration_data: bool = True


class DoctorListResponse(BaseModel):
    doctors: list[DoctorResponse]
    demonstration_data: bool = True


class SpecialityListResponse(BaseModel):
    specialities: list[str]
    demonstration_data: bool = True


class AvailabilitySlotResponse(BaseModel):
    start_time: str
    end_time: str
    status: str


class AvailabilityResponse(BaseModel):
    doctor_id: str
    date: date
    slots: list[AvailabilitySlotResponse]
    demonstration_data: bool = True


class AppointmentResponse(BaseModel):
    status: Literal["confirmed", "cancelled"]
    appointment_reference: str
    doctor_id: str
    doctor: str
    speciality: str
    date: date
    start_time: str
    end_time: str
    consultation_mode: str
    clinic: str
    location: str
    patient_name: str
    demonstration_data: bool = True
