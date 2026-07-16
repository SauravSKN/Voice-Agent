import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from app.appointments.models import normalize_phone
from app.appointments.service import AppointmentError
from app.appointments.tools import AppointmentTools
from app.memory.appointment import AppointmentWorkflowStore


SPECIALITY_ALIASES = {
    "Dermatology": ("त्वचा", "चर्म", "skin", "dermatolog"),
    "General Medicine": ("सामान्य चिकित्सा", "general medicine", "physician"),
    "Pediatrics": ("बाल रोग", "बच्च", "pediatric"),
    "Orthopedics": ("हड्डी", "जोड़", "orthopedic"),
    "Gynecology": ("स्त्री रोग", "महिला रोग", "gyneco"),
    "Cardiology": ("हृदय", "दिल के डॉक्टर", "cardiolog"),
    "ENT": ("कान नाक गला", "ईएनटी", "ent"),
    "Ophthalmology": ("आँख", "आंख", "नेत्र", "ophthalm", "eye doctor"),
}
LOCATION_ALIASES = {
    "Pune": ("पुणे", "pune"),
    "Mumbai": ("मुंबई", "mumbai"),
    "Delhi": ("दिल्ली", "delhi"),
}
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER_WORDS = {
    "एक": 1,
    "दो": 2,
    "तीन": 3,
    "चार": 4,
    "पाँच": 5,
    "पांच": 5,
    "छह": 6,
    "सात": 7,
    "आठ": 8,
    "नौ": 9,
    "दस": 10,
    "ग्यारह": 11,
    "बारह": 12,
}


@dataclass(frozen=True)
class AppointmentDialogueResult:
    response: str
    appointment_state: dict[str, Any]
    appointment: dict[str, Any] | None
    generation_time_ms: int


