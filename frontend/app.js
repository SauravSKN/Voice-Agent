const SESSION_STORAGE_KEY = "hindiVoiceAgentSessionId";
const BACKEND_BASE_URL = "http://127.0.0.1:8000";

function createConversationSessionId() {
    if (globalThis.crypto?.randomUUID) {
        return globalThis.crypto.randomUUID();
    }

    if (globalThis.crypto?.getRandomValues) {
        const values = new Uint32Array(4);
        globalThis.crypto.getRandomValues(values);
        return `session-${Array.from(values, (value) =>
            value.toString(16).padStart(8, "0")
        ).join("")}`;
    }

    return (
        `session-${Date.now().toString(36)}-` +
        Math.random().toString(36).slice(2, 14)
    );
}

function loadConversationSessionId() {
    try {
        const storedSessionId = globalThis.sessionStorage?.getItem(
            SESSION_STORAGE_KEY
        );
        if (storedSessionId) {
            return storedSessionId;
        }
    } catch (error) {
        console.warn("Session storage is unavailable:", error);
    }

    return createConversationSessionId();
}

function saveConversationSessionId(sessionId) {
    try {
        globalThis.sessionStorage?.setItem(
            SESSION_STORAGE_KEY,
            sessionId
        );
    } catch (error) {
        console.warn("Session storage is unavailable:", error);
    }
}

let conversationSessionId = loadConversationSessionId();
saveConversationSessionId(conversationSessionId);

const recordButton = document.getElementById("recordButton");
const uploadButton = document.getElementById("uploadButton");
const statusText = document.getElementById("status");
const recordingResult = document.getElementById("recordingResult");
const uploadResult = document.getElementById("uploadResult");
const audioPlayer = document.getElementById("audioPlayer");
const transcriptResult = document.getElementById("transcriptResult");
const transcriptText = document.getElementById("transcriptText");
const voiceAgentButton = document.getElementById("voiceAgentButton");
const voiceAgentStatus = document.getElementById("voiceAgentStatus");
const voiceAgentResult = document.getElementById("voiceAgentResult");
const voiceTranscriptText = document.getElementById("voiceTranscriptText");
const voiceResponseText = document.getElementById("voiceResponseText");
const voiceTiming = document.getElementById("voiceTiming");
const responseAudioPlayer = document.getElementById(
    "responseAudioPlayer"
);
const playResponseButton = document.getElementById(
    "playResponseButton"
);
const replayResponseButton = document.getElementById(
    "replayResponseButton"
);
const clearConversationButton = document.getElementById(
    "clearConversationButton"
);
const conversationStatus = document.getElementById("conversationStatus");
const chatInput = document.getElementById("chatInput");
const chatButton = document.getElementById("chatButton");
const chatStatus = document.getElementById("chatStatus");
const chatResult = document.getElementById("chatResult");
const chatResponse = document.getElementById("chatResponse");
const appointmentUi = {
    section: document.getElementById("appointmentBooking"),
    stateStatus: document.getElementById("appointmentStateStatus"),
    speciality: document.getElementById("appointmentSpeciality"),
    location: document.getElementById("appointmentLocation"),
    mode: document.getElementById("appointmentMode"),
    searchButton: document.getElementById("searchDoctorsButton"),
    searchStatus: document.getElementById("doctorSearchStatus"),
    doctorCards: document.getElementById("doctorCards"),
    selectedDoctorSummary: document.getElementById("selectedDoctorSummary"),
    date: document.getElementById("appointmentDate"),
    availabilityButton: document.getElementById("loadAvailabilityButton"),
    availabilityStatus: document.getElementById("availabilityStatus"),
    slots: document.getElementById("appointmentSlots"),
    selectedSlotSummary: document.getElementById("selectedSlotSummary"),
    patientName: document.getElementById("patientName"),
    patientPhone: document.getElementById("patientPhone"),
    patientAge: document.getElementById("patientAge"),
    reason: document.getElementById("appointmentReason"),
    bookButton: document.getElementById("bookAppointmentButton"),
    actionStatus: document.getElementById("appointmentActionStatus"),
    confirmation: document.getElementById("appointmentConfirmation"),
    reference: document.getElementById("appointmentReference"),
    confirmationDetails: document.getElementById("confirmedAppointmentDetails"),
    lookupReference: document.getElementById("lookupReference"),
    lookupPhone: document.getElementById("lookupPhone"),
    lookupButton: document.getElementById("lookupAppointmentButton"),
    lookupStatus: document.getElementById("lookupStatus"),
    lookupDetails: document.getElementById("lookupAppointmentDetails"),
    manageActions: document.getElementById("manageAppointmentActions"),
    rescheduleDate: document.getElementById("rescheduleDate"),
    rescheduleTime: document.getElementById("rescheduleStartTime"),
    rescheduleButton: document.getElementById("rescheduleAppointmentButton"),
    cancelButton: document.getElementById("cancelAppointmentButton"),
    manageStatus: document.getElementById("manageAppointmentStatus"),
};

