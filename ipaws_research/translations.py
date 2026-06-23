import asyncio
from datetime import datetime
from typing import Dict
from ipaws_research.utils import logger

# GPT-5.5
from openai import AsyncOpenAI
import os
import replicate

# Gemini
from google import genai as google_genai
from google.genai import types as genai_types

# Google NMT
from typing import Optional

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
    preserve_urgency: bool = True,
    model: str = "gpt-4o"
) -> Dict[str, Dict]:
    """
    Translate emergency alert using OpenAI models with fairness-preserving prompt.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"
    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        return _offline_translate(source_text, target_language)

    client = AsyncOpenAI()

    lang_names = {"es": "Spanish", "hi": "Hindi"}
    lang_name = lang_names.get(target_language, "Spanish")

    cultural_notes_map = {
        "es": "Use clear public service style common in Spanish-language public safety communications in the U.S.",
        "hi": "Use formal Hindi appropriate for public advisories in India; avoid slang; ensure comprehension across dialects.",
    }
    cultural_notes = cultural_notes_map.get(target_language, "")

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
    # Map friendly names to actual model strings
    model_map = {
        "gpt4o": "gpt-4o",
        "gpt5.5": os.getenv("OPENAI_GPT55_MODEL", "gpt-5.5"),
    }
    target_model = model_map.get(model, model)
    use_responses_api = target_model.startswith("gpt-5")
    
    for attempt in range(1, retries + 1):
        try:
            if use_responses_api:
                resp = await client.responses.create(
                    model=target_model,
                    instructions=system_prompt,
                    input=user_prompt,
                    reasoning={"effort": "low"},
                    text={"verbosity": "low"},
                    store=False,
                )
                text = (getattr(resp, "output_text", None) or "").strip()
                usage_tokens = None
                try:
                    usage = getattr(resp, "usage", None)
                    if usage:
                        usage_tokens = getattr(usage, "total_tokens", None) or (
                            (getattr(usage, "input_tokens", 0) or 0)
                            + (getattr(usage, "output_tokens", 0) or 0)
                        )
                except Exception:
                    usage_tokens = None
            else:
                resp = await client.chat.completions.create(
                    model=target_model,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                text = (resp.choices[0].message.content or "").strip()
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
                "model": target_model,
                "timestamp": datetime.utcnow().isoformat(),
                "tokens": str(usage_tokens) if usage_tokens is not None else ""
            }
            return {"translation": text, "metadata": metadata}
        except Exception as e:
            last_err = e
            logger.warning(f"OpenAI translation attempt {attempt} failed: {e}")
            await asyncio.sleep(delay)
            delay *= 2

    raise RuntimeError(f"OpenAI translation failed after retries: {last_err}")

async def translate_with_google_nmt(
    source_text: str,
    target_language: str,
    project_id: Optional[str] = None
) -> Dict[str, Dict]:
    """
    Translate using Google Cloud Translation API (NMT v3). Wrap sync client in thread to maintain async.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"

    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        return _offline_translate(source_text, target_language)

    def _resolve_project_id() -> Optional[str]:
        explicit_project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
        if explicit_project_id:
            return explicit_project_id
        try:
            import google.auth
            _, detected_project_id = google.auth.default()
            return detected_project_id
        except Exception:
            return None

    def _do_translate():
        from google.cloud import translate_v3
        effective_project_id = _resolve_project_id()
        if not effective_project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT or GCP_PROJECT_ID must be set, or Google ADC must expose a default project, for Google NMT")
        client = translate_v3.TranslationServiceClient()
        parent = f"projects/{effective_project_id}/locations/global"
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

async def translate_with_llama3(
    source_text: str,
    target_language: str
) -> Dict[str, Dict]:
    """
    Translate using a Replicate-hosted Llama 3 instruct model.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"

    if os.getenv("OFFLINE_MODE", "").lower() in ("1","true","yes"):
        return _offline_translate(source_text, target_language)

    api_token = os.getenv("REPLICATE_API_TOKEN")
    if not api_token:
        raise RuntimeError("REPLICATE_API_TOKEN not set for Llama 3 translation")

    model_name = os.getenv("REPLICATE_LLAMA3_MODEL", "meta/meta-llama-3-8b-instruct")
    lang_name = "Spanish" if target_language == "es" else "Hindi"
    system_prompt = (
        f"You translate emergency alerts from English to {lang_name}. "
        "Preserve urgency, directives, hazard severity, timelines, and official tone. "
        "Return only the translated alert text with no explanation."
    )
    prompt = f"Translate this emergency alert into {lang_name}:\n\n{source_text}"

    def _coerce_output(value) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "".join(str(item) for item in value).strip()
        return str(value).strip()

    def _run_replicate():
        return replicate.run(
            model_name,
            input={
                "prompt": prompt,
                "temperature": 0.2,
                "max_tokens": 256,
                "min_tokens": 0,
                "top_p": 0.95,
                "prompt_template": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" + system_prompt + "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
                "presence_penalty": 1.0,
                "frequency_penalty": 0.1,
            }
        )

    try:
        result = await asyncio.to_thread(_run_replicate)
        translation = _coerce_output(result)
        metadata = {
            "model": model_name,
            "timestamp": datetime.utcnow().isoformat(),
            "tokens": "",
        }
        return {"translation": translation, "metadata": metadata}
    except Exception as e:
        logger.error(f"Replicate Llama 3 translation failed: {e}")
        raise RuntimeError(f"Replicate Llama 3 translation failed: {e}")

async def translate_with_gemini(
    source_text: str,
    target_language: str,
) -> Dict[str, Dict]:
    """
    Translate using Google Gemini (gemini-2.0-flash by default).
    Requires GEMINI_API_KEY in environment.
    """
    assert target_language in {"es", "hi"}, "target_language must be 'es' or 'hi'"

    if os.getenv("OFFLINE_MODE", "").lower() in ("1", "true", "yes"):
        return _offline_translate(source_text, target_language)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set for Gemini translation")

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    lang_name = "Spanish" if target_language == "es" else "Hindi"
    cultural_notes = (
        "Use clear public service style common in Spanish-language public safety communications in the U.S."
        if target_language == "es"
        else "Use formal Hindi appropriate for public advisories; avoid slang; ensure comprehension across dialects."
    )
    prompt = (
        f"You are translating an emergency alert from English to {lang_name}. "
        "CRITICAL: Preserve urgency markers (immediately, now, life-threatening), directive clarity (evacuate, shelter), "
        "risk severity language, and institutional authority. Adapt culturally while maintaining an authoritative emergency tone. "
        f"{cultural_notes} Keep information complete and timelines accurate.\n\n"
        f"Translate faithfully and clearly:\n\n{source_text}"
    )

    def _run_gemini():
        client = google_genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=512,
            ),
        )
        text = (response.text or "").strip()
        usage = getattr(response, "usage_metadata", None)
        tokens = None
        if usage:
            tokens = getattr(usage, "total_token_count", None)
        return text, model_name, tokens

    try:
        text, model_used, tokens = await asyncio.to_thread(_run_gemini)
        metadata = {
            "model": model_used,
            "timestamp": datetime.utcnow().isoformat(),
            "tokens": str(tokens) if tokens is not None else "",
        }
        return {"translation": text, "metadata": metadata}
    except Exception as e:
        logger.error(f"Gemini translation failed: {e}")
        raise RuntimeError(f"Gemini translation failed: {e}")