class AppointmentAssistant:
    """Deterministic orchestration around verified appointment tools."""

    def __init__(
        self,
        tools: AppointmentTools | None = None,
        store: AppointmentWorkflowStore | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.tools = tools or AppointmentTools()
        self.store = store or AppointmentWorkflowStore()
        self._today = today

    def clear(self, session_id: str) -> bool:
        return self.store.clear(session_id)

    @classmethod
    def is_relevant(cls, user_text: str) -> bool:
        lowered = " ".join(user_text.strip().split()).lower()
        return bool(
            cls._detect_intent(lowered)
            or cls._medical_safety_response(lowered)
        )

    def record_verified_appointment(
        self,
        session_id: str,
        appointment: dict[str, Any],
        *,
        phase: str,
    ) -> dict[str, Any]:
        state = {
            "intent": "manage_appointment",
            "phase": phase,
            "appointment_reference": appointment["appointment_reference"],
            "appointment": appointment,
        }
        return self.store.replace(session_id, state)

    def handle(
        self,
        user_text: str,
        session_id: str,
    ) -> AppointmentDialogueResult | None:
        started = time.perf_counter()
        text = " ".join(user_text.strip().split())
        lowered = text.lower()
        state = self.store.get(session_id)

        safety_response = self._medical_safety_response(lowered)
        if safety_response:
            return self._result(
                started,
                safety_response,
                state,
                state.get("appointment"),
            )

        detected_intent = self._detect_intent(lowered)
        terminal_phase = state.get("phase") in {
            "confirmed",
            "complete",
            "cancelled",
        }
        if state and (
            terminal_phase
            or (
                detected_intent
                and detected_intent != state.get("intent")
            )
        ):
            previous_reference = state.get("appointment_reference")
            if detected_intent is None:
                self.store.clear(session_id)
                return None
            state = {"intent": detected_intent, "phase": "collecting"}
            if previous_reference and detected_intent in {
                "lookup_appointment",
                "cancel_appointment",
                "reschedule_appointment",
            }:
                state["appointment_reference"] = previous_reference

        if not state:
            intent = detected_intent
            if intent is None:
                return None
            state = {"intent": intent, "phase": "collecting"}

        intent = state.get("intent")
        if intent == "book_appointment":
            return self._handle_booking(started, text, lowered, session_id, state)
        if intent == "lookup_appointment":
            return self._handle_lookup(started, text, session_id, state)
        if intent == "cancel_appointment":
            return self._handle_cancel(started, text, lowered, session_id, state)
        if intent == "reschedule_appointment":
            return self._handle_reschedule(started, text, lowered, session_id, state)
        self.store.clear(session_id)
        return None

    def _handle_booking(
        self,
        started: float,
        text: str,
        lowered: str,
        session_id: str,
        state: dict[str, Any],
    ) -> AppointmentDialogueResult:
        if state.get("phase") == "awaiting_confirmation":
            if self._is_negative(lowered):
                self.store.clear(session_id)
                return self._result(started, "ठीक है, बुकिंग नहीं की गई।", {}, None)
            if not self._is_affirmative(lowered):
                return self._save_result(
                    started,
                    session_id,
                    state,
                    "कृपया हाँ कहकर बुकिंग की पुष्टि करें, या नहीं कहकर रोकें।",
                )
            try:
                appointment = self.tools.execute(
                    "book_appointment",
                    {
                        "doctor_id": state["doctor_id"],
                        "patient_name": state["patient_name"],
                        "patient_phone": state["patient_phone"],
                        "appointment_date": state["appointment_date"],
                        "start_time": state["start_time"],
                        "consultation_mode": state["consultation_mode"],
                        "reason": state.get("reason"),
                        "session_id": session_id,
                    },
                )
            except (AppointmentError, ValueError) as error:
                state["phase"] = "collecting"
                state.pop("start_time", None)
                state.pop("available_slots", None)
                return self._save_result(
                    started,
                    session_id,
                    state,
                    f"बुकिंग पूरी नहीं हुई: {error} कृपया दूसरा उपलब्ध समय चुनें।",
                )
            confirmed_state = {
                "intent": "book_appointment",
                "phase": "confirmed",
                "appointment_reference": appointment["appointment_reference"],
                "appointment": appointment,
            }
            self.store.replace(session_id, confirmed_state)
            response = (
                f"आपकी अपॉइंटमेंट {appointment['doctor']} के साथ "
                f"{appointment['date']} को {appointment['start_time']} बजे बुक हो गई है। "
                f"संदर्भ नंबर {appointment['appointment_reference']} है।"
            )
            return self._result(started, response, confirmed_state, appointment)

        self._merge_common_fields(text, lowered, state)
        awaiting = state.get("awaiting")
        if awaiting == "patient_name" and "patient_name" not in state:
            name = self._extract_name(text)
            if name:
                state["patient_name"] = name
        if awaiting == "patient_phone" and "patient_phone" not in state:
            phone = self._extract_phone(text)
            if phone:
                state["patient_phone"] = phone

        if not state.get("speciality"):
            state["awaiting"] = "speciality"
            return self._save_result(
                started, session_id, state, "आपको किस विशेषज्ञ डॉक्टर की आवश्यकता है?"
            )
        if not state.get("location"):
            state["awaiting"] = "location"
            return self._save_result(
                started, session_id, state, "कृपया शहर या क्लिनिक स्थान बताइए।"
            )
        if not state.get("consultation_mode"):
            state["awaiting"] = "consultation_mode"
            return self._save_result(
                started,
                session_id,
                state,
                "आप क्लिनिक विज़िट चाहते हैं या वीडियो परामर्श?",
            )

        if not state.get("doctor_id"):
            selected = self._select_doctor(text, state.get("doctor_options", []))
            if selected:
                state["doctor_id"] = selected["doctor_id"]
                state["doctor"] = selected
            else:
                doctors = self.tools.execute(
                    "search_doctors",
                    {
                        "speciality": state["speciality"],
                        "location": state["location"],
                        "consultation_mode": state["consultation_mode"],
                    },
                )
                state["doctor_options"] = doctors
                state["awaiting"] = "doctor_id"
                if not doctors:
                    return self._save_result(
                        started,
                        session_id,
                        state,
                        "इन फ़िल्टर के लिए कोई सक्रिय डेमो डॉक्टर उपलब्ध नहीं है। कृपया स्थान या परामर्श प्रकार बदलें।",
                    )
                summary = "; ".join(
                    f"{item['doctor_id']}, {item['name']}, {item['clinic']}, फीस {item['consultation_fee']} रुपये"
                    for item in doctors[:5]
                )
                return self._save_result(
                    started,
                    session_id,
                    state,
                    f"उपलब्ध डेमो डॉक्टर: {summary}। कृपया डॉक्टर चुनें।",
                )

        if not state.get("appointment_date"):
            state["awaiting"] = "appointment_date"
            return self._save_result(
                started, session_id, state, "आप किस तारीख की अपॉइंटमेंट चाहते हैं?"
            )

        slots = self.tools.execute(
            "get_available_slots",
            {
                "doctor_id": state["doctor_id"],
                "appointment_date": state["appointment_date"],
            },
        )
        state["available_slots"] = slots
        if not slots:
            state.pop("appointment_date", None)
            state.pop("start_time", None)
            state["awaiting"] = "appointment_date"
            return self._save_result(
                started,
                session_id,
                state,
                "उस तारीख पर कोई सत्यापित स्लॉट उपलब्ध नहीं है। कृपया दूसरी तारीख चुनें।",
            )
        valid_times = {slot["start_time"] for slot in slots}
        if state.get("start_time") not in valid_times:
            state.pop("start_time", None)
            state["awaiting"] = "start_time"
            times = ", ".join(sorted(valid_times))
            return self._save_result(
                started,
                session_id,
                state,
                f"उपलब्ध समय {times} हैं। कृपया एक समय चुनें।",
            )
        if not state.get("patient_name"):
            state["awaiting"] = "patient_name"
            return self._save_result(
                started,
                session_id,
                state,
                "बुकिंग के लिए कृपया मरीज का नाम बताइए।",
            )
        if not state.get("patient_phone"):
            state["awaiting"] = "patient_phone"
            return self._save_result(
                started,
                session_id,
                state,
                "कृपया 10 अंकों का मोबाइल नंबर बताइए।",
            )

        state["phase"] = "awaiting_confirmation"
        state["awaiting"] = "confirmation"
        doctor = state["doctor"]
        return self._save_result(
            started,
            session_id,
            state,
            f"कृपया पुष्टि करें: {doctor['name']}, {state['appointment_date']}, {state['start_time']} बजे, {state['consultation_mode']} परामर्श। क्या बुक कर दूँ?",
        )

    def _handle_lookup(
        self,
        started: float,
        text: str,
        session_id: str,
        state: dict[str, Any],
    ) -> AppointmentDialogueResult:
        self._merge_reference_phone(text, state)
        if not state.get("appointment_reference"):
            state["awaiting"] = "appointment_reference"
            return self._save_result(started, session_id, state, "कृपया अपॉइंटमेंट संदर्भ नंबर बताइए।")
        if not state.get("patient_phone"):
            state["awaiting"] = "patient_phone"
            return self._save_result(started, session_id, state, "सत्यापन के लिए 10 अंकों का मोबाइल नंबर बताइए।")
        try:
            appointment = self.tools.execute(
                "lookup_appointment",
                {
                    "appointment_reference": state["appointment_reference"],
                    "patient_phone": state["patient_phone"],
                },
            )
        except (AppointmentError, ValueError):
            self.store.clear(session_id)
            return self._result(started, "उस संदर्भ और मोबाइल नंबर से कोई अपॉइंटमेंट नहीं मिली।", {}, None)
        state = {"intent": "lookup_appointment", "phase": "complete", "appointment": appointment}
        self.store.replace(session_id, state)
        return self._result(
            started,
            f"अपॉइंटमेंट {appointment['status']} है। {appointment['doctor']}, {appointment['date']}, {appointment['start_time']} बजे।",
            state,
            appointment,
        )

    def _handle_cancel(
        self,
        started: float,
        text: str,
        lowered: str,
        session_id: str,
        state: dict[str, Any],
    ) -> AppointmentDialogueResult:
        self._merge_reference_phone(text, state)
        if not state.get("appointment_reference"):
            state["awaiting"] = "appointment_reference"
            return self._save_result(started, session_id, state, "कृपया रद्द करने वाली अपॉइंटमेंट का संदर्भ नंबर बताइए।")
        if not state.get("patient_phone"):
            state["awaiting"] = "patient_phone"
            return self._save_result(started, session_id, state, "सत्यापन के लिए 10 अंकों का मोबाइल नंबर बताइए।")
        if state.get("phase") != "awaiting_confirmation":
            state["phase"] = "awaiting_confirmation"
            return self._save_result(started, session_id, state, f"क्या आप {state['appointment_reference']} को रद्द करने की पुष्टि करते हैं?")
        if self._is_negative(lowered):
            self.store.clear(session_id)
            return self._result(started, "ठीक है, अपॉइंटमेंट रद्द नहीं की गई।", {}, None)
        if not self._is_affirmative(lowered):
            return self._save_result(started, session_id, state, "कृपया हाँ या नहीं में पुष्टि करें।")
        try:
            appointment = self.tools.execute(
                "cancel_appointment",
                {
                    "appointment_reference": state["appointment_reference"],
                    "patient_phone": state["patient_phone"],
                },
            )
        except (AppointmentError, ValueError) as error:
            return self._save_result(started, session_id, state, f"अपॉइंटमेंट रद्द नहीं हुई: {error}")
        complete = {"intent": "cancel_appointment", "phase": "cancelled", "appointment": appointment}
        self.store.replace(session_id, complete)
        return self._result(started, f"अपॉइंटमेंट {appointment['appointment_reference']} रद्द हो गई है।", complete, appointment)

    def _handle_reschedule(
        self,
        started: float,
        text: str,
        lowered: str,
        session_id: str,
        state: dict[str, Any],
    ) -> AppointmentDialogueResult:
        self._merge_reference_phone(text, state)
        if not state.get("appointment_reference"):
            state["awaiting"] = "appointment_reference"
            return self._save_result(started, session_id, state, "कृपया अपॉइंटमेंट संदर्भ नंबर बताइए।")
        if not state.get("patient_phone"):
            state["awaiting"] = "patient_phone"
            return self._save_result(started, session_id, state, "सत्यापन के लिए 10 अंकों का मोबाइल नंबर बताइए।")
        if not state.get("current_appointment"):
            try:
                current = self.tools.execute(
                    "lookup_appointment",
                    {
                        "appointment_reference": state["appointment_reference"],
                        "patient_phone": state["patient_phone"],
                    },
                )
            except (AppointmentError, ValueError):
                self.store.clear(session_id)
                return self._result(started, "उस संदर्भ और मोबाइल नंबर से कोई अपॉइंटमेंट नहीं मिली।", {}, None)
            if current["status"] != "confirmed":
                self.store.clear(session_id)
                return self._result(started, "केवल पुष्टि की गई अपॉइंटमेंट बदली जा सकती है।", {}, current)
            state["current_appointment"] = current
            state["doctor_id"] = current["doctor_id"]

        if state.get("phase") == "awaiting_confirmation":
            if self._is_negative(lowered):
                self.store.clear(session_id)
                return self._result(started, "ठीक है, मूल अपॉइंटमेंट में कोई बदलाव नहीं किया गया।", {}, None)
            if not self._is_affirmative(lowered):
                return self._save_result(started, session_id, state, "कृपया हाँ या नहीं में पुष्टि करें।")
            try:
                appointment = self.tools.execute(
                    "reschedule_appointment",
                    {
                        "appointment_reference": state["appointment_reference"],
                        "patient_phone": state["patient_phone"],
                        "appointment_date": state["appointment_date"],
                        "start_time": state["start_time"],
                    },
                )
            except (AppointmentError, ValueError) as error:
                state["phase"] = "collecting"
                state.pop("start_time", None)
                return self._save_result(started, session_id, state, f"समय नहीं बदला गया: {error} मूल अपॉइंटमेंट सुरक्षित है।")
            complete = {"intent": "reschedule_appointment", "phase": "confirmed", "appointment": appointment}
            self.store.replace(session_id, complete)
            return self._result(started, f"अपॉइंटमेंट अब {appointment['date']} को {appointment['start_time']} बजे है।", complete, appointment)

        parsed_date = self._extract_date(lowered)
        if parsed_date:
            state["appointment_date"] = parsed_date
        parsed_time = self._extract_time(lowered)
        if parsed_time:
            state["start_time"] = parsed_time
        if not state.get("appointment_date"):
            return self._save_result(started, session_id, state, "नई तारीख बताइए।")
        slots = self.tools.execute(
            "get_available_slots",
            {"doctor_id": state["doctor_id"], "appointment_date": state["appointment_date"]},
        )
        state["available_slots"] = slots
        valid_times = {slot["start_time"] for slot in slots}
        if state.get("start_time") not in valid_times:
            state.pop("start_time", None)
            return self._save_result(started, session_id, state, f"उपलब्ध नए समय: {', '.join(sorted(valid_times)) or 'कोई नहीं'}। कृपया समय चुनें।")
        state["phase"] = "awaiting_confirmation"
        return self._save_result(started, session_id, state, f"क्या अपॉइंटमेंट को {state['appointment_date']} के {state['start_time']} बजे पर बदल दूँ?")

    def _merge_common_fields(self, text: str, lowered: str, state: dict[str, Any]) -> None:
        speciality = self._extract_speciality(lowered)
        if speciality:
            state["speciality"] = speciality
        location = self._extract_location(lowered)
        if location:
            state["location"] = location
        mode = self._extract_mode(lowered)
        if mode:
            state["consultation_mode"] = mode
        appointment_date = self._extract_date(lowered)
        if appointment_date:
            state["appointment_date"] = appointment_date
        start_time = self._extract_time(lowered)
        if start_time:
            state["start_time"] = start_time
        selected = self._select_doctor(text, state.get("doctor_options", []))
        if selected:
            state["doctor_id"] = selected["doctor_id"]
            state["doctor"] = selected

    @staticmethod
    def _detect_intent(text: str) -> str | None:
        if any(word in text for word in ("रद्द", "cancel")):
            return "cancel_appointment"
        if any(word in text for word in ("reschedule", "बदल", "दूसरा समय")):
            return "reschedule_appointment"
        if any(word in text for word in ("lookup", "स्थिति", "देखना", "कहाँ है")) and any(
            word in text for word in ("appointment", "अपॉइंटमेंट", "apt-")
        ):
            return "lookup_appointment"
        if any(word in text for word in ("appointment", "अपॉइंटमेंट", "बुक", "doctor", "डॉक्टर")):
            return "book_appointment"
        if any(alias in text for aliases in SPECIALITY_ALIASES.values() for alias in aliases):
            return "book_appointment"
        return None

    @staticmethod
    def _medical_safety_response(text: str) -> str | None:
        emergency = ("सीने में दर्द", "सांस नहीं", "साँस नहीं", "बेहोश", "बहुत खून", "आत्महत्या")
        if any(term in text for term in emergency):
            return "यह आपात स्थिति हो सकती है। कृपया तुरंत स्थानीय आपातकालीन सेवा या नज़दीकी अस्पताल से संपर्क करें; मैं निदान या उपचार नहीं कर सकता।"
        medical = ("दवा", "खुराक", "डोज", "निदान", "diagnos", "prescri", "लैब रिपोर्ट", "खून की रिपोर्ट")
        if any(term in text for term in medical):
            return "मैं निदान, दवा, खुराक या रिपोर्ट की व्याख्या नहीं कर सकता। मैं उपयुक्त विशेषज्ञ की डेमो अपॉइंटमेंट खोजने में मदद कर सकता हूँ।"
        return None

    @staticmethod
    def _extract_speciality(text: str) -> str | None:
        for speciality, aliases in SPECIALITY_ALIASES.items():
            if any(alias in text for alias in aliases):
                return speciality
        return None

    @staticmethod
    def _extract_location(text: str) -> str | None:
        for location, aliases in LOCATION_ALIASES.items():
            if any(alias in text for alias in aliases):
                return location
        return None

    @staticmethod
    def _extract_mode(text: str) -> str | None:
        if "वीडियो" in text or "video" in text:
            return "video"
        if "क्लिनिक" in text or "clinic" in text or "विज़िट" in text:
            return "clinic"
        return None

    def _extract_date(self, text: str) -> str | None:
        translated = text.translate(DEVANAGARI_DIGITS)
        match = re.search(r"\b(20[0-9]{2}-[01][0-9]-[0-3][0-9])\b", translated)
        if match:
            try:
                return date.fromisoformat(match.group(1)).isoformat()
            except ValueError:
                return None
        if "परसों" in text:
            return (self._today() + timedelta(days=2)).isoformat()
        if "कल" in text or "tomorrow" in text:
            return (self._today() + timedelta(days=1)).isoformat()
        if "आज" in text or "today" in text:
            return self._today().isoformat()
        return None

    @staticmethod
    def _extract_time(text: str) -> str | None:
        translated = text.translate(DEVANAGARI_DIGITS)
        match = re.search(r"(?<![0-9:-])([01]?[0-9]|2[0-3]):([0-5][0-9])(?![0-9:])", translated)
        if not match:
            match = re.search(
                r"\b([01]?[0-9]|2[0-3])(?:\s*(?:बजे|pm|am|सुबह|दोपहर|शाम))",
                translated,
            )
        hour: int | None = None
        minute = 0
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0) if match.lastindex == 2 else 0
        if hour is None:
            for word, value in NUMBER_WORDS.items():
                if word in text and any(token in text for token in ("बजे", "सुबह", "दोपहर", "शाम")):
                    hour = value
                    break
        if hour is None:
            return None
        if ("शाम" in text or "pm" in translated) and hour < 12:
            hour += 12
        elif "दोपहर" in text and hour < 12:
            hour += 12
        elif "सुबह" in text and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _select_doctor(text: str, options: list[dict[str, Any]]) -> dict[str, Any] | None:
        upper = text.upper()
        for option in options:
            if option["doctor_id"] in upper or option["name"].lower() in text.lower():
                return option
        lowered = text.lower()
        if options and any(word in lowered for word in ("पहला", "पहले", "first")):
            return options[0]
        if len(options) > 1 and any(word in lowered for word in ("दूसरा", "दूसरे", "second")):
            return options[1]
        return None

    @staticmethod
    def _extract_name(text: str) -> str | None:
        candidate = re.sub(r"^(?:मेरा नाम|नाम|patient name|my name is)\s*", "", text, flags=re.I)
        candidate = re.sub(r"\s+(?:है|hai)$", "", candidate, flags=re.I).strip(" .।")
        if 2 <= len(candidate) <= 80 and not any(character.isdigit() for character in candidate):
            return candidate
        return None

    @staticmethod
    def _extract_phone(text: str) -> str | None:
        candidate = re.search(r"(?:\+91[\s-]?)?[6-9][0-9\s()-]{8,14}", text.translate(DEVANAGARI_DIGITS))
        if not candidate:
            return None
        try:
            return normalize_phone(candidate.group(0))
        except ValueError:
            return None

    def _merge_reference_phone(self, text: str, state: dict[str, Any]) -> None:
        reference = re.search(r"APT-[A-Z0-9]{6}", text.upper())
        if reference:
            state["appointment_reference"] = reference.group(0)
        phone = self._extract_phone(text)
        if phone:
            state["patient_phone"] = phone

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        return any(word in text for word in ("हाँ", "हां", "जी", "yes", "confirm", "कर दीजिए", "कर दो"))

    @staticmethod
    def _is_negative(text: str) -> bool:
        return any(word in text for word in ("नहीं", "नही", "no", "मत"))

    def _save_result(
        self,
        started: float,
        session_id: str,
        state: dict[str, Any],
        response: str,
    ) -> AppointmentDialogueResult:
        saved = self.store.replace(session_id, state)
        return self._result(started, response, saved, saved.get("appointment"))

    @staticmethod
    def _result(
        started: float,
        response: str,
        state: dict[str, Any],
        appointment: dict[str, Any] | None,
    ) -> AppointmentDialogueResult:
        return AppointmentDialogueResult(
            response=response,
            appointment_state=state,
            appointment=appointment,
            generation_time_ms=round((time.perf_counter() - started) * 1000),
        )