let mediaRecorder = null;
let audioChunks = [];
let microphoneStream = null;
let isRecording = false;
let recordedAudioBlob = null;
let audioUrl = null;
let responseAudioReady = false;
let voiceRequestSequence = 0;
let appointmentDoctors = [];
let selectedAppointmentDoctor = null;
let selectedAppointmentSlot = null;
let managedAppointment = null;

function resetResponseAudio() {
    responseAudioReady = false;
    responseAudioPlayer.pause();
    responseAudioPlayer.src = "";
    if (typeof responseAudioPlayer.load === "function") {
        responseAudioPlayer.load();
    }
    playResponseButton.hidden = true;
    replayResponseButton.hidden = true;
    playResponseButton.disabled = false;
    replayResponseButton.disabled = false;
}

function resolveGeneratedAudioUrl(audioUrlPath) {
    if (typeof audioUrlPath !== "string" || !audioUrlPath.trim()) {
        throw new Error("The backend did not return response audio.");
    }

    const resolvedUrl = new URL(audioUrlPath, BACKEND_BASE_URL);
    const backendUrl = new URL(BACKEND_BASE_URL);
    if (
        resolvedUrl.origin !== backendUrl.origin ||
        !resolvedUrl.pathname.startsWith("/generated-audio/")
    ) {
        throw new Error("The backend returned an unsafe audio URL.");
    }
    return resolvedUrl.href;
}

async function playGeneratedResponse(replay = false) {
    if (!responseAudioReady || !responseAudioPlayer.src) {
        voiceAgentStatus.textContent =
            "Voice agent status: Error — response audio is unavailable.";
        return;
    }

    playResponseButton.disabled = true;
    replayResponseButton.disabled = true;
    if (replay) {
        responseAudioPlayer.currentTime = 0;
    }

    try {
        voiceAgentStatus.textContent =
            "Voice agent status: Playing response...";
        await responseAudioPlayer.play();
        playResponseButton.hidden = true;
        replayResponseButton.hidden = false;
    } catch (error) {
        console.warn("Response audio playback needs user action:", error);
        playResponseButton.hidden = false;
        replayResponseButton.hidden = false;
        voiceAgentStatus.textContent =
            "Voice agent status: Voice ready — press Play Response.";
    } finally {
        playResponseButton.disabled = false;
        replayResponseButton.disabled = false;
    }
}

async function startRecording() {
    try {
        resetResponseAudio();
        statusText.textContent =
            "Status: Requesting microphone permission...";

        microphoneStream =
            await navigator.mediaDevices.getUserMedia({
                audio: true,
            });

        audioChunks = [];
        recordedAudioBlob = null;
        uploadResult.textContent = "";
        transcriptText.textContent = "";
        transcriptResult.hidden = true;
        voiceAgentStatus.textContent =
            "Voice agent status: Ready";
        voiceTranscriptText.textContent = "";
        voiceResponseText.textContent = "";
        voiceTiming.textContent = "";
        voiceAgentResult.hidden = true;

        mediaRecorder = new MediaRecorder(microphoneStream);

        mediaRecorder.addEventListener(
            "dataavailable",
            (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            }
        );

        mediaRecorder.addEventListener(
            "stop",
            createAudioPreview
        );

        mediaRecorder.start();

        isRecording = true;

        recordButton.textContent = "Stop Recording";
        statusText.textContent = "Status: Recording...";
        recordingResult.hidden = true;
    } catch (error) {
        console.error("Microphone error:", error);

        statusText.textContent =
            "Status: Microphone permission was denied or unavailable.";
    }
}

function stopRecording() {
    if (!mediaRecorder || mediaRecorder.state !== "recording") {
        return;
    }

    mediaRecorder.stop();

    if (microphoneStream) {
        microphoneStream
            .getTracks()
            .forEach((track) => track.stop());
    }

    isRecording = false;

    recordButton.textContent = "Start Recording";
    statusText.textContent =
        "Status: Processing recording...";
}

function createAudioPreview() {
    recordedAudioBlob = new Blob(audioChunks, {
        type: mediaRecorder.mimeType || "audio/webm",
    });

    if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
    }

    audioUrl = URL.createObjectURL(recordedAudioBlob);
    audioPlayer.src = audioUrl;
    recordingResult.hidden = false;

    statusText.textContent =
        "Status: Recording complete. Choose Transcribe or Ask Voice Agent.";
}

async function uploadRecording() {
    if (!recordedAudioBlob || recordedAudioBlob.size === 0) {
        uploadResult.textContent =
            "No recording is available.";
        return;
    }

    uploadButton.disabled = true;
    uploadResult.textContent =
        "Transcribing recording...";
    transcriptResult.hidden = true;

    const formData = new FormData();

    formData.append(
        "audio",
        recordedAudioBlob,
        "recording.webm"
    );
    try {
        const response = await fetch(
            "http://127.0.0.1:8000/api/transcribe",
            {
                method: "POST",
                body: formData,
            }
        );

        let data;
        try {
            data = await response.json();
        } catch (error) {
            throw new Error("The backend returned an invalid response.");
        }

        if (!response.ok) {
            throw new Error(
                data.detail || "Transcription failed."
            );
        }

        transcriptText.textContent = data.transcript;
        transcriptResult.hidden = false;
        uploadResult.textContent =
            `Transcribed ${data.size_bytes} bytes successfully.`;

        statusText.textContent =
            "Status: Transcription complete.";
    } catch (error) {
        console.error("Transcription error:", error);

        uploadResult.textContent =
            `Transcription failed: ${error.message}`;

        statusText.textContent =
            "Status: Could not transcribe the recording.";
    } finally {
        uploadButton.disabled = false;
    }
}

