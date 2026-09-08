import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from api.main import AlertPoolExpandRequest, admin_alert_pool_expand
from ipaws_research.alert_quality import review_candidate, validate_candidate
from tests.test_alert_quality import candidate


class AlertPoolExpandTests(unittest.TestCase):
    def test_continue_acquisition_fetches_only_categories_below_quota(self):
        cap_categories = {
            "evacuation": ["Geo"],
            "weather": ["Met"],
            "public_safety": ["Safety"],
            "health": ["Health"],
        }
        existing = [
            candidate(
                f"{category}-{index}",
                f"Official source text for {category} record {index}.",
                category=category,
                cap_categories=cap_categories[category],
                response_types=["Evacuate"] if category == "evacuation" else [],
            )
            for category in ("evacuation", "weather", "public_safety", "health")
            for index in range(50 if category in {"evacuation", "weather"} else 49)
        ]
        replacements = [
            candidate(
                f"replacement-{category}",
                f"Official replacement for {category}.",
                category=category,
                cap_categories=cap_categories[category],
            )
            for category in ("public_safety", "health")
        ]
        fetch = AsyncMock(return_value=replacements)

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_alert_candidates", return_value=existing),
            patch("api.main.fetch_ipaws_openapi_alerts", fetch),
            patch("api.main._save_alert_candidates"),
        ):
            response = asyncio.run(admin_alert_pool_expand(
                AlertPoolExpandRequest(targetTotal=200, startDate="2020-01-01"),
                authorization="Bearer token",
            ))

        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(
            fetch.await_args.kwargs["cap_categories"],
            ["Safety", "Security", "Health", "Env", "CBRNE"],
        )
        self.assertEqual(response.eligible_counts, {
            "weather": 50,
            "evacuation": 50,
            "public_safety": 50,
            "health": 50,
        })

    def test_approved_flag_does_not_fill_eligible_category_quota(self):
        cap_categories = {
            "evacuation": ["Geo"],
            "weather": ["Met"],
            "public_safety": ["Safety"],
            "health": ["Health"],
        }
        existing = [
            candidate(
                f"{category}-{index}",
                f"Official source text for {category} record {index}.",
                category=category,
                cap_categories=cap_categories[category],
                response_types=["Evacuate"] if category == "evacuation" else [],
            )
            for category in ("evacuation", "weather", "public_safety", "health")
            for index in range(50 if category != "health" else 49)
        ]
        flagged = validate_candidate(candidate(
            "approved-health-flag",
            "Avoid exposure until officials provide an update.\n\nAvoid exposure until officials provide an update.",
            category="health",
            cap_categories=["Health"],
        ))
        existing.append(review_candidate(
            flagged,
            decision="approved",
            reviewer_id="researcher@example.com",
            reason="Retain for audit only.",
        ))
        replacement = candidate(
            "eligible-health-replacement",
            "Official public health advisory replacement.",
            category="health",
            cap_categories=["Health"],
        )
        fetch = AsyncMock(return_value=[replacement])

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_alert_candidates", return_value=existing),
            patch("api.main.fetch_ipaws_openapi_alerts", fetch),
            patch("api.main._save_alert_candidates"),
        ):
            response = asyncio.run(admin_alert_pool_expand(
                AlertPoolExpandRequest(targetTotal=200, startDate="2020-01-01"),
                authorization="Bearer token",
            ))

        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(response.eligible_total, 200)
        self.assertEqual(response.eligible_counts["health"], 50)
        self.assertEqual(response.total, 201)

    def test_category_targeted_fetch_fills_health_shortfall(self):
        cap_categories = {
            "evacuation": ["Geo"],
            "weather": ["Met"],
            "public_safety": ["Safety"],
            "health": ["Health"],
        }
        existing = [
            candidate(
                f"{category}-{index}",
                f"Official source text for {category} record {index}.",
                category=category,
                cap_categories=cap_categories[category],
                response_types=["Evacuate"] if category == "evacuation" else [],
            )
            for category in ("evacuation", "weather", "public_safety", "health")
            for index in range(50 if category != "health" else 42)
        ]
        health_records = [
            candidate(
                f"targeted-health-{index}",
                f"Official public health advisory {index}.",
                category="health",
                cap_categories=["Health"],
            )
            for index in range(8)
        ]
        ineligible_health = candidate(
            "targeted-health-test",
            "This is only a test. No action is required.",
            category="health",
            cap_categories=["Health"],
        )
        saved = []
        fetch = AsyncMock(return_value=[*health_records, ineligible_health])

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_alert_candidates", return_value=existing),
            patch("api.main.fetch_ipaws_openapi_alerts", fetch),
            patch("api.main._save_alert_candidates", side_effect=saved.append),
        ):
            response = asyncio.run(admin_alert_pool_expand(
                AlertPoolExpandRequest(targetTotal=200, startDate="2020-01-01"),
                authorization="Bearer token",
            ))

        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(fetch.await_args.kwargs["cap_categories"], ["Health", "Env", "CBRNE"])
        self.assertEqual(response.eligible_total, 200)
        self.assertEqual(response.eligible_counts["health"], 50)
        self.assertEqual(sum(alert.category == "health" for alert in saved[0]), 51)
        self.assertEqual(response.total, 201)
        retained = next(alert for alert in saved[0] if alert.research_id == ineligible_health.research_id)
        self.assertEqual(retained.quality_status, "excluded")

    def test_empty_pool_fetches_all_required_categories_in_one_archive_pass(self):
        category_specs = [
            ("weather", ["Met"], []),
            ("evacuation", ["Geo"], ["Evacuate"]),
            ("public_safety", ["Safety"], []),
            ("health", ["Health"], []),
        ]
        responses = [
            [
                candidate(
                    f"{category}-{index}",
                    f"Official {category} alert {index}.",
                    category=category,
                    cap_categories=cap_values,
                    response_types=response_types,
                )
                for index in range(50)
            ]
            for category, cap_values, response_types in category_specs
        ]
        fetch = AsyncMock(return_value=[alert for response in responses for alert in response])

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_alert_candidates", return_value=[]),
            patch("api.main.fetch_ipaws_openapi_alerts", fetch),
            patch("api.main._save_alert_candidates"),
        ):
            response = asyncio.run(admin_alert_pool_expand(
                AlertPoolExpandRequest(targetTotal=200, startDate="2020-01-01"),
                authorization="Bearer token",
            ))

        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(
            fetch.await_args.kwargs["cap_categories"],
            ["Met", "Geo", "Rescue", "Fire", "Safety", "Security", "Health", "Env", "CBRNE"],
        )
        self.assertEqual(response.eligible_total, 200)
        self.assertEqual(set(response.eligible_counts.values()), {50})


if __name__ == "__main__":
    unittest.main()