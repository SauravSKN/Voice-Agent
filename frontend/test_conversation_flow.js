const assert = require("node:assert/strict");


class FakeElement {
    constructor() {
        this.disabled = false;
        this.hidden = false;
        this.listeners = new Map();
        this.src = "";
        this.textContent = "";
        this.value = "";
        this.currentTime = 0;
    }

    addEventListener(eventName, listener) {
        this.listeners.set(eventName, listener);
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


const elementIds = [
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

const elements = Object.fromEntries(
    elementIds.map((id) => [id, new FakeElement()])
);
elements.recordButton.textContent = "Start Recording";
elements.recordingResult.hidden = true;
elements.transcriptResult.hidden = true;
elements.voiceAgentResult.hidden = true;
elements.chatResult.hidden = true;

global.document = {
    getElementById(id) {
        return elements[id];
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
            data: new Blob(["audio"], {type: this.mimeType}),
        });
        this.listeners.get("stop")();
    }
}
global.MediaRecorder = FakeMediaRecorder;

let typedSessionId;
let voiceSessionId;
let clearedSessionId;
let clearCalls = 0;
let resolveClear;
let holdClearRequest = false;

global.fetch = async (url, options) => {
    if (url.endsWith("/api/chat")) {
        typedSessionId = JSON.parse(options.body).session_id;
        return {
            ok: true,
            async json() {
                return {
                    response: "नमस्ते सौरव।",
                    generation_time_ms: 5,
                    memory_turns: 1,
                };
            },
        };
    }

    if (url.endsWith("/api/voice/respond")) {
        voiceSessionId = options.body.get("session_id");
        return {
            ok: true,
            async json() {
                return {
                    transcript: "मेरा नाम क्या है?",
                    response: "आपका नाम सौरव है।",
                    audio_url: "/generated-audio/tts-0123456789abcdef0123456789abcdef.wav",
                    memory_turns: 2,
                    timing: {
                        transcription_ms: 10,
                        language_model_ms: 5,
                        text_to_speech_ms: 2,
                        total_ms: 15,
                    },
                };
            },
        };
    }

    if (url.endsWith("/api/conversation/clear")) {
        clearCalls += 1;
        clearedSessionId = JSON.parse(options.body).session_id;
        if (holdClearRequest) {
            return new Promise((resolve) => {
                resolveClear = resolve;
            });
        }
        return {ok: true, async json() { return {cleared: true}; }};
    }

    throw new Error(`Unexpected URL: ${url}`);
};

require("./app.js");


async function run() {
    const firstStoredSessionId = sessionValues.get(
        "hindiVoiceAgentSessionId"
    );
    assert.ok(firstStoredSessionId);

    elements.chatInput.value = "मेरा नाम सौरव है।";
    await elements.chatButton.click();

    await elements.recordButton.click();
    await elements.recordButton.click();
    await elements.voiceAgentButton.click();

    assert.equal(typedSessionId, firstStoredSessionId);
    assert.equal(voiceSessionId, firstStoredSessionId);
    assert.match(elements.voiceResponseText.textContent, /सौरव/);
    assert.match(elements.conversationStatus.textContent, /2 remembered turns/);

    holdClearRequest = true;
    const firstClear = elements.clearConversationButton.click();
    await Promise.resolve();
    await elements.clearConversationButton.click();
    assert.equal(clearCalls, 1);

    resolveClear({
        ok: true,
        async json() {
            return {status: "success", cleared: true};
        },
    });
    await firstClear;

    const newStoredSessionId = sessionValues.get(
        "hindiVoiceAgentSessionId"
    );
    assert.equal(clearedSessionId, firstStoredSessionId);
    assert.notEqual(newStoredSessionId, firstStoredSessionId);
    assert.equal(elements.chatResult.hidden, true);
    assert.equal(elements.voiceAgentResult.hidden, true);
    assert.equal(elements.clearConversationButton.disabled, false);
    assert.match(elements.conversationStatus.textContent, /New conversation/);

    console.log("Typed and voice requests share one tab session: PASS");
    console.log("Clear rotates session, clears UI, and blocks duplicates: PASS");
}


run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
