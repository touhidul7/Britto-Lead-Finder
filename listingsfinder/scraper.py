import html as html_lib
import re, hashlib, requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .config import TMCP_API_KEY, TMCP_SCRAPEDO_ENABLED, TMCP_SERPER_ENABLED
from .models import Listing, now_iso
from .queries import REGION_CITIES
from .tmcp import scrapedo_fetch as tmcp_scrapedo_fetch, serper_scrape as tmcp_serper_scrape
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36'
_SERPER_SCRAPE_FAILS={'count':0}


def _serper_scrape_html(url, timeout=30):
    """Scrape a page via Serper's scrape API, which renders JS and bypasses the
    bot protection that blocks plain requests and Scrape.do (e.g. BizBuySell).
    It returns visible text + metadata, which we wrap into minimal HTML so the
    existing BeautifulSoup-based extractors keep working unchanged."""
    if not TMCP_API_KEY or not TMCP_SERPER_ENABLED or _SERPER_SCRAPE_FAILS['count'] >= 3:
        return ''
    data = None
    # The rotate pool intermittently returns 400 'Not enough credits' when a
    # request lands on an exhausted key -- retry so rotation finds a live one.
    # After 3 consecutive total failures the pool is considered drained and the
    # rest of the run skips this API instead of paying its latency per page.
    for _ in range(2):
        try:
            data = tmcp_serper_scrape(url, timeout=timeout)
            if data:
                break
        except Exception:
            pass
    if data is None:
        _SERPER_SCRAPE_FAILS['count'] += 1
        return ''
    _SERPER_SCRAPE_FAILS['count'] = 0
    text = ' '.join((data.get('text') or '').split())
    meta = data.get('metadata') or {}
    title = (meta.get('title') or '').strip()
    desc = (meta.get('description') or meta.get('og:description') or '').strip()
    if not text and not title:
        return ''
    return (
        '<html><head>'
        f'<title>{html_lib.escape(title)}</title>'
        f'<meta name="description" content="{html_lib.escape(desc)}">'
        f'</head><body>{html_lib.escape(text)}</body></html>'
    )


# Set to True the first time Scrape.do answers 401/403 (dead/inactive token)
# so the rest of the run skips its 30s dead wait and goes straight to Serper.
_SCRAPEDO_DEAD = {'flag': False}


def fetch_url(url, use_fallback=True, render=False, timeout=8, fallback_timeout=30):
    hard = _is_hard_blocked(urlparse(url).netloc.replace('www.', ''))
    if not hard:
        try:
            r=requests.get(url,headers={'User-Agent':UA},timeout=timeout)
            if r.status_code<400 and len(r.text)>200: return r.text,'direct'
        except Exception: pass
    if use_fallback:
        if TMCP_API_KEY and TMCP_SCRAPEDO_ENABLED and not _SCRAPEDO_DEAD['flag']:
            try:
                scraped = tmcp_scrapedo_fetch(url, render=render, timeout=fallback_timeout)
                if len(scraped) > 200:
                    return scraped, ('tmcp-scrape.do+render' if render else 'tmcp-scrape.do')
            except Exception:
                pass
        # Serper scrape: final fallback, and primary for hard-blocked marketplaces.
        serper_html = _serper_scrape_html(url, timeout=fallback_timeout)
        if serper_html:
            return serper_html, 'serper'
    return '','failed'
def first(text, pats):
    for p in pats:
        m=re.search(p,text or '',re.I)
        if m: return m.group(0)[:150]
    return ''

SALE_TERMS = (
    "for sale",
    "business for sale",
    "company for sale",
    "business opportunity",
    "acquisition opportunity",
    "asking price",
    "view details",
    "more details",
    "listing",
    "listings",
)

# Title-level phrases that indicate a category/index page, not one listing.
DIRECTORY_TITLE_TERMS = (
    "businesses-for-sale-and-investment",
    "commercial listings",
    "buy & sell",
    "currently available",
    "businesses for sale and investment",
    "browse ",
    "search results",
    "all listings",
    "our listings",
    "listings page",
)

NON_LISTING_TERMS = (
    "job",
    "jobs",
    "career",
    "careers",
    "linkedin.com/company",
    "college of",
    "ocpinfo.com",
    "canlii.org",
    "reddit.com",
    "linkedin.com",
    "facebook.com/groups",
    "franchise opportunities",
    "blog",
    "news",
    "article",
    "privacy policy",
    "terms of use",
)

