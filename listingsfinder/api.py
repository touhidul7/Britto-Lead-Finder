from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .config import LISTINGSFINDER_API_KEY
from .pipeline import run_search
from .scheduler import run_due_mandates

app = FastAPI(title="Britto Soft Lead Finder API", version="2.0.0")


class SearchRequest(BaseModel):
    mandate: str = Field(..., min_length=3)
    max_queries: int = Field(30, ge=1, le=80)
    results_per_query: int = Field(10, ge=1, le=20)
    min_listings: int = Field(20, ge=1, le=60)
    scrape_pages: bool = True
    discover_sources: bool = False
    write_sheets: bool = True
    ai_provider: str = "Rule-based"
    ai_model: str = ""
    ai_api_key: str = ""
    mandate_id: str = ""
    frequency: str = "One-time"
    notify_email: str = ""
    require_email: bool = True
    website_filter: str = "Automatic from prompt"


class SchedulerRequest(BaseModel):
    force: bool = False


def require_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    if not LISTINGSFINDER_API_KEY:
        return True
    bearer = f"Bearer {LISTINGSFINDER_API_KEY}"
    if x_api_key == LISTINGSFINDER_API_KEY or authorization == bearer:
        return True
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _run_search_response(payload: SearchRequest):
    criteria, queries, listings, duplicates, potential_sources, run, sheet_results, csv_paths = run_search(
        payload.mandate,
        max_queries=payload.max_queries,
        results_per_query=payload.results_per_query,
        min_listings=payload.min_listings,
        scrape_pages=payload.scrape_pages,
        discover_sources=payload.discover_sources,
        write_sheets=payload.write_sheets,
        ai_provider=payload.ai_provider,
        ai_model=payload.ai_model,
        ai_api_key=payload.ai_api_key,
        mandate_id=payload.mandate_id,
        frequency=payload.frequency,
        notify_email=payload.notify_email,
        require_email=payload.require_email,
        website_filter=payload.website_filter,
    )
    return {
        "ok": True,
        "criteria": criteria.__dict__,
        "queries": queries,
        "run": run,
        "leads_count": len(listings),
        "duplicates_count": len(duplicates),
        "potential_sources_count": len(potential_sources),
        "leads": [listing.to_dict() for listing in listings],
        "duplicates": duplicates,
        "potential_sources": potential_sources,
        "sheet_results": sheet_results,
        "csv_paths": {key: str(value) for key, value in csv_paths.items()},
    }


@app.get("/health")
def health():
    return {"ok": True, "service": "Britto Soft Lead Finder API"}


@app.get("/api/search", dependencies=[Depends(require_api_key)])
def search_get(
    mandate: str = Query(..., min_length=3),
    max_queries: int = Query(30, ge=1, le=80),
    results_per_query: int = Query(10, ge=1, le=20),
    min_listings: int = Query(20, ge=1, le=60),
    scrape_pages: bool = True,
    discover_sources: bool = False,
    write_sheets: bool = True,
    require_email: bool = True,
    website_filter: str = "Automatic from prompt",
):
    payload = SearchRequest(
        mandate=mandate,
        max_queries=max_queries,
        results_per_query=results_per_query,
        min_listings=min_listings,
        scrape_pages=scrape_pages,
        discover_sources=discover_sources,
        write_sheets=write_sheets,
        require_email=require_email,
        website_filter=website_filter,
    )
    return _run_search_response(payload)


@app.post("/api/search", dependencies=[Depends(require_api_key)])
def search_post(payload: SearchRequest):
    return _run_search_response(payload)


@app.post("/api/scheduler/run", dependencies=[Depends(require_api_key)])
def scheduler_run(payload: SchedulerRequest):
    return {"ok": True, "results": run_due_mandates(force=payload.force)}
