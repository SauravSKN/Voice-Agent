import json
import sqlite3
from datetime import date, datetime, time, timedelta


DEMO_DOCTORS = (
    ("DOC-001", "Dr. Neha Sharma", "Dermatology", "MBBS, MD Dermatology", ("Hindi", "English", "Marathi"), 12, "City Care Clinic", "Pune", 800, 30, ("clinic", "video"), 1),
    ("DOC-002", "Dr. Arjun Mehta", "Dermatology", "MBBS, DNB Dermatology", ("Hindi", "English"), 9, "Skin Health Centre", "Pune", 700, 30, ("clinic", "video"), 1),
    ("DOC-003", "Dr. Asha Verma", "General Medicine", "MBBS, MD Medicine", ("Hindi", "English"), 15, "Sahyadri Family Clinic", "Pune", 600, 20, ("clinic", "video"), 1),
    ("DOC-004", "Dr. Kabir Rao", "Pediatrics", "MBBS, MD Pediatrics", ("Hindi", "English", "Kannada"), 11, "Little Steps Clinic", "Pune", 650, 30, ("clinic",), 1),
    ("DOC-005", "Dr. Meera Kulkarni", "Orthopedics", "MBBS, MS Orthopedics", ("Hindi", "English", "Marathi"), 14, "Mobility Care Clinic", "Mumbai", 900, 30, ("clinic", "video"), 1),
    ("DOC-006", "Dr. Kavya Iyer", "Gynecology", "MBBS, MS Obstetrics and Gynecology", ("Hindi", "English", "Tamil"), 13, "Aarogya Women's Clinic", "Pune", 850, 30, ("clinic", "video"), 1),
    ("DOC-007", "Dr. Rohan Sen", "Cardiology", "MBBS, DM Cardiology", ("Hindi", "English", "Bengali"), 18, "Heartline Clinic", "Delhi", 1200, 30, ("clinic",), 1),
    ("DOC-008", "Dr. Farah Khan", "ENT", "MBBS, MS ENT", ("Hindi", "English", "Urdu"), 10, "Clear Hearing Clinic", "Pune", 700, 20, ("clinic", "video"), 1),
    ("DOC-009", "Dr. Vikram Joshi", "Ophthalmology", "MBBS, MS Ophthalmology", ("Hindi", "English", "Marathi"), 16, "Vision First Clinic", "Pune", 750, 20, ("clinic",), 1),
    ("DOC-010", "Dr. Demo Inactive", "General Medicine", "MBBS", ("Hindi",), 5, "Closed Demo Clinic", "Pune", 400, 20, ("clinic",), 0),
)


def seed_demo_data(connection: sqlite3.Connection, today: date | None = None) -> None:
    for doctor in DEMO_DOCTORS:
        connection.execute(
            """
            INSERT OR IGNORE INTO doctors (
                id, name, speciality, qualifications, languages,
                experience_years, clinic, location, consultation_fee,
                slot_duration_minutes, consultation_modes, active,
                demonstration_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (*doctor[:4], json.dumps(doctor[4], ensure_ascii=False), *doctor[5:10], json.dumps(doctor[10]), doctor[11]),
        )

    start_date = today or date.today()
    active_doctors = connection.execute(
        "SELECT id, slot_duration_minutes FROM doctors WHERE active = 1"
    ).fetchall()
    for offset in range(1, 22):
        slot_date = start_date + timedelta(days=offset)
        if slot_date.weekday() == 6:
            continue
        for doctor in active_doctors:
            for slot_start in (time(10, 0), time(11, 0), time(14, 0), time(16, 0)):
                start_dt = datetime.combine(slot_date, slot_start)
                end_dt = start_dt + timedelta(minutes=doctor["slot_duration_minutes"])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO availability (
                        doctor_id, appointment_date, start_time, end_time, status
                    ) VALUES (?, ?, ?, ?, 'available')
                    """,
                    (
                        doctor["id"],
                        slot_date.isoformat(),
                        start_dt.strftime("%H:%M"),
                        end_dt.strftime("%H:%M"),
                    ),
                )
