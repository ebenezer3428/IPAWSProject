from datetime import datetime, timezone
import unittest

from ipaws_research.alert_quality import (
    is_candidate_selectable,
    merge_review_state,
    review_candidate,
    validate_candidate,
    validate_candidates,
)
from ipaws_research.models import EmergencyAlert, ReviewEvent


def candidate(identifier: str, text: str, **changes) -> EmergencyAlert:
    values = {
        "alert_id": f"IPAWS-{identifier}",
        "research_id": f"IPAWS-{identifier}",
        "openfema_id": f"openfema-{identifier}",
        "identifier": identifier,
        "sender": "w-nws.webmaster@noaa.gov",
        "source_text": text,
        "raw_source_text": text,
        "cleaned_source_text": text,
        "category": "weather",
        "urgency_level": "immediate",
        "certainty_level": "likely",
        "severity_level": "severe",
        "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc),
        "sent": datetime(2025, 1, 2, tzinfo=timezone.utc),
        "effective": datetime(2025, 1, 2, tzinfo=timezone.utc),
        "expires": datetime(2025, 1, 3, tzinfo=timezone.utc),
        "state": "CA",
        "area": "Los Angeles County",
        "language": "en-US",
        "status": "Actual",
        "message_type": "Alert",
    }
    values.update(changes)
    return EmergencyAlert(**values)


class AlertQualityTests(unittest.TestCase):
    def test_legacy_review_event_defaults_previous_decision(self):
        event = ReviewEvent(
            decision="approved",
            reviewer_id="researcher@example.com",
            reviewed_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            reason="Legacy audit record.",
            source_hash="abc",
        )

        self.assertEqual(event.previous_decision, "pending")

    def test_eligible_record_has_clean_status(self):
        result = validate_candidate(candidate("ONE", "A red flag warning is in effect. Avoid outdoor burning."))

        self.assertEqual(result.quality_status, "eligible")
        self.assertEqual(result.quality_findings, [])

    def test_repeated_and_mixed_language_passages_are_flagged_and_cleaned(self):
        english = "Avoid the affected area until officials issue an all clear."
        spanish = "Esta es una emergencia para esta area. Evite el incendio."
        result = validate_candidate(candidate("TWO", f"{english}\n\n{english}\n\n{spanish}"))

        self.assertEqual(result.quality_status, "flagged")
        self.assertEqual(result.cleaned_source_text.count(english), 1)
        self.assertEqual(
            {finding.code for finding in result.quality_findings},
            {"duplicate_passage", "mixed_language"},
        )

    def test_test_and_cancel_records_are_excluded(self):
        result = validate_candidate(candidate(
            "THREE",
            "This is only a test. No action is required.",
            message_type="Cancel",
        ))

        self.assertEqual(result.quality_status, "excluded")
        self.assertIn("test_message", {finding.code for finding in result.quality_findings})
        self.assertIn("cancel_message", {finding.code for finding in result.quality_findings})

    def test_duplicate_alert_text_excludes_later_record(self):
        first = candidate("FOUR", "Flood waters are rising. Move to higher ground now.")
        second = candidate("FIVE", first.source_text)

        results = validate_candidates([first, second])

        self.assertEqual(results[0].quality_status, "eligible")
        self.assertEqual(results[1].quality_status, "excluded")
        duplicate = next(finding for finding in results[1].quality_findings if finding.code == "duplicate_alert")
        self.assertEqual(duplicate.evidence, first.research_id)

    def test_same_day_event_and_county_keeps_newest_alert(self):
        older = candidate(
            "COUNTY-OLDER",
            "Older flood warning instructions.",
            event="Flood Warning",
            sent=datetime(2025, 1, 2, 8, tzinfo=timezone.utc),
            timestamp=datetime(2025, 1, 2, 8, tzinfo=timezone.utc),
        )
        newer = candidate(
            "COUNTY-NEWER",
            "Updated flood warning instructions.",
            event="Flood Warning",
            sent=datetime(2025, 1, 2, 12, tzinfo=timezone.utc),
            timestamp=datetime(2025, 1, 2, 12, tzinfo=timezone.utc),
        )

        results = validate_candidates([older, newer])

        self.assertEqual(results[0].quality_status, "excluded")
        self.assertEqual(results[1].quality_status, "eligible")
        duplicate = next(
            finding for finding in results[0].quality_findings
            if finding.code == "duplicate_county_day_event"
        )
        self.assertEqual(duplicate.evidence, newer.research_id)

    def test_county_day_dedup_keeps_different_events_and_counties(self):
        alerts = [
            candidate("LA-FLOOD", "Los Angeles flood warning.", event="Flood Warning"),
            candidate("LA-FIRE", "Los Angeles fire warning.", event="Fire Warning"),
            candidate(
                "ORANGE-FLOOD",
                "Orange County flood warning.",
                event="Flood Warning",
                area="Orange County",
            ),
        ]

        results = validate_candidates(alerts)

        self.assertTrue(all(result.quality_status == "eligible" for result in results))

    def test_approved_flag_is_audited_but_not_selectable(self):
        flagged = validate_candidate(candidate(
            "SIX",
            "Avoid this area.\n\nAvoid this area.",
        ))

        reviewed = review_candidate(
            flagged,
            decision="approved",
            reviewer_id="researcher@example.com",
            reason="Repeated paragraph removed without changing meaning.",
        )

        self.assertFalse(is_candidate_selectable(reviewed))
        self.assertEqual(reviewed.review_history[-1].reviewer_id, "researcher@example.com")
        self.assertEqual(reviewed.review_history[-1].previous_decision, "pending")
        self.assertEqual(reviewed.reviewed_source_hash, reviewed.source_hash)

    def test_changed_source_invalidates_approval_but_preserves_history(self):
        flagged = validate_candidate(candidate("SEVEN", "Warning text.\n\nWarning text."))
        reviewed = review_candidate(
            flagged,
            decision="approved",
            reviewer_id="researcher@example.com",
            reason="Exact repetition only.",
        )
        changed = reviewed.model_copy(update={"raw_source_text": "Changed warning.\n\nChanged warning."})

        revalidated = validate_candidate(changed)

        self.assertEqual(revalidated.review_decision, "pending")
        self.assertFalse(is_candidate_selectable(revalidated))
        self.assertEqual(len(revalidated.review_history), 1)

    def test_hard_exclusion_cannot_be_reviewed(self):
        excluded = validate_candidate(candidate("EIGHT", "This is only a test."))

        with self.assertRaisesRegex(ValueError, "warning-flagged"):
            review_candidate(
                excluded,
                decision="approved",
                reviewer_id="researcher@example.com",
                reason="Attempted override.",
            )

    def test_refetch_preserves_current_review_and_invalidates_changed_source(self):
        flagged = validate_candidate(candidate("NINE", "Notice.\n\nNotice."))
        reviewed = review_candidate(
            flagged,
            decision="approved",
            reviewer_id="researcher@example.com",
            reason="Repeated paragraph removed.",
        )

        unchanged = merge_review_state(reviewed, candidate("NINE", "Notice.\n\nNotice."))
        changed = merge_review_state(reviewed, candidate("NINE", "Updated notice.\n\nUpdated notice."))

        self.assertEqual(validate_candidate(unchanged).review_decision, "approved")
        changed_validated = validate_candidate(changed)
        self.assertEqual(changed_validated.review_decision, "pending")
        self.assertEqual(len(changed_validated.review_history), 1)


if __name__ == "__main__":
    unittest.main()