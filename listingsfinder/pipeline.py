import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

from .ai_parser import parse_mandate_with_ai
from .config import EXPORT_DIR, TMCP_API_KEY, TMCP_APIFY_ENABLED, TMCP_APIFY_MAX_RESULTS
from .dedupe import dedupe_leads
from .lead_scraper import enrich_no_website_lead, lead_from_apify_place, lead_from_result
from .queries import country_hint, generate_queries
from .search import reset_search_state, serper_exhausted, web_search
from .sheets import append_rows, export_csv, read_lead_sources
from .store import get_sources, replace_sources, save_listings, save_run
from .tmcp import apify_google_maps_search


def active_sources():
    sheet_sources, err = read_lead_sources()
    if sheet_sources:
        replace_sources(sheet_sources)
        return sheet_sources, "Google Sheet"
    return get_sources(), f"Local registry ({err})" if err else "Local registry"


def _lead_rows(leads, criteria_id=""):
    return [{
        "Master Lead ID": lead.master_lead_id,
        "Lead ID": lead.lead_id,
        "Source": lead.source,
        "Source URL": lead.source_url,
        "Company Name": lead.company_name,
        "Website": lead.website,
        "Page Title": lead.page_title,
        "Industry": lead.industry,
        "Location": lead.location,
        "Description": lead.description,
        "Contact Name": lead.contact_name,
        "Contact Email": lead.contact_email,
        "Email Source": lead.email_source,
        "Contact Phone": lead.contact_phone,
        "Facebook URL": lead.facebook_url,
        "Instagram URL": lead.instagram_url,
        "LinkedIn URL": lead.linkedin_url,
        "X/Twitter URL": lead.twitter_url,
        "TikTok URL": lead.tiktok_url,
        "YouTube URL": lead.youtube_url,
        "Website Status": lead.website_status,
        "Preferred Outreach": lead.preferred_outreach,
        "Opportunity Signals": lead.opportunity_signals,
        "Recommended Service": lead.recommended_service,
        "Lead Score": lead.lead_score,
        "Discovered At": lead.discovered_at,
        "Status": lead.status,
        "Notes": lead.notes,
        "Criteria ID": criteria_id,
    } for lead in leads]


def _criteria_row(criteria_id, criteria, frequency="One-time", notify_email=""):
    return {
        "Criteria ID": criteria_id,
        "Date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "User": "Britto Soft",
        "Original Query": criteria.original_query,
        "Industry": criteria.industry,
        "Location": criteria.location,
        "Services": criteria.services,
        "Keywords": criteria.keywords,
        "Opportunity Signals": criteria.opportunity_signals,
        "Website Requirement": criteria.website_requirement,
        "Exclude": criteria.exclude,
        "Frequency": frequency,
        "Last Run": "",
        "Next Run": "",
        "Notify Email": notify_email,
        "Status": "Searched",
        "Notes": "",
    }


def discover_new_sources(criteria, sources, max_results=10):
    known = {str(row.get("Website", "")).replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower() for row in sources}
    queries = [
        f"{criteria.industry} business directory {criteria.location}",
        f"{criteria.location} chamber of commerce {criteria.industry}",
        f"{criteria.industry} association members {criteria.location}",
    ]
    rows, seen = [], set()
    for query in queries:
        for result in web_search(query, num=max_results, gl=country_hint(criteria.location)):
            domain = urlparse(result.get("url", "")).netloc.replace("www.", "").lower()
            if not domain or domain in known or domain in seen:
                continue
            seen.add(domain)
            rows.append({
                "Source Name": result.get("title", domain)[:120], "Website": domain,
                "Category": "Potential Directory", "Geography": criteria.location,
                "Industry Focus": criteria.industry, "Discovered From Query": query,
                "Reason": result.get("snippet", "")[:300], "Status": "Needs Review",
                "Notes": result.get("url", ""),
            })
    return rows


def _excluded(lead, exclude):
    terms = [item.strip().lower() for item in (exclude or "").split(",") if item.strip()]
    blob = f"{lead.company_name} {lead.page_title} {lead.description} {lead.website}".lower()
    return any(term in blob for term in terms)


def _qualifies(lead, require_email, website_requirement):
    requirement = (website_requirement or "Any").strip().lower()
    if requirement == "no website":
        # Google Maps explicitly returning an empty official website field is
        # the strongest structured evidence available. Directory/search pages
        # are not accepted as proof that a business has no website.
        if lead.website or lead.source != "Apify / Google Maps":
            return False
    elif requirement == "has website" and not lead.website:
        return False
    return bool(lead.contact_email or not require_email)


