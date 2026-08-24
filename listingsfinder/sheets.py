import re
from pathlib import Path

import pandas as pd

from .config import (
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REDIRECT_PORT,
    GOOGLE_OAUTH_TOKEN_INFO,
    GOOGLE_OAUTH_TOKEN_JSON,
    GOOGLE_SERVICE_ACCOUNT_INFO,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEET_URL,
    ROOT,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

TABS = {
    "Lead Sources": ["Source Name", "Website", "Category", "Geography", "Industry Focus", "Active", "Search Method", "Priority", "Notes"],
    "Search Criteria": ["Criteria ID", "Date", "User", "Original Query", "Industry", "Location", "Services", "Keywords", "Opportunity Signals", "Website Requirement", "Exclude", "Frequency", "Last Run", "Next Run", "Notify Email", "Status", "Notes"],
    "Leads": ["Master Lead ID", "Lead ID", "Source", "Source URL", "Company Name", "Website", "Website Status", "Page Title", "Industry", "Location", "Description", "Contact Name", "Contact Email", "Email Source", "Contact Phone", "Facebook URL", "Instagram URL", "LinkedIn URL", "X/Twitter URL", "TikTok URL", "YouTube URL", "Preferred Outreach", "Opportunity Signals", "Recommended Service", "Lead Score", "Discovered At", "Status", "Notes", "Criteria ID"],
    "Lead Search Runs": ["Run ID", "Criteria ID", "Date", "User", "Search Query", "Industry", "Location", "Services", "Sources Searched", "Leads Found", "Duplicates Removed", "New Sources Found", "Notes"],
    "Potential Sources": ["Source Name", "Website", "Category", "Geography", "Industry Focus", "Discovered From Query", "Reason", "Status", "Notes"],
    "Lead Duplicates": ["Master Lead ID", "Duplicate Lead ID", "Duplicate Source", "Duplicate URL", "Match Type", "Reason", "Date Found"],
}


def sheet_id_from_url(url=GOOGLE_SHEET_URL):
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else url


def _client():
    path = Path(GOOGLE_SERVICE_ACCOUNT_JSON)
    path = ROOT / path if not path.is_absolute() else path
    import gspread

    if GOOGLE_SERVICE_ACCOUNT_INFO:
        return gspread.service_account_from_dict(GOOGLE_SERVICE_ACCOUNT_INFO), ""

    if path.exists():
        return gspread.service_account(filename=str(path)), ""

    creds, err = oauth_credentials(interactive=False)
    if err:
        return None, err
    return gspread.authorize(creds), ""


def _oauth_token_path():
    path = Path(GOOGLE_OAUTH_TOKEN_JSON)
    return ROOT / path if not path.is_absolute() else path


def _oauth_client_config():
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
        return None
    return {
        "installed": {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def oauth_credentials(interactive=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = _oauth_token_path()
    creds = None
    if GOOGLE_OAUTH_TOKEN_INFO:
        creds = Credentials.from_authorized_user_info(GOOGLE_OAUTH_TOKEN_INFO, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if creds and creds.valid:
            return creds, ""
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
    if creds and creds.valid:
        return creds, ""

    client_config = _oauth_client_config()
    if not client_config:
        return None, "Missing Google credentials. Add service_account.json or GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env."
    if not interactive:
        return None, "Google OAuth is not authorized yet. Click 'Authorize Google OAuth' in the app sidebar."

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=GOOGLE_OAUTH_REDIRECT_PORT, open_browser=True)
    token_path.parent.mkdir(exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds, f"OAuth token saved: {token_path}"


def authorize_oauth():
    try:
        creds, err = oauth_credentials(interactive=True)
    except Exception as exc:
        return (
            False,
            "Google OAuth desktop authorization cannot run inside Streamlit Cloud. "
            "Authorize locally first, then add credentials/oauth_token.json as GOOGLE_OAUTH_TOKEN_INFO in Streamlit Secrets. "
            f"Error: {exc}",
        )
    if err and not getattr(creds, "valid", False):
        return False, err
    return True, err or f"OAuth authorized and token saved: {_oauth_token_path()}"


def google_auth_status():
    try:
        gc, err = _client()
        if err:
            return False, err
        gc.open_by_key(sheet_id_from_url())
        return True, "Google Sheets connected"
    except Exception as exc:
        return False, str(exc)


def _sheet():
    gc, err = _client()
    if err:
        return None, err
    return gc.open_by_key(sheet_id_from_url()), ""


def ensure_workbook():
    sh, err = _sheet()
    if err:
        return False, err
    existing = {w.title for w in sh.worksheets()}
    for title, headers in TABS.items():
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(20, len(headers))) if title not in existing else sh.worksheet(title)
        current_headers = ws.row_values(1)
        if not current_headers:
            ws.update([headers])
        else:
            merged_headers = current_headers + [header for header in headers if header not in current_headers]
            if merged_headers != current_headers:
                ws.update([merged_headers])
        try:
            ws.freeze(rows=1)
            ws.format("1:1", {"backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}, "textFormat": {"bold": True}})
            ws.set_basic_filter()
        except Exception:
            pass
    return True, "Google Sheets workbook ready"


def read_rows(tab):
    sh, err = _sheet()
    if err:
        return [], err
    try:
        return sh.worksheet(tab).get_all_records(), ""
    except Exception as exc:
        return [], str(exc)


def read_lead_sources():
    rows, err = read_rows("Lead Sources")
    if err:
        return [], err
    rows = [row for row in rows if row.get("Source Name") and row.get("Website")]
    return rows, ""


read_deal_sources = read_lead_sources


def append_rows(tab, rows):
    if not rows:
        return True, "No rows"
    sh, err = _sheet()
    if err:
        return False, err
    try:
        ws = sh.worksheet(tab)
    except Exception:
        headers = TABS.get(tab) or list(rows[0].keys())
        ws = sh.add_worksheet(title=tab, rows=1000, cols=max(20, len(headers)))
        ws.update([headers])
    headers = ws.row_values(1) or list(rows[0].keys())
    required_headers = TABS.get(tab, [])
    merged_headers = headers + [header for header in required_headers if header not in headers]
    if merged_headers != headers:
        ws.update([merged_headers])
        headers = merged_headers
    # RAW prevents international phone numbers such as +1... from being
    # interpreted as formulas and displayed as #ERROR! in Google Sheets.
    ws.append_rows([[row.get(header, "") for header in headers] for row in rows], value_input_option="RAW")
    return True, f"Appended {len(rows)} row(s) to {tab}"


def export_csv(name, rows, export_dir):
    path = Path(export_dir) / f"{name}.csv"
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return str(path)