async function askVoiceAgent() {
    if (voiceAgentButton.disabled) {
        return;
    }

    if (!recordedAudioBlob || recordedAudioBlob.size === 0) {
        voiceAgentStatus.textContent =
            "Voice agent status: Error — no recording is available.";
        voiceAgentResult.hidden = true;
        return;
    }

    recordButton.disabled = true;
    uploadButton.disabled = true;
    voiceAgentButton.disabled = true;
    voiceAgentResult.hidden = true;
    const requestSequence = ++voiceRequestSequence;
    resetResponseAudio();
    voiceAgentStatus.textContent =
        "Voice agent status: Preparing audio...";

    const formData = new FormData();
    formData.append(
        "audio",
        recordedAudioBlob,
        "recording.webm"
    );
    formData.append("session_id", conversationSessionId);

    const controller = new AbortController();
    const timeoutId = setTimeout(
        () => controller.abort(),
        180000
    );

    try {
        voiceAgentStatus.textContent =
            "Voice agent status: Uploading audio...";

        const responsePromise = fetch(
            `${BACKEND_BASE_URL}/api/voice/respond`,
            {
                method: "POST",
                body: formData,
                signal: controller.signal,
            }
        );

        voiceAgentStatus.textContent =
            "Voice agent status: Processing speech, generating response, " +
            "and generating voice...";

        const response = await responsePromise;

        let data;
        try {
            data = await response.json();
        } catch (error) {
            throw new Error("The backend returned an invalid response.");
        }

        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : "The voice-agent request failed."
            );
        }

        if (requestSequence !== voiceRequestSequence) {
            return;
        }

        voiceTranscriptText.textContent = data.transcript;
        voiceResponseText.textContent = data.response;
        applyAssistantAppointmentPayload(data);
        voiceTiming.textContent =
            `Transcription: ${data.timing.transcription_ms} ms · ` +
            `Language model: ${data.timing.language_model_ms} ms · ` +
            `Text to speech: ${data.timing.text_to_speech_ms} ms · ` +
            `Total: ${data.timing.total_ms} ms`;
        voiceAgentResult.hidden = false;
        voiceAgentStatus.textContent =
            "Voice agent status: Loading generated voice...";
        conversationStatus.textContent =
            `Conversation status: ${data.memory_turns} remembered ` +
            `${data.memory_turns === 1 ? "turn" : "turns"}.`;
        statusText.textContent =
            "Status: Voice response complete.";

        responseAudioPlayer.src = resolveGeneratedAudioUrl(
            data.audio_url
        );
        responseAudioReady = true;
        replayResponseButton.hidden = false;
        await playGeneratedResponse();
    } catch (error) {
        console.error("Voice-agent error:", error);

        const errorMessage = error.name === "AbortError"
            ? "The voice-agent request timed out."
            : error.message;

        voiceAgentStatus.textContent =
            `Voice agent status: Error — ${errorMessage}`;
        statusText.textContent =
            "Status: Voice-agent request failed.";
    } finally {
        clearTimeout(timeoutId);
        recordButton.disabled = false;
        uploadButton.disabled = false;
        voiceAgentButton.disabled = false;
    }
}

async function sendChatMessage() {
    if (chatButton.disabled) {
        return;
    }

    const message = chatInput.value.trim();

    if (!message) {
        chatStatus.textContent =
            "Chat status: Enter a message first.";
        chatResult.hidden = true;
        return;
    }

    chatButton.disabled = true;
    chatStatus.textContent =
        "Chat status: Waiting for the local model...";
    chatResult.hidden = true;

    const controller = new AbortController();
    const timeoutId = setTimeout(
        () => controller.abort(),
        65000
    );

    try {
        const response = await fetch(
            "http://127.0.0.1:8000/api/chat",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message,
                    session_id: conversationSessionId,
                }),
                signal: controller.signal,
            }
        );

        let data;
        try {
            data = await response.json();
        } catch (error) {
            throw new Error("The backend returned an invalid response.");
        }

        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : "The local model request failed."
            );
        }

        chatResponse.textContent = data.response;
        applyAssistantAppointmentPayload(data);
        chatResult.hidden = false;
        chatStatus.textContent =
            `Chat status: Response received in ` +
            `${data.generation_time_ms} ms.`;
        conversationStatus.textContent =
            `Conversation status: ${data.memory_turns} remembered ` +
            `${data.memory_turns === 1 ? "turn" : "turns"}.`;
    } catch (error) {
        console.error("Chat error:", error);

        if (error.name === "AbortError") {
            chatStatus.textContent =
                "Chat status: The local model request timed out.";
        } else {
            chatStatus.textContent =
                `Chat status: ${error.message}`;
        }
    } finally {
        clearTimeout(timeoutId);
        chatButton.disabled = false;
    }
}

