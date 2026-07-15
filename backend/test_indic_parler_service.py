import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.indic_parler_service import (
    IndicParlerRuntime,
    IndicParlerWorkerSettings,
    ModelBundle,
    WorkerConfigurationError,
    WorkerModelError,
    _description_for,
)


class IndicParlerWorkerTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"INDIC_PARLER_MODEL": "arbitrary/model"},
            clear=True,
        ):
            with self.assertRaises(WorkerConfigurationError):
                IndicParlerWorkerSettings.from_environment()

    def test_cuda_unavailable_without_fallback_fails_clearly(self) -> None:
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False)
        )
        with (
            patch.dict(
                os.environ,
                {
                    "INDIC_PARLER_DEVICE": "cuda",
                    "INDIC_PARLER_DTYPE": "float16",
                    "INDIC_PARLER_ALLOW_CPU_FALLBACK": "false",
                },
                clear=True,
            ),
            patch.dict(sys.modules, {"torch": fake_torch}),
        ):
            runtime = IndicParlerRuntime()
            with self.assertRaisesRegex(WorkerModelError, "no CUDA device"):
                runtime.get_model()

    def test_cuda_unavailable_with_fallback_selects_cpu(self) -> None:
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False)
        )
        bundle = ModelBundle(
            model=object(),
            prompt_tokenizer=object(),
            description_tokenizer=object(),
            torch=fake_torch,
            numpy=object(),
            actual_device="cpu",
            sample_rate=24000,
            model_loading_ms=5,
        )
        with (
            patch.dict(
                os.environ,
                {
                    "INDIC_PARLER_DEVICE": "cuda",
                    "INDIC_PARLER_DTYPE": "float16",
                    "INDIC_PARLER_ALLOW_CPU_FALLBACK": "true",
                },
                clear=True,
            ),
            patch.dict(sys.modules, {"torch": fake_torch}),
        ):
            runtime = IndicParlerRuntime()
            with patch.object(
                runtime,
                "_load_on_device",
                return_value=bundle,
            ) as loader:
                selected, loaded_now = runtime.get_model()

        loader.assert_called_once_with("cpu")
        self.assertIs(selected, bundle)
        self.assertTrue(loaded_now)

    def test_configured_description_is_not_reused_for_other_speaker(self) -> None:
        settings = IndicParlerWorkerSettings(
            model_name="ai4bharat/indic-parler-tts",
            requested_device="cuda",
            dtype="float16",
            configured_speaker="Divya",
            description="Divya custom description.",
            max_input_chars=500,
            allow_cpu_fallback=False,
        )
        self.assertEqual(
            _description_for("Divya", "configured", settings),
            "Divya custom description.",
        )
        self.assertIn(
            "Rohit speaks in a calm, friendly and natural Hindi voice",
            _description_for("Rohit", "configured", settings),
        )


if __name__ == "__main__":
    unittest.main()
