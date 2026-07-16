const assert = require("node:assert/strict");


class FakeElement {
    constructor(tagName = "DIV") {
        this.tagName = tagName.toUpperCase();
        this.disabled = false;
        this.hidden = false;
        this.listeners = new Map();
        this.children = [];
        this.className = "";
        this.src = "";
        this.textContent = "";
        this.value = "";
        this.currentTime = 0;
        this.min = "";
        this.type = "";
    }

    addEventListener(eventName, listener) {
        this.listeners.set(eventName, listener);
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = children;
        this.textContent = "";
    }

    async click() {
        if (this.disabled) {
            return;
        }
        const listener = this.listeners.get("click");
        if (listener) {
            await listener();
        }
    }

    pause() {}

    load() {}

    async play() {
        const playing = this.listeners.get("playing");
        if (playing) {
            playing();
        }
        const ended = this.listeners.get("ended");
        if (ended) {
            ended();
        }
    }
}


const baseElementIds = [
    "recordButton",
    "uploadButton",
    "status",
    "recordingResult",
    "uploadResult",
    "audioPlayer",
    "transcriptResult",
    "transcriptText",
    "voiceAgentButton",
    "voiceAgentStatus",
    "voiceAgentResult",
    "voiceTranscriptText",
    "voiceResponseText",
    "voiceTiming",
    "responseAudioPlayer",
    "playResponseButton",
    "replayResponseButton",
    "clearConversationButton",
    "conversationStatus",
    "chatInput",
    "chatButton",
    "chatStatus",
    "chatResult",
    "chatResponse",
];

const appointmentElementIds = [
    "appointmentBooking",
    "appointmentStateStatus",
    "appointmentSpeciality",
    "appointmentLocation",
    "appointmentMode",
    "searchDoctorsButton",
    "doctorSearchStatus",
    "doctorCards",
    "selectedDoctorSummary",
    "appointmentDate",
    "loadAvailabilityButton",
    "availabilityStatus",
    "appointmentSlots",
    "selectedSlotSummary",
    "patientName",
    "patientPhone",
    "patientAge",
    "appointmentReason",
    "bookAppointmentButton",
    "appointmentActionStatus",
    "appointmentConfirmation",
    "appointmentReference",
    "confirmedAppointmentDetails",
    "lookupReference",
    "lookupPhone",
    "lookupAppointmentButton",
    "lookupStatus",
    "lookupAppointmentDetails",
    "manageAppointmentActions",
    "rescheduleDate",
    "rescheduleStartTime",
    "rescheduleAppointmentButton",
    "cancelAppointmentButton",
    "manageAppointmentStatus",
];

const elements = Object.fromEntries(
    [...baseElementIds, ...appointmentElementIds].map(
        (id) => [id, new FakeElement()]
    )
);
elements.recordButton.textContent = "Start Recording";
elements.recordingResult.hidden = true;
elements.transcriptResult.hidden = true;
elements.voiceAgentResult.hidden = true;
elements.chatResult.hidden = true;
elements.appointmentConfirmation.hidden = true;
elements.manageAppointmentActions.hidden = true;

global.document = {
    getElementById(id) {
        return elements[id];
    },
    createElement(tagName) {
        return new FakeElement(tagName);
    },
    createTextNode(text) {
        const node = new FakeElement("#text");
        node.textContent = text;
        return node;
    },
};

const sessionValues = new Map();
global.sessionStorage = {
    getItem(key) {
        return sessionValues.get(key) || null;
    },
    setItem(key, value) {
        sessionValues.set(key, value);
    },
};

global.confirm = () => true;

const fakeStream = {
    getTracks() {
        return [{stop() {}}];
    },
};
Object.defineProperty(global, "navigator", {
    value: {
        mediaDevices: {
            async getUserMedia() {
                return fakeStream;
            },
        },
    },
    configurable: true,
});

class FakeMediaRecorder {
    constructor() {
        this.listeners = new Map();
        this.mimeType = "audio/webm";
        this.state = "inactive";
    }

    addEventListener(eventName, listener) {
        this.listeners.set(eventName, listener);
    }

    start() {
        this.state = "recording";
    }

    stop() {
        this.state = "inactive";
        this.listeners.get("dataavailable")({
            data: new Blob(["demo audio"], {type: this.mimeType}),
        });
        this.listeners.get("stop")();
    }
}
global.MediaRecorder = FakeMediaRecorder;

