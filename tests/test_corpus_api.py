import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.main import (
    ResearchCorpusPrepareRequest,
    ResearchCorpusTranslateRequest,
    ResearchCorpusTranslationReviewRequest,
    _require_frozen_artifact,
    admin_freeze_research_corpus,
    admin_prepare_research_corpus,
    admin_review_research_corpus_translation,
    admin_translate_research_corpus,
)
from ipaws_research.corpus import (
    add_corpus_translation,
    build_corpus_draft,
    freeze_corpus,
    review_corpus_translation,
)
from tests.test_alert_quality import candidate
from tests.test_alert_selection import balanced_candidates


class ResearchCorpusApiTests(unittest.TestCase):
    def test_prepare_snapshots_exact_balanced_selection(self):
        alerts = balanced_candidates()
        selected_ids = {alert.research_id for alert in alerts}
        saved = []

        with (
            patch("api.main.ALERT_POOL_SELECTED", selected_ids),
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_research_corpus", return_value=None),
            patch("api.main._load_alert_candidates", return_value=alerts),
            patch("api.main._save_research_corpus", side_effect=saved.append),
        ):
            response = asyncio.run(admin_prepare_research_corpus(
                ResearchCorpusPrepareRequest(systems=["gemini"], languages=["es"]),
                authorization="Bearer token",
            ))

        self.assertEqual(response["source_count"], 48)
        self.assertEqual(response["missing_count"], 48)
        self.assertEqual(len(saved[0].sources), 48)

    def test_translation_batch_saves_each_completed_artifact(self):
        alert = candidate("BATCH", "Official source text.")
        draft = build_corpus_draft(
            [alert], [alert.research_id], ["gemini"], ["es"], "admin@example.com"
        )
        saved = []

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_research_corpus", return_value=draft),
            patch("api.main._save_research_corpus", side_effect=saved.append),
            patch("api.main._translate_corpus_source", new=AsyncMock(return_value={
                "translation": "Texto oficial.",
                "metadata": {"model": "test"},
            })),
        ):
            response = asyncio.run(admin_translate_research_corpus(
                ResearchCorpusTranslateRequest(system="gemini", language="es", batch_size=5),
                authorization="Bearer token",
            ))

        self.assertEqual(response["generated"], 1)
        self.assertEqual(response["missing_count"], 0)
        self.assertEqual(response["approved_count"], 1)
        self.assertEqual(response["unapproved_count"], 0)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].translations[0].review_decision, "approved")
        self.assertEqual(saved[0].translations[0].review_history[-1].reviewer_id, "system:auto-approval")

    def test_translation_review_persists_reviewer_and_correction(self):
        alert = candidate("REVIEW", "Official source text.")
        draft = build_corpus_draft(
            [alert], [alert.research_id], ["gemini"], ["es"], "admin@example.com"
        )
        draft = add_corpus_translation(draft, alert.research_id, "gemini", "es", "Texto generado.")
        saved = []

        with (
            patch("api.main._require_session_role", return_value={"email": "reviewer@example.com"}),
            patch("api.main._load_research_corpus", return_value=draft),
            patch("api.main._save_research_corpus", side_effect=saved.append),
        ):
            response = asyncio.run(admin_review_research_corpus_translation(
                ResearchCorpusTranslationReviewRequest(
                    alert_id=alert.research_id,
                    system="gemini",
                    language="es",
                    decision="approved",
                    reason="Terminology corrected.",
                    reviewed_text="Texto corregido.",
                ),
                authorization="Bearer token",
            ))

        self.assertEqual(response["approved_count"], 1)
        self.assertEqual(saved[0].translations[0].generated_translation_text, "Texto generado.")
        self.assertEqual(saved[0].translations[0].translation_text, "Texto corregido.")
        self.assertEqual(saved[0].translations[0].review_history[-1].reviewer_id, "reviewer@example.com")

    def test_regeneration_endpoint_replaces_existing_automatic_approval(self):
        alert = candidate("REGENERATE", "Official source text.")
        draft = build_corpus_draft(
            [alert], [alert.research_id], ["gemini"], ["es"], "admin@example.com"
        )
        draft = add_corpus_translation(draft, alert.research_id, "gemini", "es", "Primera version.")
        draft = review_corpus_translation(
            draft, alert.research_id, "gemini", "es", "approved",
            "reviewer@example.com", "Verified.",
        )
        saved = []

        with (
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_research_corpus", return_value=draft),
            patch("api.main._save_research_corpus", side_effect=saved.append),
            patch("api.main._translate_corpus_source", new=AsyncMock(return_value={
                "translation": "Segunda version.",
                "metadata": {"model": "test"},
            })),
        ):
            response = asyncio.run(admin_translate_research_corpus(
                ResearchCorpusTranslateRequest(
                    system="gemini",
                    language="es",
                    batch_size=1,
                    regenerate_alert_id=alert.research_id,
                ),
                authorization="Bearer token",
            ))

        self.assertEqual(response["approved_count"], 1)
        self.assertEqual(response["unapproved_count"], 0)
        self.assertEqual(saved[0].translations[0].review_decision, "approved")
        self.assertEqual(len(saved[0].translations[0].review_history), 2)
        self.assertEqual(saved[0].translations[0].review_history[-1].reviewer_id, "system:auto-approval")

    def test_scoring_requires_exact_frozen_source_and_translation(self):
        alert = candidate("SCORE", "Exact official source.")
        corpus = build_corpus_draft(
            [alert], [alert.research_id], ["gemini"], ["es"], "admin@example.com"
        )
        corpus = add_corpus_translation(
            corpus, alert.research_id, "gemini", "es", "Traduccion exacta."
        )
        corpus = review_corpus_translation(
            corpus, alert.research_id, "gemini", "es", "approved",
            "reviewer@example.com", "Translation verified.",
        )
        corpus = freeze_corpus(corpus, "admin@example.com")

        with patch("api.main._load_research_corpus", return_value=corpus):
            resolved = _require_frozen_artifact(
                alert.research_id,
                corpus.corpus_id,
                "Exact official source.",
                "Traduccion exacta.",
                "gemini",
                "es",
            )
            self.assertEqual(resolved[0].corpus_id, corpus.corpus_id)
            with self.assertRaises(HTTPException) as raised:
                _require_frozen_artifact(
                    alert.research_id,
                    corpus.corpus_id,
                    "Altered source.",
                    "Traduccion exacta.",
                    "gemini",
                    "es",
                )

        self.assertEqual(raised.exception.status_code, 409)

    def test_freeze_rejects_source_changes_after_preparation(self):
        alerts = balanced_candidates()
        selected_ids = {alert.research_id for alert in alerts}
        draft = build_corpus_draft(
            alerts, selected_ids, ["gemini"], ["es"], "admin@example.com"
        )
        changed = list(alerts)
        changed[0] = changed[0].model_copy(update={
            "source_text": "Changed after preparation.",
            "cleaned_source_text": "Changed after preparation.",
        })

        with (
            patch("api.main.ALERT_POOL_SELECTED", selected_ids),
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_research_corpus", return_value=draft),
            patch("api.main._load_alert_candidates", return_value=changed),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(admin_freeze_research_corpus(authorization="Bearer token"))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("changed after preparation", raised.exception.detail)

    def test_freeze_auto_approves_existing_pending_translations(self):
        alerts = balanced_candidates()
        selected_ids = {alert.research_id for alert in alerts}
        draft = build_corpus_draft(
            alerts, selected_ids, ["gemini"], ["es"], "admin@example.com"
        )
        for alert in alerts:
            draft = add_corpus_translation(
                draft, alert.research_id, "gemini", "es", f"Translation for {alert.research_id}."
            )
        saved = []

        with (
            patch("api.main.ALERT_POOL_SELECTED", selected_ids),
            patch("api.main._require_session_role", return_value={"email": "admin@example.com"}),
            patch("api.main._load_research_corpus", return_value=draft),
            patch("api.main._load_alert_candidates", return_value=alerts),
            patch("api.main._save_research_corpus", side_effect=saved.append),
        ):
            response = asyncio.run(admin_freeze_research_corpus(authorization="Bearer token"))

        self.assertEqual(response["status"], "frozen")
        self.assertEqual(response["approved_count"], 48)
        self.assertEqual(response["unapproved_count"], 0)
        self.assertEqual(saved[0].translations[0].review_history[-1].reviewer_id, "system:auto-approval")


if __name__ == "__main__":
    unittest.main()