import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api.main import AlertReviewRequest, admin_alert_pool_review
from ipaws_research.alert_quality import validate_candidate
from tests.test_alert_quality import candidate


class AlertReviewApiTests(unittest.TestCase):
    def test_approve_persists_authenticated_audit_event(self):
        flagged = validate_candidate(candidate("API-ONE", "Notice.\n\nNotice."))
        saved = []

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_alert_candidates", return_value=[flagged]),
            patch("api.main._save_alert_candidates", side_effect=lambda records: saved.extend(records)),
        ):
            response = asyncio.run(admin_alert_pool_review(
                flagged.research_id,
                AlertReviewRequest(decision="approved", reason="Exact duplicate paragraph only."),
                authorization="Bearer token",
            ))

        self.assertFalse(response["selectable"])
        self.assertEqual(saved[0].review_history[-1].reviewer_id, "admin@example.com")
        self.assertEqual(saved[0].review_decision, "approved")

    def test_hard_exclusion_returns_conflict(self):
        excluded = validate_candidate(candidate("API-TWO", "This is only a test."))

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_alert_candidates", return_value=[excluded]),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(admin_alert_pool_review(
                excluded.research_id,
                AlertReviewRequest(decision="approved", reason="Attempted override."),
                authorization="Bearer token",
            ))

        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()