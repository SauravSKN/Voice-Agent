import sqlite3
from typing import Any


class AvailabilityRepository:
    def list_available(
        self,
        connection: sqlite3.Connection,
        doctor_id: str,
        appointment_date: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT start_time, end_time, status
            FROM availability
            WHERE doctor_id = ? AND appointment_date = ? AND status = 'available'
            ORDER BY start_time
            """,
            (doctor_id, appointment_date),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_slot(
        self,
        connection: sqlite3.Connection,
        doctor_id: str,
        appointment_date: str,
        start_time: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM availability
            WHERE doctor_id = ? AND appointment_date = ? AND start_time = ?
            """,
            (doctor_id, appointment_date, start_time),
        ).fetchone()
