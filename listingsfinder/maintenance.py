import requests

from .scraper import UA


def check_source_health(sources, timeout=12):
    rows = []
    for source in sources:
        website = (source.get("Website") or "").strip()
        url = website if website.startswith(("http://", "https://")) else f"https://{website}"
        row = {
            **source,
            "Checked URL": url,
            "HTTP Status": "",
            "Site Active": "No",
            "Issue": "",
        }
        try:
            response = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, allow_redirects=True)
            row["HTTP Status"] = response.status_code
            row["Final URL"] = response.url
            row["Site Active"] = "Yes" if response.status_code < 400 else "No"
            if "login" in response.url.lower():
                row["Issue"] = "Redirected to login"
            elif response.status_code >= 400:
                row["Issue"] = "HTTP error"
        except Exception as exc:
            row["Issue"] = str(exc)[:200]
        rows.append(row)
    return rows