NON_LISTING_PATH_PARTS = (
    "/blog",
    "/news",
    "/article",
    "/contact",
    "/login",
    "/sign",
    "/privacy",
    "/terms",
    "shortlist",
    "alert",
    "save=",
)



def _looks_like_listing_path(path):
    path = (path or "").lower()
    return bool(
        re.search(r"/(business|business-opportunity|listing|listings|opportunity|opportunities)/", path)
        or re.search(r"/[a-z0-9-]+-for-sale(?:[/.]|$)", path)
        or re.search(r"/[a-z0-9-]+-[a-z0-9]+/$", path)
    )


def _looks_like_next_page(text, href):
    label = (text or "").strip().lower()
    href_low = (href or "").lower()
    return (
        label in ("next", "next page", ">", ">>")
        or "next" in label
        or re.search(r"[?&](page|p)=\d+", href_low)
        or re.search(r"/(page|p)/\d+", href_low)
    )
def title_from_url(url):
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"\.(aspx|html?|php)$", "", slug, flags=re.I)
    return re.sub(r"[-_]+", " ", slug).strip().title()


def _industry_tokens(industry):
    return {w for w in re.split(r"[^a-z0-9]+", (industry or "").lower()) if len(w) > 2}


def matches_industry(text, industry):
    """Word-boundary industry match so short tokens cannot hit inside other
    words (e.g. industry "spa" must not match "space"); longer tokens may take
    suffixes ("plumbing" ~ "plumbings", "plumber" ~ "plumbers")."""
    words = _industry_tokens(industry)
    if not words:
        return True
    text = (text or "").lower()
    for word in words:
        pattern = rf"\b{re.escape(word)}\b" if len(word) <= 4 else rf"\b{re.escape(word)}"
        if re.search(pattern, text):
            return True
    return False


# Full state/province name -> postal abbreviation. Used only in comma-anchored
# form (", NY", ", ON") so short codes never match inside ordinary words.
LOCATION_ABBREV = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va",
    "washington": "wa", "wisconsin": "wi", "wyoming": "wy",
    "new york": "ny", "new jersey": "nj", "new mexico": "nm", "north carolina": "nc",
    "south carolina": "sc", "north dakota": "nd", "south dakota": "sd", "new hampshire": "nh",
    "rhode island": "ri", "west virginia": "wv",
    "ontario": "on", "quebec": "qc", "alberta": "ab", "manitoba": "mb",
    "saskatchewan": "sk", "british columbia": "bc", "nova scotia": "ns",
    "new brunswick": "nb", "newfoundland": "nl", "newfoundland and labrador": "nl",
    "prince edward island": "pe",
}

# Common alternate names for cities users actually search for.
LOCATION_SYNONYMS = {
    "new york": ["new york city", "nyc", "manhattan", "brooklyn"],
    "new york city": ["new york", "nyc", "manhattan", "brooklyn"],
    "toronto": ["greater toronto", "gta"],
}


def _location_phrases(location):
    """Return (phrases, abbrev) accepted as evidence the text is in `location`.

    Phrases are matched as whole words/phrases (\\b-anchored), never substrings,
    so 'New York' cannot match 'New Jersey' and 'ON' cannot match 'company'.
    A mandate for a region (province/state) also accepts its known cities,
    since listing pages say 'Ottawa, ON' rather than 'Ontario'."""
    loc = re.sub(r"\s+", " ", (location or "").strip().lower()).strip(" ,.")
    if not loc:
        return [], ""
    primary = loc.split(",")[0].strip()
    phrases = [loc, primary] + LOCATION_SYNONYMS.get(primary, [])
    for region, cities in REGION_CITIES.items():
        if primary == region:
            phrases += [c.lower() for c in cities]
            break
    deduped = []
    for p in phrases:
        if p and p not in deduped:
            deduped.append(p)
    return deduped, LOCATION_ABBREV.get(primary, "")


def matches_location(text, location):
    """Strict location check: the exact place name (or a known synonym /
    child city of a region mandate) must appear as a whole phrase."""
    if not (location or "").strip():
        return True
    text = re.sub(r"\s+", " ", (text or "").lower())
    phrases, abbrev = _location_phrases(location)
    for phrase in phrases:
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return True
    if abbrev and re.search(rf",\s*{abbrev}\b", text):
        return True
    return False


def _known_cities():
    cities = set()
    for region_cities in REGION_CITIES.values():
        cities.update(c.lower() for c in region_cities)
    return cities


