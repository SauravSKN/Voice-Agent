import sqlite3
from typing import Any


class AppointmentRepository:
    @staticmethod
    def claim_slot(connection: sqlite3.Connection, slot_id: int) -> bool:
        cursor = connection.execute(
            "UPDATE availability SET status = 'booked' WHERE id = ? AND status = 'available'",
            (slot_id,),
        )
        return cursor.rowcount == 1

    @staticmethod
    def release_slot(
        connection: sqlite3.Connection,
        doctor_id: str,
        appointment_date: str,
        start_time: str,
    ) -> None:
        connection.execute(
            """
            UPDATE availability SET status = 'available'
            WHERE doctor_id = ? AND appointment_date = ? AND start_time = ?
              AND status = 'booked'
            """,
            (doctor_id, appointment_date, start_time),
        )

    @staticmethod
    def insert(
        connection: sqlite3.Connection,
        values: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO appointments (
                public_reference, doctor_id, patient_name, patient_phone,
                patient_age, appointment_date, start_time, end_time,
                consultation_mode, reason, status, created_at, updated_at
            ) VALUES (
                :public_reference, :doctor_id, :patient_name, :patient_phone,
                :patient_age, :appointment_date, :start_time, :end_time,
                :consultation_mode, :reason, 'confirmed', :created_at, :updated_at
            )
            """,
            values,
        )

    @staticmethod
    def find_verified(
        connection: sqlite3.Connection,
        reference: str,
        phone: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT a.*, d.name AS doctor_name, d.speciality, d.clinic, d.location
            FROM appointments a JOIN doctors d ON d.id = a.doctor_id
            WHERE a.public_reference = ? AND a.patient_phone = ?
            """,
            (reference, phone),
        ).fetchone()

    @staticmethod
    def set_cancelled(
        connection: sqlite3.Connection,
        appointment_id: int,
        updated_at: str,
    ) -> bool:
        cursor = connection.execute(
            """
            UPDATE appointments SET status = 'cancelled', updated_at = ?
            WHERE id = ? AND status = 'confirmed'
            """,
            (updated_at, appointment_id),
        )
        return cursor.rowcount == 1

    @staticmethod
    def move(
        connection: sqlite3.Connection,
        appointment_id: int,
        appointment_date: str,
        start_time: str,
        end_time: str,
        updated_at: str,
    ) -> bool:
        cursor = connection.execute(
            """
            UPDATE appointments
            SET appointment_date = ?, start_time = ?, end_time = ?, updated_at = ?
            WHERE id = ? AND status = 'confirmed'
            """,
            (appointment_date, start_time, end_time, updated_at, appointment_id),
        )
        return cursor.rowcount == 1