async function clearConversation() {
    if (clearConversationButton.disabled) {
        return;
    }

    clearConversationButton.disabled = true;
    conversationStatus.textContent =
        "Conversation status: Clearing...";

    const controller = new AbortController();
    const timeoutId = setTimeout(
        () => controller.abort(),
        65000
    );

    try {
        const response = await fetch(
            "http://127.0.0.1:8000/api/conversation/clear",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    session_id: conversationSessionId,
                }),
                signal: controller.signal,
            }
        );

        let data;
        try {
            data = await response.json();
        } catch (error) {
            throw new Error("The backend returned an invalid response.");
        }

        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : "The conversation could not be cleared."
            );
        }

        conversationSessionId = createConversationSessionId();
        saveConversationSessionId(conversationSessionId);
        voiceRequestSequence += 1;
        resetResponseAudio();

        chatInput.value = "";
        chatResponse.textContent = "";
        chatResult.hidden = true;
        chatStatus.textContent = "Chat status: Ready";
        transcriptText.textContent = "";
        transcriptResult.hidden = true;
        voiceTranscriptText.textContent = "";
        voiceResponseText.textContent = "";
        voiceTiming.textContent = "";
        voiceAgentResult.hidden = true;
        voiceAgentStatus.textContent = "Voice agent status: Ready";
        uploadResult.textContent = "";
        resetAppointmentUi();
        conversationStatus.textContent =
            "Conversation status: New conversation started.";
    } catch (error) {
        console.error("Conversation-clear error:", error);
        const errorMessage = error.name === "AbortError"
            ? "The clear request timed out."
            : error.message;
        conversationStatus.textContent =
            `Conversation status: Error — ${errorMessage}`;
    } finally {
        clearTimeout(timeoutId);
        clearConversationButton.disabled = false;
    }
}

function appointmentApiError(data, fallback) {
    if (typeof data?.detail === "string") {
        return data.detail;
    }
    if (typeof data?.message === "string") {
        return data.message;
    }
    return fallback;
}

async function appointmentRequest(path, options = {}) {
    const response = await fetch(`${BACKEND_BASE_URL}${path}`, options);
    let data;
    try {
        data = await response.json();
    } catch (error) {
        throw new Error("The appointment service returned an invalid response.");
    }
    if (!response.ok) {
        throw new Error(
            appointmentApiError(data, "The appointment request failed.")
        );
    }
    return data;
}

function normaliseAppointment(data) {
    return data?.appointment || data;
}

function appointmentReferenceValue(appointment) {
    return (
        appointment?.reference ||
        appointment?.appointment_reference ||
        appointment?.booking_reference ||
        ""
    );
}

function readableMode(mode) {
    if (mode === "clinic" || mode === "in_person") {
        return "In person";
    }
    if (mode === "video") {
        return "Video";
    }
    return mode || "Not specified";
}

function readableTime(value) {
    if (typeof value !== "string" || !value) {
        return "Not specified";
    }
    return value.length >= 5 ? value.slice(0, 5) : value;
}

function clearElement(element) {
    if (!element) {
        return;
    }
    if (typeof element.replaceChildren === "function") {
        element.replaceChildren();
    } else {
        element.textContent = "";
    }
}

function addTextLine(container, label, value) {
    if (!container || value === undefined || value === null || value === "") {
        return;
    }
    const line = document.createElement("p");
    const labelNode = document.createElement("strong");
    labelNode.textContent = `${label}: `;
    line.appendChild(labelNode);
    line.appendChild(document.createTextNode(String(value)));
    container.appendChild(line);
}

function formatDoctorSummary(doctor) {
    const name = doctor?.name || doctor?.doctor_name || "Selected doctor";
    const speciality = doctor?.speciality || "Speciality not listed";
    const location = doctor?.location || doctor?.clinic || "Location not listed";
    return `${name} · ${speciality} · ${location}`;
}

