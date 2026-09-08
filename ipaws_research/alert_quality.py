from __future__ import annotations

import re
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from ipaws_research.models import EmergencyAlert, QualityFinding, ReviewEvent


EXCLUSION_CODES = {
    "empty_source",
    "missing_identity",
    "test_message",
    "cancel_message",
    "non_actual_status",
}

TEST_PHRASES = (
    "this is only a test",
    "this is a test of",
    "no action is required",
    "there is no emergency",
    "required monthly test",
    "this concludes this test",
)

SPANISH_MARKERS = re.compile(
    r"\b(?:esta|este|una|para|por|evite|area|emergencia|incendio|policia|refugio|evacuacion)\b",
    re.IGNORECASE,
)
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
COUNTY_NAME = re.compile(r"\b([a-z][a-z .'-]*?\s+county)\b", re.IGNORECASE)


def _finding(code: str, severity: str, message: str, evidence: str = "") -> QualityFinding:
    return QualityFinding(code=code, severity=severity, message=message, evidence=evidence[:300])


def clean_repeated_passages(text: str) -> tuple[str, List[str]]:
    """Remove exact repeated paragraphs while retaining evidence for review."""
    passages = [passage.strip() for passage in re.split(r"\n\s*\n", text or "") if passage.strip()]
    seen = set()
    cleaned: List[str] = []
    duplicates: List[str] = []
    for passage in passages:
        normalized = re.sub(r"\s+", " ", passage).strip().casefold()
        if normalized in seen:
            duplicates.append(passage)
            continue
        seen.add(normalized)
        cleaned.append(passage)
    return "\n\n".join(cleaned), duplicates


def source_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _county_names(area: str) -> set[str]:
    return {
        re.sub(r"\s+", " ", match).strip().casefold()
        for match in COUNTY_NAME.findall(area or "")
    }