const doctor = {
    doctor_id: "doc-101",
    name: "Dr. Asha Demo",
    speciality: "General Medicine",
    qualifications: ["MBBS", "MD"],
    languages: ["Hindi", "English"],
    experience_years: 12,
    clinic: "Demo Health Centre",
    location: "New Delhi",
    consultation_fee: 700,
    slot_duration_minutes: 30,
    consultation_modes: ["clinic", "video"],
};

const slot = {
    start_time: "10:30",
    end_time: "11:00",
    status: "available",
};

let appointment = {
    reference: "APT-DEMO-001",
    doctor_id: doctor.doctor_id,
    doctor_name: doctor.name,
    patient_name: "Demo Patient",
    patient_phone: "9990001111",
    appointment_date: "2099-05-20",
    start_time: "10:30",
    consultation_mode: "clinic",
    status: "confirmed",
};

let failNextDoctorSearch = true;
let bookingBody;
let rescheduleBody;
let cancelBody;
let doctorSearchUrl;
let clearCalls = 0;

function jsonResponse(data, ok = true) {
    return {
        ok,
        async json() {
            return data;
        },
    };
}

global.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/specialities")) {
        return jsonResponse({specialities: ["General Medicine", "Dermatology"]});
    }

    if (url.includes("/api/doctors?") && !url.includes("/availability")) {
        doctorSearchUrl = url;
        if (failNextDoctorSearch) {
            failNextDoctorSearch = false;
            return jsonResponse({detail: "Doctor search is temporarily unavailable."}, false);
        }
        return jsonResponse({doctors: [doctor]});
    }

    if (url.includes(`/api/doctors/${doctor.doctor_id}/availability`)) {
        return jsonResponse({
            doctor_id: doctor.doctor_id,
            date: "2099-05-20",
            slots: [slot, {start_time: "11:00", end_time: "11:30", status: "booked"}],
        });
    }

    if (url.endsWith("/api/appointments") && options.method === "POST") {
        bookingBody = JSON.parse(options.body);
        appointment = {...appointment, ...bookingBody, reference: "APT-DEMO-001"};
        return jsonResponse({appointment});
    }

    if (url.includes("/api/appointments/APT-DEMO-001/reschedule")) {
        const body = JSON.parse(options.body);
        rescheduleBody = body;
        appointment = {...appointment, ...body, status: "rescheduled"};
        return jsonResponse({appointment});
    }

    if (url.includes("/api/appointments/APT-DEMO-001/cancel")) {
        cancelBody = JSON.parse(options.body);
        appointment = {...appointment, status: "cancelled"};
        return jsonResponse({appointment});
    }

    if (url.includes("/api/appointments/APT-DEMO-001?phone=")) {
        return jsonResponse({appointment});
    }

    if (url.endsWith("/api/chat")) {
        return jsonResponse({
            response: "मैंने उपलब्ध डॉक्टर दिखा दिए हैं।",
            generation_time_ms: 4,
            memory_turns: 1,
            appointment_state: {
                stage: "choose_slot",
                doctor_options: [doctor],
                selected_doctor: doctor,
                appointment_date: "2099-05-20",
                available_slots: [slot],
            },
        });
    }

    if (url.endsWith("/api/voice/respond")) {
        return jsonResponse({
            transcript: "अपॉइंटमेंट बुक करें",
            response: "आपकी डेमो अपॉइंटमेंट बुक हो गई है।",
            audio_url: "/generated-audio/tts-0123456789abcdef0123456789abcdef.wav",
            memory_turns: 2,
            appointment,
            timing: {
                transcription_ms: 10,
                language_model_ms: 5,
                text_to_speech_ms: 2,
                total_ms: 17,
            },
        });
    }

    if (url.endsWith("/api/conversation/clear")) {
        clearCalls += 1;
        return jsonResponse({status: "success", cleared: true});
    }

    throw new Error(`Unexpected URL: ${url}`);
};

require("./app.js");


function findChildByTag(container, tagName) {
    return container.children.find((child) => child.tagName === tagName);
}

async function nextTurn() {
    await new Promise((resolve) => setImmediate(resolve));
}