_KNOWN_CITIES = None
_PLACE_CODES = set(LOCATION_ABBREV.values())


def _containing_region(city):
    for region, cities in REGION_CITIES.items():
        if city in (c.lower() for c in cities):
            return region
    return ""


def location_conflict(title, location):
    """True when the listing TITLE names a different known place than the
    mandate location (e.g. 'Plumbing Business In Jasper AB' for a Toronto
    mandate). Titles are the most reliable location signal on marketplace
    pages, whose body text mentions many cities in related-listing boilerplate."""
    global _KNOWN_CITIES
    if not (location or "").strip() or not (title or "").strip():
        return False
    if matches_location(title, location):
        return False
    if _KNOWN_CITIES is None:
        _KNOWN_CITIES = _known_cities()
    accepted, abbrev = _location_phrases(location)
    accepted_set = set(accepted)
    primary = accepted[0].split(",")[0].strip() if accepted else ""
    region = _containing_region(primary) or (primary if primary in REGION_CITIES else "")
    region_abbrev = LOCATION_ABBREV.get(region, "") or abbrev
    low = re.sub(r"\s+", " ", title.lower())
    for city in _KNOWN_CITIES:
        if city in accepted_set:
            continue
        if re.search(rf"\b{re.escape(city)}\b", low):
            return True
    # Standalone uppercase province/state code that isn't the mandate's own
    # (skip all-caps titles where ordinary words would look like codes, and
    # currency notations like CA$).
    if not title.isupper():
        for m in re.finditer(r"\b([A-Z]{2})\b(?!\$)", title):
            code = m.group(1).lower()
            if code in _PLACE_CODES and code != region_abbrev:
                return True
    return False


def is_directory_result(result):
    url = (result.get("url", "") or "").lower()
    url_path = urlparse(result.get("url", "")).path.lower()
    title = (result.get("title", "") or "").lower()
    haystack = f"{title} {url}"
    # Search-result pages (e.g. ?q=, ?keyword=, ?search=, ?location=) are
    # listings indexes, not a single listing -- treat as a directory so they
    # get expanded into their child listings.
    if re.search(r"[?&](q|query|keyword|keywords|search|term|s|location|city|state|industry|category)=", url):
        return True
    # Index-style paths: /search/..., /browse/..., agent/broker profile pages
    # (they list many businesses), or paths that END at a section root
    # (/listings, /businesses-for-sale, /category/plumbing).
    if re.search(r"/(search|browse|marketplace|category|categories|directory|results?|agents?|brokers?)(/|$)", url_path):
        return True
    if re.search(r"/(listings?|businesses|opportunities|business-for-sale|businesses-for-sale|buy-a-business)/?$", url_path):
        return True
    # Slug-style category indexes like "/plumbing-businesses-for-sale/" or
    # "/restaurant-companies-for-sale". Marketplaces use these for whole
    # categories; individual listings almost always carry a numeric ID.
    if re.search(r"(businesses|companies)-for-sale", url_path):
        return True
    if re.search(r"-business-for-sale/?$", url_path) and not re.search(r"\d{4,}", url_path):
        return True
    # Plural category titles ("Plumbing Businesses For Sale in ...", "Restaurants
    # for sale, ..."). The lookahead keeps singular 'business for sale' titles --
    # those are individual listings.
    if re.search(r"\b(?!business\b)[a-z0-9&'-]+s\s+for sale(?:\s+in\b|,|$)", title):
        return True
    # "147 Businesses For Sale in Toronto" / "19 Available To Buy Now" counts.
    if re.search(r"\b\d+\s+(businesses|listings|results|matches|opportunities|available)\b", title):
        return True
    if url_path.rstrip("/") in ("/commercial", "/business-for-sale", "/marketplace"):
        return True
    if url_path in ("", "/"):
        return True
    return any(term in haystack for term in DIRECTORY_TITLE_TERMS)


SOCIAL_DOMAINS = (
    "instagram.com", "facebook.com", "twitter.com", "x.com", "tiktok.com",
    "youtube.com", "youtu.be", "pinterest.com", "reddit.com", "linkedin.com",
    "threads.net", "t.me", "medium.com",
)

# Service / lead-gen directories and search engines -- they list service
# providers or web results, never businesses for sale.
NON_LISTING_DOMAINS = (
    "yellowpages.ca", "yellowpages.com", "yelp.com", "yelp.ca", "houzz.com",
    "thumbtack.com", "angi.com", "angieslist.com", "homestars.com",
    "google.com", "bing.com", "wikipedia.org", "indeed.com", "glassdoor.com",
)


