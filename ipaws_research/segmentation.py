from typing import List, Tuple
import re
import spacy
from ipaws_research.utils import logger

def _load_spacy(language: str):
    try:
        if language == "en":
            return spacy.load("en_core_web_sm")
        elif language == "es":
            return spacy.load("es_core_news_sm")
        else:
            # Hindi: use UD multi-language for sentence segmentation
            return spacy.load("xx_sent_ud_sm")
    except Exception as e:
        logger.warning(f"spaCy model load failed for {language}: {e}; using blank model with sentencizer")
        nlp = spacy.blank(language if language in {"en","es"} else "xx")
        nlp.add_pipe("sentencizer")
        return nlp

DIRECTIVE_KEYWORDS = {
    "en": ["evacuate","shelter","move","stay","remain","avoid","leave","do not"],
    "es": ["evacuar","refugiarse","mover","quedarse","evitar","salir","no"],
    "hi": ["खाली करें","शरण लें","हटें","रहें","बचें","छोड़ें","न करें"]
}
URGENCY_KEYWORDS = {
    "en": ["immediately","now","urgent","asap","right away"],
    "es": ["inmediatamente","ahora","urgente"],
    "hi": ["तुरंत","अभी","आपात"]
}
RISK_KEYWORDS = {
    "en": ["life-threatening","dangerous","severe","extreme","hazard"],
    "es": ["peligro de muerte","peligroso","severo","extremo","riesgo"],
    "hi": ["जीवन के लिए खतरनाक","खतरनाक","गंभीर","अत्यधिक","जोखिम"]
}
AUTHORITY_KEYWORDS = {
    "en": ["FEMA","Cal OES","official","issued by","authority"],
    "es": ["FEMA","Cal OES","oficial","emitido por","autoridad"],
    "hi": ["FEMA","Cal OES","आधिकारिक","जारी किया","प्राधिकरण"]
}

def identify_communicative_function(segment: str, language: str = "en") -> str:
    s = segment.lower()
    # Priority order
    for kw in URGENCY_KEYWORDS.get(language, []):
        if kw in s:
            return "urgency"
    for kw in DIRECTIVE_KEYWORDS.get(language, []):
        if kw in s:
            return "directive"
    for kw in RISK_KEYWORDS.get(language, []):
        if kw in s:
            return "risk"
    for kw in AUTHORITY_KEYWORDS.get(language, []):
        if kw in s:
            return "authority"
    return "context"

def _split_clauses(text: str) -> List[str]:
    # Split on semicolons, dashes, and conjunctions as a heuristic
    parts = re.split(r"[;\-]|\b(and|y|और)\b", text)
    return [p.strip() for p in parts if p and not re.fullmatch(r"(and|y|और)", p)]

def segment_alert(text: str, language: str = "en") -> List[Tuple[str, str]]:
    """Segment alert into sentence/clause-level units with communicative functions."""
    nlp = _load_spacy(language)
    doc = nlp(text)
    segments: List[Tuple[str, str]] = []
    for sent in doc.sents:
        clauses = _split_clauses(sent.text)
        for c in clauses:
            func = identify_communicative_function(c, language=language)
            segments.append((c, func))
    return segments