async function run() {
    await nextTurn();
    assert.equal(elements.appointmentSpeciality.children.length, 3);
    assert.match(elements.appointmentStateStatus.textContent, /Ready/);

    elements.chatInput.value = "एक डॉक्टर की अपॉइंटमेंट चाहिए";
    await elements.chatButton.click();
    assert.match(elements.appointmentStateStatus.textContent, /choose_slot/);
    assert.match(elements.selectedDoctorSummary.textContent, /Dr. Asha Demo/);
    assert.equal(elements.appointmentSlots.children.length, 1);

    await elements.recordButton.click();
    await elements.recordButton.click();
    await elements.voiceAgentButton.click();
    assert.equal(elements.appointmentConfirmation.hidden, false);
    assert.match(elements.appointmentReference.textContent, /APT-DEMO-001/);

    await elements.clearConversationButton.click();
    assert.equal(clearCalls, 1);
    assert.equal(elements.appointmentConfirmation.hidden, true);
    assert.equal(elements.doctorCards.children.length, 0);
    assert.equal(elements.appointmentSlots.children.length, 0);
    assert.equal(elements.patientName.value, "");
    assert.match(elements.appointmentStateStatus.textContent, /Ready/);

    elements.appointmentSpeciality.value = "General Medicine";
    elements.appointmentLocation.value = "New Delhi";
    elements.appointmentMode.value = "clinic";

    await elements.searchDoctorsButton.click();
    assert.match(elements.doctorSearchStatus.textContent, /try again/i);
    assert.equal(elements.searchDoctorsButton.disabled, false);

    await elements.searchDoctorsButton.click();
    assert.match(doctorSearchUrl, /speciality=General\+Medicine/);
    assert.match(doctorSearchUrl, /location=New\+Delhi/);
    assert.match(doctorSearchUrl, /consultation_mode=clinic/);
    assert.equal(elements.doctorCards.children.length, 1);

    const chooseDoctor = findChildByTag(elements.doctorCards.children[0], "BUTTON");
    await chooseDoctor.click();
    assert.match(elements.selectedDoctorSummary.textContent, /Dr. Asha Demo/);
    assert.equal(elements.loadAvailabilityButton.disabled, false);

    elements.appointmentDate.value = "2099-05-20";
    await elements.loadAvailabilityButton.click();
    assert.equal(elements.appointmentSlots.children.length, 1);
    await elements.appointmentSlots.children[0].click();
    assert.match(elements.selectedSlotSummary.textContent, /10:30/);
    assert.equal(elements.bookAppointmentButton.disabled, false);

    elements.patientName.value = "Demo Patient";
    elements.patientPhone.value = "9990001111";
    elements.patientAge.value = "121";
    elements.appointmentReason.value = "Routine demo consultation";
    await elements.bookAppointmentButton.click();
    assert.match(elements.appointmentActionStatus.textContent, /between 0 and 120/);
    assert.equal(bookingBody, undefined);

    elements.patientAge.value = "35";
    await elements.bookAppointmentButton.click();

    const storedSessionId = sessionValues.get("hindiVoiceAgentSessionId");
    assert.equal(bookingBody.session_id, storedSessionId);
    assert.equal(bookingBody.doctor_id, doctor.doctor_id);
    assert.equal(bookingBody.patient_age, 35);
    assert.equal(elements.appointmentConfirmation.hidden, false);
    assert.match(elements.appointmentReference.textContent, /APT-DEMO-001/);

    await elements.lookupAppointmentButton.click();
    assert.equal(elements.manageAppointmentActions.hidden, false);
    assert.match(elements.lookupStatus.textContent, /found/i);

    elements.rescheduleDate.value = "2099-05-21";
    elements.rescheduleStartTime.value = "14:00";
    await elements.rescheduleAppointmentButton.click();
    assert.match(elements.manageAppointmentStatus.textContent, /rescheduled/i);
    assert.equal(appointment.start_time, "14:00");
    assert.equal(rescheduleBody.patient_phone, "9990001111");
    assert.equal(rescheduleBody.session_id, storedSessionId);
    assert.equal(Object.hasOwn(rescheduleBody, "phone"), false);

    await elements.cancelAppointmentButton.click();
    assert.match(elements.manageAppointmentStatus.textContent, /cancelled/i);
    assert.equal(appointment.status, "cancelled");
    assert.deepEqual(cancelBody, {
        patient_phone: "9990001111",
        session_id: storedSessionId,
    });
    assert.equal(elements.cancelAppointmentButton.disabled, true);

    await elements.clearConversationButton.click();
    assert.equal(elements.lookupReference.value, "");
    assert.equal(elements.manageAppointmentActions.hidden, true);
    assert.equal(elements.appointmentConfirmation.hidden, true);

    console.log("Chat and voice appointment state share the conversation UI: PASS");
    console.log("Search, availability, book, lookup, reschedule, cancel: PASS");
    console.log("Error recovery and New Conversation appointment reset: PASS");
}


run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
