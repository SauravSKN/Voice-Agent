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
        this.pauseCalls = 0;
        this.loadCalls = 0;
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

    pause() {
        this.pauseCalls += 1;
    }

    load() {
        this.loadCalls += 1;
    }

    async play() {}

    dispatch(eventName) {
        const listener = this.listeners.get(eventName);
        if (listener) {
            listener();
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
elements.playResponseButton.hidden = true;
elements.replayResponseButton.hidden = true;

global.document = {
    getElementById(id) {
        return elements[id];
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

let playAttempts = 0;
elements.responseAudioPlayer.play = async function () {
    playAttempts += 1;
    if (playAttempts === 1) {
        const error = new Error("autoplay blocked");
        error.name = "NotAllowedError";
        throw error;
    }
    this.dispatch("playing");
};

global.fetch = async (url) => {
    assert.equal(url, "http://127.0.0.1:8000/api/voice/respond");
    return {
        ok: true,
        async json() {
            return {
                status: "success",
                transcript: "भारत की राजधानी क्या है?",
                response: "भारत की राजधानी नई दिल्ली है।",
                audio_url:
                    "/generated-audio/tts-0123456789abcdef0123456789abcdef.wav",
                memory_turns: 1,
                timing: {
                    transcription_ms: 3000,
                    language_model_ms: 1200,
                    text_to_speech_ms: 900,
                    total_ms: 5100,
                },
            };
        },
    };
};

require("./app.js");


async function run() {
    await elements.recordButton.click();
    await elements.recordButton.click();
    await elements.voiceAgentButton.click();

    assert.equal(playAttempts, 1);
    assert.equal(elements.voiceAgentResult.hidden, false);
    assert.equal(elements.playResponseButton.hidden, false);
    assert.equal(elements.replayResponseButton.hidden, false);
    assert.match(elements.voiceAgentStatus.textContent, /press Play Response/);
    assert.match(elements.responseAudioPlayer.src, /^http:\/\/127\.0\.0\.1:8000/);

    await elements.playResponseButton.click();
    assert.equal(playAttempts, 2);
    assert.match(elements.voiceAgentStatus.textContent, /Playing response/);

    elements.responseAudioPlayer.currentTime = 8;
    await elements.replayResponseButton.click();
    assert.equal(playAttempts, 3);
    assert.equal(elements.responseAudioPlayer.currentTime, 0);

    elements.responseAudioPlayer.dispatch("ended");
    assert.equal(
        elements.voiceAgentStatus.textContent,
        "Voice agent status: Complete"
    );

    elements.responseAudioPlayer.dispatch("error");
    assert.match(elements.voiceAgentStatus.textContent, /audio is unavailable/);
    assert.equal(elements.playResponseButton.hidden, true);
    assert.equal(elements.replayResponseButton.hidden, true);

    const pausesBeforeNewRecording = elements.responseAudioPlayer.pauseCalls;
    await elements.recordButton.click();
    assert.ok(
        elements.responseAudioPlayer.pauseCalls > pausesBeforeNewRecording
    );
    assert.equal(elements.responseAudioPlayer.src, "");

    console.log("Autoplay fallback and Play Response: PASS");
    console.log("Replay, completion, stale-audio error, and reset: PASS");
}


run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
