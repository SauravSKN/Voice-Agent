import unittest

from app.memory.conversation import (
    ConversationConfigurationError,
    ConversationSettings,
    ConversationStore,
    InvalidSessionIdError,
)


class MutableClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def settings(*, max_turns=6, ttl_seconds=1800, max_sessions=100):
    return ConversationSettings(
        max_turns=max_turns,
        ttl_seconds=ttl_seconds,
        max_sessions=max_sessions,
    )


class ConversationStoreTests(unittest.TestCase):
    def test_sessions_are_isolated_and_store_only_completed_turns(self):
        store = ConversationStore(settings())

        self.assertEqual(
            store.add_turn("session-a", "मेरा नाम सौरव है।", "नमस्ते।"),
            1,
        )

        self.assertEqual(store.get_history("session-b"), [])
        self.assertEqual(
            store.get_history("session-a"),
            [
                {"role": "user", "content": "मेरा नाम सौरव है।"},
                {"role": "assistant", "content": "नमस्ते।"},
            ],
        )

    def test_maximum_turns_trim_oldest_complete_turns(self):
        store = ConversationStore(settings(max_turns=2))

        for number in range(1, 4):
            store.add_turn(
                "trim-session",
                f"user-{number}",
                f"assistant-{number}",
            )

        history = store.get_history("trim-session")
        self.assertEqual(
            [message["content"] for message in history],
            ["user-2", "assistant-2", "user-3", "assistant-3"],
        )
        self.assertEqual(store.turn_count("trim-session"), 2)

    def test_inactive_session_expires(self):
        clock = MutableClock()
        store = ConversationStore(
            settings(ttl_seconds=60),
            clock=clock,
        )
        store.add_turn("expiring", "user", "assistant")

        clock.advance(59)
        self.assertEqual(store.turn_count("expiring"), 1)
        clock.advance(60)
        self.assertEqual(store.get_history("expiring"), [])
        self.assertEqual(store.session_count(), 0)

    def test_maximum_sessions_evicts_least_recently_active(self):
        clock = MutableClock()
        store = ConversationStore(
            settings(max_sessions=2),
            clock=clock,
        )
        store.add_turn("session-a", "a", "a")
        clock.advance(1)
        store.add_turn("session-b", "b", "b")
        clock.advance(1)
        store.get_history("session-a")
        clock.advance(1)
        store.add_turn("session-c", "c", "c")

        self.assertEqual(store.get_history("session-b"), [])
        self.assertEqual(store.turn_count("session-a"), 1)
        self.assertEqual(store.turn_count("session-c"), 1)
        self.assertEqual(store.session_count(), 2)

    def test_history_result_is_a_copy(self):
        store = ConversationStore(settings())
        store.add_turn("copy-session", "user", "assistant")

        history = store.get_history("copy-session")
        history[0]["content"] = "changed"

        self.assertEqual(
            store.get_history("copy-session")[0]["content"],
            "user",
        )

    def test_clear_is_idempotent(self):
        store = ConversationStore(settings())
        store.add_turn("clear-session", "user", "assistant")

        self.assertTrue(store.clear("clear-session"))
        self.assertFalse(store.clear("clear-session"))

    def test_invalid_session_ids_are_rejected(self):
        store = ConversationStore(settings())
        invalid_ids = ["", " ", "../secret", "has space", "x" * 129]

        for session_id in invalid_ids:
            with self.subTest(session_id=session_id):
                with self.assertRaises(InvalidSessionIdError):
                    store.get_history(session_id)

    def test_environment_configuration_validation(self):
        invalid_environments = [
            {"CONVERSATION_MAX_TURNS": "0"},
            {"CONVERSATION_MAX_TURNS": "many"},
            {"CONVERSATION_TTL_MINUTES": "0"},
            {"CONVERSATION_MAX_SESSIONS": "0"},
        ]

        for environment in invalid_environments:
            with self.subTest(environment=environment):
                with self.assertRaises(ConversationConfigurationError):
                    ConversationSettings.from_environment(environment)


if __name__ == "__main__":
    unittest.main()
