import json
from typing import Dict
from openai import AsyncOpenAI
from ipaws_research.models import SegmentEvaluation
from ipaws_research.utils import logger
import os

async def evaluate_segment_fairness(
    source_segment: str,
    translated_segment: str,
    language: str,
    context: str = ""
) -> SegmentEvaluation:
    """Use GPT-4o to evaluate fairness metrics with structured JSON output."""
    assert language in {"es", "hi"}, "language must be 'es' or 'hi'"
    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        # Simple rule-based scoring for offline mode
        s = source_segment.lower()
        t = translated_segment.lower()
        def score_presence(words):
            return 2 if any(w in t for w in words) else (1 if any(w in s for w in words) else 0)
        pf1 = score_presence(["inmediatamente","अभी","immediately","now","urgent"])
        pf2 = score_presence(["evacuar","खाली करें","evacuate","shelter","move"])
        pf3 = score_presence(["peligro de muerte","जीवन के लिए खतरनाक","life-threatening","severe","extreme"])
        pf4 = score_presence(["fema","cal oes","oficial","आधिकारिक","official"]) 
        pf5 = score_presence(["ahora","अभी","now","6pm","overnight"])
        pf6 = min(2, pf1 and pf2 and pf3 and pf4 and pf5)
        if1 = 2 if any(w in t for w in ["por favor","कृपया"]) else 1
        if2 = 2 if len(t) > 10 else 1
        if3 = 1
        if4 = 2
        if5 = 2
        if6 = 2 if any(w in t for w in ["fema","cal oes","oficial","आधिकारिक"]) else 1
        rationale = {
            "pf1": "Urgency markers detected in translation" if pf1==2 else "Limited or missing urgency cues",
            "pf2": "Directive verbs present" if pf2==2 else "Directive unclear",
            "pf3": "Severity preserved" if pf3==2 else "Severity not fully preserved",
            "pf4": "Authority present" if pf4==2 else "Authority weak/absent",
            "pf5": "Temporal cues preserved" if pf5==2 else "Temporal cues weak/absent",
            "pf6": "Procedural elements present" if pf6==2 else "Some elements missing",
            "if1": "Tone acceptable",
            "if2": "Accessible language",
            "if3": "Some empathy",
            "if4": "Clear and readable",
            "if5": "Culturally appropriate",
            "if6": "Trust reinforced",
        }
        return SegmentEvaluation(
            pf1_urgency_preservation=int(pf1),
            pf2_directive_clarity=int(pf2),
            pf3_risk_severity=int(pf3),
            pf4_authority_attribution=int(pf4),
            pf5_temporal_accuracy=int(pf5),
            pf6_procedural_completeness=int(pf6),
            if1_respectful_tone=int(if1),
            if2_inclusion=int(if2),
            if3_empathy_marker=int(if3),
            if4_linguistic_clarity=int(if4),
            if5_cultural_appropriateness=int(if5),
            if6_trust_signal=int(if6),
            rationale=rationale,
        )

    client = AsyncOpenAI()

    prompt = f"""You are an expert bilingual evaluator assessing emergency alert translation fairness.

SOURCE (English): "{source_segment}"
TRANSLATION ({language}): "{translated_segment}"

Score each metric on a 0-1-2 scale:
- 0 = Degraded/Absent: Indicator missing, weakened, or misleading
- 1 = Partially Preserved: Present but softened or less effective
- 2 = Fully Preserved: Retained with comparable force and clarity

PROCEDURAL FAIRNESS METRICS:

1. PF1 - Urgency Preservation
   Does translation preserve urgency cues like "immediately", "now", "life-threatening"?
   Examples: "inmediatamente", "अभी", "जीवन के लिए खतरनाक"

2. PF2 - Directive Clarity
   Is the required action (evacuate, shelter, move) explicit and clear?
   0: Ambiguous action | 1: Indirect phrasing | 2: Clear imperative

3. PF3 - Risk Severity
   Is hazard severity (life-threatening, extreme, severe) preserved?
   0: Risk downplayed | 1: General severity | 2: Specific severity maintained

4. PF4 - Authority Attribution
   Is institutional authority (Cal OES, FEMA, official) clearly conveyed?
   0: Authority absent | 1: Weak authority | 2: Clear authority

5. PF5 - Temporal Accuracy
   Are time references (immediately, overnight, 6pm) accurately translated?
   0: Time wrong/missing | 1: Partial accuracy | 2: Fully accurate

6. PF6 - Procedural Completeness
   Are all procedural elements (what, when, where, who) present?
   0: Major elements missing | 1: Some missing | 2: All present

INTERACTIONAL FAIRNESS METRICS:

7. IF1 - Respectful Tone
   Is the tone respectful and appropriate (not dismissive or condescending)?
   0: Disrespectful | 1: Neutral/formal | 2: Respectful

8. IF2 - Inclusion
   Is language accessible to diverse audiences (not overly technical)?
   0: Exclusionary | 1: Limited inclusion | 2: Inclusive

9. IF3 - Empathy Marker
   Are empathy cues (safety, concern, reassurance) present?
   0: No empathy | 1: Weak empathy | 2: Clear empathy

10. IF4 - Linguistic Clarity
    Is translation fluent, readable, and syntactically clear?
    0: Confusing | 1: Moderately clear | 2: Very clear

11. IF5 - Cultural Appropriateness
    Does translation align with cultural norms and expectations?
    0: Culturally inappropriate | 1: Minor issues | 2: Appropriate

12. IF6 - Trust Signal
    Does translation foster trust in authorities and compliance?
    0: Trust undermined | 1: Neutral | 2: Trust reinforced

Return JSON with this exact structure:
{{
  "pf1_urgency_preservation": <0|1|2>,
  "pf2_directive_clarity": <0|1|2>,
  "pf3_risk_severity": <0|1|2>,
  "pf4_authority_attribution": <0|1|2>,
  "pf5_temporal_accuracy": <0|1|2>,
  "pf6_procedural_completeness": <0|1|2>,
  "if1_respectful_tone": <0|1|2>,
  "if2_inclusion": <0|1|2>,
  "if3_empathy_marker": <0|1|2>,
  "if4_linguistic_clarity": <0|1|2>,
  "if5_cultural_appropriateness": <0|1|2>,
  "if6_trust_signal": <0|1|2>,
  "rationale": {{
    "pf1": "brief explanation",
    "pf2": "brief explanation",
    "pf3": "brief explanation",
    "pf4": "brief explanation",
    "pf5": "brief explanation",
    "pf6": "brief explanation",
    "if1": "brief explanation",
    "if2": "brief explanation",
    "if3": "brief explanation",
    "if4": "brief explanation",
    "if5": "brief explanation",
    "if6": "brief explanation"
  }}
}}
"""

    # Prefer chat completions JSON mode for broader SDK compatibility
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    try:
        resp = await client.chat.completions.create(
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You return JSON only, no extra text."},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
    except Exception as e:
        logger.error(f"OpenAI chat.completions failed: {e}")
        # Fallback to Responses API if available
        try:
            resp = await client.responses.create(
                model=model,
                temperature=0.1,
                input=prompt,
            )
            raw = getattr(resp, "output_text", None) or "{}"
        except Exception as e2:
            logger.error(f"OpenAI responses.create failed: {e2}")
            raise

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.error(f"Failed to parse evaluator JSON: {e}; raw={raw}")
        raise

    # Validate metrics are 0/1/2
    keys = [
        "pf1_urgency_preservation","pf2_directive_clarity","pf3_risk_severity",
        "pf4_authority_attribution","pf5_temporal_accuracy","pf6_procedural_completeness",
        "if1_respectful_tone","if2_inclusion","if3_empathy_marker","if4_linguistic_clarity",
        "if5_cultural_appropriateness","if6_trust_signal"
    ]
    for k in keys:
        v = data.get(k)
        if v not in (0,1,2):
            logger.warning(f"Evaluator value for {k} invalid: {v}; coercing to 0")
            data[k] = 0

    if "rationale" not in data:
        data["rationale"] = {}

    return SegmentEvaluation(**data)
