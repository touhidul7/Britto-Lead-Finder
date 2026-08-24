# Coolify Deployment

Yes, this app can be deployed through Coolify from GitHub.

## What Coolify Uses

Use the repo root `docker-compose.yml`.

It starts three containers:

- `ui` for Streamlit
- `api` for the HTTP API
- `scheduler` for automatic mandate polling

## Setup Steps

1. Connect your GitHub repository in Coolify.
2. Choose Docker Compose deployment.
3. Point Coolify at the repo root `docker-compose.yml`.
4. Add the required environment variables in Coolify, not in the repo.
5. Deploy.

## Environment Variables

Add the same variables you would normally put in `.env`, especially:

```text
GOOGLE_SHEET_URL
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_TOKEN_INFO
RESEND_API_KEY
RESEND_FROM_EMAIL
LISTINGSFINDER_API_KEY
SERPER_API_KEY
SCRAPEDO_TOKEN
AI_PROVIDER
ANTHROPIC_API_KEY
ANTHROPIC_MODEL
OPENROUTER_API_KEY
OPENROUTER_MODEL
SCHEDULER_POLL_SECONDS
SCHEDULE_MAX_QUERIES
SCHEDULE_RESULTS_PER_QUERY
SCHEDULE_SCRAPE_PAGES
SCHEDULE_DISCOVER_SOURCES
```

## Notes

- Coolify can auto-deploy on GitHub pushes.
- The scheduler runs continuously inside its own container, so mandates are checked automatically.
- The API returns the collected listings after the search finishes.
- In Coolify, route the `ui` service to internal port `8501`. This is the Streamlit dashboard.
- If you want the API publicly reachable, route the `api` service to internal port `8000` or give it its own domain/subdomain.
- Do not add a domain to `scheduler`; it is a background worker and has no web port.
- The compose file uses `expose` instead of fixed host `ports`, so it will not conflict with ports already used on the VPS.

## Quick Test

After deploy, check:

```text
/health
```

on the API container, and use the Streamlit dashboard to confirm Google Sheets access.
## Streamlit Bad Gateway or Chunk Errors

If the UI loads but shows an error like:

```text
Failed to fetch dynamically imported module: /static/js/Spinner...
```

Do this:

1. Hard refresh the browser tab with `Ctrl+F5` or open the UI in an incognito window.
2. Confirm the `ui` domain routes to internal port `8501`.
3. Confirm the `api` domain routes to internal port `8000`.
4. Do not route any domain to `scheduler`.
5. Redeploy after pushing the latest Docker/Compose changes.

This usually happens when the browser has cached old Streamlit frontend chunks after a redeploy, or when Coolify routes the UI domain to the wrong service/port.