import pandas as pd
import streamlit as st

st.set_page_config(page_title="Britto Soft Lead Finder", page_icon="BS", layout="wide")

from listingsfinder.ai_parser import ANTHROPIC_MODELS, OPENROUTER_MODELS, ai_status
from listingsfinder.config import (
    AI_PROVIDER,
    ANTHROPIC_MODEL,
    EXPORT_DIR,
    GOOGLE_SHEET_URL,
    OPENROUTER_MODEL,
    SEARCH_PROVIDER,
    TMCP_API_KEY,
    TMCP_APIFY_ENABLED,
    TMCP_SCRAPEDO_ENABLED,
    TMCP_SERPER_ENABLED,
)
from listingsfinder.maintenance import check_source_health
from listingsfinder.pipeline import active_sources, run_search
from listingsfinder.scheduler import due_mandates, email_status, read_mandate_rows, run_due_mandates
from listingsfinder.sheets import append_rows, authorize_oauth, ensure_workbook, export_csv, google_auth_status
from listingsfinder.store import get_setting, get_sources, init_db, list_listings, list_runs, save_setting, save_source

init_db()

st.title("Britto Soft Lead Finder")
st.caption("Find potential clients, audit public website signals, prioritize opportunities, and save results to Google Sheets.")

with st.sidebar:
    st.subheader("System Status")
    st.write("Search mode:", SEARCH_PROVIDER)
    st.write("TMCP gateway:", "Connected key configured" if TMCP_API_KEY else "Missing key")
    st.write("Apify Rotate:", "Primary" if TMCP_API_KEY and TMCP_APIFY_ENABLED else "Disabled")
    st.write("Scrape.do Rotate:", "Enabled" if TMCP_API_KEY and TMCP_SCRAPEDO_ENABLED else "Disabled")
    st.write("Serper Rotate:", "Optional fallback enabled" if TMCP_API_KEY and TMCP_SERPER_ENABLED else "Optional / disabled")
    st.link_button("Open Google Sheet", GOOGLE_SHEET_URL)
    google_ok, google_msg = google_auth_status()
    if google_ok:
        st.success("Google Sheets connected")
    else:
        st.warning("Google Sheets not connected")
        if st.button("Authorize Google OAuth"):
            ok, msg = authorize_oauth()
            (st.success if ok else st.warning)(msg)
    if st.button("Prepare Lead Sheet Tabs"):
        ok, msg = ensure_workbook()
        (st.success if ok else st.warning)(msg)
    if st.button("Sync Sources From Sheet"):
        sources, origin = active_sources()
        st.success(f"Loaded {len(sources)} sources from {origin}")

saved_ai_settings = get_setting("ai_settings", {})
if "ai_provider" not in st.session_state:
    saved_provider = saved_ai_settings.get("provider", AI_PROVIDER)
    st.session_state.ai_provider = saved_provider if saved_provider in ("Rule-based", "Anthropic", "OpenRouter") else "Rule-based"
if "anthropic_model" not in st.session_state:
    st.session_state.anthropic_model = saved_ai_settings.get("anthropic_model", ANTHROPIC_MODEL)
if "openrouter_model" not in st.session_state:
    st.session_state.openrouter_model = saved_ai_settings.get("openrouter_model", OPENROUTER_MODEL)
if "anthropic_api_key" not in st.session_state:
    st.session_state.anthropic_api_key = saved_ai_settings.get("anthropic_api_key", "")
if "openrouter_api_key" not in st.session_state:
    st.session_state.openrouter_api_key = saved_ai_settings.get("openrouter_api_key", "")
if "remember_anthropic_key" not in st.session_state:
    st.session_state.remember_anthropic_key = bool(saved_ai_settings.get("anthropic_api_key"))
if "remember_openrouter_key" not in st.session_state:
    st.session_state.remember_openrouter_key = bool(saved_ai_settings.get("openrouter_api_key"))

tabs = st.tabs(["Find Leads", "Lead Sources", "Local Leads", "Source Discovery", "Automation", "Maintenance", "Rules", "AI Settings"])

