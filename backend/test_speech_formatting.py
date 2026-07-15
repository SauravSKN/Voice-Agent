import unittest

from app.services.speech_formatting import prepare_text_for_speech


class SpeechFormattingTests(unittest.TestCase):
    def test_markdown_time_and_reliable_terms_are_prepared(self) -> None:
        displayed = "**आपकी meeting 5:30 PM पर है**"
        spoken = prepare_text_for_speech(displayed)

        self.assertEqual(
            spoken,
            "आपकी मीटिंग शाम पाँच बजकर तीस मिनट पर है।",
        )
        self.assertEqual(displayed, "**आपकी meeting 5:30 PM पर है**")

    def test_repeated_punctuation_and_whitespace_are_normalized(self) -> None:
        self.assertEqual(
            prepare_text_for_speech("  नमस्ते!!!   कैसे हैं???  "),
            "नमस्ते! कैसे हैं?",
        )

    def test_unsupported_time_is_not_guessed(self) -> None:
        self.assertEqual(
            prepare_text_for_speech("बैठक 5:17 PM पर है।"),
            "बैठक 5:17 PM पर है।",
        )

    def test_long_text_is_bounded_at_a_safe_boundary(self) -> None:
        spoken = prepare_text_for_speech(
            "पहला वाक्य। " + ("बहुत लंबा उत्तर " * 20),
            max_chars=50,
        )
        self.assertLessEqual(len(spoken), 51)
        self.assertTrue(spoken.endswith("।"))


if __name__ == "__main__":
    unittest.main()
