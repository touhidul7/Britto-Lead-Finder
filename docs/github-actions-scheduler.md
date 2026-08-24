# GitHub Actions Scheduler

Use this when the app code is on GitHub and you want recurring mandates to run automatically.

## What It Does

The workflow in `.github/workflows/scheduled-mandates.yml` runs:

```text
python -m listingsfinder.scheduler
```

It checks the Google Sheet `Mandates` tab, runs due mandates, appends listings, updates `Last Run` and `Next Run`, and sends Resend email notifications when configured.

## Required GitHub Secrets

Go to:

```text
GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret
```

Add:

```text
GOOGLE_SHEET_URL
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_TOKEN_JSON
RESEND_API_KEY
RESEND_FROM_EMAIL
```

Optional:

```text
SEARCH_PROVIDER
SERPER_API_KEY
SCRAPEDO_TOKEN
SCHEDULE_MAX_QUERIES
SCHEDULE_RESULTS_PER_QUERY
SCHEDULE_SCRAPE_PAGES
SCHEDULE_DISCOVER_SOURCES
AI_PROVIDER
ANTHROPIC_API_KEY
ANTHROPIC_MODEL
OPENROUTER_API_KEY
OPENROUTER_MODEL
```

## Google OAuth Token Secret

For `GOOGLE_OAUTH_TOKEN_JSON`, paste the full contents of:

```text
credentials/oauth_token.json
```

It must be raw JSON starting with `{`, for example:

```json
{"token":"...","refresh_token":"...","token_uri":"https://oauth2.googleapis.com/token","client_id":"...","client_secret":"...","scopes":["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]}
```

Do not paste the TOML output from `oauth_token_to_toml.py` into this GitHub secret.

Do not commit that file to GitHub.

## Schedule

GitHub cron runs in UTC. The workflow triggers at both `09:00 UTC` and `10:00 UTC` to cover daylight saving time changes for 5 AM Eastern.

Duplicate triggers are safe because the app checks each mandate's `Next Run` before running.

## Manual Test

In GitHub:

```text
Actions -> Run scheduled mandates -> Run workflow
```

Use `force=true` when you want to test immediately. This ignores `Next Run` for the manual run only.

Then check the workflow logs and the Google Sheet.
