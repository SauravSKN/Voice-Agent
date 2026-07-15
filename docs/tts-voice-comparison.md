# Hindi TTS voice comparison

Status: real GPU generation, automated validation, API validation, resource coexistence testing, and browser flow validation completed on 2026-07-15. Human listening remains pending, so no subjective winner is declared.

Piper Priyamvada remains the operational default and fallback. Divya and Rohit are fixed optional voices. This decision is based on measured latency and stability, not an unperformed listening comparison.

## Validated configuration

- GPU: NVIDIA GeForce RTX 5050 Laptop GPU, 8151 MiB total VRAM.
- Indic model: `ai4bharat/indic-parler-tts`, CUDA, `float16`, isolated in `.venv-indic-parler` behind `http://127.0.0.1:8002`.
- Main environment: Faster-Whisper and Piper remain unchanged; the safe default keeps Faster-Whisper on CPU with `int8`.
- Indic runtime: official matched PyTorch 2.11.0/torchaudio 2.11.0 CUDA 13.0 wheel set. No system-wide CUDA toolkit or administrator installation was required.
- Authentication: local Hugging Face authentication succeeded. Tokens are not stored in the repository or printed by project code.
- Loaded Indic worker system working set: approximately 1.92 GB. Whole-GPU telemetry is used for VRAM because Windows WDDM returned per-process memory as unavailable.

