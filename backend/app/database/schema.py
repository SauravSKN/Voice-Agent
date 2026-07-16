SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS doctors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    speciality TEXT NOT NULL,
    qualifications TEXT NOT NULL,
    languages TEXT NOT NULL,
    experience_years INTEGER NOT NULL CHECK (experience_years >= 0),
    clinic TEXT NOT NULL,
    location TEXT NOT NULL,
    consultation_fee INTEGER NOT NULL CHECK (consultation_fee >= 0),
    slot_duration_minutes INTEGER NOT NULL CHECK (slot_duration_minutes BETWEEN 10 AND 180),
    consultation_modes TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    demonstration_data INTEGER NOT NULL DEFAULT 1 CHECK (demonstration_data = 1)
);

CREATE INDEX IF NOT EXISTS idx_doctors_speciality_location
    ON doctors (speciality, location, active);

CREATE TABLE IF NOT EXISTS availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id TEXT NOT NULL,
    appointment_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available', 'booked', 'blocked')),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    UNIQUE (doctor_id, appointment_date, start_time)
);

CREATE INDEX IF NOT EXISTS idx_availability_lookup
    ON availability (doctor_id, appointment_date, status, start_time);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_reference TEXT NOT NULL UNIQUE,
    doctor_id TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL,
    patient_age INTEGER NULL CHECK (patient_age IS NULL OR patient_age BETWEEN 0 AND 120),
    appointment_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    consultation_mode TEXT NOT NULL CHECK (consultation_mode IN ('clinic', 'video')),
    reason TEXT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed'
        CHECK (status IN ('confirmed', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (doctor_id) REFERENCES doctors(id)
);

CREATE INDEX IF NOT EXISTS idx_appointments_reference_phone
    ON appointments (public_reference, patient_phone);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_slot
    ON appointments (doctor_id, appointment_date, start_time, status);
"""