function renderDoctors(doctors) {
    if (!appointmentUi.section) {
        return;
    }
    appointmentDoctors = Array.isArray(doctors) ? doctors : [];
    clearElement(appointmentUi.doctorCards);

    if (appointmentDoctors.length === 0) {
        appointmentUi.searchStatus.textContent =
            "No doctors matched those filters. Try a different speciality, location, or mode.";
        return;
    }

    appointmentDoctors.forEach((doctor) => {
        const card = document.createElement("article");
        card.className = "doctor-card";
        if (
            selectedAppointmentDoctor &&
            selectedAppointmentDoctor.doctor_id === doctor.doctor_id
        ) {
            card.className += " is-selected";
        }

        const title = document.createElement("h4");
        title.textContent = doctor.name;
        card.appendChild(title);

        const speciality = document.createElement("p");
        speciality.textContent = doctor.speciality;
        card.appendChild(speciality);

        const credentials = document.createElement("p");
        credentials.className = "doctor-meta";
        const qualifications = Array.isArray(doctor.qualifications)
            ? doctor.qualifications.join(", ")
            : doctor.qualifications;
        credentials.textContent = [
            qualifications,
            doctor.experience_years !== undefined
                ? `${doctor.experience_years} years experience`
                : "",
        ].filter(Boolean).join(" · ");
        card.appendChild(credentials);

        const clinic = document.createElement("p");
        clinic.className = "doctor-meta";
        clinic.textContent = [doctor.clinic, doctor.location]
            .filter(Boolean)
            .join(" · ");
        card.appendChild(clinic);

        const languages = Array.isArray(doctor.languages)
            ? doctor.languages.join(", ")
            : doctor.languages;
        addTextLine(card, "Languages", languages);
        addTextLine(
            card,
            "Fee",
            doctor.consultation_fee !== undefined
                ? `₹${doctor.consultation_fee}`
                : "Not listed"
        );
        addTextLine(
            card,
            "Modes",
            Array.isArray(doctor.consultation_modes)
                ? doctor.consultation_modes.map(readableMode).join(", ")
                : readableMode(doctor.consultation_modes)
        );

        const chooseButton = document.createElement("button");
        chooseButton.type = "button";
        chooseButton.textContent = "Choose this doctor";
        chooseButton.addEventListener("click", () => selectDoctor(doctor));
        card.appendChild(chooseButton);
        appointmentUi.doctorCards.appendChild(card);
    });

    appointmentUi.searchStatus.textContent =
        `${appointmentDoctors.length} ${appointmentDoctors.length === 1 ? "doctor" : "doctors"} found.`;
}

function selectDoctor(doctor) {
    selectedAppointmentDoctor = doctor;
    selectedAppointmentSlot = null;
    appointmentUi.selectedDoctorSummary.textContent = formatDoctorSummary(doctor);
    appointmentUi.selectedSlotSummary.textContent = "No time selected.";
    appointmentUi.availabilityButton.disabled = false;
    appointmentUi.bookButton.disabled = true;
    appointmentUi.availabilityStatus.textContent =
        "Choose a date, then show availability.";
    clearElement(appointmentUi.slots);
    if (appointmentDoctors.length > 0) {
        renderDoctors(appointmentDoctors);
    }
}

function renderAvailability(slots, date = appointmentUi.date.value) {
    clearElement(appointmentUi.slots);
    selectedAppointmentSlot = null;
    appointmentUi.bookButton.disabled = true;
    appointmentUi.selectedSlotSummary.textContent = "No time selected.";
    const availableSlots = (Array.isArray(slots) ? slots : []).filter(
        (slot) => !slot.status || slot.status === "available"
    );

    if (availableSlots.length === 0) {
        appointmentUi.availabilityStatus.textContent =
            "No available times on this date. Choose another date and try again.";
        return;
    }

    availableSlots.forEach((slot) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "slot-button";
        button.textContent = readableTime(slot.start_time);
        button.addEventListener("click", () => {
            selectedAppointmentSlot = slot;
            Array.from(appointmentUi.slots.children).forEach((child) => {
                child.className = "slot-button";
            });
            button.className = "slot-button is-selected";
            appointmentUi.selectedSlotSummary.textContent =
                `Selected: ${date} at ${readableTime(slot.start_time)}.`;
            appointmentUi.bookButton.disabled = false;
        });
        appointmentUi.slots.appendChild(button);
    });
    appointmentUi.availabilityStatus.textContent =
        `${availableSlots.length} available ${availableSlots.length === 1 ? "time" : "times"}.`;
}

function renderAppointmentDetails(container, appointment) {
    clearElement(container);
    if (!appointment || typeof appointment !== "object") {
        return;
    }
    addTextLine(container, "Reference", appointmentReferenceValue(appointment));
    addTextLine(
        container,
        "Doctor",
        appointment.doctor_name || appointment.doctor?.name ||
            selectedAppointmentDoctor?.name
    );
    addTextLine(container, "Date", appointment.appointment_date || appointment.date);
    addTextLine(
        container,
        "Time",
        readableTime(appointment.start_time)
    );
    addTextLine(
        container,
        "Mode",
        readableMode(appointment.consultation_mode)
    );
    addTextLine(container, "Status", appointment.status);
}

function renderConfirmedAppointment(appointment) {
    if (!appointmentUi.section || !appointment) {
        return;
    }
    const reference = appointmentReferenceValue(appointment);
    appointmentUi.reference.textContent = reference
        ? `Reference: ${reference}`
        : "The service did not return a booking reference.";
    renderAppointmentDetails(appointmentUi.confirmationDetails, appointment);
    appointmentUi.confirmation.hidden = false;
    appointmentUi.actionStatus.textContent =
        `Appointment ${appointment.status || "confirmed"}. Save the reference for this demo session.`;
    if (reference) {
        appointmentUi.lookupReference.value = reference;
    }
    if (appointment.patient_phone || appointmentUi.patientPhone.value) {
        appointmentUi.lookupPhone.value =
            appointment.patient_phone || appointmentUi.patientPhone.value;
    }
}

function renderManagedAppointment(appointment) {
    managedAppointment = appointment;
    renderAppointmentDetails(appointmentUi.lookupDetails, appointment);
    appointmentUi.manageActions.hidden = false;
    appointmentUi.lookupStatus.textContent = "Booking found.";
    appointmentUi.rescheduleDate.value =
        appointment.appointment_date || appointment.date || "";
    appointmentUi.rescheduleTime.value = readableTime(appointment.start_time) === "Not specified"
        ? ""
        : readableTime(appointment.start_time);
}