def _is_social(url):
    netloc = urlparse(url or "").netloc.replace("www.", "").lower()
    return any(netloc == d or netloc.endswith("." + d) for d in SOCIAL_DOMAINS)


def _is_non_listing_domain(url):
    netloc = urlparse(url or "").netloc.replace("www.", "").lower()
    return any(netloc == d or netloc.endswith("." + d) for d in NON_LISTING_DOMAINS)


def _is_listing_url(path):
    """Structural check for an individual listing URL (not a category/index)."""
    path = (path or "").lower()
    if any(skip in path for skip in NON_LISTING_PATH_PARTS):
        return False
    # Category/search indexes, not individual listings.
    if re.search(r"(businesses|companies)-for-sale", path) or "/search" in path:
        return False
    if re.search(r"/(blog|news|press|insights?|resources?|articles?|stories|guides?)(/|$)", path):
        return False
    if re.search(r"(how-much|hourly-rate|cost-to|price-list|pricing|-rates?-|how-to-)", path):
        return False
    return bool(
        re.search(r"/(business|businesses|business-opportunity|listing|listings|opportunity|opportunities|engagement|business-details|profile)/", path)
        or re.search(r"-for-sale(?:[-/.]|$)", path)
        or re.search(r"[-/]\d{4,}(?:[-/.]|$)", path)
    )


def is_relevant_result(result, industry="", location="", require_location=True):
    haystack = " ".join([result.get("title", ""), result.get("url", ""), result.get("snippet", "")]).lower()
    path = urlparse(result.get("url", "")).path.lower().rstrip("/")
    title = (result.get("title", "") or "").strip().lower()
    # Social networks and service/lead-gen directories are never broker listings.
    if _is_social(result.get("url", "")) or _is_non_listing_domain(result.get("url", "")):
        return False
    # Service-cost / pricing articles (e.g. "how much to pay a plumber").
    if re.search(r"(how-much|hourly-rate|cost-to|price-list|pricing|how-to-|-rates?-)", path):
        return False
    if title in ("skip to content", "more details", "view details", "contact seller", "save", "spinner", "untitled", "home", "404", "page not found", "access denied", "just a moment...", "just a moment") or title.startswith("all results"):
        return False
    # A title naming a different known city than the mandate is a hard reject.
    if location and location_conflict(result.get("title", ""), location):
        return False
    if any(part in path for part in NON_LISTING_PATH_PARTS):
        return False
    # Hard block for editorial/blog content and dated article URLs. Unlike the
    # NON_LISTING_TERMS check below, this cannot be bypassed by a stray price,
    # because blog posts about businesses for sale routinely quote prices.
    if re.search(r"/(blog|news|press|insights?|resources?|articles?|stories|guides?)(/|$)", path):
        return False
    if re.search(r"/(19|20)\d\d/\d{1,2}/", path):
        return False
    if re.search(r"/(businesses-for-sale|business-for-sale|companies-for-sale|listings|search|category|browse)$", path):
        return False
    if not matches_industry(haystack, industry):
        return False
    has_industry = True
    # Strict location gate: the place name itself must appear as a phrase.
    # Callers that will verify against the full scraped page later (directory
    # children, pre-scrape candidates) pass require_location=False.
    if require_location and not matches_location(haystack, location):
        return False
    has_sale = any(term in haystack for term in SALE_TERMS) or bool(re.search(r"\$[0-9][0-9,.]+", haystack))
    if any(term in haystack for term in ("linkedin.com", "facebook.com/groups")):
        return False
    if any(term in haystack for term in NON_LISTING_TERMS) and not ("for sale" in haystack and re.search(r"\$[0-9][0-9,]{2,}|asking price|cash flow|ebitda|annual revenue", haystack)):
        return False
    return bool(has_industry and has_sale)


def _candidate_from_anchor(anchor, page_url, result):
    href = urljoin(page_url, anchor["href"])
    parsed = urlparse(href)
    clean_url = href.split("#")[0]
    text = " ".join(anchor.get_text(" ", strip=True).split())
    parent_text = " ".join((anchor.parent.get_text(" ", strip=True) if anchor.parent else text).split())
    return {
        "title": title_from_url(clean_url) if text.lower().startswith("more detail") else (text or title_from_url(clean_url) or result.get("title", "")),
        "url": clean_url,
        "snippet": parent_text[:700] or result.get("snippet", ""),
        "source": f"{result.get('source', 'Google/Serper')} expanded",
        "query": result.get("query", ""),
        "path": parsed.path.lower(),
        "domain": parsed.netloc.replace("www.", ""),
    }


