import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from ipaws_research import alert_retrieval


def official_record(identifier: str, sent: str, category: str = "Met") -> dict:
    return {
        "id": f"openfema-{identifier}",
        "identifier": identifier,
        "sender": "w-nws.webmaster@noaa.gov",
        "sent": sent,
        "status": "Actual",
        "msgType": "Alert",
        "scope": "Public",
        "originalMessage": f"<alert><identifier>{identifier}</identifier></alert>",
        "info": [{
            "language": "en-US",
            "category": [category],
            "event": "Extreme Fire Danger",
            "headline": "Extreme Fire Danger issued by NWS",
            "description": "Critical fire weather conditions are expected.",
            "instruction": "Avoid outdoor burning.",
            "urgency": "Expected",
            "severity": "Moderate",
            "certainty": "Likely",
            "effective": "2025-01-02T10:00:00-08:00",
            "expires": "2025-01-02T18:00:00-08:00",
            "eventCode": [{"name": "SAME", "value": "RFW"}],
            "areas": [{
                "areaDesc": "Los Angeles County",
                "geocode": [
                    {"name": "SAME", "value": "006037"},
                    {"name": "UGC", "value": "CAZ000"},
                ],
            }],
        }],
    }


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self.payload

    async def text(self):
        return "upstream error"


class FakeSession:
    def __init__(self, pages, calls, status=200):
        self.pages = iter(pages)
        self.calls = calls
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        response = next(self.pages)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response, self.status)


def fake_session(pages, status=200):
    calls = []
    replacement = lambda: FakeSession(pages, calls, status)
    return calls, patch.object(alert_retrieval.aiohttp, "ClientSession", replacement)


