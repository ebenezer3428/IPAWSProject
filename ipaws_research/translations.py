import asyncio
from datetime import datetime
from typing import Dict
from ipaws_research.utils import logger

# GPT-4o
from openai import AsyncOpenAI
import os

# Google NMT
from typing import Optional

# Meta NLLB-200
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

# Cache for NLLB models
_NLLB_CACHE = {}

def _offline_translate(source_text: str, target_language: str) -> Dict[str, Dict]:
    es_map = {
        "Evacuate": "Evacuar",
        "immediately": "inmediatamente",
        "Life-threatening": "peligro de muerte",
        "conditions": "condiciones",
        "due to": "debido a",
        "wildfire": "incendio forestal",
        "Shelter": "Refugiarse",
        "Move": "Moverse",
    }
    hi_map = {
        "Evacuate": "खाली करें",
        "immediately": "अभी",
        "Life-threatening": "जीवन के लिए खतरनाक",
        "conditions": "स्थिति",
        "due to": "के कारण",
        "wildfire": "वनाग्नि",
        "Shelter": "शरण लें",
        "Move": "हटें",
    }
    text = source_text
    if target_language == "es":
        for k, v in es_map.items():
            text = text.replace(k, v).replace(k.lower(), v)
        translation = f"{text}"
    else:
        for k, v in hi_map.items():
            text = text.replace(k, v).replace(k.lower(), v)
        translation = f"{text}"
    metadata = {"model": "offline", "timestamp": datetime.utcnow().isoformat(), "tokens": ""}
    return {"translation": translation, "metadata": metadata}

async def translate_with_gpt4o(
    source_text: str,
    target_language: str,
    preserve_urgency: bool = True
) -> Dict[str, Dict]:
    """
    Translate emergency alert using GPT-4o with fairness-preserving prompt.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"
    client = AsyncOpenAI()

    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        return _offline_translate(source_text, target_language)

    lang_name = "Spanish" if target_language == "es" else "Hindi"
    cultural_notes = (
        "Use clear public service style common in Spanish-language public safety communications in the U.S."
        if target_language == "es"
        else "Use formal Hindi appropriate for public advisories in India; avoid slang; ensure comprehension across dialects."
    )

    system_prompt = (
        f"You are translating an emergency alert from English to {lang_name}. "
        "CRITICAL: Preserve urgency markers (immediately, now, life-threatening), directive clarity (evacuate, shelter), "
        "risk severity language, and institutional authority. Adapt culturally while maintaining an authoritative emergency tone. "
        f"{cultural_notes} "
        "Keep information complete and timelines accurate."
    )

    user_prompt = (
        ("Emphasize urgency cues where present. " if preserve_urgency else "") +
        f"Translate faithfully and clearly:\n\n{source_text}"
    )

    retries = 3
    delay = 1.5
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
            # Prefer Chat Completions for broader SDK compatibility
            resp = await client.chat.completions.create(
                model=model_name,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = resp.choices[0].message.content or ""
            usage_tokens = None
            try:
                usage = getattr(resp, "usage", None)
                if usage:
                    usage_tokens = getattr(usage, "total_tokens", None) or (
                        getattr(usage, "prompt_tokens", 0) + getattr(usage, "completion_tokens", 0)
                    )
            except Exception:
                usage_tokens = None

            metadata = {
                "model": model_name,
                "timestamp": datetime.utcnow().isoformat(),
                "tokens": str(usage_tokens) if usage_tokens is not None else ""
            }
            return {"translation": text.strip(), "metadata": metadata}
        except Exception as e:
            last_err = e
            logger.warning(f"GPT-4o translation attempt {attempt} failed: {e}")
            await asyncio.sleep(delay)
            delay *= 2

    raise RuntimeError(f"translate_with_gpt4o failed after retries: {last_err}")

async def translate_with_google_nmt(
    source_text: str,
    target_language: str,
    project_id: str = "your-project-id"
) -> Dict[str, Dict]:
    """
    Translate using Google Cloud Translation API (NMT v3). Wrap sync client in thread to maintain async.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"

    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        return _offline_translate(source_text, target_language)

    async def _do_translate():
        from google.cloud import translate_v3
        client = translate_v3.TranslationServiceClient()
        parent = f"projects/{project_id}/locations/global"
        lang_map = {"es": "es-ES", "hi": "hi-IN"}
        target_code = lang_map[target_language]
        request = translate_v3.TranslateTextRequest(
            parent=parent,
            contents=[source_text],
            source_language_code="en",
            target_language_code=target_code,
            mime_type="text/plain",
        )
        response = client.translate_text(request=request)
        translations = response.translations
        translated_text = translations[0].translated_text if translations else ""
        metadata = {
            "model": getattr(response, "model", "nmt-v3"),
            "timestamp": datetime.utcnow().isoformat(),
            "tokens": "",
            "detected_language": translations[0].detected_language_code if translations else ""
        }
        return {"translation": translated_text, "metadata": metadata}

    return await asyncio.to_thread(_do_translate)

async def translate_with_nllb200(
    source_text: str,
    target_language: str,
    model_size: str = "distilled-600M"
) -> Dict[str, Dict]:
    """
    Translate using Meta's NLLB-200 with caching and beam search.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"

    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        return _offline_translate(source_text, target_language)
    repo_map = {
        "distilled-600M": "facebook/nllb-200-distilled-600M",
        "1.3B": "facebook/nllb-200-1.3B",
        "3.3B": "facebook/nllb-200-3.3B",
    }
    repo = repo_map.get(model_size, repo_map["distilled-600M"])

    def _load_model():
        if repo not in _NLLB_CACHE:
            tokenizer = AutoTokenizer.from_pretrained(repo)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = AutoModelForSeq2SeqLM.from_pretrained(repo)
            model.to(device)
            _NLLB_CACHE[repo] = {"tokenizer": tokenizer, "model": model, "device": device}
        return _NLLB_CACHE[repo]

    def _translate_sync():
        bundle = _load_model()
        tokenizer = bundle["tokenizer"]
        model = bundle["model"]
        device = bundle["device"]
        # Language codes
        src = "eng_Latn"
        tgt = "spa_Latn" if target_language == "es" else "hin_Deva"
        inputs = tokenizer(source_text, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        generated_tokens = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids(tgt),
            num_beams=5,
            max_length=512,
        )
        result = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
        metadata = {
            "model": repo,
            "timestamp": datetime.utcnow().isoformat(),
            "tokens": "",
        }
        return {"translation": result.strip(), "metadata": metadata}

    return await asyncio.to_thread(_translate_sync)
