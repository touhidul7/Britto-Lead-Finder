# VPS Deployment

This setup runs three processes on the VPS:

```text
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
uvicorn listingsfinder.api:app --host 0.0.0.0 --port 8000
python -m listingsfinder.scheduler_service
```

Streamlit is the dashboard. The API is for other apps/automations. The scheduler loop checks Google Sheets automatically every few minutes and runs due mandates.

## Environment

Add these to `.env` on the VPS:

```text
GOOGLE_SHEET_URL=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_TOKEN_JSON=credentials/oauth_token.json
RESEND_API_KEY=
RESEND_FROM_EMAIL=ListingsFinder <notifications@yourdomain.com>
LISTINGSFINDER_API_KEY=choose-a-long-random-secret
SCHEDULER_POLL_SECONDS=300
SCHEDULE_MAX_QUERIES=4
SCHEDULE_RESULTS_PER_QUERY=5
SCHEDULE_SCRAPE_PAGES=false
SCHEDULE_DISCOVER_SOURCES=false
```

`SERPER_API_KEY` and `SCRAPEDO_TOKEN` are optional but recommended for more reliable search/scraping.

## Mandates Tab Values

For a one-time mandate that should run once automatically:

```text
Original Query: Pharmacies for sale in Ontario
Frequency: One-time
Status: Active
Last Run: leave blank
Next Run: leave blank, or set a past/current date-time
Notify Email: optional email address
```

After it runs, the app sets `Last Run` and changes `Status` to `Completed`, so it will not run again.

For recurring mandates:

```text
Frequency: Daily, Weekly, or Monthly
Status: Active
Last Run: leave blank for first run
Next Run: optional. Use this if you want to control the first run time.
Notify Email: optional email address
```

The recurring schedule uses 5 AM Eastern for the next run after each successful run.

Use `Status` values `Inactive`, `Paused`, or `Disabled` to stop a mandate.

## API Auth

If `LISTINGSFINDER_API_KEY` is set, pass it as either:

```text
X-API-Key: your-key
```

or:

```text
Authorization: Bearer your-key
```

## API Examples

POST search:

```bash
curl -X POST http://YOUR_VPS_IP:8000/api/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"mandate":"Pharmacies for sale in Ontario","max_queries":4,"results_per_query":5,"write_sheets":true}'
```

GET search:

```bash
curl "http://YOUR_VPS_IP:8000/api/search?mandate=Pharmacies%20for%20sale%20in%20Ontario&max_queries=4&results_per_query=5" \
  -H "X-API-Key: your-key"
```

Run due scheduled mandates through API:

```bash
curl -X POST http://YOUR_VPS_IP:8000/api/scheduler/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"force":false}'
```

The search API waits until the run finishes, then returns the parsed criteria, queries, run summary, listings, duplicate count, sheet export status, and CSV paths.

## systemd

Copy these unit files to `/etc/systemd/system/` on the VPS:

```text
deploy/systemd/listingsfinder-ui.service
deploy/systemd/listingsfinder-api.service
deploy/systemd/listingsfinder-scheduler.service
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable listingsfinder-ui listingsfinder-api listingsfinder-scheduler
sudo systemctl start listingsfinder-ui listingsfinder-api listingsfinder-scheduler
sudo systemctl status listingsfinder-ui listingsfinder-api listingsfinder-scheduler
```

If your app folder or virtualenv lives somewhere else, update the `WorkingDirectory` and `ExecStart` paths inside each unit file before enabling them.