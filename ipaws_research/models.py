from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime

class EmergencyAlert(BaseModel):
    alert_id: str
    source_text: str
    category: str
    urgency_level: str
    certainty_level: str = "unknown"
    severity_level: str = "unknown"
    timestamp: datetime
    state: str = "CA"
    area: str = ""

class TranslatedAlert(BaseModel):
    alert_id: str
    system: str  # 'gpt4o' | 'google_nmt' | 'nllb200'
    target_language: str  # 'es' | 'hi'
    translation_text: str
    metadata: Dict[str, Optional[str]] = Field(default_factory=dict)

class AlertSegment(BaseModel):
    alert_id: str
    segment_index: int
    segment_text: str
    communicative_function: str  # 'directive' | 'urgency' | 'risk' | 'authority' | 'context'
    language: str  # 'en'|'es'|'hi'

class FairnessScore(BaseModel):
    alert_id: str
    system: str
    language: str
    segment_index: int
    # Procedural Fairness (0-2)
    pf1_urgency_preservation: int
    pf2_directive_clarity: int
    pf3_risk_severity: int
    pf4_authority_attribution: int
    pf5_temporal_accuracy: int
    pf6_procedural_completeness: int
    # Interactional Fairness (0-2)
    if1_respectful_tone: int
    if2_inclusion: int
    if3_empathy_marker: int
    if4_linguistic_clarity: int
    if5_cultural_appropriateness: int
    if6_trust_signal: int
    rationale: Dict[str, str]

class CompositeScores(BaseModel):
    alert_id: str
    language: str
    system: str
    pfi: float
    ifi: float
    ofs: float
    segments_count: int

class StatisticalResults(BaseModel):
    name: str
    test: str
    statistic: float
    p_value: float
    effect_size: Optional[float] = None
    details: Dict[str, str] = Field(default_factory=dict)

# Reuse for evaluator structured output
class SegmentEvaluation(BaseModel):
    pf1_urgency_preservation: int
    pf2_directive_clarity: int
    pf3_risk_severity: int
    pf4_authority_attribution: int
    pf5_temporal_accuracy: int
    pf6_procedural_completeness: int
    if1_respectful_tone: int
    if2_inclusion: int
    if3_empathy_marker: int
    if4_linguistic_clarity: int
    if5_cultural_appropriateness: int
    if6_trust_signal: int
    rationale: Dict[str, str]
