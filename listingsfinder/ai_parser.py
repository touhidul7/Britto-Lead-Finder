import json
import re

import requests

from .config import ANTHROPIC_API_KEY, TMCP_API_KEY
from .models import SearchCriteria
from .parser import clean_industry, parse_mandate
from .tmcp import openrouter_chat

ANTHROPIC_MODELS = [
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-1-20250805",
    "claude-3-5-haiku-20241022",
]

OPENROUTER_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.1",
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-pro",
    "meta-llama/llama-3.3-70b-instruct",
]

SYSTEM_PROMPT = """You convert Britto Soft lead searches into structured search criteria.
Return JSON only. Never estimate unknown values.
Fields:
industry string, location string, services string, keywords string,
opportunity_signals string, exclude string, website_requirement string.
The goal is finding potential clients for a digital agency from public business information.

Rules:
- Strip instruction words such as please, find, search for, best, looking for.
- Correct obvious typos in business words, such as copany -> company.
- Do not include company/business/entity words in industry unless they are part of the actual sector.
- Keep industry short and preserve the user's actual target sector.
- Put requested Britto Soft services such as Website Design, SEO, Digital Marketing,
  E-commerce Development, Custom Software, App Development, or Automation in services.
- Keep opportunity signals factual, such as no website, outdated website, or weak SEO.
- website_requirement must be exactly Any, No Website, or Has Website.
- Phrases such as "without a website", "no website", or "exclude businesses with a website"
  mean website_requirement is No Website.
- Never weaken an explicit website requirement."""


def _json_from_text(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("AI response did not contain JSON")
    return json.loads(match.group(0))


def _criteria_from_payload(original_query, payload):
    fallback = parse_mandate(original_query)
    industry = clean_industry(str(payload.get("industry") or fallback.industry or ""))
    return SearchCriteria(
        original_query=original_query,
        industry=industry,
        location=str(payload.get("location") or fallback.location or "").strip(),
        services=str(payload.get("services") or fallback.services or "").strip(),
        keywords=str(payload.get("keywords") or industry or fallback.keywords or "").strip(),
        opportunity_signals=str(payload.get("opportunity_signals") or fallback.opportunity_signals or "").strip(),
        exclude=str(payload.get("exclude") or fallback.exclude or "").strip(),
        website_requirement=(
            fallback.website_requirement
            if fallback.website_requirement != "Any"
            else str(payload.get("website_requirement") or "Any").strip()
        ),
    )


def _parse_with_anthropic(mandate, model, api_key=""):
    key = api_key or ANTHROPIC_API_KEY
    if not key:
        raise ValueError("Missing ANTHROPIC_API_KEY")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 500,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": mandate}],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return _criteria_from_payload(mandate, _json_from_text(text))


def _parse_with_openrouter(mandate, model, api_key=""):
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": mandate},
        ],
        "response_format": {"type": "json_object"},
    }
    if not TMCP_API_KEY:
        raise ValueError("Missing TMCP_API_KEY")
    data = openrouter_chat(payload, timeout=60)
    text = data["choices"][0]["message"]["content"]
    return _criteria_from_payload(mandate, _json_from_text(text))


def parse_mandate_with_ai(mandate, provider="Rule-based", model="", api_key=""):
    provider = (provider or "Rule-based").strip()
    if provider == "Anthropic":
        return _parse_with_anthropic(mandate, model or ANTHROPIC_MODELS[0], api_key), "Anthropic"
    if provider == "OpenRouter":
        return _parse_with_openrouter(mandate, model or OPENROUTER_MODELS[0], api_key), "OpenRouter"
    return parse_mandate(mandate), "Rule-based"


def ai_status(provider, api_key=""):
    if provider == "Anthropic":
        return bool(api_key or ANTHROPIC_API_KEY), "Configured" if (api_key or ANTHROPIC_API_KEY) else "Missing Anthropic API key"
    if provider == "OpenRouter":
        ok = bool(TMCP_API_KEY)
        return ok, "TMCP key configured; OpenRouter Rotate permission is checked when used" if ok else "Missing TMCP_API_KEY"
    return True, "Rule-based parser does not require an AI key"
