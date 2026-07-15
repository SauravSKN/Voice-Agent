# Licence notices

This document is an engineering inventory, not legal advice or a guarantee. Verify upstream terms and the intended use before distribution.

## Project source code

No project-level `LICENSE` file has been selected. Therefore the owner has not granted a general open-source licence for this project's original source. Choose and add a suitable source-code licence before public redistribution; do not assume third-party permissive licences automatically cover this repository's original code.

## Speech-to-Text

- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) is MIT-licensed.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) is MIT-licensed.
- Other installed dependencies (including PyAV, tokenizers, ONNX Runtime, FastAPI, and their transitive packages) retain their individual notices. A distributor must review the installed package metadata and include notices as their licences require.
- Whisper model weights have their own upstream model/data terms and are downloaded/cached separately; they are not part of this repository.

## Language model

- [Ollama's open-source repository](https://github.com/ollama/ollama/blob/main/LICENSE) uses the MIT licence; separately distributed app components may have additional terms, so use the licence supplied with the installed version.
- The exact [Ollama `qwen3:4b-instruct` entry](https://ollama.com/library/qwen3%3A4b-instruct) reports Apache License 2.0 for that model artifact.
- Ollama model blobs are downloaded independently and must not be copied into this repository.

## Text-to-Speech

- The current [OHF-Voice Piper runtime](https://github.com/OHF-Voice/piper1-gpl) is GPL-3.0. Distribution of a package containing or linking it requires a separate GPL compliance review.
- The `rhasspy/piper-voices` repository is labelled MIT, but each voice model can have more restrictive dataset/model-card terms. Upstream explicitly directs users to review each voice's model card.
- The selected [Priyamvada model card](https://huggingface.co/rhasspy/piper-voices/blob/main/hi/hi_IN/priyamvada/medium/MODEL_CARD) identifies the training dataset licence as **CC BY-NC-SA 4.0**.

### Selected voice warning

`hi_IN-priyamvada-medium` must be treated as non-commercial/share-alike material unless qualified legal advice establishes otherwise for a particular use. Attribution and licence/share-alike obligations may apply. The model binary and config are therefore excluded by `.gitignore` and must be downloaded by each developer after reviewing the terms.

Do not describe the entire project as MIT merely because the voices repository page has an MIT label. Runtime code, repository code, model artifacts, and training dataset terms are separate layers.
