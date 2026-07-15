import os
import tempfile
import time
import unittest
import wave
from pathlib import Path

from app.services.text_to_speech import (
    EmptyTextToSpeechOutputError,
    InvalidTextToSpeechInputError,
    TextToSpeechConfigurationError,
    TextToSpeechGenerationError,
    TextToSpeechModelLoadingError,
    TextToSpeechService,
    TextToSpeechSettings,
    is_safe_audio_filename,
)


class FakeVoice:
    def __init__(self, *, fail: bool = False, empty: bool = False) -> None:
        self.fail = fail
        self.empty = empty
        self.calls = 0

    def synthesize_wav(self, text, wav_file) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthesis failed")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        if not self.empty:
            wav_file.writeframes(b"\x00\x00" * 100)


class VoiceFactory:
    def __init__(self, voice: FakeVoice, *, fail_cuda: bool = False) -> None:
        self.voice = voice
        self.fail_cuda = fail_cuda
        self.calls = []

    def __call__(self, model_path, *, config_path, use_cuda):
        self.calls.append(use_cuda)
        if use_cuda and self.fail_cuda:
            raise RuntimeError("cuda load failed")
        return self.voice


class TextToSpeechServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.model_path = self.root / "voice.onnx"
        self.model_path.write_bytes(b"model")
        Path(f"{self.model_path}.json").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def settings(self, **overrides) -> TextToSpeechSettings:
        values = {
            "provider": "piper",
            "model_path": self.model_path,
            "requested_device": "cpu",
            "output_format": "wav",
            "max_input_chars": 50,
            "allow_cpu_fallback": True,
            "timeout_seconds": 60.0,
            "output_ttl_minutes": 60,
            "max_output_files": 2,
        }
        values.update(overrides)
        return TextToSpeechSettings(**values)

    def service(self, voice=None, factory=None, **settings_overrides):
        selected_voice = voice or FakeVoice()
        selected_factory = factory or VoiceFactory(selected_voice)
        service = TextToSpeechService(
            self.settings(**settings_overrides),
            voice_factory=selected_factory,
            provider_getter=lambda: ["CPUExecutionProvider"],
            output_directory=self.root / "output",
        )
        return service, selected_voice, selected_factory

    def test_blank_input_is_rejected(self) -> None:
        service, _, _ = self.service()
        with self.assertRaises(InvalidTextToSpeechInputError):
            service.generate("   ")

    def test_excessive_input_is_rejected(self) -> None:
        service, _, _ = self.service(max_input_chars=5)
        with self.assertRaises(InvalidTextToSpeechInputError):
            service.generate("123456")

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaises(TextToSpeechConfigurationError):
            TextToSpeechSettings.from_environment(
                {"TTS_PROVIDER": "unknown"},
                base_directory=self.root,
            )

    def test_missing_model_is_reported(self) -> None:
        with self.assertRaises(TextToSpeechModelLoadingError):
            TextToSpeechService(
                self.settings(model_path=self.root / "missing.onnx"),
                voice_factory=VoiceFactory(FakeVoice()),
                provider_getter=lambda: ["CPUExecutionProvider"],
                output_directory=self.root / "output",
            )

    def test_generation_failure_removes_partial_output(self) -> None:
        service, _, _ = self.service(voice=FakeVoice(fail=True))
        with self.assertRaises(TextToSpeechGenerationError):
            service.generate("नमस्ते")
        self.assertEqual([], list(service.output_directory.iterdir()))

    def test_empty_output_is_rejected_and_removed(self) -> None:
        service, _, _ = self.service(voice=FakeVoice(empty=True))
        with self.assertRaises(EmptyTextToSpeechOutputError):
            service.generate("नमस्ते")
        self.assertEqual([], list(service.output_directory.iterdir()))

    def test_safe_unique_filename_and_valid_wav(self) -> None:
        service, _, _ = self.service()
        first = service.generate("नमस्ते")
        second = service.generate("फिर मिलेंगे")
        self.assertNotEqual(first.filename, second.filename)
        self.assertTrue(is_safe_audio_filename(first.filename))
        self.assertEqual(service.output_directory, first.file_path.parent)
        with wave.open(str(first.file_path), "rb") as wav_file:
            self.assertGreater(wav_file.getnframes(), 0)

    def test_model_is_loaded_once_and_reused(self) -> None:
        factory = VoiceFactory(FakeVoice())
        service, _, _ = self.service(factory=factory)
        service.generate("पहला")
        service.generate("दूसरा")
        self.assertEqual([False], factory.calls)
        self.assertEqual(2, factory.voice.calls)

    def test_generation_enforces_output_file_cap(self) -> None:
        service, _, _ = self.service(max_output_files=2)
        first = service.generate("पहला")
        service.generate("दूसरा")
        service.generate("तीसरा")

        self.assertFalse(first.file_path.exists())
        self.assertEqual(
            2,
            len(list(service.output_directory.glob("tts-*.wav"))),
        )

    def test_cuda_request_falls_back_to_cpu(self) -> None:
        factory = VoiceFactory(FakeVoice())
        service = TextToSpeechService(
            self.settings(requested_device="cuda"),
            voice_factory=factory,
            provider_getter=lambda: ["CPUExecutionProvider"],
            output_directory=self.root / "output",
        )
        self.assertEqual("cpu", service.actual_device)
        self.assertEqual([False], factory.calls)

    def test_cuda_request_without_fallback_fails_clearly(self) -> None:
        with self.assertRaises(TextToSpeechModelLoadingError):
            TextToSpeechService(
                self.settings(
                    requested_device="cuda",
                    allow_cpu_fallback=False,
                ),
                voice_factory=VoiceFactory(FakeVoice()),
                provider_getter=lambda: ["CPUExecutionProvider"],
                output_directory=self.root / "output",
            )

    def test_cuda_load_failure_retries_cpu_once(self) -> None:
        factory = VoiceFactory(FakeVoice(), fail_cuda=True)
        service = TextToSpeechService(
            self.settings(requested_device="cuda"),
            voice_factory=factory,
            provider_getter=lambda: [
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ],
            output_directory=self.root / "output",
        )
        self.assertEqual("cpu", service.actual_device)
        self.assertEqual([True, False], factory.calls)

    def test_cleanup_removes_expired_and_excess_files(self) -> None:
        service, _, _ = self.service(
            output_ttl_minutes=1,
            max_output_files=2,
        )
        expired = service.output_directory / (
            "tts-00000000000000000000000000000001.wav"
        )
        old = service.output_directory / (
            "tts-00000000000000000000000000000002.wav"
        )
        newest = service.output_directory / (
            "tts-00000000000000000000000000000003.wav"
        )
        ignored = service.output_directory / "notes.txt"
        for path in (expired, old, newest, ignored):
            path.write_bytes(b"data")
        now = time.time()
        os.utime(expired, (now - 120, now - 120))
        os.utime(old, (now - 20, now - 20))
        os.utime(newest, (now - 10, now - 10))

        removed = service.cleanup_generated_audio(current_time=now)

        self.assertEqual(1, removed)
        self.assertFalse(expired.exists())
        self.assertTrue(old.exists())
        self.assertTrue(newest.exists())
        self.assertTrue(ignored.exists())


if __name__ == "__main__":
    unittest.main()
