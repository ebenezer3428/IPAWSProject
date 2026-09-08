from datetime import datetime, timezone
import unittest

from ipaws_research.corpus import (
    add_corpus_translation,
    build_corpus_draft,
    corpus_missing_conditions,
    freeze_corpus,
    get_frozen_translation,
    review_corpus_translation,
)
from tests.test_alert_quality import candidate


class ResearchCorpusTests(unittest.TestCase):
    def setUp(self):
        self.alerts = [candidate("CORPUS-A", "Official warning A."), candidate("CORPUS-B", "Official warning B.")]
        self.draft = build_corpus_draft(
            self.alerts,
            [alert.research_id for alert in self.alerts],
            systems=["gemini"],
            languages=["es"],
            created_by="admin@example.com",
            created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )

    def test_freeze_requires_every_declared_translation(self):
        with self.assertRaisesRegex(ValueError, "missing 2 translations"):
            freeze_corpus(self.draft, "admin@example.com")

    def test_complete_corpus_freezes_and_resolves_exact_translation(self):
        corpus = self.draft
        for alert in self.alerts:
            corpus = add_corpus_translation(
                corpus,
                alert.research_id,
                "gemini",
                "es",
                f"Traduccion de {alert.research_id}",
                {"model": "test-model"},
            )

        for alert in self.alerts:
            corpus = review_corpus_translation(
                corpus, alert.research_id, "gemini", "es", "approved",
                "reviewer@example.com", "Translation verified.",
            )
        frozen = freeze_corpus(corpus, "admin@example.com")
        artifact = get_frozen_translation(frozen, self.alerts[0].research_id, "gemini", "es")

        self.assertEqual(frozen.status, "frozen")
        self.assertEqual(artifact.metadata["model"], "test-model")
        self.assertEqual(corpus_missing_conditions(frozen), [])

    def test_changed_source_prevents_freeze(self):
        changed = self.draft.model_copy(deep=True)
        changed.sources[0].source_text = "Altered source."

        with self.assertRaisesRegex(ValueError, "source selection has changed"):
            freeze_corpus(changed, "admin@example.com")

    def test_frozen_translation_cannot_be_replaced(self):
        corpus = self.draft
        for alert in self.alerts:
            corpus = add_corpus_translation(corpus, alert.research_id, "gemini", "es", "Texto oficial")
            corpus = review_corpus_translation(
                corpus, alert.research_id, "gemini", "es", "approved",
                "reviewer@example.com", "Translation verified.",
            )
        frozen = freeze_corpus(corpus, "admin@example.com")

        with self.assertRaisesRegex(ValueError, "cannot be changed"):
            add_corpus_translation(frozen, self.alerts[0].research_id, "gemini", "es", "Nuevo texto")

    def test_frozen_lookup_rejects_source_tampering(self):
        corpus = self.draft
        for alert in self.alerts:
            corpus = add_corpus_translation(corpus, alert.research_id, "gemini", "es", "Texto oficial")
            corpus = review_corpus_translation(
                corpus, alert.research_id, "gemini", "es", "approved",
                "reviewer@example.com", "Translation verified.",
            )
        frozen = freeze_corpus(corpus, "admin@example.com").model_copy(deep=True)
        frozen.sources[0].source_text = "Tampered source."

        with self.assertRaisesRegex(ValueError, "source hash"):
            get_frozen_translation(frozen, self.alerts[0].research_id, "gemini", "es")

    def test_freeze_requires_translation_approval(self):
        corpus = self.draft
        for alert in self.alerts:
            corpus = add_corpus_translation(corpus, alert.research_id, "gemini", "es", "Texto oficial")

        with self.assertRaisesRegex(ValueError, "2 translations awaiting approval"):
            freeze_corpus(corpus, "admin@example.com")

    def test_review_preserves_generated_text_and_uses_correction(self):
        corpus = add_corpus_translation(
            self.draft, self.alerts[0].research_id, "gemini", "es", "Texto generado."
        )
        reviewed = review_corpus_translation(
            corpus, self.alerts[0].research_id, "gemini", "es", "approved",
            "reviewer@example.com", "Corrected terminology.", "Texto corregido.",
        )
        artifact = reviewed.translations[0]

        self.assertEqual(artifact.generated_translation_text, "Texto generado.")
        self.assertEqual(artifact.translation_text, "Texto corregido.")
        self.assertEqual(artifact.review_history[-1].reviewer_id, "reviewer@example.com")

    def test_regeneration_invalidates_approval_and_preserves_history(self):
        corpus = add_corpus_translation(
            self.draft, self.alerts[0].research_id, "gemini", "es", "Primera version."
        )
        corpus = review_corpus_translation(
            corpus, self.alerts[0].research_id, "gemini", "es", "approved",
            "reviewer@example.com", "Verified.",
        )
        regenerated = add_corpus_translation(
            corpus, self.alerts[0].research_id, "gemini", "es", "Segunda version."
        )

        self.assertEqual(regenerated.translations[0].review_decision, "pending")
        self.assertEqual(len(regenerated.translations[0].review_history), 1)


if __name__ == "__main__":
    unittest.main()