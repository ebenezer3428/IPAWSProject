from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from pydantic import BaseModel, Field

from ipaws_research.models import EmergencyAlert


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class CorpusSource(BaseModel):
    alert_id: str
    source_text: str
    source_hash: str
    category: str
    identifier: str = ""
    openfema_id: str = ""
    sender: str = ""
    area: str = ""
    language: str = ""
    sent: datetime | None = None
    event: str = ""
    urgency: str = ""
    severity: str = ""
    certainty: str = ""
    message_type: str = ""


class CorpusTranslation(BaseModel):
    alert_id: str
    system: str
    language: str
    source_hash: str
    translation_text: str
    translation_hash: str
    generated_translation_text: str = ""
    generated_translation_hash: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    review_decision: str = "pending"
    reviewed_source_hash: str = ""
    reviewed_generated_hash: str = ""
    reviewed_translation_hash: str = ""
    review_history: List["TranslationReviewEvent"] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.generated_translation_text:
            self.generated_translation_text = self.translation_text
        if not self.generated_translation_hash:
            self.generated_translation_hash = text_hash(self.generated_translation_text)


class TranslationReviewEvent(BaseModel):
    previous_decision: str = "pending"
    decision: str
    reviewer_id: str
    reviewed_at: datetime
    reason: str
    source_hash: str
    generated_translation_hash: str
    translation_hash: str
    translation_text: str


class ResearchCorpus(BaseModel):
    schema_version: int = 1
    corpus_id: str
    status: str = "draft"
    created_at: datetime
    created_by: str
    frozen_at: datetime | None = None
    frozen_by: str = ""
    selection_hash: str
    systems: List[str]
    languages: List[str]
    sources: List[CorpusSource]
    translations: List[CorpusTranslation] = Field(default_factory=list)


