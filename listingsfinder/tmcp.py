from urllib.parse import quote

import requests

from .config import (
    TMCP_APIFY_ACTOR,
    TMCP_APIFY_LEADS_PER_PLACE,
    TMCP_APIFY_SCRAPE_CONTACTS,
    TMCP_APIFY_SOCIAL_PROFILES,
    TMCP_APIFY_VERIFY_EMAILS,
    TMCP_API_KEY,
    TMCP_BASE_URL,
    TMCP_SCRAPEDO_ENABLED,
    TMCP_SERPER_ENABLED,
)


def configured():
    return bool(TMCP_API_KEY)


def _require_key():
    if not TMCP_API_KEY:
        raise ValueError("Missing TMCP_API_KEY (TMCP_api_key is also supported)")
    return TMCP_API_KEY


def apify_google_maps_search(industry, location, max_results=20, timeout=300):
    key = _require_key()
    endpoint = f"{TMCP_BASE_URL}/api/apify/v2/acts/{quote(TMCP_APIFY_ACTOR, safe='~')}/run-sync-get-dataset-items"
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        params={"clean": "true", "format": "json"},
        json={
            "searchStringsArray": [industry or "business"],
            "locationQuery": location or "",
            "maxCrawledPlacesPerSearch": max(1, min(int(max_results), 100)),
            "language": "en",
            "maxImages": 0,
            "scrapeContacts": TMCP_APIFY_SCRAPE_CONTACTS,
            "maximumLeadsEnrichmentRecords": max(0, min(TMCP_APIFY_LEADS_PER_PLACE, 10)),
            "verifyLeadsEnrichmentEmails": TMCP_APIFY_VERIFY_EMAILS,
            "maxCompetitorsToAnalyze": 0,
            "scrapeSocialMediaProfiles": {
                "facebooks": TMCP_APIFY_SOCIAL_PROFILES,
                "instagrams": TMCP_APIFY_SOCIAL_PROFILES,
                "youtubes": TMCP_APIFY_SOCIAL_PROFILES,
                "tiktoks": TMCP_APIFY_SOCIAL_PROFILES,
                "twitters": TMCP_APIFY_SOCIAL_PROFILES,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("data") or []
    return payload if isinstance(payload, list) else []


def scrapedo_fetch(url, render=False, timeout=45):
    if not TMCP_SCRAPEDO_ENABLED:
        return ""
    key = _require_key()
    response = requests.get(
        f"{TMCP_BASE_URL}/api/scrapedo",
        params={"token": key, "url": url, "render": "true" if render else "false"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def serper_search(query, num=10, gl="us", hl="en", timeout=30):
    if not TMCP_SERPER_ENABLED:
        return []
    key = _require_key()
    response = requests.post(
        f"{TMCP_BASE_URL}/api/serper/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": num, "gl": gl, "hl": hl},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("organic", []) or []


def serper_scrape(url, timeout=45):
    if not TMCP_SERPER_ENABLED:
        return {}
    key = _require_key()
    response = requests.post(
        f"{TMCP_BASE_URL}/api/serper/scrape",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"url": url},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def openrouter_chat(payload, timeout=60):
    key = _require_key()
    response = requests.post(
        f"{TMCP_BASE_URL}/api/openrouter/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