class AlertRetrievalTests(unittest.TestCase):
    def test_health_cap_category_is_not_overridden_by_generic_shelter_text(self):
        record = official_record("HEALTH-SHELTER", "2025-01-02T12:00:00Z", category="Health")
        record["info"][0].update({
            "event": "Extreme Heat Emergency",
            "description": "Dangerous heat conditions create a public health risk.",
            "instruction": "Use a cooling shelter if needed.",
        })

        alert = alert_retrieval._to_emergency_alert(record, "CA")

        self.assertEqual(alert.category, "health")

    def test_health_family_cap_category_is_not_overridden_by_evacuation_response(self):
        for cap_category in ("Health", "Env", "CBRNE"):
            with self.subTest(cap_category=cap_category):
                record = official_record(
                    f"{cap_category}-EVACUATE",
                    "2025-01-02T12:00:00Z",
                    category=cap_category,
                )
                record["info"][0]["responseType"] = ["Evacuate"]

                alert = alert_retrieval._to_emergency_alert(record, "CA")

                self.assertEqual(alert.category, "health")

    def test_health_text_without_cap_health_is_not_classified_as_health(self):
        record = official_record("BOIL-WATER", "2025-01-02T12:00:00Z", category="")
        record["info"][0].update({
            "event": "Boil Water Advisory",
            "headline": "Boil water before drinking until further notice",
            "description": "A drinking water contamination risk may affect public health.",
            "instruction": "Use bottled water or boil tap water for one minute.",
        })

        alert = alert_retrieval._to_emergency_alert(record, "CA")

        self.assertEqual(alert.category, "unknown")

    def test_health_env_and_cbrne_cap_categories_map_to_health(self):
        for cap_category in ("Health", "Env", "CBRNE"):
            with self.subTest(cap_category=cap_category):
                record = official_record(cap_category.upper(), "2025-01-02T12:00:00Z", category=cap_category)
                record["info"][0].update({
                    "event": "Official Advisory",
                    "headline": "Official advisory issued",
                    "description": "Officials are monitoring local conditions.",
                    "instruction": "Monitor official information.",
                })

                alert = alert_retrieval._to_emergency_alert(record, "CA")

                self.assertEqual(alert.category, "health")

    def test_missing_effective_defaults_to_sent(self):
        record = official_record("HEALTH-NO-EFFECTIVE", "2025-01-02T12:00:00Z", category="Health")
        record["info"][0].pop("effective")

        alert = alert_retrieval._to_emergency_alert(record, "CA")

        self.assertEqual(alert.effective, alert.sent)

    def test_geo_rescue_or_fire_requires_evacuation_response_or_text(self):
        evacuation = official_record("GEO-EVAC", "2025-01-02T12:00:00Z", category="Geo")
        evacuation["info"][0].update({
            "event": "Landslide Emergency",
            "responseType": ["Evacuate"],
            "headline": "Leave the affected area",
            "description": "A landslide threatens nearby homes.",
            "instruction": "Relocate as directed by local officials.",
        })
        informational = official_record("FIRE-MONITOR", "2025-01-02T11:00:00Z", category="Fire")
        informational["info"][0].update({
            "event": "Structure Fire",
            "responseType": ["Monitor"],
            "headline": "Structure fire update",
            "description": "Fire crews remain on scene.",
            "instruction": "Monitor official information.",
        })

        evacuation_alert = alert_retrieval._to_emergency_alert(evacuation, "CA")
        informational_alert = alert_retrieval._to_emergency_alert(informational, "CA")

        self.assertEqual(evacuation_alert.category, "evacuation")
        self.assertEqual(evacuation_alert.response_types, ["Evacuate"])
        self.assertEqual(informational_alert.category, "unknown")

    def test_fetch_pages_and_retains_official_metadata(self):
        records = [
            official_record("NWS-ONE", "2025-01-02T12:00:00Z"),
            official_record("NWS-TWO", "2025-01-02T11:00:00Z"),
            official_record("NWS-THREE", "2025-01-02T10:00:00Z"),
        ]
        calls, session_patch = fake_session([
            {"IpawsArchivedAlerts": records[:2]},
            {"IpawsArchivedAlerts": records[2:]},
        ])

        with session_patch:
            alerts = asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                datetime(2025, 1, 3, tzinfo=timezone.utc),
                top=2,
                shuffle=False,
            ))

        self.assertEqual([call["params"]["$skip"] for call in calls], ["0", "2"])
        self.assertNotIn("contains(info/area", calls[0]["params"]["$filter"])
        self.assertEqual(len(alerts), 3)
        first = alerts[0]
        self.assertEqual(first.alert_id, first.research_id)
        self.assertTrue(first.alert_id.startswith("IPAWS-"))
        self.assertEqual(first.openfema_id, "openfema-NWS-ONE")
        self.assertEqual(first.identifier, "NWS-ONE")
        self.assertEqual(first.sender, "w-nws.webmaster@noaa.gov")
        self.assertEqual(first.language, "en-US")
        self.assertEqual(first.area, "Los Angeles County")
        self.assertEqual(first.event_codes, {"SAME": "RFW"})
        self.assertIsNotNone(first.effective)
        self.assertIsNotNone(first.expires)
        self.assertTrue(first.original_message.startswith("<alert>"))
        self.assertEqual(first.raw_record, records[0])

    def test_fetch_filters_categories_and_event_codes_locally(self):
        weather = official_record("NWS-WEATHER", "2025-01-02T12:00:00Z")
        safety = official_record("NWS-SAFETY", "2025-01-02T11:00:00Z", category="Safety")
        safety["info"][0]["eventCode"] = [{"name": "SAME", "value": "LEW"}]
        _, session_patch = fake_session([{"IpawsArchivedAlerts": [weather, safety]}])

        with session_patch:
            alerts = asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2025, 1, 1),
                datetime(2025, 1, 3),
                top=10,
                shuffle=False,
                cap_categories=["Safety"],
                event_codes=["LEW"],
            ))

        self.assertEqual([alert.identifier for alert in alerts], ["NWS-SAFETY"])
        self.assertEqual(alerts[0].category, "public_safety")

    def test_california_fetch_uses_valid_server_side_geometry_filter(self):
        calls, session_patch = fake_session([{"IpawsArchivedAlerts": []}])

        with session_patch:
            asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2025, 1, 1),
                datetime(2025, 1, 31),
                state="CA",
                shuffle=False,
                cap_categories=["Health"],
            ))

        filter_string = calls[0]["params"]["$filter"]
        self.assertIn("geo.intersects(searchGeometry, geography'POLYGON", filter_string)
        self.assertNotIn("SRID=4326", filter_string)

    def test_category_filtered_fetch_partitions_multi_year_history(self):
        irrelevant_2025 = [
            official_record(f"MET-2025-{index}", f"2025-01-0{index + 1}T12:00:00Z")
            for index in range(2)
        ]
        health_2025 = official_record("HEALTH-2025", "2025-01-01T12:00:00Z", category="Health")
        irrelevant_2024 = [
            official_record(f"MET-2024-{index}", f"2024-12-0{index + 1}T12:00:00Z")
            for index in range(2)
        ]
        health_2024 = official_record("HEALTH-2024", "2024-12-01T12:00:00Z", category="Health")
        calls, session_patch = fake_session([
            {"IpawsArchivedAlerts": irrelevant_2025},
            {"IpawsArchivedAlerts": [health_2025]},
            {"IpawsArchivedAlerts": irrelevant_2024},
            {"IpawsArchivedAlerts": [health_2024]},
        ])

        with session_patch:
            alerts = asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2024, 12, 1, tzinfo=timezone.utc),
                datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc),
                top=2,
                shuffle=False,
                cap_categories=["Health"],
            ))

        self.assertEqual([alert.identifier for alert in alerts], ["HEALTH-2025", "HEALTH-2024"])
        self.assertIn("sent ge '2025-01-01T00:00:00Z'", calls[0]["params"]["$filter"])
        self.assertIn("sent ge '2024-12-01T00:00:00Z'", calls[2]["params"]["$filter"])
        self.assertEqual([call["params"]["$skip"] for call in calls], ["0", "2", "0", "2"])

    def test_category_filtered_fetch_uses_monthly_windows(self):
        calls, session_patch = fake_session([
            {"IpawsArchivedAlerts": []}
            for _ in range(6)
        ])

        with session_patch:
            asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2024, 10, 1, tzinfo=timezone.utc),
                datetime(2025, 3, 31, 23, 59, 59, tzinfo=timezone.utc),
                top=500,
                shuffle=False,
                cap_categories=["Health", "Env", "CBRNE"],
            ))

        self.assertEqual(len(calls), 6)
        self.assertIn("sent ge '2025-03-01T00:00:00Z'", calls[0]["params"]["$filter"])
        self.assertIn("sent ge '2024-10-01T00:00:00Z'", calls[-1]["params"]["$filter"])

    def test_fetch_keeps_successful_windows_when_one_window_times_out(self):
        health = official_record("HEALTH-2025", "2025-01-01T12:00:00Z", category="Health")
        _, session_patch = fake_session([
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            {"IpawsArchivedAlerts": [health]},
        ])

        with session_patch:
            alerts = asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2024, 12, 1, tzinfo=timezone.utc),
                datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc),
                top=500,
                shuffle=False,
                cap_categories=["Health"],
            ))

        self.assertEqual([alert.identifier for alert in alerts], ["HEALTH-2025"])

    def test_fetch_skips_unavailable_openfema_window(self):
        _, session_patch = fake_session([{}, {}], status=503)

        with session_patch:
            alerts = asyncio.run(alert_retrieval.fetch_ipaws_openapi_alerts(
                datetime(2025, 1, 1),
                datetime(2025, 1, 3),
                shuffle=False,
            ))

        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()