with tabs[0]:
    st.subheader("Lead Search")
    mandate = st.text_input("What kind of clients do you want?", value="", placeholder="Find restaurants in Dhaka that need a better website and SEO")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    max_queries = c1.slider("Max Google queries", 1, 80, 30)
    results_per_query = c2.slider("Results per query", 1, 20, 10)
    min_listings = c3.slider("Target leads", 1, 60, 20)
    scrape_pages = c4.toggle("Scrape result pages", value=True)
    discover_sources = c5.toggle("Find new sources", value=True)
    require_email = c6.toggle("Require public email", value=True, help="Only save leads with a publicly discovered email address")
    website_filter = st.selectbox(
        "Website filter",
        ["Automatic from prompt", "No website only", "Has website only", "Any website status"],
        help="No website only is enforced against the official website field returned by Google Maps.",
    )
    frequency = st.selectbox("Search frequency", ["One-time", "Daily", "Weekly", "Monthly"])
    write_sheets = st.toggle("Write to Google Sheets when credentials are available", value=True)

    if st.button("Find Leads", type="primary"):
        with st.spinner("Finding companies, checking public pages, prioritizing opportunities, and exporting..."):
            criteria, queries, listings, duplicates, potential_sources, run, sheet_results, csv_paths = run_search(
                mandate,
                max_queries=max_queries,
                results_per_query=results_per_query,
                min_listings=min_listings,
                scrape_pages=scrape_pages,
                discover_sources=discover_sources,
                write_sheets=write_sheets,
                ai_provider=st.session_state.ai_provider,
                ai_model=st.session_state.anthropic_model if st.session_state.ai_provider == "Anthropic" else st.session_state.openrouter_model,
                ai_api_key=st.session_state.anthropic_api_key if st.session_state.ai_provider == "Anthropic" else st.session_state.openrouter_api_key,
                frequency=frequency,
                require_email=require_email,
                website_filter=website_filter,
            )

        st.success(f"Done: {len(listings)} unique leads, {len(duplicates)} duplicates removed, {len(potential_sources)} potential new sources.")
        st.write("Parsed criteria", criteria.__dict__)
        st.caption(run.get("Notes", ""))
        st.write("Queries used", queries)

        rows = [listing.to_dict() for listing in listings]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        with st.expander("Export results"):
            st.write(csv_paths)
            if sheet_results:
                st.dataframe(pd.DataFrame(sheet_results), use_container_width=True)

with tabs[1]:
    st.subheader("Lead Sources Registry")
    sources, origin = active_sources()
    st.caption(f"Current source registry: {origin}")
    edited = st.data_editor(pd.DataFrame(sources), use_container_width=True, num_rows="dynamic")
    c1, c2 = st.columns(2)
    if c1.button("Save Sources Locally"):
        for row in edited.fillna("").to_dict(orient="records"):
            if row.get("Source Name"):
                save_source(row)
        st.success("Sources saved locally")
    if c2.button("Export Sources to Google Sheet"):
        ok, msg = append_rows("Lead Sources", edited.fillna("").to_dict(orient="records"))
        (st.success if ok else st.warning)(msg)

with tabs[2]:
    st.subheader("Local Leads")
    st.caption(f"CSV exports folder: {EXPORT_DIR}")
    listings = list_listings()
    runs = list_runs()
    c1, c2 = st.columns(2)
    with c1:
        st.write("Recent runs")
        run_rows = [row.get("run", row) for row in runs]
        st.dataframe(pd.DataFrame(run_rows), use_container_width=True)
    with c2:
        st.write("Stored leads")
        st.dataframe(pd.DataFrame(listings), use_container_width=True)

