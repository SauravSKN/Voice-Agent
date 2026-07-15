import argparse
import shutil
import wave
from dataclasses import replace
from pathlib import Path

from app.indic_parler_service import (
    IndicParlerWorkerSettings,
    _description_for,
)
from app.services.text_to_speech import (
    IndicParlerClient,
    TextToSpeechService,
    TextToSpeechSettings,
)
from test_indic_parler_tts import verify_wav


SENTENCES = (
    "नमस्ते, मैं आपका हिंदी एआई सहायक हूँ।",
    "भारत की राजधानी नई दिल्ली है।",
    "सौरव, आपका स्वागत है। मैं आपकी कैसे सहायता कर सकता हूँ?",
    "कृपया एक क्षण रुकिए। मैं आपकी बात समझने की कोशिश कर रहा हूँ।",
    "आपकी बैठक आज शाम पाँच बजकर तीस मिनट पर है।",
)
STYLES = (
    "neutral",
    "warm_friendly",
    "calm_assistant",
    "slightly_expressive",
    "moderate_pace",
    "slightly_slower",
)


def report(
    label: str,
    result,
    destination: Path,
    *,
    description: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.file_path, destination)
    duration, file_size = verify_wav(destination)
    print(f"\n{label}")
    print(f"Provider: {result.provider}")
    print(f"Speaker: {result.voice}")
    print(f"Description: {description}")
    print(f"Model loading time: {result.model_loading_time_ms} ms")
    print(f"Synthesis time: {result.generation_time_ms} ms")
    print(f"Audio duration: {duration:.3f} s")
    print(f"File size: {file_size} bytes")
    print(f"Peak GPU memory: {result.peak_gpu_memory_mb:.1f} MiB")
    print(
        "Real-time factor: "
        f"{(result.generation_time_ms / 1000) / duration:.3f}"
    )
    print("Python WAV validation: PASS; FFprobe validation: PASS")
    print(f"WAV: {destination}")


def run_matrix(settings: TextToSpeechSettings, output: Path) -> None:
    client = IndicParlerClient(
        settings.indic_service_url,
        settings.indic_timeout_seconds,
    )
    worker_settings = IndicParlerWorkerSettings.from_environment()
    for speaker in ("Divya", "Rohit"):
        for sentence_index, sentence in enumerate(SENTENCES, start=1):
            for style in STYLES:
                response = client.synthesize(
                    sentence,
                    speaker=speaker,
                    style=style,
                )
                filename = (
                    f"indic-parler-{speaker.lower()}-"
                    f"sentence-{sentence_index}-{style}.wav"
                )
                path = output / "matrix" / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(response.audio_bytes)
                duration, file_size = verify_wav(path)
                description = _description_for(
                    speaker,
                    style,
                    worker_settings,
                )
                print(
                    f"{speaker} / sentence {sentence_index} / {style}: "
                    f"{response.synthesis_time_ms} ms, {duration:.3f} s, "
                    f"{file_size} bytes, "
                    f"{response.peak_gpu_memory_mb:.1f} MiB"
                )
                print(f"Description: {description}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Generate all 60 bounded speaker/sentence/style samples.",
    )
    arguments = parser.parse_args()

    settings = TextToSpeechSettings.from_environment()
    output = Path(__file__).resolve().parent / "generated_audio" / "comparisons"

    piper_service = TextToSpeechService(
        replace(settings, provider="piper")
    )
    for sentence_index, sentence in enumerate(SENTENCES, start=1):
        piper = piper_service.generate(sentence, "piper")
        piper_name = (
            "piper-divya-equivalent.wav"
            if sentence_index == 1
            else f"piper-sentence-{sentence_index}.wav"
        )
        report(
            f"Piper Priyamvada / sentence {sentence_index}",
            piper,
            output / piper_name,
            description="Piper Priyamvada fixed Hindi voice",
        )

    indic_service = TextToSpeechService(
        replace(
            settings,
            provider="indic_parler",
            allow_piper_fallback=False,
        )
    )
    worker_settings = IndicParlerWorkerSettings.from_environment()
    for speaker in ("Divya", "Rohit"):
        description = _description_for(
            speaker,
            "configured",
            worker_settings,
        )
        for sentence_index, sentence in enumerate(SENTENCES, start=1):
            result = indic_service.generate(
                sentence,
                f"indic_parler_{speaker.lower()}",
            )
            indic_name = (
                f"indic-parler-{speaker.lower()}.wav"
                if sentence_index == 1
                else (
                    f"indic-parler-{speaker.lower()}-"
                    f"sentence-{sentence_index}.wav"
                )
            )
            report(
                f"Indic Parler {speaker} / sentence {sentence_index}",
                result,
                output / indic_name,
                description=description,
            )

    if arguments.matrix:
        run_matrix(settings, output)


if __name__ == "__main__":
    main()
