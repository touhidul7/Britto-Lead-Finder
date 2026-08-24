import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib
from zoneinfo import ZoneInfo

import requests

from .config import RESEND_API_KEY, RESEND_FROM_EMAIL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER
from .pipeline import run_search
from .sheets import _sheet

EASTERN = ZoneInfo("America/New_York")
FREQUENCIES = {"one-time", "daily", "weekly", "monthly"}


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


SCHEDULE_MAX_QUERIES = int(os.getenv("SCHEDULE_MAX_QUERIES", "30") or "30")
SCHEDULE_RESULTS_PER_QUERY = int(os.getenv("SCHEDULE_RESULTS_PER_QUERY", "10") or "10")
SCHEDULE_SCRAPE_PAGES = _env_bool("SCHEDULE_SCRAPE_PAGES", True)
SCHEDULE_DISCOVER_SOURCES = _env_bool("SCHEDULE_DISCOVER_SOURCES", False)


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=EASTERN)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(EASTERN) if parsed.tzinfo else parsed.replace(tzinfo=EASTERN)
    except ValueError:
        return None


def _next_run(now, frequency):
    base = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if frequency == "daily":
        return base + (timedelta(days=1) if now >= base else timedelta())
    if frequency == "weekly":
        return base + timedelta(days=7)
    if frequency == "monthly":
        month = base.month + 1
        year = base.year + (1 if month == 13 else 0)
        month = 1 if month == 13 else month
        return base.replace(year=year, month=month)
    return ""


def _send_email(to_email, subject, body):
    if RESEND_API_KEY:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM_EMAIL, "to": [to_email], "subject": subject, "text": body},
            timeout=30,
        )
        response.raise_for_status()
        return True, "Email sent with Resend"
    if not to_email or not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        return False, "Email provider not configured"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
    return True, "Email sent"


def email_status():
    if RESEND_API_KEY:
        return True, "Resend configured"
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        return True, "SMTP configured"
    return False, "Email provider not configured"



def _row_value(row, *names):
    normalized = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        value = normalized.get(str(name).strip().lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _email_body(mandate, listings):
    lines = [
        f"Britto Soft Lead Finder found {len(listings)} lead(s).",
        f"Search: {mandate}",
        "",
    ]
    for item in listings[:25]:
        lines.append(f"- {item.company_name} (score {item.lead_score})")
        lines.append(f"  {item.website or item.source_url}")
    return "\n".join(lines)
def read_mandate_rows():
    sh, err = _sheet()
    if err:
        return [], err
    try:
        return sh.worksheet("Search Criteria").get_all_records(), ""
    except Exception as exc:
        return [], str(exc)


def due_mandates(rows, now=None, force=False):
    now = now or datetime.now(EASTERN)
    due = []
    for index, row in enumerate(rows, start=2):
        raw_frequency = str(row.get("Frequency", "") or "").strip()
        frequency = raw_frequency.lower()
        status = str(row.get("Status", "") or "").strip().lower()
        if status in ("inactive", "paused", "disabled", "completed", "done"):
            continue
        if frequency not in FREQUENCIES:
            continue
        next_run = _parse_dt(row.get("Next Run"))
        last_run = _parse_dt(row.get("Last Run"))
        if frequency == "one-time":
            if force or (not last_run and (not next_run or next_run <= now)):
                due.append((index, row, frequency))
            continue
        if force:
            due.append((index, row, frequency))
            continue
        if next_run and next_run > now:
            continue
        if not next_run and last_run:
            next_run = _next_run(last_run, frequency)
            if next_run and next_run > now:
                continue
        due.append((index, row, frequency))
    return due

def run_due_mandates(force=False):
    sh, err = _sheet()
    if err:
        return [{"ok": False, "message": err}]
    ws = sh.worksheet("Search Criteria")
    rows = ws.get_all_records()
    headers = ws.row_values(1)
    now = datetime.now(EASTERN)
    results = []

    def col(name):
        return headers.index(name) + 1 if name in headers else None

    for row_index, row, frequency in due_mandates(rows, now, force=force):
        mandate = row.get("Original Query") or row.get("Search Query")
        if not mandate:
            continue
        mandate_id = row.get("Criteria ID") or row.get("Mandate ID") or ""
        criteria, queries, listings, duplicates, potential, run, sheet_results, csv_paths = run_search(
            mandate,
            max_queries=SCHEDULE_MAX_QUERIES,
            results_per_query=SCHEDULE_RESULTS_PER_QUERY,
            scrape_pages=SCHEDULE_SCRAPE_PAGES,
            discover_sources=SCHEDULE_DISCOVER_SOURCES,
            write_sheets=True,
            mandate_id=mandate_id,
            log_mandate=False,
            frequency=frequency.title(),
        )
        last_run_value = now.isoformat(timespec="seconds")
        next_run_value = _next_run(now, frequency)
        if col("Last Run"):
            ws.update_cell(row_index, col("Last Run"), last_run_value)
        if col("Next Run"):
            ws.update_cell(row_index, col("Next Run"), next_run_value.isoformat(timespec="seconds") if next_run_value else "")
        if col("Status"):
            ws.update_cell(row_index, col("Status"), "Completed" if frequency == "one-time" else "Scheduled")
        email_status = None
        notify_email = _row_value(row, "Notify Email", "Notification Email", "Email", "Notify")
        if notify_email and listings:
            try:
                body = _email_body(mandate, listings)
                email_status = _send_email(notify_email, f"Britto Soft: {len(listings)} leads found", body)
            except Exception as exc:
                email_status = (False, f"Email send failed: {exc}")
        elif not notify_email:
            email_status = (False, "No Notify Email set")
        elif not listings:
            email_status = (False, "No leads found, email skipped")
        print(f"Scheduled lead search {mandate_id or row_index}: leads={len(listings)} notify_email={bool(notify_email)} email={email_status}", flush=True)
        results.append(
            {
                "ok": True,
                "criteria_id": mandate_id,
                "query": mandate,
                "leads": len(listings),
                "duplicates": len(duplicates),
                "email": email_status,
            }
        )
    return results


if __name__ == "__main__":
    force = str(os.getenv("FORCE_SCHEDULED_MANDATES", "")).strip().lower() in ("1", "true", "yes")
    results = run_due_mandates(force=force)
    if not results:
        print("No due lead searches found.")
    for result in results:
        print(result)
