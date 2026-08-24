import os
import json
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
DEFAULT_SHEET_URL=''


def _streamlit_secrets_available():
    candidates = [
        Path.home() / ".streamlit" / "secrets.toml",
        ROOT / ".streamlit" / "secrets.toml",
    ]
    return any(path.exists() for path in candidates)


def _streamlit_secret(name):
    if not _streamlit_secrets_available():
        return None
    try:
        import streamlit as st

        return st.secrets[name] if name in st.secrets else None
    except Exception:
        return None


def setting(name, default=""):
    value = os.getenv(name)
    if value not in (None, ""):
        return str(value).strip()
    secret = _streamlit_secret(name)
    if secret not in (None, ""):
        return str(secret).strip()
    return str(default).strip()


def bool_setting(name, default=False):
    value = setting(name, "true" if default else "false")
    return value.lower() in ("1", "true", "yes", "on")


def secret_dict(name):
    value = os.getenv(name)
    if value not in (None, ""):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    secret = _streamlit_secret(name)
    if secret:
        try:
            return dict(secret)
        except Exception:
            return None
    return None


SEARCH_PROVIDER=setting('SEARCH_PROVIDER','auto')
TMCP_API_KEY=setting('TMCP_API_KEY', setting('TMCP_api_key'))
TMCP_BASE_URL=setting('TMCP_BASE_URL','https://tmcp.vercel.app').rstrip('/')
TMCP_APIFY_ENABLED=bool_setting('TMCP_APIFY_ENABLED', True)
TMCP_APIFY_ACTOR=setting('TMCP_APIFY_ACTOR','compass~crawler-google-places').replace('/', '~')
TMCP_APIFY_MAX_RESULTS=int(setting('TMCP_APIFY_MAX_RESULTS','20') or '20')
TMCP_APIFY_SCRAPE_CONTACTS=bool_setting('TMCP_APIFY_SCRAPE_CONTACTS', True)
TMCP_APIFY_SOCIAL_PROFILES=bool_setting('TMCP_APIFY_SOCIAL_PROFILES', True)
TMCP_APIFY_LEADS_PER_PLACE=int(setting('TMCP_APIFY_LEADS_PER_PLACE','1') or '1')
TMCP_APIFY_VERIFY_EMAILS=bool_setting('TMCP_APIFY_VERIFY_EMAILS', False)
TMCP_SCRAPEDO_ENABLED=bool_setting('TMCP_SCRAPEDO_ENABLED', True)
TMCP_SERPER_ENABLED=bool_setting('TMCP_SERPER_ENABLED', False)
GOOGLE_SHEET_URL=setting('GOOGLE_SHEET_URL',DEFAULT_SHEET_URL)
GOOGLE_SERVICE_ACCOUNT_JSON=setting('GOOGLE_SERVICE_ACCOUNT_JSON','credentials/service_account.json')
GOOGLE_SERVICE_ACCOUNT_INFO=secret_dict('GOOGLE_SERVICE_ACCOUNT_INFO')
GOOGLE_OAUTH_CLIENT_ID=setting('GOOGLE_OAUTH_CLIENT_ID')
GOOGLE_OAUTH_CLIENT_SECRET=setting('GOOGLE_OAUTH_CLIENT_SECRET')
GOOGLE_OAUTH_TOKEN_JSON=setting('GOOGLE_OAUTH_TOKEN_JSON','credentials/oauth_token.json')
GOOGLE_OAUTH_TOKEN_INFO=secret_dict('GOOGLE_OAUTH_TOKEN_INFO')
GOOGLE_OAUTH_REDIRECT_PORT=int(setting('GOOGLE_OAUTH_REDIRECT_PORT','8502') or '8502')
AI_PROVIDER=setting('AI_PROVIDER','Rule-based')
ANTHROPIC_API_KEY=setting('ANTHROPIC_API_KEY')
ANTHROPIC_MODEL=setting('ANTHROPIC_MODEL','claude-sonnet-4-5-20250929')
OPENROUTER_MODEL=setting('OPENROUTER_MODEL','anthropic/claude-sonnet-4.5')
SMTP_HOST=setting('SMTP_HOST')
SMTP_PORT=int(setting('SMTP_PORT','587') or '587')
SMTP_USER=setting('SMTP_USER')
SMTP_PASSWORD=setting('SMTP_PASSWORD')
SMTP_FROM=setting('SMTP_FROM',SMTP_USER)
RESEND_API_KEY=setting('RESEND_API_KEY')
RESEND_FROM_EMAIL=setting('RESEND_FROM_EMAIL','Britto Soft Lead Finder <onboarding@resend.dev>')
LISTINGSFINDER_API_KEY=setting('LEADFINDER_API_KEY', setting('LISTINGSFINDER_API_KEY'))
SCHEDULER_POLL_SECONDS=int(setting('SCHEDULER_POLL_SECONDS','300') or '300')
DIRECTORY_MAX_LINKS_PER_PAGE=int(setting('DIRECTORY_MAX_LINKS_PER_PAGE','25') or '25')
DIRECTORY_MAX_PAGES=int(setting('DIRECTORY_MAX_PAGES','10') or '10')
DATA_DIR=ROOT/'data'; EXPORT_DIR=ROOT/'exports'; DB_PATH=DATA_DIR/'listingsfinder.db'
for p in (DATA_DIR,EXPORT_DIR,ROOT/'credentials'): p.mkdir(exist_ok=True)
