from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SearchCriteria:
    original_query: str
    industry: str = ""
    location: str = ""
    services: str = "Website Design, SEO, Digital Marketing"
    keywords: str = ""
    opportunity_signals: str = ""
    exclude: str = ""
    website_requirement: str = "Any"


@dataclass
class Lead:
    master_lead_id: str = ""
    lead_id: str = ""
    source: str = ""
    source_url: str = ""
    company_name: str = ""
    website: str = ""
    page_title: str = ""
    industry: str = ""
    location: str = ""
    description: str = ""
    contact_name: str = ""
    contact_email: str = ""
    email_source: str = ""
    contact_phone: str = ""
    facebook_url: str = ""
    instagram_url: str = ""
    linkedin_url: str = ""
    twitter_url: str = ""
    tiktok_url: str = ""
    youtube_url: str = ""
    website_status: str = ""
    preferred_outreach: str = ""
    opportunity_signals: str = ""
    recommended_service: str = ""
    lead_score: int = 0
    discovered_at: str = ""
    status: str = "New"
    notes: str = ""

    def to_dict(self):
        return asdict(self)


# Backwards-compatible import for older integrations during the product rename.
Listing = Lead
