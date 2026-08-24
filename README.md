# Britto Soft Lead Finder

Lead discovery and website-opportunity auditing for Britto Soft. The app searches public company sites and business directories, extracts public business contact details, prioritizes useful leads, removes duplicates, and stores results in Google Sheets.

## What it does

- Parses searches such as `Find restaurants in Dhaka that need a better website and SEO`.
- Uses TMCP Apify Rotate as the primary Google Maps lead source.
- Uses keyless web search as a supplement and TMCP Serper Rotate only when explicitly enabled and free fallbacks return nothing.
- Checks public pages for observable signals such as missing mobile metadata, missing SEO basics, no clear enquiry path, or no independent website.
- Recommends relevant Britto Soft services and calculates a transparent lead-quality score.
- Deduplicates by website domain, public email, phone, and company name.
- Exports `Lead Sources`, `Search Criteria`, `Leads`, `Lead Search Runs`, `Potential Sources`, and `Lead Duplicates` to Google Sheets.
- Runs one-time or recurring searches from the `Search Criteria` tab.

The app does not guess private contact information or send automated outreach. Review every lead before contacting it and follow applicable privacy and anti-spam rules.

## Local setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

On Windows, `run_app.bat` starts the Streamlit UI at `http://127.0.0.1:8501`.

## Google Sheets

Set the copied workbook URL and one supported credential method in `.env`:

```text
GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit
GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
```

OAuth variables are also supported. The authenticated Google account or service account must have edit access to the workbook. Click **Prepare Lead Sheet Tabs** in the sidebar once; existing copied-client tabs are retained.

## TMCP rotate providers

```text
TMCP_API_KEY=mcp_live_your_key
TMCP_BASE_URL=https://tmcp.vercel.app
TMCP_APIFY_ENABLED=true
TMCP_APIFY_ACTOR=compass~crawler-google-places
TMCP_APIFY_MAX_RESULTS=20
TMCP_SCRAPEDO_ENABLED=true
TMCP_SERPER_ENABLED=false
SEARCH_PROVIDER=auto
```

The app uses only TMCP rotation proxies for Apify, Scrape.do, Serper, and OpenRouter. Apify supplies structured business leads; Scrape.do audits sites when direct requests fail. Serper is off by default to minimize usage. Set `TMCP_SERPER_ENABLED=true` only when you want it as the final fallback.

## AI criteria parsing

Rule-based parsing needs no AI key. Anthropic and OpenRouter can be selected in the UI for more complex natural-language searches.

```text
AI_PROVIDER=Rule-based
ANTHROPIC_API_KEY=
OPENROUTER_MODEL=anthropic/claude-sonnet-4.5
```

## API

Run:

```bash
uvicorn listingsfinder.api:app --host 0.0.0.0 --port 8000
```

Optional authentication uses `LEADFINDER_API_KEY` (the old `LISTINGSFINDER_API_KEY` remains supported).

```http
POST /api/search
Content-Type: application/json
X-API-Key: your-key

{
  "mandate": "Find dental clinics in Toronto that need SEO and web design",
  "max_queries": 20,
  "results_per_query": 10,
  "min_listings": 20,
  "scrape_pages": true,
  "discover_sources": false,
  "write_sheets": true
}
```

The response uses `leads_count` and `leads`. The request field `mandate` and `min_listings` remain unchanged for compatibility with existing n8n or API clients.

## Scheduler

The scheduler reads active rows from `Search Criteria`. Supported frequencies are `One-time`, `Daily`, `Weekly`, and `Monthly`.

```bash
python -m listingsfinder.scheduler_service
```

Useful settings:

```text
SCHEDULER_POLL_SECONDS=300
SCHEDULE_MAX_QUERIES=30
SCHEDULE_RESULTS_PER_QUERY=10
SCHEDULE_SCRAPE_PAGES=true
SCHEDULE_DISCOVER_SOURCES=false
```
