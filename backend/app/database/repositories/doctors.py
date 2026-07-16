import json
import sqlite3
from typing import Any


def serialize_doctor(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "doctor_id": row["id"],
        "name": row["name"],
        "speciality": row["speciality"],
        "qualifications": row["qualifications"],
        "languages": json.loads(row["languages"]),
        "experience_years": row["experience_years"],
        "clinic": row["clinic"],
        "location": row["location"],
        "consultation_fee": row["consultation_fee"],
        "slot_duration_minutes": row["slot_duration_minutes"],
        "consultation_modes": json.loads(row["consultation_modes"]),
        "demonstration_data": True,
    }


class DoctorRepository:
    def search(
        self,
        connection: sqlite3.Connection,
        *,
        speciality: str | None = None,
        location: str | None = None,
        consultation_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["active = 1"]
        parameters: list[str] = []
        if speciality:
            clauses.append("lower(speciality) = lower(?)")
            parameters.append(speciality)
        if location:
            clauses.append("lower(location) = lower(?)")
            parameters.append(location)
        if consultation_mode:
            clauses.append("consultation_modes LIKE ?")
            parameters.append(f'%"{consultation_mode}"%')
        rows = connection.execute(
            f"SELECT * FROM doctors WHERE {' AND '.join(clauses)} ORDER BY speciality, name",
            parameters,
        ).fetchall()
        return [serialize_doctor(row) for row in rows]

    def get_active(
        self,
        connection: sqlite3.Connection,
        doctor_id: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM doctors WHERE id = ? AND active = 1",
            (doctor_id,),
        ).fetchone()
        return serialize_doctor(row) if row else None

    def specialities(self, connection: sqlite3.Connection) -> list[str]:
        rows = connection.execute(
            "SELECT DISTINCT speciality FROM doctors WHERE active = 1 ORDER BY speciality"
        ).fetchall()
        return [row["speciality"] for row in rows]
