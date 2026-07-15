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
elements.recordingResult.hidden = true;
elements.transcriptResult.hidden = true;
elements.voiceAgentResult.hidden = true;
elements.chatResult.hidden = true;

global.document = {
    getElementById(id) {
        return elements[id];
    },
};

require("./app.js");


async function run() {
    const realFetch = global.fetch;

    elements.chatInput.value = "भारत की राजधानी क्या है?";

    await elements.chatButton.click();

    assert.equal(elements.chatResult.hidden, false);
    assert.match(elements.chatResponse.textContent, /नई दिल्ली/);
    assert.match(elements.chatStatus.textContent, /Response received/);
    assert.equal(elements.chatButton.disabled, false);

    console.log("Typed Hindi -> POST /api/chat -> Hindi DOM display: PASS");
    console.log(`Displayed response: ${elements.chatResponse.textContent}`);

    elements.chatInput.value = "   ";
    await elements.chatButton.click();
    assert.match(elements.chatStatus.textContent, /Enter a message/);

    let fetchCalls = 0;
    let finishRequest;
    global.fetch = async () => {
        fetchCalls += 1;
        return new Promise((resolve) => {
            finishRequest = resolve;
        });
    };
    elements.chatInput.value = "नमस्ते";
    const firstClick = elements.chatButton.click();
    await Promise.resolve();
    await elements.chatButton.click();
    assert.equal(fetchCalls, 1);
    finishRequest({
        ok: true,
        async json() {
            return {
                response: "नमस्ते!",
                generation_time_ms: 10,
            };
        },
    });
    await firstClick;

    global.fetch = async () => ({
        ok: false,
        async json() {
            return {detail: "The configured local language model is unavailable."};
        },
    });
    elements.chatInput.value = "मॉडल जाँच";
    await elements.chatButton.click();
    assert.match(elements.chatStatus.textContent, /model is unavailable/);

    global.fetch = async () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        throw error;
    };
    elements.chatInput.value = "समय जाँच";
    await elements.chatButton.click();
    assert.match(elements.chatStatus.textContent, /timed out/);

    global.fetch = async () => {
        throw new TypeError("backend unavailable");
    };
    elements.chatInput.value = "बैकएंड जाँच";
    await elements.chatButton.click();
    assert.match(elements.chatStatus.textContent, /backend unavailable/);

    global.fetch = realFetch;
    console.log(
        "Empty, duplicate, unavailable, timeout, and backend-error states: PASS"
    );
}


run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