function applyAssistantAppointmentPayload(data) {
    if (!appointmentUi.section || !data) {
        return;
    }
    const state = data.appointment_state;
    const appointment = data.appointment || state?.appointment;

    if (!state && !appointment) {
        return;
    }

    if (state && typeof state === "object") {
        if (Array.isArray(state.specialities)) {
            populateSpecialities(state.specialities);
        }
        const doctors = state.doctors || state.doctor_options;
        if (Array.isArray(doctors)) {
            renderDoctors(doctors);
        }
        const doctor = state.selected_doctor || state.doctor;
        if (doctor && typeof doctor === "object") {
            selectDoctor(doctor);
        }
        const slots = state.slots || state.available_slots ||
            state.availability?.slots;
        if (Array.isArray(slots)) {
            const date = state.date || state.appointment_date ||
                state.availability?.date;
            if (date) {
                appointmentUi.date.value = date;
            }
            renderAvailability(slots, date || appointmentUi.date.value);
        }
        appointmentUi.stateStatus.textContent =
            `Appointment assistant: ${state.message || state.stage || state.status || "Updated from conversation"}`;
    } else if (typeof state === "string") {
        appointmentUi.stateStatus.textContent =
            `Appointment assistant: ${state}`;
    }

    if (appointment) {
        renderConfirmedAppointment(appointment);
    }
}

function populateSpecialities(specialities) {
    const current = appointmentUi.speciality.value;
    clearElement(appointmentUi.speciality);
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = "Choose a speciality";
    appointmentUi.speciality.appendChild(prompt);
    (Array.isArray(specialities) ? specialities : []).forEach((speciality) => {
        const option = document.createElement("option");
        option.value = speciality;
        option.textContent = speciality;
        appointmentUi.speciality.appendChild(option);
    });
    appointmentUi.speciality.value = current;
}

async function loadSpecialities() {
    appointmentUi.stateStatus.textContent =
        "Appointment assistant: Loading specialities...";
    try {
        const data = await appointmentRequest("/api/specialities");
        populateSpecialities(data.specialities);
        appointmentUi.stateStatus.textContent =
            "Appointment assistant: Ready";
    } catch (error) {
        appointmentUi.stateStatus.textContent =
            `Appointment assistant: ${error.message} Retry by reloading the page.`;
    }
}

async function searchDoctors() {
    if (appointmentUi.searchButton.disabled) {
        return;
    }
    const speciality = appointmentUi.speciality.value;
    if (!speciality) {
        appointmentUi.searchStatus.textContent =
            "Choose a speciality before searching.";
        return;
    }

    appointmentUi.searchButton.disabled = true;
    appointmentUi.searchStatus.textContent = "Searching doctors...";
    const params = new URLSearchParams({speciality});
    if (appointmentUi.location.value.trim()) {
        params.set("location", appointmentUi.location.value.trim());
    }
    if (appointmentUi.mode.value) {
        params.set("consultation_mode", appointmentUi.mode.value);
    }

    try {
        const data = await appointmentRequest(`/api/doctors?${params}`);
        selectedAppointmentDoctor = null;
        selectedAppointmentSlot = null;
        appointmentUi.selectedDoctorSummary.textContent =
            "Select a doctor to continue.";
        appointmentUi.availabilityButton.disabled = true;
        appointmentUi.bookButton.disabled = true;
        clearElement(appointmentUi.slots);
        renderDoctors(data.doctors);
    } catch (error) {
        clearElement(appointmentUi.doctorCards);
        appointmentUi.searchStatus.textContent =
            `${error.message} Check the filters and try again.`;
    } finally {
        appointmentUi.searchButton.disabled = false;
    }
}

async function loadAvailability() {
    if (!selectedAppointmentDoctor) {
        appointmentUi.availabilityStatus.textContent =
            "Select a doctor first.";
        return;
    }
    if (!appointmentUi.date.value) {
        appointmentUi.availabilityStatus.textContent =
            "Choose an appointment date first.";
        return;
    }

    appointmentUi.availabilityButton.disabled = true;
    appointmentUi.availabilityStatus.textContent = "Loading availability...";
    try {
        const doctorId = encodeURIComponent(selectedAppointmentDoctor.doctor_id);
        const date = encodeURIComponent(appointmentUi.date.value);
        const data = await appointmentRequest(
            `/api/doctors/${doctorId}/availability?date=${date}`
        );
        renderAvailability(data.slots, data.date || appointmentUi.date.value);
    } catch (error) {
        clearElement(appointmentUi.slots);
        appointmentUi.availabilityStatus.textContent =
            `${error.message} Choose another date or try again.`;
    } finally {
        appointmentUi.availabilityButton.disabled = false;
    }
}

function validDemoPhone(value) {
    let digits = value.trim().replace(/[\s()-]/g, "");
    if (digits.startsWith("+91")) {
        digits = digits.slice(3);
    } else if (digits.startsWith("91") && digits.length === 12) {
        digits = digits.slice(2);
    }
    return /^[6-9]\d{9}$/.test(digits);
}

