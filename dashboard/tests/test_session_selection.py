import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_selection import resolve_selected_session


class ResolveSelectedSessionTests(unittest.TestCase):
    def test_defaults_to_latest_session_when_prior_selection_missing(self) -> None:
        selected, message = resolve_selected_session(
            session_ids=[2, 1],
            prior_selected_session_id=None,
            active_session_id=None,
            latest_session_id=2,
            live_mode=False,
        )

        self.assertEqual(selected, 2)
        self.assertIsNone(message)

    def test_live_mode_prefers_active_session(self) -> None:
        selected, message = resolve_selected_session(
            session_ids=[2, 1],
            prior_selected_session_id=1,
            active_session_id=2,
            latest_session_id=2,
            live_mode=True,
        )

        self.assertEqual(selected, 2)
        self.assertEqual(message, "Auto-switched to active session 2.")

    def test_live_mode_falls_back_to_latest_session(self) -> None:
        selected, message = resolve_selected_session(
            session_ids=[2, 1],
            prior_selected_session_id=1,
            active_session_id=None,
            latest_session_id=2,
            live_mode=True,
        )

        self.assertEqual(selected, 2)
        self.assertEqual(message, "Active session unavailable. Showing latest session 2.")


if __name__ == "__main__":
    unittest.main()