def _event_type(event: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", event.casefold()).strip()


def is_candidate_selectable(alert: EmergencyAlert) -> bool:
    return alert.quality_status == "eligible"


def review_candidate(
    alert: EmergencyAlert,
    decision: str,
    reviewer_id: str,
    reason: str,
    cleaned_text: str = "",
    reviewed_at: datetime | None = None,
) -> EmergencyAlert:
    normalized_decision = decision.strip().lower()
    if alert.quality_status != "flagged":
        raise ValueError("Only warning-flagged records can be reviewed")
    if any(finding.severity == "error" for finding in alert.quality_findings):
        raise ValueError("Records with error findings cannot be approved or rejected through soft-flag review")
    if normalized_decision not in {"approved", "rejected"}:
        raise ValueError("Review decision must be approved or rejected")
    if not reviewer_id.strip() or not reason.strip():
        raise ValueError("Reviewer identity and reason are required")
    approved_text = cleaned_text.strip() if normalized_decision == "approved" else ""
    if normalized_decision == "approved" and cleaned_text and not approved_text:
        raise ValueError("Approved cleaned text cannot be empty")
    current_hash = source_text_hash(alert.raw_source_text or alert.source_text)
    event = ReviewEvent(
        previous_decision=alert.review_decision,
        decision=normalized_decision,
        reviewer_id=reviewer_id.strip(),
        reviewed_at=reviewed_at or datetime.now(timezone.utc),
        reason=reason.strip(),
        source_hash=current_hash,
    )
    updates = {
        "review_decision": normalized_decision,
        "reviewed_source_hash": current_hash,
        "reviewed_cleaned_text": approved_text,
        "review_history": [*alert.review_history, event],
    }
    if approved_text:
        updates.update({"source_text": approved_text, "cleaned_source_text": approved_text})
    return alert.model_copy(update=updates)


def merge_review_state(existing: EmergencyAlert, incoming: EmergencyAlert) -> EmergencyAlert:
    existing_hash = source_text_hash(existing.raw_source_text or existing.source_text)
    incoming_hash = source_text_hash(incoming.raw_source_text or incoming.source_text)
    updates = {"review_history": list(existing.review_history)}
    if existing_hash == incoming_hash:
        updates.update({
            "review_decision": existing.review_decision,
            "reviewed_source_hash": existing.reviewed_source_hash,
            "reviewed_cleaned_text": existing.reviewed_cleaned_text,
        })
    return incoming.model_copy(update=updates)


def validate_candidate(alert: EmergencyAlert) -> EmergencyAlert:
    findings: List[QualityFinding] = []
    raw_text = (alert.raw_source_text or alert.source_text or "").strip()
    cleaned_text, duplicate_passages = clean_repeated_passages(raw_text)
    current_hash = source_text_hash(raw_text)

    if not raw_text:
        findings.append(_finding("empty_source", "error", "No English source text was extracted."))
    if not alert.identifier or not alert.sender:
        findings.append(_finding(
            "missing_identity",
            "error",
            "CAP identifier and sender are required for source provenance.",
        ))
    if alert.status and alert.status.casefold() != "actual":
        findings.append(_finding("non_actual_status", "error", f"CAP status is {alert.status}.", alert.status))
    if alert.message_type.casefold() == "cancel":
        findings.append(_finding("cancel_message", "error", "Cancellation-only records are not research source alerts."))
    matched_test_phrase = next((phrase for phrase in TEST_PHRASES if phrase in raw_text.casefold()), "")
    if matched_test_phrase:
        findings.append(_finding("test_message", "error", "The source text identifies this as a test.", matched_test_phrase))
    if duplicate_passages:
        findings.append(_finding(
            "duplicate_passage",
            "warning",
            "One or more exact passages repeat within the alert.",
            duplicate_passages[0],
        ))
    if DEVANAGARI.search(raw_text) or len(SPANISH_MARKERS.findall(raw_text)) >= 3:
        findings.append(_finding(
            "mixed_language",
            "warning",
            "The English source field contains likely non-English content.",
        ))
    if alert.category == "unknown":
        findings.append(_finding("unknown_category", "warning", "The alert could not be assigned to a study category."))

    missing_metadata = [
        name for name, value in (
            ("language", alert.language),
            ("sent", alert.sent),
            ("effective", alert.effective),
            ("expires", alert.expires),
            ("area", alert.area),
            ("urgency", alert.urgency_level if alert.urgency_level != "unknown" else ""),
            ("severity", alert.severity_level if alert.severity_level != "unknown" else ""),
            ("certainty", alert.certainty_level if alert.certainty_level != "unknown" else ""),
            ("message_type", alert.message_type),
        ) if not value
    ]
    if missing_metadata:
        findings.append(_finding(
            "missing_metadata",
            "warning",
            "One or more expected CAP metadata fields are missing.",
            ", ".join(missing_metadata),
        ))

    codes = {finding.code for finding in findings}
    status = "excluded" if codes.intersection(EXCLUSION_CODES) else ("flagged" if findings else "eligible")
    review_is_current = alert.reviewed_source_hash == current_hash
    review_decision = alert.review_decision if review_is_current else "pending"
    reviewed_source_hash = alert.reviewed_source_hash if review_is_current else ""
    reviewed_cleaned_text = alert.reviewed_cleaned_text if review_is_current else ""
    if status == "flagged" and review_decision == "approved" and reviewed_cleaned_text:
        cleaned_text = reviewed_cleaned_text
    return alert.model_copy(update={
        "source_text": cleaned_text,
        "cleaned_source_text": cleaned_text,
        "quality_status": status,
        "quality_findings": findings,
        "source_hash": current_hash,
        "review_decision": review_decision,
        "reviewed_source_hash": reviewed_source_hash,
        "reviewed_cleaned_text": reviewed_cleaned_text,
    })


def validate_candidates(alerts: Iterable[EmergencyAlert]) -> List[EmergencyAlert]:
    validated = [validate_candidate(alert) for alert in alerts]
    by_text: Dict[str, List[int]] = defaultdict(list)
    for index, alert in enumerate(validated):
        normalized = re.sub(r"\s+", " ", alert.cleaned_source_text).strip().casefold()
        if normalized:
            by_text[normalized].append(index)

    for indexes in by_text.values():
        for duplicate_index in indexes[1:]:
            alert = validated[duplicate_index]
            finding = _finding(
                "duplicate_alert",
                "error",
                "This alert duplicates another candidate's normalized research text.",
                validated[indexes[0]].research_id,
            )
            validated[duplicate_index] = alert.model_copy(update={
                "quality_status": "excluded",
                "quality_findings": [*alert.quality_findings, finding],
            })

    claimed_county_events: Dict[tuple[str, str, str], int] = {}
    newest_first = sorted(
        range(len(validated)),
        key=lambda index: validated[index].sent or validated[index].timestamp,
        reverse=True,
    )
    for index in newest_first:
        alert = validated[index]
        event_type = _event_type(alert.event)
        sent_at = alert.sent or alert.timestamp
        counties = _county_names(alert.area)
        if not event_type or not counties or not sent_at:
            continue
        keys = {(sent_at.date().isoformat(), event_type, county) for county in counties}
        duplicate_key = next((key for key in keys if key in claimed_county_events), None)
        if duplicate_key:
            original = validated[claimed_county_events[duplicate_key]]
            finding = _finding(
                "duplicate_county_day_event",
                "error",
                "A newer alert has the same event type for this county on the same day.",
                original.research_id or original.alert_id,
            )
            validated[index] = alert.model_copy(update={
                "quality_status": "excluded",
                "quality_findings": [*alert.quality_findings, finding],
            })
            continue
        for key in keys:
            claimed_county_events[key] = index
    return validated