async function bookAppointment() {
    if (appointmentUi.bookButton.disabled) {
        return;
    }
    const name = appointmentUi.patientName.value.trim();
    const phone = appointmentUi.patientPhone.value.trim();
    if (!name) {
        appointmentUi.actionStatus.textContent =
            "Enter a fictional patient name.";
        return;
    }
    if (!validDemoPhone(phone)) {
        appointmentUi.actionStatus.textContent =
            "Enter a valid demo phone number (7–20 digits and common separators).";
        return;
    }
    const ageValue = appointmentUi.patientAge.value;
    if (
        ageValue !== "" &&
        (!Number.isInteger(Number(ageValue)) || Number(ageValue) < 0 ||
            Number(ageValue) > 120)
    ) {
        appointmentUi.actionStatus.textContent =
            "Age must be a whole number between 0 and 120.";
        return;
    }
    if (!selectedAppointmentDoctor || !selectedAppointmentSlot) {
        appointmentUi.actionStatus.textContent =
            "Select a doctor and an available time first.";
        return;
    }

    const body = {
        doctor_id: selectedAppointmentDoctor.doctor_id,
        patient_name: name,
        patient_phone: phone,
        appointment_date: appointmentUi.date.value,
        start_time: selectedAppointmentSlot.start_time,
        consultation_mode: appointmentUi.mode.value ||
            selectedAppointmentDoctor.consultation_modes?.[0] ||
            "clinic",
        session_id: conversationSessionId,
    };
    if (ageValue !== "") {
        body.patient_age = Number(ageValue);
    }
    if (appointmentUi.reason.value.trim()) {
        body.reason = appointmentUi.reason.value.trim();
    }

    appointmentUi.bookButton.disabled = true;
    appointmentUi.actionStatus.textContent = "Confirming appointment...";
    try {
        const data = await appointmentRequest("/api/appointments", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body),
        });
        renderConfirmedAppointment(normaliseAppointment(data));
    } catch (error) {
        appointmentUi.actionStatus.textContent =
            `${error.message} Your selection is still available to retry.`;
        appointmentUi.bookButton.disabled = false;
    }
}

async function lookupAppointment() {
    if (appointmentUi.lookupButton.disabled) {
        return;
    }
    const reference = appointmentUi.lookupReference.value.trim();
    const phone = appointmentUi.lookupPhone.value.trim();
    if (!reference || !validDemoPhone(phone)) {
        appointmentUi.lookupStatus.textContent =
            "Enter the booking reference and a valid demo phone number.";
        return;
    }

    appointmentUi.lookupButton.disabled = true;
    appointmentUi.lookupStatus.textContent = "Finding booking...";
    appointmentUi.manageActions.hidden = true;
    clearElement(appointmentUi.lookupDetails);
    try {
        const data = await appointmentRequest(
            `/api/appointments/${encodeURIComponent(reference)}?phone=${encodeURIComponent(phone)}`
        );
        renderManagedAppointment(normaliseAppointment(data));
    } catch (error) {
        managedAppointment = null;
        appointmentUi.lookupStatus.textContent =
            `${error.message} Check the reference and phone, then try again.`;
    } finally {
        appointmentUi.lookupButton.disabled = false;
    }
}

async function rescheduleAppointment() {
    const reference = appointmentReferenceValue(managedAppointment) ||
        appointmentUi.lookupReference.value.trim();
    const phone = appointmentUi.lookupPhone.value.trim();
    if (!reference || !phone || !appointmentUi.rescheduleDate.value ||
        !appointmentUi.rescheduleTime.value) {
        appointmentUi.manageStatus.textContent =
            "Choose a new date and start time first.";
        return;
    }

    appointmentUi.rescheduleButton.disabled = true;
    appointmentUi.manageStatus.textContent = "Rescheduling appointment...";
    try {
        const data = await appointmentRequest(
            `/api/appointments/${encodeURIComponent(reference)}/reschedule`,
            {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    appointment_date: appointmentUi.rescheduleDate.value,
                    start_time: appointmentUi.rescheduleTime.value,
                    patient_phone: phone,
                    session_id: conversationSessionId,
                }),
            }
        );
        const appointment = normaliseAppointment(data);
        renderManagedAppointment(appointment);
        renderConfirmedAppointment(appointment);
        appointmentUi.manageStatus.textContent =
            "Appointment rescheduled successfully.";
    } catch (error) {
        appointmentUi.manageStatus.textContent =
            `${error.message} Choose another time or try again.`;
    } finally {
        appointmentUi.rescheduleButton.disabled = false;
    }
}