# Domains that block plain requests and Scrape.do (PerimeterX/Cloudflare).
# fetch_url routes these straight to the Serper scrape API (which renders them),
# so individual listing pages still get data. We skip *directory expansion* for
# them, though, since the Serper scrape returns text without the anchor links
# needed to crawl a category page into its children.
HARD_BLOCKED_DOMAINS = (
    "bizbuysell.com",
    "dealstream.com",
    "businessesforsale.com",
)


def _is_hard_blocked(domain):
    domain = (domain or "").lower()
    return any(domain == d or domain.endswith("." + d) for d in HARD_BLOCKED_DOMAINS)


def _harvest_anchors(soup, page_url, base_domain, result, industry, location, pages, visited_pages, seen_urls, found, max_links):
    for anchor in soup.find_all("a", href=True):
        candidate = _candidate_from_anchor(anchor, page_url, result)
        if candidate["domain"] != base_domain:
            continue
        if candidate["path"] in ("", "/"):
            continue
        url = candidate["url"]
        label = anchor.get_text(" ", strip=True)
        if _looks_like_next_page(label, anchor.get("href", "")) and url not in visited_pages and url not in pages:
            pages.append(url)
            continue
        if url in seen_urls:
            continue
        if _is_social(url) or any(skip in candidate["path"] for skip in NON_LISTING_PATH_PARTS):
            continue
        if is_directory_result(candidate):
            continue
        # Relaxed acceptance: the parent page already matched this industry and
        # location, so any same-domain link whose path structurally looks like an
        # individual listing counts -- we do not re-require the keywords to appear
        # in the (often empty) anchor text. Location is verified later against
        # the full scraped page, where the city actually appears.
        if _is_listing_url(candidate["path"]) or is_relevant_result(candidate, industry, location, require_location=False):
            seen_urls.add(url)
            found.append(candidate)
            if len(found) >= max_links:
                return


def discover_listing_links(result, industry="", location="", max_links=25, max_pages=4):
    base_url = result.get("url", "")
    base_domain = urlparse(base_url).netloc.replace("www.", "")
    if _is_hard_blocked(base_domain):
        return []
    pages = [base_url]
    visited_pages = set()
    found = []
    seen_urls = set()
    rendered_base = False

    while pages and len(visited_pages) < max_pages and len(found) < max_links:
        page_url = pages.pop(0)
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)
        # Index page uses the Scrape.do fallback (marketplaces block plain
        # requests); paginated subpages stay on the fast direct path.
        html, method = fetch_url(page_url, use_fallback=(page_url == base_url), render=False)
        if html:
            _harvest_anchors(BeautifulSoup(html, "lxml"), page_url, base_domain, result, industry, location, pages, visited_pages, seen_urls, found, max_links)
        # Many marketplaces inject listing cards via JavaScript, so a static
        # fetch of the index returns only nav/category links. If the index
        # yielded nothing, retry it once with JS rendering through Scrape.do.
        if page_url == base_url and not found and not rendered_base and TMCP_API_KEY and TMCP_SCRAPEDO_ENABLED:
            rendered_base = True
            html, method = fetch_url(page_url, use_fallback=True, render=True, fallback_timeout=45)
            if html:
                _harvest_anchors(BeautifulSoup(html, "lxml"), page_url, base_domain, result, industry, location, pages, visited_pages, seen_urls, found, max_links)
    return found


def expand_directory_results(results, industry="", location="", max_links_per_page=25, max_directory_pages=10, state=None):
    """Turn directory/search results into their child listing candidates.

    `state` (a dict) carries the directory-page budget across multiple calls
    within one run, so the incremental pipeline can call this per query batch.
    Location is NOT enforced here -- search snippets and anchor text often omit
    the city even for correctly-located listings; the scrape stage verifies the
    location against the full page text instead."""
    if state is None:
        state = {}
    state.setdefault("directory_pages", 0)
    expanded = []
    seen = state.setdefault("seen_urls", set())
    for result in results:
        is_directory = is_directory_result(result)
        children = []
        if is_directory and state["directory_pages"] < max_directory_pages:
            state["directory_pages"] += 1
            children = discover_listing_links(result, industry, location, max_links=max_links_per_page)
        candidates = children if children else ([] if is_directory else [result])
        for candidate in candidates:
            url = candidate.get("url", "")
            if url and url not in seen and is_relevant_result(candidate, industry, location, require_location=False):
                seen.add(url)
                expanded.append(candidate)
    return expanded

