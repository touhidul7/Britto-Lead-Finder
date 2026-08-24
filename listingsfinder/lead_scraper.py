import hashlib
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import Lead, now_iso
from .scraper import fetch_url, matches_industry, matches_location


IGNORED_DOMAINS = {
    "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com", "wikipedia.org", "indeed.com",
    "glassdoor.com", "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
}
DIRECTORY_DOMAINS = {
    "yelp.com", "yelp.ca", "yellowpages.com", "yellowpages.ca", "bbb.org",
    "clutch.co", "mapquest.com", "chamberofcommerce.com", "angi.com",
    "houzz.com", "thumbtack.com", "homestars.com", "facebook.com",
}
SOCIAL_HOSTS = {
    "facebook_url": ("facebook.com", "fb.com"),
    "instagram_url": ("instagram.com",),
    "linkedin_url": ("linkedin.com",),
    "twitter_url": ("twitter.com", "x.com"),
    "tiktok_url": ("tiktok.com",),
    "youtube_url": ("youtube.com", "youtu.be"),
}
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
CONTACT_LINK_RE = re.compile(r"contact|about|team|staff|connect|location|support", re.I)
BAD_EMAIL_PARTS = (
    "example.com", "domain.com", "email.com", "sentry.io", "wixpress.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
    "tiktok.com", "youtube.com",
)
BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


def _domain(url):
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _is_domain(domain, choices):
    return any(domain == item or domain.endswith("." + item) for item in choices)


def _clean_url(url):
    value = (url or "").strip()
    if value and not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    return value


def _decode_cfemail(value):
    try:
        key = int(value[:2], 16)
        return "".join(chr(int(value[i:i + 2], 16) ^ key) for i in range(2, len(value), 2))
    except (TypeError, ValueError):
        return ""


def _valid_email(value):
    email = (value or "").strip(" .,:;<>[]()\"'").lower()
    if not EMAIL_RE.fullmatch(email) or email.endswith(BAD_EMAIL_SUFFIXES):
        return ""
    if any(part in email for part in BAD_EMAIL_PARTS):
        return ""
    return email


def _emails_from_page(html, soup):
    values = []
    for anchor in soup.select('a[href^="mailto:"]'):
        values.append(anchor.get("href", "").split(":", 1)[-1].split("?", 1)[0])
    for node in soup.select("[data-cfemail]"):
        values.append(_decode_cfemail(node.get("data-cfemail", "")))
    for node in soup.select("[itemprop='email'], meta[name='email']"):
        values.append(node.get("content") or node.get("href") or node.get_text(" ", strip=True))
    structured = " ".join(node.string or "" for node in soup.select('script[type="application/ld+json"]'))
    text = " ".join((soup.get_text(" ", strip=True), structured))
    text = re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", text, flags=re.I)
    text = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", text, flags=re.I)
    text = re.sub(
        r"\b([A-Z0-9._%+\-]+)\s+at\s+([A-Z0-9.\-]+)\s+dot\s+([A-Z]{2,})\b",
        r"\1@\2.\3",
        text,
        flags=re.I,
    )
    values.extend(EMAIL_RE.findall(text))
    seen = []
    for value in values:
        email = _valid_email(value)
        if email and email not in seen:
            seen.append(email)
    return seen


def _social_urls_from_soup(soup):
    found = {}
    for anchor in soup.find_all("a", href=True):
        url = anchor.get("href", "").strip()
        if url.startswith("//"):
            url = "https:" + url
        domain = _domain(url)
        for field, hosts in SOCIAL_HOSTS.items():
            if domain and _is_domain(domain, hosts):
                found.setdefault(field, url.split("#", 1)[0])
    return found


