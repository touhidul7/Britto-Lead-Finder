import re

from .models import SearchCriteria


DEFAULT_SERVICES = "Website Design, SEO, Digital Marketing"
SERVICE_ALIASES = {
    "website": "Website Design",
    "web design": "Website Design",
    "web development": "Web Development",
    "ecommerce": "E-commerce Development",
    "e-commerce": "E-commerce Development",
    "seo": "SEO",
    "search engine optimization": "SEO",
    "digital marketing": "Digital Marketing",
    "social media": "Social Media Marketing",
    "software": "Custom Software",
    "app": "App Development",
    "automation": "Business Automation",
    "branding": "Branding",
}


def clean_industry(value):
    value = (value or "").strip()
    value = re.sub(r"\bcopany\b", "company", value, flags=re.I)
    value = re.sub(
        r"\b(?:please|find|search for|look for|looking for|show me|get me|leads? for|prospects? for|potential clients? for|best|independent|a|an|the)\b",
        " ", value, flags=re.I,
    )
    value = re.sub(r"\b(?:companies|company|businesses|business|firms|firm|leads?|prospects?|clients?)\b", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -,.")
    value = value.title()
    value = re.sub(r"\bHvac\b", "HVAC", value)
    value = re.sub(r"\bSaas\b", "SaaS", value)
    return value


def _services_from_query(query):
    low = (query or "").lower()
    found = []
    for phrase, label in sorted(SERVICE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", low) and label not in found:
            found.append(label)
    return ", ".join(found) or DEFAULT_SERVICES


def _industry_from_query(query):
    text = (query or "").strip()
    text = re.sub(r"\b(?:that|who)\s+(?:need|needs|want|wants|require|requires|lack|lacks)\b.*$", " ", text, flags=re.I)
    text = re.sub(r"\b(?:needing|for)\s+(?:a\s+)?(?:new\s+)?(?:website|web design|seo|digital marketing|software|app|automation)\b.*$", " ", text, flags=re.I)
    text = re.split(r"\b(?:in|near|around|located in|based in)\b", text, maxsplit=1, flags=re.I)[0]
    return clean_industry(text)


def parse_mandate(query):
    q = (query or "").strip()
    no_website = bool(re.search(
        r"\b(?:without|no)\s+(?:an?\s+|any\s+|official\s+)*(?:web\s*site|site)\b|"
        r"\b(?:do not|don't|does not|doesn't)\s+have\s+(?:an?\s+)?(?:web\s*site|site)\b",
        q,
        re.I,
    ))
    has_website = bool(re.search(
        r"\b(?:with|have|has|having)\s+(?:an?\s+|official\s+)*(?:web\s*site|site)\b",
        q,
        re.I,
    ))
    website_requirement = "No Website" if no_website else ("Has Website" if has_website else "Any")
    match = re.search(
        r"\b(?:in|near|around|located in|based in)\s+([a-zA-Z .'-]+?)(?:\s+(?:that|who|needing|for|with|without|exclude|excluding)\b|$)",
        q, re.I,
    )
    location = match.group(1).strip().rstrip(".,").title() if match else ""
    match = re.search(r"\b(?:exclude|excluding|not)\s+(.+)$", q, re.I)
    exclude = match.group(1).strip() if match else ""
    match = re.search(r"\b(?:that|who)\s+(?:need|needs|lack|lacks|have|has)\s+(.+?)(?:\s+exclude\b|$)", q, re.I)
    signals = match.group(1).strip() if match else ("No website" if no_website else "")
    industry = _industry_from_query(q)
    return SearchCriteria(
        original_query=q,
        industry=industry,
        location=location,
        services=_services_from_query(q),
        keywords=industry,
        opportunity_signals=signals,
        exclude=exclude,
        website_requirement=website_requirement,
    )
