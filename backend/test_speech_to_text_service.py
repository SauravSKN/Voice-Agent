import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main as main_module
from app.services.speech_to_text import (
    EmptyAudioError,
    ModelInitializationError,
    NoSpeechDetectedError,
    SpeechToTextService,
    TranscriptionError,
    WhisperConfigurationError,
)


class FakeModel:
    def __init__(self, texts=None, error=None):
        self.texts = texts or []
        self.error = error

    def transcribe(self, *_args, **_kwargs):
        if self.error:
            raise self.error

        segments = (
            SimpleNamespace(text=text)
            for text in self.texts
        )
        information = SimpleNamespace(
            language="hi",
            language_probability=0.99,
        )
        return segments, information


class RecordingModelFactory:
    def __init__(self, failing_devices=None):
        self.calls = []
        self.failing_devices = set(failing_devices or [])

    def __call__(self, model_name, *, device, compute_type):
        self.calls.append((model_name, device, compute_type))

        if device in self.failing_devices:
            raise RuntimeError(f"{device} initialization failed")

        return FakeModel(texts=["test transcript"])


def make_service(model):
    service = SpeechToTextService.__new__(SpeechToTextService)
    service.model = model
    return service


class SpeechToTextServiceTests(unittest.TestCase):
    def test_api_service_is_cached_once(self):
        cached_service = object()
        main_module.get_speech_service.cache_clear()

        try:
            with patch.object(
                main_module,
                "SpeechToTextService",
                return_value=cached_service,
            ) as service_factory:
                first_service = main_module.get_speech_service()
                second_service = main_module.get_speech_service()

            self.assertIs(first_service, cached_service)
            self.assertIs(second_service, cached_service)
            service_factory.assert_called_once_with()
        finally:
            main_module.get_speech_service.cache_clear()

    def test_explicit_cpu_selection(self):
        factory = RecordingModelFactory()
        environment = {
            "WHISPER_MODEL": "medium",
            "WHISPER_DEVICE": "cpu",
            "WHISPER_COMPUTE_TYPE": "int8",
            "WHISPER_ALLOW_CPU_FALLBACK": "true",
        }

        with patch.dict(os.environ, environment, clear=True):
            service = SpeechToTextService(
                model_factory=factory,
                cuda_device_count_getter=lambda: 1,
            )

        self.assertEqual(factory.calls, [("medium", "cpu", "int8")])
        self.assertEqual(service.actual_device, "cpu")
        self.assertEqual(service.actual_compute_type, "int8")

    def test_successful_cuda_selection(self):
        factory = RecordingModelFactory()
        environment = {
            "WHISPER_MODEL": "medium",
            "WHISPER_DEVICE": "cuda",
            "WHISPER_COMPUTE_TYPE": "float16",
            "WHISPER_ALLOW_CPU_FALLBACK": "false",
        }

        with patch.dict(os.environ, environment, clear=True):
            service = SpeechToTextService(
                model_factory=factory,
                cuda_device_count_getter=lambda: 1,
            )

        self.assertEqual(factory.calls, [("medium", "cuda", "float16")])
        self.assertEqual(service.actual_device, "cuda")
        self.assertEqual(service.actual_compute_type, "float16")

    def test_cuda_requested_but_unavailable(self):
        factory = RecordingModelFactory()
        environment = {
            "WHISPER_MODEL": "medium",
            "WHISPER_DEVICE": "cuda",
            "WHISPER_COMPUTE_TYPE": "float16",
            "WHISPER_ALLOW_CPU_FALLBACK": "false",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ModelInitializationError,
                "detected no CUDA devices",
            ):
                SpeechToTextService(
                    model_factory=factory,
                    cuda_device_count_getter=lambda: 0,
                )

        self.assertEqual(factory.calls, [])

    def test_cpu_fallback_enabled(self):
        factory = RecordingModelFactory(failing_devices={"cuda"})
        environment = {
            "WHISPER_MODEL": "medium",
            "WHISPER_DEVICE": "cuda",
            "WHISPER_COMPUTE_TYPE": "float16",
            "WHISPER_ALLOW_CPU_FALLBACK": "true",
        }

        with patch.dict(os.environ, environment, clear=True):
            service = SpeechToTextService(
                model_factory=factory,
                cuda_device_count_getter=lambda: 1,
            )

        self.assertEqual(
            factory.calls,
            [
                ("medium", "cuda", "float16"),
                ("medium", "cpu", "int8"),
            ],
        )
        self.assertEqual(service.actual_device, "cpu")
        self.assertEqual(service.actual_compute_type, "int8")

    def test_cpu_fallback_disabled(self):
        factory = RecordingModelFactory(failing_devices={"cuda"})
        environment = {
            "WHISPER_MODEL": "medium",
            "WHISPER_DEVICE": "cuda",
            "WHISPER_COMPUTE_TYPE": "float16",
            "WHISPER_ALLOW_CPU_FALLBACK": "false",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ModelInitializationError,
                "could not initialize on CUDA",
            ):
                SpeechToTextService(
                    model_factory=factory,
                    cuda_device_count_getter=lambda: 1,
                )

        self.assertEqual(factory.calls, [("medium", "cuda", "float16")])

    def test_invalid_configuration(self):
        invalid_environments = [
            {
                "WHISPER_MODEL": "medium",
                "WHISPER_DEVICE": "gpu",
                "WHISPER_COMPUTE_TYPE": "float16",
                "WHISPER_ALLOW_CPU_FALLBACK": "true",
            },
            {
                "WHISPER_MODEL": "medium",
                "WHISPER_DEVICE": "cpu",
                "WHISPER_COMPUTE_TYPE": "float16",
                "WHISPER_ALLOW_CPU_FALLBACK": "true",
            },
            {
                "WHISPER_MODEL": "medium",
                "WHISPER_DEVICE": "cuda",
                "WHISPER_COMPUTE_TYPE": "not-a-compute-type",
                "WHISPER_ALLOW_CPU_FALLBACK": "true",
            },
            {
                "WHISPER_MODEL": " ",
                "WHISPER_DEVICE": "cpu",
                "WHISPER_COMPUTE_TYPE": "int8",
                "WHISPER_ALLOW_CPU_FALLBACK": "true",
            },
            {
                "WHISPER_MODEL": "medium",
                "WHISPER_DEVICE": "cpu",
                "WHISPER_COMPUTE_TYPE": "int8",
                "WHISPER_ALLOW_CPU_FALLBACK": "sometimes",
            },
        ]

        for environment in invalid_environments:
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(WhisperConfigurationError):
                        SpeechToTextService(
                            model_factory=RecordingModelFactory(),
                            cuda_device_count_getter=lambda: 1,
                        )

    def test_conservative_common_error_corrections(self):
        clean = SpeechToTextService.correct_common_errors

        self.assertEqual(clean("में एक वॉइस एजेंट हूँ"), "मैं एक वॉइस एजेंट हूँ")
        self.assertEqual(clean("और में एक एजेंट हूँ"), "और मैं एक एजेंट हूँ")
        self.assertEqual(clean("घर में एक कमरा है"), "घर में एक कमरा है")
        self.assertEqual(clean("हिंदी एजेंड"), "हिंदी वॉइस एजेंट")
        self.assertEqual(clean("हिंदी एजेंट"), "हिंदी वॉइस एजेंट")
        self.assertEqual(clean("मेरो नाम अमित है"), "मेरा नाम अमित है")
        self.assertEqual(clean("मेरो नाम अमित हो"), "मेरो नाम अमित हो")
        self.assertEqual(clean("मेरो साथी नेपाली हैं"), "मेरो साथी नेपाली हैं")

    def test_missing_audio(self):
        service = make_service(FakeModel())

        with self.assertRaises(FileNotFoundError):
            service.transcribe(Path("missing-audio.webm"))

    def test_empty_audio(self):
        service = make_service(FakeModel())

        with tempfile.NamedTemporaryFile() as audio_file:
            with self.assertRaises(EmptyAudioError):
                service.transcribe(Path(audio_file.name))

    def test_silence(self):
        service = make_service(FakeModel(texts=[]))

        with tempfile.NamedTemporaryFile() as audio_file:
            audio_file.write(b"not-empty")
            audio_file.flush()

            with self.assertRaises(NoSpeechDetectedError):
                service.transcribe(Path(audio_file.name))

    def test_transcription_error(self):
        service = make_service(FakeModel(error=RuntimeError("decoder failed")))

        with tempfile.NamedTemporaryFile() as audio_file:
            audio_file.write(b"not-empty")
            audio_file.flush()

            with self.assertRaisesRegex(TranscriptionError, "decoder failed"):
                service.transcribe(Path(audio_file.name))

    def test_returns_cleaned_transcript(self):
        service = make_service(FakeModel(texts=[" में एक ", " एजेंट हूँ "]))

        with tempfile.NamedTemporaryFile() as audio_file:
            audio_file.write(b"not-empty")
            audio_file.flush()

            self.assertEqual(
                service.transcribe(Path(audio_file.name)),
                "मैं एक एजेंट हूँ",
            )


if __name__ == "__main__":
    unittest.main()