with tabs[3]:
    st.subheader("Potential New Sources")
    st.caption("Run a search with source discovery enabled to populate this tab in Google Sheets and CSV exports.")
    runs = list_runs()
    rows = []
    for row in runs:
        csv_paths = row.get("csv_paths", {})
        if csv_paths.get("Potential Sources"):
            rows.append({"Run ID": row.get("run", {}).get("Run ID"), "CSV": csv_paths["Potential Sources"]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

with tabs[4]:
    st.subheader("Automation")
    c1, c2 = st.columns(2)
    google_ok, google_msg = google_auth_status()
    email_ok, email_msg = email_status()
    c1.metric("Google Sheets", "Connected" if google_ok else "Not connected")
    c2.metric("Email", email_msg)

    mandate_rows, mandate_err = read_mandate_rows()
    if mandate_err:
        st.warning(mandate_err)
    else:
        recurring_rows = [
            row for row in mandate_rows
            if str(row.get("Frequency", "") or "").strip().lower() in ("daily", "weekly", "monthly")
        ]
        due_rows = due_mandates(mandate_rows)
        st.write("Recurring lead searches")
        st.dataframe(pd.DataFrame(recurring_rows), use_container_width=True)
        st.caption(f"{len(due_rows)} search(es) are due now.")

    if st.button("Run Due Searches Now", type="primary"):
        with st.spinner("Running due recurring lead searches..."):
            results = run_due_mandates()
        st.dataframe(pd.DataFrame(results), use_container_width=True)

    st.info(
        "Manual runs can be triggered here. For fully automatic 5 AM Eastern runs, schedule "
        "`python -m listingsfinder.scheduler` on the host using Streamlit Cloud cron alternative, "
        "GitHub Actions, a VPS cron job, or Windows Task Scheduler."
    )

with tabs[5]:
    st.subheader("Source Registry Maintenance")
    sources = get_sources()
    limit = st.slider("Sources to check", 1, max(1, len(sources)), min(10, len(sources)))
    if st.button("Check Source Health"):
        with st.spinner("Checking source homepages..."):
            health_rows = check_source_health(sources[:limit])
        st.dataframe(pd.DataFrame(health_rows), use_container_width=True)
        path = export_csv("source_health_latest", health_rows, EXPORT_DIR)
        st.info(f"Saved CSV: {path}")

with tabs[6]:
    st.subheader("Scope Rules")
    st.markdown(
        """
- Find public business leads by industry and location.
- Search company sites and approved public directories.
- Check websites for basic, observable improvement opportunities.
- Deduplicate by website domain, public contact details, and company name.
- Export Leads, Search Criteria, Lead Search Runs, Lead Duplicates, and Potential Sources.
- Score completeness and opportunity signals transparently; never invent facts.
- Collect only publicly available business contact information.
- Keep outreach manual so every lead can be reviewed first.
"""
    )

with tabs[7]:
    st.subheader("AI Settings")
    provider = st.selectbox(
        "Provider",
        ["Rule-based", "Anthropic", "OpenRouter"],
        index=["Rule-based", "Anthropic", "OpenRouter"].index(st.session_state.ai_provider),
    )
    st.session_state.ai_provider = provider

    if provider == "Anthropic":
        st.session_state.anthropic_api_key = st.text_input(
            "Anthropic API key",
            value=st.session_state.anthropic_api_key,
            type="password",
            placeholder="Paste key for this session or configure Streamlit Secrets",
        )
        st.session_state.remember_anthropic_key = st.checkbox(
            "Remember Anthropic key locally",
            value=st.session_state.remember_anthropic_key,
        )
        model_options = list(dict.fromkeys([st.session_state.anthropic_model] + ANTHROPIC_MODELS))
        st.session_state.anthropic_model = st.selectbox("Model", model_options)
    elif provider == "OpenRouter":
        st.info("OpenRouter requests use the TMCP OpenRouter Rotate pool configured in .env.")
        model_options = list(dict.fromkeys([st.session_state.openrouter_model] + OPENROUTER_MODELS))
        selected = st.selectbox("Model", model_options + ["Custom model id"])
        if selected == "Custom model id":
            st.session_state.openrouter_model = st.text_input("OpenRouter model id", value=st.session_state.openrouter_model)
        else:
            st.session_state.openrouter_model = selected
    else:
        st.info("Rule-based mode is fastest and does not use AI tokens.")

    active_key = st.session_state.anthropic_api_key if provider == "Anthropic" else ""
    ok, msg = ai_status(provider, active_key)
    (st.success if ok else st.warning)(msg)
    if st.button("Save AI Settings"):
        save_setting(
            "ai_settings",
            {
                "provider": st.session_state.ai_provider,
                "anthropic_model": st.session_state.anthropic_model,
                "openrouter_model": st.session_state.openrouter_model,
                "anthropic_api_key": st.session_state.anthropic_api_key if st.session_state.remember_anthropic_key else "",
                "openrouter_api_key": "",
            },
        )
        st.success("AI settings saved")
    st.caption("Provider and model are saved locally after clicking Save AI Settings. API keys are saved only if the remember option is checked; otherwise keys stay in the current session only.")
