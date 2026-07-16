# Doctor appointment system

## Scope and safety

This is a loopback-only demonstration using synthetic doctors and fictional patient details. It schedules demo appointments; it does not diagnose, prescribe, recommend dosage, interpret laboratory reports, provide emergency treatment, take payments, process insurance, or connect to a real hospital system.

Doctor facts and appointment confirmations come only from SQLite through controlled backend tools. Ollama is not used as a source of doctors, qualifications, fees, clinics, availability, or booking success.

## Demo directory

The seed contains 10 fictional doctors, 9 active and 1 inactive test record. It covers General Medicine, Dermatology, Pediatrics, Orthopedics, Gynecology, Cardiology, ENT, and Ophthalmology. Records include a public doctor ID, name, speciality, qualifications, languages, experience, clinic, location, fee, slot length, consultation modes, active state, and an explicit demonstration-data flag.

Active IDs are `DOC-001` through `DOC-009`. The inactive `DOC-010` exists only to verify exclusion. Pune has two active dermatologists: Dr. Neha Sharma at City Care Clinic and Dr. Arjun Mehta at Skin Health Centre. Availability is seeded for the next 21 days, excluding Sundays, at 10:00, 11:00, 14:00, and 16:00.

## Data model

`doctors` uses the public text ID as its primary key and stores JSON arrays for languages and consultation modes. `availability` has a foreign key to the doctor and a unique `(doctor_id, appointment_date, start_time)` key. `appointments` stores a unique public reference, doctor foreign key, minimal fictional patient/contact fields, slot, mode, optional bounded reason, status, and timestamps.

Indexes support active speciality/location search, availability lookup, verified reference+phone lookup, and doctor/slot status checks. SQLite foreign keys are enabled for every connection.

## API

- `GET /api/specialities`
- `GET /api/doctors?speciality=&location=&consultation_mode=`
- `GET /api/doctors/{doctor_id}`
- `GET /api/doctors/{doctor_id}/availability?date=YYYY-MM-DD`
- `POST /api/appointments`
- `GET /api/appointments/{reference}?phone=`
- `POST /api/appointments/{reference}/reschedule`
- `POST /api/appointments/{reference}/cancel`
- `POST /api/chat`
- `POST /api/voice/respond`
- `POST /api/conversation/clear`

REST responses omit internal numeric IDs, patient phone, database paths, stack traces, and raw SQL. Appointment lookup and changes require both the public reference and normalized 10-digit Indian demo mobile number.

## Booking rules

The service validates the public doctor ID, active state, offered consultation mode, patient name, phone, optional age/reason, real slot existence, availability, and future date/time. Booking uses `BEGIN IMMEDIATE` plus a conditional `available → booked` update, so concurrent callers cannot both win.

References use six unambiguous random characters after `APT-`, are fully validated, checked for uniqueness, and retried. Cancellation accepts only confirmed appointments and releases their slot. Rescheduling claims the destination before moving the appointment and releases the original only inside the same successful transaction; rollback preserves the original on failure.

## Controlled tools and dialogue

The allowlist is `search_doctors`, `get_doctor_details`, `get_available_slots`, `book_appointment`, `lookup_appointment`, `reschedule_appointment`, and `cancel_appointment`. Unknown names, raw SQL, and non-object arguments are rejected. REST operations have a 10-second timeout boundary; SQLite also has a bounded busy timeout.

The deterministic Hindi/Hinglish dialogue collects speciality, location, mode, doctor, date, verified slot, fictional name, phone, and explicit confirmation one field at a time. It retains only the current session's bounded workflow state. Completed workflows release unrelated chat and may transition to lookup, reschedule, or cancellation. Voice and typed requests use the same session. Form operations include that session ID so verified results update the same workflow store.

## Privacy lifecycle

Chat history and appointment workflow state are separate, process-local, bounded, expiring stores. **New Conversation** clears both and rotates the browser session ID. Audio is never stored in either memory store. SQLite holds only the minimal demo booking fields; runtime databases and journals are ignored by Git. Removing the configured SQLite file resets demo appointments and causes synthetic data to be recreated lazily.

This design is not a production medical compliance claim. See `privacy.md` for missing production controls.

## Verification recorded on 2026-07-16

The fast suite passed 94 backend tests in 1.117 seconds using injected model fakes, and all 6 frontend Node test files passed. `pip check` reported no broken requirements. Appointment coverage includes concurrent atomic booking, full REST lifecycle, invalid/past/unavailable input, duplicate reference retry, failed-reschedule rollback, medical refusal, typed-to-voice confirmation, session isolation, and clear behavior.

A live local synthetic conversation began with `मुझे कल किसी त्वचा रोग विशेषज्ञ से अपॉइंटमेंट चाहिए।` and booked Dr. Neha Sharma for 2026-07-17 at 16:00 with reference `APT-9L7DY8`. Per-turn HTTP wall times were 127, 4, 7, 3, 5, 6, 6, and 9 ms. Lookup took 2 ms, reschedule to 14:00 took 11 ms, and cancellation took 7 ms. A second booking of the occupied destination returned HTTP 409; a nonexistent 13:00 slot returned HTTP 404. The diagnosis/dosage request was refused and New Conversation returned `cleared=true`.

In the in-app browser, Dermatology + Pune + In person returned the two seeded doctor cards; Dr. Neha Sharma showed four verified times for 2026-07-18. A fictional form booking displayed reference `APT-DJQ9ME`, lookup succeeded, rescheduling from 10:00 to 11:00 updated both confirmation and management views, typed appointment input updated the workflow status, and New Conversation cleared the UI. The browser-native cancellation confirmation could not be completed by automation after its dialog left the controlled tab unresponsive; API, service, and frontend-mock cancellation tests passed.

## Known local limitation

On the validation host, Windows Application Control blocked native modules from the installed PyAV 18.0.0 package. Pure unit/API tests used a process-local `faster_whisper` import stub only where transcription was not exercised. No package was installed, removed, or downgraded. Real microphone-to-Whisper browser validation must be rerun after the host policy permits the existing PyAV modules; this milestone does not claim that blocked run passed.
