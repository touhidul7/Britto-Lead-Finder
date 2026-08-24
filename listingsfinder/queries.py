import re


REGION_CITIES = {
    "bangladesh": ["Dhaka", "Chattogram", "Sylhet", "Khulna", "Rajshahi"],
    "ontario": ["Toronto", "Ottawa", "Mississauga", "Hamilton", "London", "Kitchener"],
    "british columbia": ["Vancouver", "Surrey", "Victoria", "Burnaby", "Kelowna"],
    "alberta": ["Calgary", "Edmonton"],
    "california": ["Los Angeles", "San Diego", "San Francisco", "San Jose", "Sacramento"],
    "texas": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth"],
    "florida": ["Miami", "Orlando", "Tampa", "Jacksonville"],
    "new york": ["New York City", "Buffalo", "Rochester", "Albany"],
}
REGION_COUNTRY = {
    "ontario": "Canada", "british columbia": "Canada", "alberta": "Canada",
    "california": "United States", "texas": "United States", "florida": "United States", "new york": "United States",
}


def _active(source):
    return str(source.get("Active", "TRUE")).strip().lower() in ("", "true", "yes", "1", "active", "y")


def country_hint(location):
    key = (location or "").strip().lower()
    if "united states" in key or re.search(r"\busa?\b", key):
        return "us"
    if "canada" in key:
        return "ca"
    for region, country in REGION_COUNTRY.items():
        if region in key:
            return "ca" if country == "Canada" else "us"
    return None


def _expand_locations(location):
    location = (location or "").strip()
    if not location:
        return [""]
    out = [location]
    key = location.lower()
    for region, cities in REGION_CITIES.items():
        if region == key or region in key:
            out.extend(cities)
            break
    return list(dict.fromkeys(out))


def generate_queries(criteria, sources=None):
    industry = (criteria.industry or criteria.keywords or "business").strip()
    locations = _expand_locations(criteria.location)
    templates = [
        '\"{term}\" \"{loc}\" contact', '\"{term}\" in \"{loc}\"',
        'best \"{term}\" \"{loc}\"', 'local \"{term}\" \"{loc}\"',
        '\"{term}\" \"{loc}\" email', '\"{term}\" \"{loc}\" phone',
        '\"{term}\" \"{loc}\" services', '\"{term}\" near \"{loc}\"',
    ]
    out = []
    for template in templates:
        for location in locations:
            out.append(re.sub(r'\s+', ' ', template.format(term=industry, loc=location)).strip())
    for domain in ("yelp.com", "yellowpages.com", "yellowpages.ca", "bbb.org", "chamberofcommerce.com", "facebook.com"):
        for location in locations[:3]:
            out.append(f'site:{domain} "{industry}" "{location}"'.strip())
    for source in sources or []:
        method = str(source.get("Search Method", "Google site search")).lower()
        if _active(source) and source.get("Website") and "site" in method:
            domain = str(source["Website"]).replace("https://", "").replace("http://", "").split("/")[0]
            for location in locations[:3]:
                out.append(f'site:{domain} "{industry}" "{location}"'.strip())
    if criteria.opportunity_signals:
        out.insert(0, f'"{industry}" "{criteria.location}" {criteria.opportunity_signals}'.strip())
    return list(dict.fromkeys(query for query in out if query))[:150]
