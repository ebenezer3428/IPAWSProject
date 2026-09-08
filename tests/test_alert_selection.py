import unittest

from fastapi import HTTPException

from api.main import ALERT_SELECTION_TARGETS, _validate_alert_selection
from ipaws_research.alert_quality import review_candidate, validate_candidate
from tests.test_alert_quality import candidate


def balanced_candidates():
    alerts = []
    for category, count in ALERT_SELECTION_TARGETS.items():
        for index in range(count):
            alert = candidate(
                f"{category}-{index}",
                f"Official source text for {category} record {index}.",
                category=category,
                quality_status="eligible",
            )
            alerts.append(alert)
    return alerts


class AlertSelectionTests(unittest.TestCase):
    def test_accepts_exact_balanced_eligible_selection(self):
        alerts = balanced_candidates()

        counts = _validate_alert_selection([alert.research_id for alert in alerts], alerts)

        self.assertEqual(counts, ALERT_SELECTION_TARGETS)

    def test_rejects_wrong_category_distribution(self):
        alerts = balanced_candidates()
        alerts[-1] = alerts[-1].model_copy(update={"category": "weather"})

        with self.assertRaisesRegex(HTTPException, "category targets"):
            _validate_alert_selection([alert.research_id for alert in alerts], alerts)

    def test_rejects_duplicate_ids(self):
        alerts = balanced_candidates()
        selected = [alert.research_id for alert in alerts]
        selected[-1] = selected[0]

        with self.assertRaisesRegex(HTTPException, "48 unique"):
            _validate_alert_selection(selected, alerts)

    def test_rejects_noneligible_record(self):
        alerts = balanced_candidates()
        alerts[0] = alerts[0].model_copy(update={"quality_status": "excluded"})

        with self.assertRaisesRegex(HTTPException, "not eligible"):
            _validate_alert_selection([alert.research_id for alert in alerts], alerts)

    def test_rejects_current_approved_soft_flag(self):
        alerts = balanced_candidates()
        flagged = validate_candidate(alerts[0].model_copy(update={
            "raw_source_text": "Official notice.\n\nOfficial notice.",
        }))
        alerts[0] = review_candidate(
            flagged,
            decision="approved",
            reviewer_id="researcher@example.com",
            reason="Only an exact repeated paragraph was removed.",
        )

        with self.assertRaisesRegex(HTTPException, "not eligible"):
            _validate_alert_selection([alert.research_id for alert in alerts], alerts)


if __name__ == "__main__":
    unittest.main()