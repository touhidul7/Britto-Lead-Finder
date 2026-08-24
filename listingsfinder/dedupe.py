import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from rapidfuzz import fuzz


def _norm(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _domain(value):
    return urlparse(value or "").netloc.lower().removeprefix("www.")


def dedupe_listings(leads):
    masters, duplicates = [], []
    found_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for lead in leads:
        match = reason = match_type = None
        for master in masters:
            lead_domain, master_domain = _domain(lead.website), _domain(master.website)
            if lead_domain and lead_domain == master_domain:
                match, reason, match_type = master, "Same website domain", "Exact"
                break
            if lead.contact_email and _norm(lead.contact_email) == _norm(master.contact_email):
                match, reason, match_type = master, "Same email", "Exact"
                break
            if lead.contact_phone and _norm(lead.contact_phone) == _norm(master.contact_phone):
                match, reason, match_type = master, "Same phone", "Exact"
                break
            score = fuzz.token_set_ratio(lead.company_name, master.company_name)
            if score >= 90 and (lead.location == master.location or not lead.location or not master.location):
                match, reason, match_type = master, f"Similar company name score {score}", "Strong"
                break
        if match:
            duplicates.append({"Master Lead ID": match.master_lead_id, "Duplicate Lead ID": lead.lead_id, "Duplicate Source": lead.source, "Duplicate URL": lead.source_url, "Match Type": match_type, "Reason": reason, "Date Found": found_at})
        else:
            lead.master_lead_id = f"BRITTO-{len(masters) + 1:05d}"
            masters.append(lead)
    return masters, duplicates


dedupe_leads = dedupe_listings
