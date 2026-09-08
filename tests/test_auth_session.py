import unittest
from unittest.mock import patch

from api import main


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        main.SESSIONS.clear()

    def test_session_is_valid_after_instance_memory_is_cleared(self):
        with patch.object(main, "SESSION_SECRET", "stable-test-secret"):
            created = main._create_session("Researcher", "user", "user@example.com")
            main.SESSIONS.clear()
            session = main._get_valid_session(created["token"])

        self.assertIsNotNone(session)
        self.assertEqual(session["email"], "user@example.com")

    def test_session_uses_two_hour_default(self):
        with (
            patch.object(main, "SESSION_SECRET", "stable-test-secret"),
            patch.object(main, "SESSION_TTL_SECONDS", 7200),
            patch.object(main.time, "time", return_value=1_000_000),
        ):
            created = main._create_session("Researcher", "user")
            session = main._get_valid_session(created["token"])

        self.assertEqual(session["exp"], 1_007_200)

    def test_expired_or_modified_session_is_rejected(self):
        with (
            patch.object(main, "SESSION_SECRET", "stable-test-secret"),
            patch.object(main, "SESSION_TTL_SECONDS", 7200),
            patch.object(main.time, "time", return_value=1_000_000),
        ):
            token = main._create_session("Researcher", "user")["token"]
            modified = token[:-1] + ("A" if token[-1] != "A" else "B")
            self.assertIsNone(main._get_valid_session(modified))

        with (
            patch.object(main, "SESSION_SECRET", "stable-test-secret"),
            patch.object(main.time, "time", return_value=1_007_201),
        ):
            self.assertIsNone(main._get_valid_session(token))

        self.assertIsNone(main._get_valid_session("not.a-valid-signature!"))


if __name__ == "__main__":
    unittest.main()