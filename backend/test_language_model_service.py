import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from app.services.language_model import (
    BlankModelResponseError,
    InvalidLanguageModelInputError,
    LanguageModelConfigurationError,
    LanguageModelService,
    LanguageModelTimeoutError,
    ModelLoadingError,
    ModelServerUnavailableError,
)


VALID_ENVIRONMENT = {
    "LLM_PROVIDER": "ollama",
    "LLM_MODEL": "qwen3:4b-instruct",
    "LLM_BASE_URL": "http://127.0.0.1:11434",
    "LLM_MAX_TOKENS": "160",
    "LLM_TEMPERATURE": "0.4",
    "LLM_TIMEOUT_SECONDS": "60",
    "LLM_MAX_INPUT_CHARS": "2000",
    "LLM_MAX_RESPONSE_CHARS": "1200",
    "LLM_CONTEXT_TOKENS": "4096",
    "LLM_KEEP_ALIVE": "5m",
    "LLM_MAX_HISTORY_MESSAGES": "12",
}


def make_service(
    transport,
    *,
    max_input_chars="2000",
    max_history_messages="12",
):
    environment = dict(VALID_ENVIRONMENT)
    environment["LLM_MAX_INPUT_CHARS"] = max_input_chars
    environment["LLM_MAX_HISTORY_MESSAGES"] = max_history_messages
    with tempfile.TemporaryDirectory() as temporary_directory:
        prompt_path = Path(temporary_directory) / "prompt.txt"
        prompt_path.write_text("Respond briefly in Hindi.", encoding="utf-8")
        with patch.dict(os.environ, environment, clear=True):
            return LanguageModelService(
                transport=transport,
                prompt_path=prompt_path,
            )


class LanguageModelServiceTests(unittest.TestCase):
    def test_blank_input_rejected(self):
        service = make_service(lambda *_args: {})

        with self.assertRaisesRegex(
            InvalidLanguageModelInputError,
            "must not be blank",
        ):
            service.generate("   ")

    def test_excessive_input_rejected(self):
        service = make_service(lambda *_args: {}, max_input_chars="5")

        with self.assertRaisesRegex(
            InvalidLanguageModelInputError,
            "too long",
        ):
            service.generate("123456")

    def test_timeout_mapping(self):
        service = make_service(
            lambda *_args: (_ for _ in ()).throw(TimeoutError("slow"))
        )

        with self.assertRaises(LanguageModelTimeoutError):
            service.generate("नमस्ते")

    def test_unavailable_model_server(self):
        service = make_service(
            lambda *_args: (_ for _ in ()).throw(
                URLError(ConnectionRefusedError("refused"))
            )
        )

        with self.assertRaises(ModelServerUnavailableError):
            service.generate("नमस्ते")

    def test_missing_model_mapping(self):
        error = HTTPError(
            "http://127.0.0.1:11434/api/chat",
            404,
            "not found",
            {},
            None,
        )
        service = make_service(
            lambda *_args: (_ for _ in ()).throw(error)
        )

        with self.assertRaises(ModelLoadingError):
            service.generate("नमस्ते")

    def test_blank_model_response(self):
        service = make_service(
            lambda *_args: {"message": {"content": "   "}}
        )

        with self.assertRaises(BlankModelResponseError):
            service.generate("नमस्ते")

    def test_output_cleanup(self):
        service = make_service(
            lambda *_args: {
                "message": {
                    "content": "```markdown\n**सहायक:** नमस्ते!\n```"
                }
            }
        )

        result = service.generate("नमस्ते")

        self.assertEqual(result.response, "नमस्ते!")
        self.assertGreaterEqual(result.generation_time_ms, 0)

    def test_history_precedes_current_message_without_duplication(self):
        captured_payloads = []

        def transport(_url, payload, _timeout):
            captured_payloads.append(payload)
            return {"message": {"content": "आपका नाम सौरव है।"}}

        service = make_service(transport)
        history = [
            {"role": "user", "content": "मेरा नाम सौरव है।"},
            {"role": "assistant", "content": "नमस्ते सौरव।"},
        ]

        service.generate("मेरा नाम क्या है?", history=history)

        messages = captured_payloads[0]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1:3], history)
        self.assertEqual(
            messages[3],
            {"role": "user", "content": "मेरा नाम क्या है?"},
        )
        self.assertEqual(
            sum(
                message == messages[3]
                for message in messages
            ),
            1,
        )

    def test_history_is_capped_before_sending_to_ollama(self):
        captured_payloads = []

        def transport(_url, payload, _timeout):
            captured_payloads.append(payload)
            return {"message": {"content": "ठीक है।"}}

        service = make_service(
            transport,
            max_history_messages="2",
        )
        history = [
            {"role": "user", "content": "पहला"},
            {"role": "assistant", "content": "पहला उत्तर"},
            {"role": "user", "content": "दूसरा"},
            {"role": "assistant", "content": "दूसरा उत्तर"},
        ]

        service.generate("अगला", history=history)

        self.assertEqual(
            captured_payloads[0]["messages"][1:-1],
            history[-2:],
        )

    def test_configuration_validation(self):
        invalid_values = [
            {"LLM_PROVIDER": "cloud"},
            {"LLM_BASE_URL": "https://example.com"},
            {"LLM_MODEL": " "},
            {"LLM_MAX_TOKENS": "0"},
            {"LLM_TEMPERATURE": "warm"},
            {"LLM_TIMEOUT_SECONDS": "0"},
            {"LLM_CONTEXT_TOKENS": "100"},
            {"LLM_MAX_HISTORY_MESSAGES": "3"},
        ]

        for overrides in invalid_values:
            environment = dict(VALID_ENVIRONMENT)
            environment.update(overrides)
            with self.subTest(overrides=overrides):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(LanguageModelConfigurationError):
                        LanguageModelService(transport=lambda *_args: {})


if __name__ == "__main__":
    unittest.main()