def _strings(payload):
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _strings(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            yield from _strings(value)
    elif isinstance(payload, str):
        yield payload


def _contacts_from_apify(place):
    emails, socials = [], {}
    for value in _strings(place):
        emails.extend(EMAIL_RE.findall(value))
        if value.startswith(("http://", "https://")):
            domain = _domain(value)
            for field, hosts in SOCIAL_HOSTS.items():
                if domain and _is_domain(domain, hosts):
                    socials.setdefault(field, value.split("#", 1)[0])
    clean_emails = []
    for value in emails:
        email = _valid_email(value)
        if email and email not in clean_emails:
            clean_emails.append(email)
    return clean_emails, socials


def _rank_email(email, website):
    business_domain = _domain(website)
    email_domain = email.rsplit("@", 1)[-1]
    same_domain = business_domain == email_domain or business_domain.endswith("." + email_domain)
    role = email.split("@", 1)[0] in {"info", "hello", "contact", "office", "sales", "admin", "support", "enquiries", "inquiries"}
    return (same_domain, role)


def _enrich_public_contacts(website, initial_html="", initial_method="", seed_emails=None, seed_socials=None, seed_source=""):
    website = _clean_url(website)
    if not website:
        return "", "", {}, [], initial_method
    pages = [(website, initial_html, initial_method)]
    visited = set()
    email_sources = {email: seed_source for email in (seed_emails or []) if _valid_email(email)}
    socials = dict(seed_socials or {})
    contact_urls, methods = [], []
    for page_url, supplied_html, supplied_method in pages:
        if page_url in visited:
            continue
        visited.add(page_url)
        html, method = (supplied_html, supplied_method) if supplied_html else fetch_url(page_url)
        if method:
            methods.append(method)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for email in _emails_from_page(html, soup):
            email_sources.setdefault(email, page_url)
        socials.update({key: value for key, value in _social_urls_from_soup(soup).items() if key not in socials})
        if page_url == website:
            base_domain = _domain(website)
            for anchor in soup.find_all("a", href=True):
                href = urljoin(website, anchor.get("href", "")).split("#", 1)[0]
                label = f"{anchor.get_text(' ', strip=True)} {anchor.get('href', '')}"
                if _domain(href) == base_domain and CONTACT_LINK_RE.search(label) and href not in contact_urls:
                    contact_urls.append(href)
            pages.extend((url, "", "") for url in contact_urls[:4])
    # Some businesses publish the email only in a public social profile bio.
    if not email_sources:
        for social_url in list(socials.values())[:3]:
            html, method = fetch_url(social_url, render=False, timeout=8, fallback_timeout=20)
            if method:
                methods.append(method)
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for email in _emails_from_page(html, soup):
                email_sources.setdefault(email, social_url)
    ranked = sorted(email_sources, key=lambda value: _rank_email(value, website), reverse=True)
    email = ranked[0] if ranked else ""
    return email, email_sources.get(email, ""), socials, contact_urls, "+".join(dict.fromkeys(methods))


def _first(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text or "", re.I)
        if match:
            return match.group(0)[:180]
    return ""


def _json_ld_organizations(soup):
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.string or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in list(items):
            if isinstance(item, dict) and item.get("@graph"):
                items.extend(x for x in item["@graph"] if isinstance(x, dict))
        for item in items:
            kind = item.get("@type", "") if isinstance(item, dict) else ""
            kinds = kind if isinstance(kind, list) else [kind]
            if any(value in ("Organization", "LocalBusiness", "ProfessionalService", "Store") or str(value).endswith("Business") for value in kinds):
                yield item


def _company_name(soup, title, domain):
    for item in _json_ld_organizations(soup):
        if item.get("name"):
            return str(item["name"])[:200]
    og = soup.find("meta", attrs={"property": "og:site_name"})
    if og and og.get("content"):
        return og["content"].strip()[:200]
    cleaned = re.split(r"\s+[|\-–—:]\s+", title or "")[0].strip()
    if cleaned and cleaned.lower() not in ("home", "homepage", "welcome"):
        return cleaned[:200]
    return domain.split(".")[0].replace("-", " ").title()


def _opportunity_signals(soup, text, website, email, phone, page_checked=True):
    signals = []
    low = (text or "").lower()
    if not website:
        signals.append("No company website found")
    if page_checked and website and not website.startswith("https://"):
        signals.append("Website does not use HTTPS")
    if page_checked and website and not soup.find("meta", attrs={"name": re.compile("viewport", re.I)}):
        signals.append("No mobile viewport detected")
    if page_checked and website and not soup.find("meta", attrs={"name": re.compile("description", re.I)}):
        signals.append("Missing meta description")
    if page_checked and website and not soup.find("h1"):
        signals.append("No H1 heading detected")
    if page_checked and ("under construction" in low or "coming soon" in low):
        signals.append("Website appears unfinished")
    if page_checked and website and not (soup.select_one("form") or soup.select_one("a[href*='contact']") or soup.select_one("a[href^='mailto:']")):
        signals.append("No clear website enquiry path")
    if not email:
        signals.append("Public email not found")
    if not phone:
        signals.append("Public phone not found")
    return signals


def _recommended_service(signals, requested_services):
    joined = " ".join(signals).lower()
    recommendations = []
    if any(word in joined for word in ("no company website", "viewport", "unfinished", "h1", "meta description")):
        recommendations.append("Website Design")
    if any(word in joined for word in ("meta description", "h1")):
        recommendations.append("SEO")
    if "enquiry path" in joined:
        recommendations.append("Lead Generation")
    for service in (requested_services or "").split(","):
        service = service.strip()
        if service and service not in recommendations:
            recommendations.append(service)
    return ", ".join(recommendations[:3])


def _score(lead):
    score = 35
    score += 10 if lead.company_name else 0
    score += 10 if lead.location else 0
    score += 10 if lead.industry else 0
    score += 15 if lead.contact_email else 0
    score += 10 if lead.contact_phone else 0
    social_count = sum(bool(value) for value in (
        lead.facebook_url, lead.instagram_url, lead.linkedin_url,
        lead.twitter_url, lead.tiktok_url, lead.youtube_url,
    ))
    score += min(10, social_count * 2)
    if lead.opportunity_signals:
        score += min(10, len(lead.opportunity_signals.split("; ")) * 2)
    return min(100, score)


def _preferred_outreach(lead):
    if lead.contact_email:
        return f"Email: {lead.contact_email}"
    for label, value in (
        ("Instagram DM", lead.instagram_url), ("Facebook DM", lead.facebook_url),
        ("LinkedIn", lead.linkedin_url), ("X/Twitter DM", lead.twitter_url),
        ("TikTok", lead.tiktok_url), ("Phone", lead.contact_phone),
    ):
        if value:
            return f"{label}: {value}"
    return ""


def _company_result_match(company_name, result):
    stop = {"the", "and", "inc", "ltd", "llc", "gym", "gyms", "fitness", "club", "centre", "center"}
    words = {
        word for word in re.findall(r"[a-z0-9]+", (company_name or "").lower())
        if len(word) > 2 and word not in stop
    }
    blob = " ".join(str(result.get(key, "")) for key in ("title", "snippet", "url")).lower()
    return not words or len(words & set(re.findall(r"[a-z0-9]+", blob))) >= max(1, (len(words) + 1) // 2)


def _looks_like_official_site(company_name, url, title=""):
    domain = _domain(url)
    if not domain or _is_domain(domain, DIRECTORY_DOMAINS) or _is_domain(domain, IGNORED_DOMAINS):
        return False
    company_compact = "".join(re.findall(r"[a-z0-9]+", (company_name or "").lower()))
    domain_compact = "".join(re.findall(r"[a-z0-9]+", domain.split(".")[0]))
    title_low = (title or "").lower()
    return bool(
        len(domain_compact) >= 5
        and (domain_compact in company_compact or company_compact in domain_compact)
        and _company_result_match(company_name, {"title": title_low, "url": url})
    )


def enrich_no_website_lead(lead, results, scrape_profiles=True):
    """Enrich a Google Maps business whose official website field is empty.

    Exact-name web results may reveal a public email/social profile. If they
    reveal an apparent official domain, retain it so the strict no-website
    pipeline filter rejects the business instead of producing a false lead.
    """
    email_source = ""
    for result in results:
        if not _company_result_match(lead.company_name, result):
            continue
        url = _clean_url(str(result.get("url") or ""))
        domain = _domain(url)
        if _looks_like_official_site(lead.company_name, url, str(result.get("title") or "")):
            lead.website = url
            lead.website_status = "Website discovered during verification"
            continue
        for field, hosts in SOCIAL_HOSTS.items():
            if domain and _is_domain(domain, hosts) and not getattr(lead, field):
                setattr(lead, field, url.split("#", 1)[0])
        blob = f"{result.get('title', '')} {result.get('snippet', '')}"
        for candidate in EMAIL_RE.findall(blob):
            email = _valid_email(candidate)
            # Do not mistake a directory's own support address for the
            # business's contact address.
            if email and not (_is_domain(domain, DIRECTORY_DOMAINS) and email.endswith("@" + domain)):
                lead.contact_email = email
                email_source = url or "exact-name web search"
                break
        if lead.contact_email:
            break
    if not lead.contact_email and scrape_profiles:
        profiles = [
            lead.facebook_url, lead.instagram_url, lead.linkedin_url,
            lead.twitter_url, lead.tiktok_url, lead.youtube_url,
        ]
        for profile in [value for value in profiles if value][:3]:
            html, _ = fetch_url(profile, render=False, timeout=8, fallback_timeout=20)
            if not html:
                continue
            emails = _emails_from_page(html, BeautifulSoup(html, "lxml"))
            if emails:
                lead.contact_email = emails[0]
                email_source = profile
                break
    if email_source:
        lead.email_source = email_source
    if not lead.website:
        lead.website_status = "No website listed; exact-name verification completed"
    lead.preferred_outreach = _preferred_outreach(lead)
    lead.lead_score = _score(lead)
    lead.notes = f"{lead.notes}; no_website_contact_enrichment=completed"
    return lead


def _matches_industry(text, industry):
    if matches_industry(text, industry):
        return True
    words = {word for word in re.split(r"[^a-z0-9]+", (industry or "").lower()) if len(word) > 2}
    haystack = {word for word in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(word) > 2}
    stems = {word[:-1] if word.endswith("s") else word for word in words}
    haystack_stems = {word[:-1] if word.endswith("s") else word for word in haystack}
    return bool(stems & haystack_stems) if stems else True


def is_relevant_lead(lead, industry="", location=""):
    domain = _domain(lead.website or lead.source_url)
    if not domain or _is_domain(domain, IGNORED_DOMAINS):
        return False
    blob = f"{lead.company_name} {lead.page_title} {lead.description} {lead.location} {lead.industry}"
    if industry and not _matches_industry(blob, industry):
        return False
    if location and not matches_location(blob, location):
        return False
    return bool(lead.company_name and (lead.website or lead.contact_email or lead.contact_phone))


def lead_from_result(result, criteria, scrape_pages=True):
    source_url = result.get("url", "")
    source_domain = _domain(source_url)
    if not source_url.startswith(("http://", "https://")) or _is_domain(source_domain, IGNORED_DOMAINS):
        return None
    html, method = ("", "search-snippet")
    if scrape_pages:
        html, method = fetch_url(source_url)
    soup = BeautifulSoup(html or "", "lxml")
    title_node = soup.find("title")
    title = (title_node.get_text(" ", strip=True) if title_node else result.get("title", ""))[:300]
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    description = ((meta.get("content", "") if meta else "") or result.get("snippet", ""))[:1000]
    text = soup.get_text(" ", strip=True)[:12000]
    combined = f"{title} {description} {text} {result.get('snippet', '')}"
    website = "" if _is_domain(source_domain, DIRECTORY_DOMAINS) else source_url
    email, email_source, socials, contact_urls, enrichment_method = _enrich_public_contacts(
        website or source_url,
        initial_html=html if scrape_pages else "",
        initial_method=method,
    ) if scrape_pages else ("", "", {}, [], method)
    if not email:
        email = _valid_email(_first(combined, [r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"]))
        email_source = "search result" if email else ""
    phone = _first(combined, [r"(?:\+?[0-9]{1,3}[\s.-]?)?(?:\(?[0-9]{2,4}\)?[\s.-]?)?[0-9]{3,4}[\s.-][0-9]{3,4}"])
    company = _company_name(soup, title, source_domain)
    location = criteria.location if matches_location(combined, criteria.location) else ""
    industry = criteria.industry if _matches_industry(combined, criteria.industry) else ""
    signals = _opportunity_signals(soup, text, website, email, phone, page_checked=bool(html))
    lid = hashlib.sha1((website or source_url).encode()).hexdigest()[:12].upper()
    lead = Lead(
        lead_id=f"LEAD-{lid}", source=result.get("source", "") or source_domain,
        source_url=source_url, company_name=company, website=website,
        page_title=title, industry=industry, location=location,
        description=description, contact_email=email, email_source=email_source, contact_phone=phone,
        facebook_url=socials.get("facebook_url", ""),
        instagram_url=socials.get("instagram_url", ""),
        linkedin_url=socials.get("linkedin_url", ""),
        twitter_url=socials.get("twitter_url", ""),
        tiktok_url=socials.get("tiktok_url", ""),
        youtube_url=socials.get("youtube_url", ""),
        opportunity_signals="; ".join(signals),
        recommended_service=_recommended_service(signals, criteria.services),
        discovered_at=now_iso(),
        notes=f"fetch_method={enrichment_method or method}; contact_pages={len(contact_urls)}; query={result.get('query', '')}",
    )
    lead.lead_score = _score(lead)
    lead.website_status = "Website found" if lead.website else "No official website found"
    lead.preferred_outreach = _preferred_outreach(lead)
    return lead if is_relevant_lead(lead, criteria.industry, criteria.location) else None


def lead_from_apify_place(place, criteria, scrape_pages=True):
    company = str(place.get("title") or place.get("name") or "").strip()[:200]
    if not company:
        return None
    website = _clean_url(str(place.get("website") or place.get("websiteUrl") or "").strip())
    maps_url = str(place.get("url") or place.get("googleMapsUrl") or "").strip()
    address = str(place.get("address") or place.get("street") or "").strip()
    location_parts = [place.get("city"), place.get("state"), place.get("countryCode")]
    place_location = ", ".join(str(value) for value in location_parts if value) or address
    category = str(place.get("categoryName") or place.get("category") or "").strip()
    phone = str(place.get("phone") or place.get("phoneUnformatted") or "").strip()
    raw_emails = place.get("emails") or []
    if isinstance(raw_emails, str):
        raw_emails = [raw_emails]
    apify_emails, apify_socials = _contacts_from_apify(place)
    website_domain = _domain(website)
    for field, hosts in SOCIAL_HOSTS.items():
        if website_domain and _is_domain(website_domain, hosts):
            apify_socials.setdefault(field, website)
            website = ""
            break
    direct_email = _valid_email(str(place.get("email") or (raw_emails[0] if raw_emails else "")).strip())
    if direct_email and direct_email not in apify_emails:
        apify_emails.insert(0, direct_email)

    html, method = "", "apify-google-maps"
    if scrape_pages and website:
        html, fetch_method = fetch_url(website)
        method += f"+{fetch_method}"
    soup = BeautifulSoup(html or "", "lxml")
    text = soup.get_text(" ", strip=True)[:12000]
    if scrape_pages and website:
        email, email_source, socials, contact_urls, enrichment_method = _enrich_public_contacts(
            website,
            initial_html=html,
            initial_method=method,
            seed_emails=apify_emails,
            seed_socials=apify_socials,
            seed_source="Apify contact enrichment",
        )
        method = enrichment_method or method
    else:
        email = apify_emails[0] if apify_emails else ""
        email_source = "Apify contact enrichment" if email else ""
        socials, contact_urls = apify_socials, []
    signals = _opportunity_signals(soup, text, website, email, phone, page_checked=bool(html))
    identity = website or str(place.get("placeId") or maps_url or f"{company}:{place_location}")
    lid = hashlib.sha1(identity.encode()).hexdigest()[:12].upper()
    lead = Lead(
        lead_id=f"LEAD-{lid}",
        source="Apify / Google Maps",
        source_url=maps_url or website,
        company_name=company,
        website=website,
        page_title=company,
        industry=criteria.industry or category,
        location=criteria.location or place_location,
        description="; ".join(value for value in (category, address) if value)[:1000],
        contact_email=email,
        email_source=email_source,
        contact_phone=phone,
        facebook_url=socials.get("facebook_url", ""),
        instagram_url=socials.get("instagram_url", ""),
        linkedin_url=socials.get("linkedin_url", ""),
        twitter_url=socials.get("twitter_url", ""),
        tiktok_url=socials.get("tiktok_url", ""),
        youtube_url=socials.get("youtube_url", ""),
        opportunity_signals="; ".join(signals),
        recommended_service=_recommended_service(signals, criteria.services),
        discovered_at=now_iso(),
        notes=f"fetch_method={method}; contact_pages={len(contact_urls)}; place_id={place.get('placeId', '')}",
    )
    lead.lead_score = _score(lead)
    lead.website_status = "Website found" if lead.website else "No website listed on Google Maps"
    lead.preferred_outreach = _preferred_outreach(lead)
    return lead