Sources: [AI4Bharat model card](https://huggingface.co/ai4bharat/indic-parler-tts), [official Parler-TTS repository](https://github.com/huggingface/parler-tts), [official PyTorch installation matrix](https://pytorch.org/get-started/previous-versions/).

## Listening and engineering comparison

| Voice | Naturalness | Clarity | Hindi pronunciation | Names | Hinglish | Pace | Pauses | Robotic quality | Cold load | Warm synthesis (five-sentence average) | RAM/VRAM | Licence | Stability |
|---|---|---|---|---|---|---|---|---|---:|---:|---|---|---|
| Piper Priyamvada | Pending human listening | Pending | Pending | Pending | Pending | Pending | Pending | Pending | 2.298 s | 0.197 s (0.122-0.241 s) | CPU; 0 MiB GPU | Voice dataset/model card: CC BY-NC-SA 4.0; see `docs/licenses.md` | 5/5 WAV and FFprobe checks passed; retained as default/fallback |
| Indic Parler Divya | Pending human listening | Pending | Pending | Pending | Pending | Moderate requested | Natural conversational pauses requested | Pending | 64.381 s first retrieval/load; 57.986 s cached cold load | 9.796 s (6.957-11.606 s) | ~1.92 GB worker RAM; 2.64 GiB observed whole-GPU matrix peak | Apache-2.0 model/repository | 5/5 WAV and FFprobe checks passed; real API and browser provider metadata passed |
| Indic Parler Rohit | Pending human listening | Pending | Pending | Pending | Pending | Moderate requested | Small natural pauses requested | Pending | Shared cached model | 9.709 s (6.315-13.650 s) | Shares worker/model; 2.64 GiB observed whole-GPU matrix peak | Apache-2.0 model/repository | 5/5 WAV and FFprobe checks passed; real API and browser provider metadata passed |

No naturalness, pronunciation, Hinglish, names, or robotic-quality claim is made until a person listens to the generated files in `backend/generated_audio/comparisons`.

## Fixed test material

Piper, Divya, and Rohit were generated with the same five sentences:

1. नमस्ते, मैं आपका हिंदी एआई सहायक हूँ।
2. भारत की राजधानी नई दिल्ली है।
3. सौरव, आपका स्वागत है। मैं आपकी कैसे सहायता कर सकता हूँ?
4. कृपया एक क्षण रुकिए। मैं आपकी बात समझने की कोशिश कर रहा हूँ।
5. आपकी बैठक आज शाम पाँच बजकर तीस मिनट पर है।

Divya description:

> Divya speaks in a warm, natural and conversational Hindi voice. Her pace is moderate, her pitch is balanced, and her speech is slightly expressive. The recording is clear and close, with no background noise.

Rohit description:

> Rohit speaks in a calm, friendly and natural Hindi voice. His pace is moderate, his pronunciation is clear, and he uses small natural pauses. The recording is clear and close, with no background noise.

Extreme emotion, artificial pitch, voice cloning, reference audio, arbitrary browser descriptions, and arbitrary model names are unsupported.

## Measured generation results

All 15 WAV files passed Python `wave` validation and FFprobe inspection.

| Voice | Synthesis times, seconds | Audio durations, seconds | Real-time factor |
|---|---|---|---|
| Piper | 0.241, 0.122, 0.219, 0.228, 0.176 | 3.471, 2.624, 4.818, 4.934, 4.063 | 0.043-0.069 |
| Divya | 10.726, 6.957, 9.950, 11.606, 9.739 | 3.866, 2.694, 4.063, 4.911, 4.191 | 2.324-2.774 |
| Rohit | 9.467, 6.315, 10.096, 13.650, 9.017 | 3.901, 2.519, 4.307, 5.712, 3.762 | 2.344-2.507 |

Matrix telemetry: 2644 MiB whole-GPU peak, 95% maximum utilization, and 12.6% sampled average utilization. The short CUDA bursts make sampled averages and some individual peaks conservative.

## Resource coexistence

| Resource case | Peak GPU memory | Result | Notes |
|---|---:|---|---|
| Indic Parler alone | 2252-2644 MiB | Pass | Real Divya/Rohit generation completed |
| Ollama Qwen 3 4B Instruct + Indic Parler | 5769 MiB | Pass | Divya: 8.447 s synthesis, 2.763 s audio, RTF 3.057; maximum sampled utilization 95% |
| Faster-Whisper medium CUDA `float16` + Ollama Qwen + Indic Parler | 7850/8151 MiB | Functional but unsafe | Whisper loaded on CUDA in 3.704 s and transcribed in 3.235 s; Divya then generated successfully, but only about 301 MiB headroom remained and utilization reached 100% |
| Faster-Whisper CPU `int8` + Ollama GPU + Indic Parler GPU | Safe selected strategy | Recommended | Preserves the proven CPU STT path and avoids three-model VRAM pressure |

The all-GPU case worked once but is not a safe steady-state configuration on an 8 GB laptop GPU. The application therefore keeps CPU Whisper as the reliable default, Ollama on GPU, lazy Indic Parler on GPU, and Piper as fallback.

## API and browser validation

- Real `/api/voice/respond` requests reported `piper / Priyamvada`, `indic_parler / Divya`, and `indic_parler / Rohit` accurately.
- Returned Divya and Rohit URLs served valid `audio/wav` files over HTTP 200 and passed FFprobe.
- With the Indic worker deliberately unavailable, a Divya request fell back and reported `piper / Priyamvada` honestly.
- The live browser selector reached the backend for all three fixed choices. Completed results showed transcript, response, provider/voice metadata, generated audio, and replay controls.
- Replay advanced the audio clock with `paused=false`. Starting a new recording paused playback, reset time to zero, cleared the stale source and transcript/response text, and hid the old result.
- Browser conversation memory correctly returned `आपका नाम सौरव है।` after `मेरा नाम सौरव है।` / `मेरा नाम क्या है?`; New Conversation reset the remembered turns.
- A real microphone WebM was accepted, but the device captured the requested राजधानी sentence inaccurately as `अपने लिए लिए लिए लिए लिए लिए लिए.`. The recording-to-response pipeline succeeded; exact microphone transcription remains an environmental/input-quality limitation and is not recorded as a phrase-recognition pass.

## Human decision record

- Listener: pending
- Date: pending
- Divya result: pending
- Rohit result: pending
- Piper comparison: pending
- Selected operational default: `piper`
- Optional natural voices: `indic_parler_divya`, `indic_parler_rohit`
- Runtime note: Flash Attention 2 is not installed; the validated PyTorch attention path is used instead.
- Warning: client timeout cannot forcibly stop an already-running autoregressive worker generation; keep responses bounded to 500 characters.