def _selection_hash(sources: Iterable[CorpusSource]) -> str:
    payload = [
        {"alert_id": source.alert_id, "source_hash": source.source_hash}
        for source in sorted(sources, key=lambda item: item.alert_id)
    ]
    return text_hash(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def build_corpus_draft(
    candidates: Iterable[EmergencyAlert],
    selected_ids: Iterable[str],
    systems: Iterable[str],
    languages: Iterable[str],
    created_by: str,
    created_at: datetime | None = None,
) -> ResearchCorpus:
    selected = set(selected_ids)
    by_id = {candidate.research_id or candidate.alert_id: candidate for candidate in candidates}
    sources = []
    for alert_id in sorted(selected):
        candidate = by_id[alert_id]
        source_text = candidate.cleaned_source_text or candidate.source_text
        sources.append(CorpusSource(
            alert_id=alert_id,
            source_text=source_text,
            source_hash=text_hash(source_text),
            category=candidate.category,
            identifier=candidate.identifier,
            openfema_id=candidate.openfema_id,
            sender=candidate.sender,
            area=candidate.area,
            language=candidate.language,
            sent=candidate.sent,
            event=candidate.event,
            urgency=candidate.urgency_level,
            severity=candidate.severity_level,
            certainty=candidate.certainty_level,
            message_type=candidate.message_type,
        ))
    selection_hash = _selection_hash(sources)
    timestamp = created_at or datetime.now(timezone.utc)
    return ResearchCorpus(
        corpus_id=f"CORPUS-{selection_hash[:16].upper()}",
        created_at=timestamp,
        created_by=created_by,
        selection_hash=selection_hash,
        systems=sorted(set(systems)),
        languages=sorted(set(languages)),
        sources=sources,
    )


def add_corpus_translation(
    corpus: ResearchCorpus,
    alert_id: str,
    system: str,
    language: str,
    translation_text: str,
    metadata: Dict[str, Any] | None = None,
) -> ResearchCorpus:
    if corpus.status != "draft":
        raise ValueError("Frozen corpus translations cannot be changed")
    source = next((item for item in corpus.sources if item.alert_id == alert_id), None)
    if source is None:
        raise ValueError("Translation alert is not part of this corpus")
    if system not in corpus.systems or language not in corpus.languages:
        raise ValueError("Translation condition is not declared by this corpus")
    cleaned_translation = translation_text.strip()
    if not cleaned_translation:
        raise ValueError("Translation text cannot be empty")
    artifact = CorpusTranslation(
        alert_id=alert_id,
        system=system,
        language=language,
        source_hash=source.source_hash,
        translation_text=cleaned_translation,
        translation_hash=text_hash(cleaned_translation),
        generated_translation_text=cleaned_translation,
        generated_translation_hash=text_hash(cleaned_translation),
        metadata=metadata or {},
    )
    previous = next((
        item for item in corpus.translations
        if (item.alert_id, item.system, item.language) == (alert_id, system, language)
    ), None)
    if previous is not None:
        artifact.review_history = list(previous.review_history)
    translations = [
        item for item in corpus.translations
        if (item.alert_id, item.system, item.language) != (alert_id, system, language)
    ]
    translations.append(artifact)
    translations.sort(key=lambda item: (item.alert_id, item.system, item.language))
    return corpus.model_copy(update={"translations": translations})


def review_corpus_translation(
    corpus: ResearchCorpus,
    alert_id: str,
    system: str,
    language: str,
    decision: str,
    reviewer_id: str,
    reason: str,
    reviewed_text: str = "",
    reviewed_at: datetime | None = None,
) -> ResearchCorpus:
    if corpus.status != "draft":
        raise ValueError("Frozen corpus translations cannot be reviewed")
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approved", "rejected"}:
        raise ValueError("Review decision must be approved or rejected")
    if not reviewer_id.strip() or not reason.strip():
        raise ValueError("Reviewer identity and reason are required")
    index = next((
        index for index, item in enumerate(corpus.translations)
        if (item.alert_id, item.system, item.language) == (alert_id, system, language)
    ), None)
    if index is None:
        raise ValueError("Translation artifact was not found")
    artifact = corpus.translations[index]
    effective_text = reviewed_text.strip() if reviewed_text.strip() else artifact.generated_translation_text
    effective_hash = text_hash(effective_text)
    event = TranslationReviewEvent(
        previous_decision=artifact.review_decision,
        decision=normalized_decision,
        reviewer_id=reviewer_id.strip(),
        reviewed_at=reviewed_at or datetime.now(timezone.utc),
        reason=reason.strip(),
        source_hash=artifact.source_hash,
        generated_translation_hash=artifact.generated_translation_hash,
        translation_hash=effective_hash,
        translation_text=effective_text,
    )
    reviewed = artifact.model_copy(update={
        "translation_text": effective_text,
        "translation_hash": effective_hash,
        "review_decision": normalized_decision,
        "reviewed_source_hash": artifact.source_hash,
        "reviewed_generated_hash": artifact.generated_translation_hash,
        "reviewed_translation_hash": effective_hash,
        "review_history": [*artifact.review_history, event],
    })
    translations = list(corpus.translations)
    translations[index] = reviewed
    return corpus.model_copy(update={"translations": translations})


def is_translation_approved(item: CorpusTranslation) -> bool:
    return (
        item.review_decision == "approved"
        and item.reviewed_source_hash == item.source_hash
        and item.generated_translation_hash == text_hash(item.generated_translation_text)
        and item.reviewed_generated_hash == item.generated_translation_hash
        and item.translation_hash == text_hash(item.translation_text)
        and item.reviewed_translation_hash == item.translation_hash
    )


def corpus_missing_conditions(corpus: ResearchCorpus) -> List[str]:
    present = {
        (item.alert_id, item.system, item.language)
        for item in corpus.translations
        if item.translation_text
        and item.translation_hash == text_hash(item.translation_text)
        and any(
            source.alert_id == item.alert_id and source.source_hash == item.source_hash
            for source in corpus.sources
        )
    }
    return [
        f"{source.alert_id}:{system}:{language}"
        for source in corpus.sources
        for system in corpus.systems
        for language in corpus.languages
        if (source.alert_id, system, language) not in present
    ]


def corpus_unapproved_conditions(corpus: ResearchCorpus) -> List[str]:
    return [
        f"{item.alert_id}:{item.system}:{item.language}"
        for item in corpus.translations
        if not is_translation_approved(item)
    ]


def freeze_corpus(
    corpus: ResearchCorpus,
    frozen_by: str,
    frozen_at: datetime | None = None,
) -> ResearchCorpus:
    if corpus.status != "draft":
        raise ValueError("Corpus is already frozen")
    if any(source.source_hash != text_hash(source.source_text) for source in corpus.sources):
        raise ValueError("Corpus source selection has changed")
    if _selection_hash(corpus.sources) != corpus.selection_hash:
        raise ValueError("Corpus source selection has changed")
    missing = corpus_missing_conditions(corpus)
    if missing:
        raise ValueError(f"Corpus is missing {len(missing)} translations")
    unapproved = corpus_unapproved_conditions(corpus)
    if unapproved:
        raise ValueError(f"Corpus has {len(unapproved)} translations awaiting approval")
    return corpus.model_copy(update={
        "status": "frozen",
        "frozen_at": frozen_at or datetime.now(timezone.utc),
        "frozen_by": frozen_by,
    })


def get_frozen_translation(
    corpus: ResearchCorpus,
    alert_id: str,
    system: str,
    language: str,
) -> CorpusTranslation:
    if corpus.status != "frozen":
        raise ValueError("Research corpus is not frozen")
    source = next((item for item in corpus.sources if item.alert_id == alert_id), None)
    if source is None or source.source_hash != text_hash(source.source_text):
        raise ValueError("Frozen source hash does not match its text")
    if _selection_hash(corpus.sources) != corpus.selection_hash:
        raise ValueError("Frozen corpus selection hash does not match its sources")
    artifact = next((
        item for item in corpus.translations
        if (item.alert_id, item.system, item.language) == (alert_id, system, language)
    ), None)
    if artifact is None:
        raise ValueError("Frozen translation was not found")
    if artifact.source_hash != source.source_hash:
        raise ValueError("Frozen translation source hash does not match its source")
    if artifact.translation_hash != text_hash(artifact.translation_text):
        raise ValueError("Frozen translation hash does not match its text")
    if not is_translation_approved(artifact):
        raise ValueError("Frozen translation approval is invalid")
    return artifact