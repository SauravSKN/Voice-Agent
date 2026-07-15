const assert = require("node:assert/strict");


class FakeElement {
    constructor() {
        this.disabled = false;
        this.hidden = false;
        this.listeners = new Map();
        this.src = "";
        this._textContent = "";
        this.textHistory = [];
        this.value = "";
        this.currentTime = 0;
    }

    get textContent() {
        return this._textContent;
    }

    set textContent(value) {
        this._textContent = value;
        this.textHistory.push(value);
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

const fakeTrack = {
    stop() {},
};
const fakeStream = {
    getTracks() {
        return [fakeTrack];
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
            data: new Blob(["recorded-audio"], {type: this.mimeType}),
        });
        this.listeners.get("stop")();
    }
}

global.MediaRecorder = FakeMediaRecorder;

let fetchCalls = 0;
let finishRequest;
global.fetch = async (url) => {
    fetchCalls += 1;
    assert.equal(url, "http://127.0.0.1:8000/api/voice/respond");
    return new Promise((resolve) => {
        finishRequest = resolve;
    });
};

require("./app.js");


async function run() {
    await elements.recordButton.click();
    await elements.recordButton.click();

    const firstRequest = elements.voiceAgentButton.click();
    await Promise.resolve();

    assert.equal(fetchCalls, 1);
    assert.equal(elements.voiceAgentButton.disabled, true);
    assert.ok(
        elements.voiceAgentStatus.textHistory.some(
            (status) => status.includes("Preparing audio")
        )
    );
    assert.ok(
        elements.voiceAgentStatus.textHistory.some(
            (status) => status.includes("Uploading audio")
        )
    );
    assert.match(
        elements.voiceAgentStatus.textContent,
        /Processing speech, generating response, and generating voice/
    );

    await elements.voiceAgentButton.click();
    assert.equal(fetchCalls, 1);

    finishRequest({
        ok: true,
        async json() {
            return {
                status: "success",
                transcript: "भारत की राजधानी क्या है?",
                response: "भारत की राजधानी नई दिल्ली है।",
                audio_url: "/generated-audio/tts-0123456789abcdef0123456789abcdef.wav",
                memory_turns: 1,
                timing: {
                    transcription_ms: 9200,
                    language_model_ms: 1200,
                    text_to_speech_ms: 400,
                    total_ms: 10400,
                },
            };
        },
    });
    await firstRequest;

    assert.equal(elements.voiceAgentResult.hidden, false);
    assert.match(elements.voiceTranscriptText.textContent, /राजधानी/);
    assert.match(elements.voiceResponseText.textContent, /नई दिल्ली/);
    assert.match(elements.voiceTiming.textContent, /10400 ms/);
    assert.match(elements.voiceTiming.textContent, /Text to speech: 400 ms/);
    assert.match(
        elements.responseAudioPlayer.src,
        /generated-audio\/tts-[0-9a-f]{32}\.wav/
    );
    assert.equal(elements.replayResponseButton.hidden, false);
    assert.equal(elements.voiceAgentButton.disabled, false);
    assert.equal(
        elements.voiceAgentStatus.textContent,
        "Voice agent status: Complete"
    );

    global.fetch = async () => ({
        ok: false,
        async json() {
            return {detail: "The local language model is unavailable."};
        },
    });
    await elements.voiceAgentButton.click();
    assert.match(elements.voiceAgentStatus.textContent, /Error/);
    assert.match(elements.voiceAgentStatus.textContent, /unavailable/);
    assert.equal(elements.voiceAgentButton.disabled, false);

    console.log(
        "Recording -> /api/voice/respond -> transcript and response DOM: PASS"
    );
    console.log("Loading, duplicate-click, and backend-error states: PASS");
}


run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
