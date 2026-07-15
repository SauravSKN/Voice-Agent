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

let mediaRecorder = null;
let audioChunks = [];
let microphoneStream = null;
let isRecording = false;
let recordedAudioBlob = null;
let audioUrl = null;
let responseAudioReady = false;
let voiceRequestSequence = 0;

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