async function cancelAppointment() {
    const reference = appointmentReferenceValue(managedAppointment) ||
        appointmentUi.lookupReference.value.trim();
    const phone = appointmentUi.lookupPhone.value.trim();
    if (!reference || !phone) {
        appointmentUi.manageStatus.textContent =
            "Find the booking before cancelling it.";
        return;
    }
    if (
        typeof globalThis.confirm === "function" &&
        !globalThis.confirm("Cancel this demo appointment?")
    ) {
        return;
    }

    appointmentUi.cancelButton.disabled = true;
    appointmentUi.manageStatus.textContent = "Cancelling appointment...";
    try {
        const data = await appointmentRequest(
            `/api/appointments/${encodeURIComponent(reference)}/cancel`,
            {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    patient_phone: phone,
                    session_id: conversationSessionId,
                }),
            }
        );
        const appointment = normaliseAppointment(data);
        renderManagedAppointment(appointment);
        renderConfirmedAppointment(appointment);
        appointmentUi.manageStatus.textContent =
            "Appointment cancelled successfully.";
        appointmentUi.rescheduleButton.disabled = true;
        appointmentUi.cancelButton.disabled = true;
    } catch (error) {
        appointmentUi.manageStatus.textContent =
            `${error.message} The booking was not changed; try again.`;
        appointmentUi.cancelButton.disabled = false;
    }
}

function resetAppointmentUi() {
    if (!appointmentUi.section) {
        return;
    }
    appointmentDoctors = [];
    selectedAppointmentDoctor = null;
    selectedAppointmentSlot = null;
    managedAppointment = null;
    appointmentUi.speciality.value = "";
    appointmentUi.location.value = "";
    appointmentUi.mode.value = "";
    appointmentUi.date.value = "";
    appointmentUi.patientName.value = "";
    appointmentUi.patientPhone.value = "";
    appointmentUi.patientAge.value = "";
    appointmentUi.reason.value = "";
    appointmentUi.lookupReference.value = "";
    appointmentUi.lookupPhone.value = "";
    appointmentUi.rescheduleDate.value = "";
    appointmentUi.rescheduleTime.value = "";
    clearElement(appointmentUi.doctorCards);
    clearElement(appointmentUi.slots);
    clearElement(appointmentUi.confirmationDetails);
    clearElement(appointmentUi.lookupDetails);
    appointmentUi.selectedDoctorSummary.textContent =
        "Select a doctor to continue.";
    appointmentUi.selectedSlotSummary.textContent = "No time selected.";
    appointmentUi.searchStatus.textContent = "";
    appointmentUi.availabilityStatus.textContent = "";
    appointmentUi.actionStatus.textContent = "";
    appointmentUi.lookupStatus.textContent = "";
    appointmentUi.manageStatus.textContent = "";
    appointmentUi.reference.textContent = "";
    appointmentUi.confirmation.hidden = true;
    appointmentUi.manageActions.hidden = true;
    appointmentUi.availabilityButton.disabled = true;
    appointmentUi.bookButton.disabled = true;
    appointmentUi.rescheduleButton.disabled = false;
    appointmentUi.cancelButton.disabled = false;
    appointmentUi.stateStatus.textContent = "Appointment assistant: Ready";
}

function initialiseAppointments() {
    if (!appointmentUi.section) {
        return;
    }
    const today = new Date().toISOString().slice(0, 10);
    appointmentUi.date.min = today;
    appointmentUi.rescheduleDate.min = today;
    appointmentUi.searchButton.addEventListener("click", searchDoctors);
    appointmentUi.availabilityButton.addEventListener("click", loadAvailability);
    appointmentUi.bookButton.addEventListener("click", bookAppointment);
    appointmentUi.lookupButton.addEventListener("click", lookupAppointment);
    appointmentUi.rescheduleButton.addEventListener("click", rescheduleAppointment);
    appointmentUi.cancelButton.addEventListener("click", cancelAppointment);
    loadSpecialities();
}

recordButton.addEventListener(
    "click",
    async () => {
        if (isRecording) {
            stopRecording();
        } else {
            await startRecording();
        }
    }
);

uploadButton.addEventListener(
    "click",
    uploadRecording
);

voiceAgentButton.addEventListener(
    "click",
    askVoiceAgent
);

chatButton.addEventListener(
    "click",
    sendChatMessage
);

clearConversationButton.addEventListener(
    "click",
    clearConversation
);

playResponseButton.addEventListener(
    "click",
    async () => {
        await playGeneratedResponse();
    }
);

replayResponseButton.addEventListener(
    "click",
    async () => {
        await playGeneratedResponse(true);
    }
);

responseAudioPlayer.addEventListener(
    "playing",
    () => {
        if (responseAudioReady) {
            voiceAgentStatus.textContent =
                "Voice agent status: Playing response...";
        }
    }
);

responseAudioPlayer.addEventListener(
    "ended",
    () => {
        if (responseAudioReady) {
            playResponseButton.hidden = true;
            replayResponseButton.hidden = false;
            voiceAgentStatus.textContent =
                "Voice agent status: Complete";
        }
    }
);

responseAudioPlayer.addEventListener(
    "error",
    () => {
        if (responseAudioReady) {
            responseAudioReady = false;
            playResponseButton.hidden = true;
            replayResponseButton.hidden = true;
            voiceAgentStatus.textContent =
                "Voice agent status: Error — generated audio is unavailable.";
        }
    }
);

chatInput.addEventListener(
    "keydown",
    async (event) => {
        if (event.key === "Enter") {
            await sendChatMessage();
        }
    }
);

initialiseAppointments();