def run_search(
    mandate, max_queries=30, results_per_query=10, scrape_pages=True,
    discover_sources=True, write_sheets=True, ai_provider="Rule-based",
    ai_model="", ai_api_key="", mandate_id="", log_mandate=True,
    frequency="One-time", notify_email="", min_listings=20,
    require_email=True, website_filter="Automatic from prompt",
):
    reset_search_state()
    criteria_id = mandate_id or "CRIT-" + uuid.uuid4().hex[:8].upper()
    run_id = "RUN-" + uuid.uuid4().hex[:8].upper()
    try:
        criteria, parser_used = parse_mandate_with_ai(mandate, ai_provider, ai_model, ai_api_key)
        parser_note = f"criteria parser: {parser_used}"
    except Exception as exc:
        criteria, _ = parse_mandate_with_ai(mandate, "Rule-based", "")
        parser_note = f"criteria parser: Rule-based fallback; AI error: {exc}"

    filter_map = {
        "No website only": "No Website",
        "Has website only": "Has Website",
        "Any website status": "Any",
    }
    if website_filter in filter_map:
        criteria.website_requirement = filter_map[website_filter]

    sources, source_origin = active_sources()
    all_queries = generate_queries(criteria, sources)
    queries, candidates, seen_urls = [], [], set()
    search_errors = 0
    apify_count = 0
    apify_note = "Apify Rotate disabled"
    if TMCP_API_KEY and TMCP_APIFY_ENABLED:
        try:
            apify_limit = min(TMCP_APIFY_MAX_RESULTS, max(min_listings, results_per_query))
            places = apify_google_maps_search(criteria.industry, criteria.location, max_results=apify_limit)
            apify_count = len(places)
            with ThreadPoolExecutor(max_workers=6) as pool:
                mapped_leads = list(pool.map(lambda place: lead_from_apify_place(place, criteria, scrape_pages), places))
            if criteria.website_requirement == "No Website":
                no_site_leads = [lead for lead in mapped_leads if lead and not lead.website]
                enrichment_limit = min(len(no_site_leads), max(min_listings * 3, results_per_query))
                for lead in no_site_leads[:enrichment_limit]:
                    contact_results = []
                    for contact_query in (
                        f'"{lead.company_name}" "{criteria.location}" email contact',
                        f'"{lead.company_name}" "{criteria.location}" Facebook Instagram LinkedIn',
                    ):
                        try:
                            contact_results.extend(web_search(contact_query, num=5, gl=country_hint(criteria.location)))
                        except Exception:
                            search_errors += 1
                    enrich_no_website_lead(lead, contact_results, scrape_profiles=scrape_pages)
            for lead in mapped_leads:
                if lead and _qualifies(lead, require_email, criteria.website_requirement) and not _excluded(lead, criteria.exclude):
                    candidates.append(lead)
            apify_note = f"TMCP Apify Rotate: {apify_count} places"
        except Exception as exc:
            apify_note = f"TMCP Apify Rotate error: {exc}"
    for query in all_queries[:max_queries]:
        if len(dedupe_leads(candidates)[0]) >= min_listings:
            break
        queries.append(query)
        try:
            results = web_search(query, num=results_per_query, gl=country_hint(criteria.location))
        except Exception:
            search_errors += 1
            continue
        fresh = []
        for result in results:
            url = result.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                fresh.append(result)
        with ThreadPoolExecutor(max_workers=6) as pool:
            for lead in pool.map(lambda item: lead_from_result(item, criteria, scrape_pages), fresh):
                if lead and _qualifies(lead, require_email, criteria.website_requirement) and not _excluded(lead, criteria.exclude):
                    candidates.append(lead)

    leads, duplicates = dedupe_leads(candidates)
    leads.sort(key=lambda lead: lead.lead_score, reverse=True)
    if search_errors:
        parser_note += f"; search errors: {search_errors}"
    if serper_exhausted():
        parser_note += "; WARNING: Serper credits exhausted -- fallback search coverage may be limited"
    potential_sources = discover_new_sources(criteria, sources) if discover_sources else []
    save_listings(leads)

    run = {
        "Run ID": run_id, "Criteria ID": criteria_id,
        "Date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "User": "Britto Soft", "Search Query": mandate,
        "Industry": criteria.industry, "Location": criteria.location,
        "Services": criteria.services, "Sources Searched": len(sources),
        "Leads Found": len(leads), "Duplicates Removed": len(duplicates),
        "New Sources Found": len(potential_sources),
        "Notes": f"Lead discovery + public-page audit; website requirement: {criteria.website_requirement}; email requirement: {'required' if require_email else 'optional'}; source registry: {source_origin}; {apify_note}; {parser_note}; unique web URLs: {len(seen_urls)}; target {min_listings} leads: {'met' if len(leads) >= min_listings else f'short ({len(leads)}) after {len(queries)} web queries'}",
    }
    rows = _lead_rows(leads, criteria_id)
    csv_paths = {
        "Leads": export_csv("leads_" + run_id, rows, EXPORT_DIR),
        "Lead Duplicates": export_csv("duplicates_" + run_id, duplicates, EXPORT_DIR),
        "Potential Sources": export_csv("potential_sources_" + run_id, potential_sources, EXPORT_DIR),
    }
    sheet_results = []
    if write_sheets:
        exports = [("Leads", rows), ("Lead Search Runs", [run]), ("Lead Duplicates", duplicates), ("Potential Sources", potential_sources)]
        if log_mandate:
            exports.insert(0, ("Search Criteria", [_criteria_row(criteria_id, criteria, frequency, notify_email)]))
        for tab, tab_rows in exports:
            ok, message = append_rows(tab, tab_rows)
            sheet_results.append({"tab": tab, "ok": ok, "message": message})
    save_run(run_id, {"criteria": criteria.__dict__, "queries": queries, "run": run, "sheet_results": sheet_results, "csv_paths": csv_paths})
    return criteria, queries, leads, duplicates, potential_sources, run, sheet_results, csv_paths
