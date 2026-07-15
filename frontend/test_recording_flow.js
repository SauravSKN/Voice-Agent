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
        const listener = this.listeners.get("click");
        if (listener) {
            await listener();
        }
    }

    pause() {}

    load() {}

    async play() {}
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
    "ttsVoice",
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
elements.ttsVoice.value = "piper";
elements.recordButton.textContent = "Start Recording";
elements.recordingResult.hidden = true;
elements.transcriptResult.hidden = true;
elements.voiceAgentResult.hidden = true;

global.document = {
    getElementById(id) {
        return elements[id];
    },
};

const sampleAudio = new Uint8Array([26, 69, 223, 163, 1, 2, 3, 4]);

const fakeTrack = {
    stopped: false,
    stop() {
        this.stopped = true;
    },
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
    constructor(stream) {
        this.listeners = new Map();
        this.mimeType = "audio/webm";
        this.state = "inactive";
        this.stream = stream;
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
            data: new Blob([sampleAudio], {type: this.mimeType}),
        });
        this.listeners.get("stop")();
    }
}

global.MediaRecorder = FakeMediaRecorder;

let uploadedAudio;
global.fetch = async (url, options) => {
    assert.equal(url, "http://127.0.0.1:8000/api/transcribe");
    assert.equal(options.method, "POST");
    uploadedAudio = options.body.get("audio");
    return {
        ok: true,
        async json() {
            return {
                status: "transcribed",
                raw_transcript:
                    "\u0939\u093f\u0902\u0926\u0940 \u0935\u0949\u0907\u0938 " +
                    "\u090f\u091c\u0947\u0902\u091f",
                transcript:
                    "\u0939\u093f\u0902\u0926\u0940 \u0935\u0949\u0907\u0938 " +
                    "\u090f\u091c\u0947\u0902\u091f",
                size_bytes: sampleAudio.byteLength,
            };
        },
    };
};

if (!URL.createObjectURL) {
    URL.createObjectURL = () => "blob:test-recording";
    URL.revokeObjectURL = () => {};
}

require("./app.js");


async function run() {
    await elements.recordButton.click();
    assert.equal(elements.status.textContent, "Status: Recording...");
    assert.equal(elements.recordButton.textContent, "Stop Recording");

    await elements.recordButton.click();
    assert.equal(fakeTrack.stopped, true);
    assert.equal(elements.recordingResult.hidden, false);
    assert.equal(elements.recordButton.textContent, "Start Recording");

    await elements.uploadButton.click();
    assert.ok(uploadedAudio instanceof Blob);
    assert.ok(uploadedAudio.size > 0);
    assert.equal(elements.transcriptResult.hidden, false);
    assert.equal(elements.status.textContent, "Status: Transcription complete.");
    assert.match(elements.transcriptText.textContent, /हिंदी वॉइस एजेंट/);

    console.log("Recording -> POST /api/transcribe -> Hindi DOM display: PASS");
    console.log(`Displayed transcript: ${elements.transcriptText.textContent}`);
}


run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