def is_listing_page(listing, industry="", location=""):
    """Final output gate: must be a single, on-location, on-industry listing."""
    # Broad discovery terms are useful for niche agency mandates, but a general
    # digital agency must not pass a dental/medical-agency mandate unless its
    # own page mentions both the target vertical and agency/marketing work.
    industry_low = (industry or "").lower()
    if "marketing" in industry_low and any(
        word in industry_low for word in ("dental", "dentist", "clinic", "medical", "healthcare")
    ):
        raw_page = f"{listing.listing_title} {listing.description} {listing.source_url}".lower()
        vertical_match = any(
            word in raw_page for word in ("dental", "dentist", "orthodont", "clinic", "medical", "healthcare")
        )
        agency_match = any(word in raw_page for word in ("marketing", "advertis", "agency", "digital"))
        if not (vertical_match and agency_match):
            return False
    candidate = {
        "title": listing.listing_title,
        "url": listing.source_url,
        "snippet": f"{listing.description} {listing.location} {listing.industry}".strip(),
        "source": listing.source,
    }
    if is_directory_result(candidate):
        return False
    if not is_relevant_result(candidate, industry, location):
        return False
    # Structural requirement: the URL must look like one listing page, or the
    # page must expose deal financials (asking price / revenue / cash flow) --
    # directories and search pages have neither.
    has_financials = any([listing.asking_price, listing.revenue, listing.cash_flow, listing.ebitda])
    return has_financials or _is_listing_url(urlparse(listing.source_url).path)
def scrape_result(result, industry='', location=''):
    html,method=fetch_url(result['url']); soup=BeautifulSoup(html or '', 'lxml')
    title=(soup.find('title').get_text(' ',strip=True) if soup.find('title') else result.get('title',''))[:300]
    meta=soup.find('meta',attrs={'name':'description'}) or soup.find('meta',attrs={'property':'og:description'})
    desc=(meta.get('content','') if meta else '') or result.get('snippet','')
    text=soup.get_text(' ',strip=True)[:8000]
    if not desc: desc=text[:500]
    url=result['url']; domain=urlparse(url).netloc.replace('www.',''); lid=hashlib.sha1(url.encode()).hexdigest()[:12].upper()
    # Only stamp the mandate location/industry on the listing when the page
    # actually confirms them; otherwise leave blank so is_listing_page rejects
    # the listing instead of mislabeling it. Verify against the TOP of the page
    # only -- marketplace footers/related-listing boilerplate mention dozens of
    # cities and industries -- and reject when the title names a different city.
    loc_blob=f"{title} {desc} {text[:5000]} {result.get('snippet','')} {url}"
    ind_blob=f"{title} {desc} {text[:2500]} {result.get('snippet','')} {url}"
    verified_location=location if (matches_location(loc_blob, location) and not location_conflict(title, location)) else ''
    verified_industry=industry if matches_industry(ind_blob, industry) else ''
    l=Listing(listing_id=f'SRC-{lid}',source=domain,source_url=url,listing_title=title,industry=verified_industry,location=verified_location,asking_price=first(text,[r'(?:asking price|price)[:\s]*\$[0-9,]+(?:\.?[0-9]+)?\s*(?:M|K|million)?',r'\$[0-9][0-9,]+(?:\.?[0-9]+)?\s*(?:M|K|million)?']),revenue=first(text,[r'(?:revenue|sales)[:\s]*\$[0-9,]+(?:\.?[0-9]+)?\s*(?:M|K|million)?']),cash_flow=first(text,[r'(?:cash flow|sde)[:\s]*\$[0-9,]+(?:\.?[0-9]+)?\s*(?:M|K|million)?']),ebitda=first(text,[r'EBITDA[:\s]*\$[0-9,]+(?:\.?[0-9]+)?\s*(?:M|K|million)?']),description=desc[:1000],contact_email=first(text,[r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}']),contact_phone=first(text,[r'(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}']),scrape_date=now_iso(),notes=f'fetch_method={method}; query={result.get("query","")}')
    return l
