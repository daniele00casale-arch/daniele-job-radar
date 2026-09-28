"""
API connectors for Daniele Job Radar.

Each fetch_* function returns a list of plain dicts with a common shape:

    {
        "source": str,            # human-readable source name
        "source_id": str,         # id/slug/guid, used for de-duplication
        "title": str,
        "company": str,
        "location": str,          # free-text location / restriction string
        "worldwide": bool,        # True only when we are confident it's open worldwide
        "description": str,       # plain text (HTML stripped)
        "employment_type": str,   # "Full Time", "Contract", ...
        "seniority": str,         # ALWAYS a plain string (never a list)
        "salary": str,            # human-readable, "" when unknown
        "url": str,               # original application link
        "published_at": str,      # ISO date when possible
    }

Every network call is wrapped by the caller (app.py) in a try/except, so a
single connector failing (timeout, schema change, HTTP error) never brings
down the whole dashboard - it is reported in the "Avvisi connettori" panel
instead.
"""
import os
import re
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "DanieleJobRadar/1.0 (personal job search dashboard)"}
TIMEOUT = 25

WORLDWIDE_HINTS = [
    "worldwide", "anywhere in the world", "work from anywhere", "fully remote",
    "remote worldwide", "remote - worldwide", "all countries", "global remote",
    "no location restriction", "location independent", "remote, anywhere",
]
RESTRICTED_HINTS = [
    "us only", "u.s. only", "united states only", "uk only", "canada only",
    "eu only", "european union only", "must be based in", "must reside in",
    "remote within", "timezone", "must be located in", "candidates must be",
]

SALARY_RX = re.compile(
    r"(?:USD|EUR|GBP|\$|€|£)\s?\d[\d,\.]{2,}(?:\s?[-–to]{1,3}\s?(?:USD|EUR|GBP|\$|€|£)?\s?\d[\d,\.]{2,})?"
    r"(?:\s?(?:/|per)\s?(?:year|yr|annum|month|hour))?",
    re.I,
)


def clean_html(value):
    """Strip HTML tags/entities and collapse whitespace."""
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def to_text(value):
    """Coerce any field (str, list, None, number) into a plain string.

    This matters a lot: some APIs (Himalayas) return `seniority` as a list
    like ["Senior", "Manager"] instead of a string. Passing a list into
    `" ".join([...])` elsewhere in the codebase raises a TypeError and
    crashes the whole app - this helper is the single place that prevents
    that class of bug for every connector.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(to_text(v) for v in value if v)
    return str(value)


def to_iso_date(value):
    """Best-effort conversion of a timestamp (unix int, ISO string, RFC822
    string) into a short ISO date string. Falls back to str(value)."""
    if not value:
        return ""
    try:
        # Unix timestamp (Himalayas / Arbeitnow use seconds-since-epoch ints)
        num = float(value)
        return datetime.fromtimestamp(num, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    try:
        return datetime(*value[:6]).strftime("%Y-%m-%d")  # feedparser time.struct_time-ish
    except Exception:
        return str(value)


def guess_worldwide(location_text, description_text, explicit=None):
    """Decide whether a job is genuinely open worldwide / work-from-anywhere.

    `explicit` lets a connector pass a definitive signal from the source
    itself (e.g. Himalayas' empty `locationRestrictions` list, or WWR's
    <region>Anywhere in the World</region> tag) which always wins over the
    text heuristics below.
    """
    if explicit is True:
        return True
    if explicit is False:
        return False
    blob = f"{location_text} {description_text}".lower()
    if any(bad in blob for bad in RESTRICTED_HINTS):
        return False
    return any(good in blob for good in WORLDWIDE_HINTS)


def extract_salary(text):
    """Best-effort salary extraction from free-text description, used as a
    fallback when the source doesn't expose a structured salary field."""
    if not text:
        return ""
    m = SALARY_RX.search(text)
    return m.group(0).strip() if m else ""


def _pick_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("jobs", "data", "results"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


# --------------------------------------------------------------------------
# Himalayas — https://himalayas.app/jobs/api/search
# Confirmed live response shape (Sept 2026): top-level {comments, updatedAt,
# offset, limit, totalCount, jobs:[...]}. Each job has companyName,
# employmentType, seniority (LIST), locationRestrictions (LIST, empty means
# no restriction i.e. worldwide), minSalary/maxSalary/currency/salaryPeriod,
# applicationLink, pubDate (unix seconds), categories (LIST).
# --------------------------------------------------------------------------
def fetch_himalayas(query="product", pages=2, page_size=20):
    out = []
    offset = 0
    for _ in range(pages):
        params = {"q": query, "limit": page_size, "offset": offset}
        r = requests.get("https://himalayas.app/jobs/api/search", params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        jobs = _pick_list(payload)
        if not jobs:
            break
        for j in jobs:
            company = j.get("companyName") or ""
            if not company and isinstance(j.get("company"), dict):
                company = j["company"].get("name", "")
            restrictions = j.get("locationRestrictions") or []
            location = ", ".join(restrictions) if restrictions else "Worldwide"
            categories = j.get("categories") or j.get("parentCategories") or []
            description = clean_html(j.get("description") or j.get("excerpt") or "")
            salary_bits = [str(j.get("minSalary") or ""), str(j.get("maxSalary") or "")]
            salary = "-".join(b for b in salary_bits if b).strip("-")
            if salary and j.get("currency"):
                salary = f"{salary} {j['currency']}"
            out.append({
                "source": "Himalayas",
                "source_id": str(j.get("guid") or j.get("id") or j.get("applicationLink") or ""),
                "title": j.get("title", ""),
                "company": company,
                "location": location,
                "worldwide": guess_worldwide(location, description, explicit=(len(restrictions) == 0)),
                "description": description + ((" Categorie: " + ", ".join(categories)) if categories else ""),
                "employment_type": j.get("employmentType") or j.get("employment_type") or "",
                "seniority": to_text(j.get("seniority")),
                "salary": salary or extract_salary(description),
                "url": j.get("applicationLink") or j.get("applyUrl") or j.get("url") or "",
                "published_at": to_iso_date(j.get("pubDate")),
            })
        total = payload.get("totalCount", 0) if isinstance(payload, dict) else 0
        offset += page_size
        if offset >= total:
            break
    return out


# --------------------------------------------------------------------------
# Arbeitnow — https://www.arbeitnow.com/api/job-board-api
# Confirmed live response shape: {data:[...]} with slug, company_name,
# title, description (HTML), remote (bool), url, tags (LIST), job_types
# (LIST, mixes contract type AND seniority e.g. ["Full-time fixed-term",
# "mid"]), location, created_at (unix seconds). No pagination metadata is
# returned; the "page" query parameter is accepted by the API.
# --------------------------------------------------------------------------
def fetch_arbeitnow(pages=2):
    out = []
    for page in range(1, pages + 1):
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        jobs = _pick_list(payload)
        if not jobs:
            break
        for j in jobs:
            description = clean_html(j.get("description", ""))
            job_types = j.get("job_types") or []
            tags = j.get("tags") or []
            location = j.get("location", "") or ("Remote" if j.get("remote") else "")
            extra_text = " ".join(job_types + tags)
            out.append({
                "source": "Arbeitnow",
                "source_id": str(j.get("slug") or j.get("id") or j.get("url") or ""),
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "location": location,
                "worldwide": guess_worldwide(location, description + " " + extra_text) if j.get("remote") else False,
                "description": description + (" Tag: " + ", ".join(tags) if tags else ""),
                "employment_type": ", ".join(t for t in job_types if not re.search(r"^(junior|mid|senior|lead|entry)$", t, re.I)),
                "seniority": to_text([t for t in job_types if re.search(r"junior|mid|senior|lead|entry", t, re.I)]),
                "salary": extract_salary(description),
                "url": j.get("url", ""),
                "published_at": to_iso_date(j.get("created_at")),
            })
    return out


# --------------------------------------------------------------------------
# Remotive — https://remotive.com/api/remote-jobs
# Documented response shape: {"job-count": N, "jobs": [...]}. Each job has
# id, url, title, company_name, category, tags (LIST), job_type
# ("full_time"/"contract"/"freelance"/"internship"...), publication_date,
# candidate_required_location, salary, description (HTML).
# NOTE: as of this build, automated fetch tools are blocked from previewing
# remotive.com/remotive.io by that site's robots.txt, so the live shape
# could not be re-verified inside this sandbox on this run; the connector
# below follows Remotive's public, documented schema. It degrades
# gracefully (empty list + a reported error) if the schema ever changes.
# --------------------------------------------------------------------------
def fetch_remotive(query="product"):
    r = requests.get("https://remotive.com/api/remote-jobs", params={"search": query, "limit": 100}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        description = clean_html(j.get("description", ""))
        location = j.get("candidate_required_location", "") or ""
        tags = j.get("tags") or []
        out.append({
            "source": "Remotive",
            "source_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company": j.get("company_name", ""),
            "location": location,
            "worldwide": guess_worldwide(location, description),
            "description": description + (" Tag: " + ", ".join(tags) if tags else ""),
            "employment_type": to_text(j.get("job_type", "")).replace("_", " ").title(),
            "seniority": "",
            "salary": to_text(j.get("salary", "")) or extract_salary(description),
            "url": j.get("url", ""),
            "published_at": to_iso_date(j.get("publication_date", "")),
        })
    return out


# --------------------------------------------------------------------------
# We Work Remotely — official RSS feeds.
# Confirmed live feed shape (Sept 2026): <item><title>Company: Job
# title</title><region>Anywhere in the World</region><category>...</category>
# <description>HTML</description><pubDate/><guid/><link/></item>.
# <region> is the authoritative worldwide signal - much more reliable than
# guessing from free text.
# --------------------------------------------------------------------------
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
]

EMPLOYMENT_TYPE_RX = re.compile(r"full[\s-]?time|part[\s-]?time|contract(?:or)?|freelance|internship", re.I)


def _guess_employment_type(text):
    m = EMPLOYMENT_TYPE_RX.search(text or "")
    return m.group(0).title() if m else "Full-Time"


# --------------------------------------------------------------------------
# Adzuna — https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
# OPTIONAL connector, disabled unless ADZUNA_APP_ID and ADZUNA_APP_KEY are
# set (as env vars or in a local .env file - see .env.example). Adzuna's
# documented response shape: {"results": [{title, company:{display_name},
# location:{display_name, area}, redirect_url, salary_min, salary_max,
# created, contract_type, contract_time, description, category:{label}}]}.
# NOT LIVE-TESTED in this build: no Adzuna credentials were provided. The
# connector below follows Adzuna's public documented schema and fails
# loudly with a clear "not configured" message rather than silently
# returning nothing, so the dashboard's "Avvisi connettori" panel always
# tells you exactly why Adzuna is or isn't contributing results.
# --------------------------------------------------------------------------
def adzuna_configured():
    return bool(os.environ.get("ADZUNA_APP_ID")) and bool(os.environ.get("ADZUNA_APP_KEY"))


def fetch_adzuna(query="product manager", country=None, max_days_old=30, results_per_page=50):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("non configurato: imposta ADZUNA_APP_ID e ADZUNA_APP_KEY (vedi .env.example) per attivare questa fonte opzionale")
    country = country or os.environ.get("ADZUNA_COUNTRY", "it")
    params = {
        "app_id": app_id, "app_key": app_key, "what": query,
        "max_days_old": max_days_old, "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    r = requests.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("results", []):
        description = clean_html(j.get("description", ""))
        location = ""
        loc = j.get("location") or {}
        if isinstance(loc, dict):
            location = loc.get("display_name", "")
        salary_bits = [str(j.get("salary_min") or ""), str(j.get("salary_max") or "")]
        salary = "-".join(b for b in salary_bits if b and b != "0.0").strip("-")
        company = ""
        comp = j.get("company") or {}
        if isinstance(comp, dict):
            company = comp.get("display_name", "")
        out.append({
            "source": "Adzuna",
            "source_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company": company,
            "location": location,
            "worldwide": guess_worldwide(location, description),
            "description": description,
            "employment_type": ", ".join(x for x in [j.get("contract_type", ""), j.get("contract_time", "")] if x),
            "seniority": "",
            "salary": salary,
            "url": j.get("redirect_url", ""),
            "published_at": to_iso_date(j.get("created", "")),
        })
    return out


# --------------------------------------------------------------------------
# The Muse — https://www.themuse.com/api/public/jobs
# Confirmed live response shape (WebFetch, this build): {page, page_count,
# items_per_page, total, results:[{name(title), contents(HTML description),
# publication_date, locations:[{name}], categories:[{name}], levels:[{name}],
# company:{name}, refs:{landing_page}}]}. Optional API key supported via
# THE_MUSE_API_KEY env var (raises the request quota; works without one).
# --------------------------------------------------------------------------
MUSE_CATEGORIES = ["Product Management", "Business & Strategy", "Data Science", "Marketing & PR",
                    "Software Engineering", "Project & Program Management", "Retail"]
MUSE_LEVELS = ["Entry Level", "Internship"]


def fetch_the_muse(pages=1):
    out = []
    api_key = os.environ.get("THE_MUSE_API_KEY")
    for page in range(1, pages + 1):
        params = [("page", page)] + [("category", c) for c in MUSE_CATEGORIES] + [("level", l) for l in MUSE_LEVELS]
        if api_key:
            params.append(("api_key", api_key))
        r = requests.get("https://www.themuse.com/api/public/jobs", params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results", [])
        if not results:
            break
        for j in results:
            company = (j.get("company") or {}).get("name", "")
            locations = [l.get("name", "") for l in (j.get("locations") or [])]
            location = ", ".join(locations) if locations else ""
            categories = [c.get("name", "") for c in (j.get("categories") or [])]
            levels = [l.get("name", "") for l in (j.get("levels") or [])]
            description = clean_html(j.get("contents", ""))
            out.append({
                "source": "The Muse",
                "source_id": str(j.get("id", "")),
                "title": j.get("name", ""),
                "company": company,
                "location": location,
                "worldwide": guess_worldwide(location, description),
                "description": description + (f" Categoria: {', '.join(categories)}." if categories else ""),
                "employment_type": "",
                "seniority": to_text(levels),
                "salary": extract_salary(description),
                "url": (j.get("refs") or {}).get("landing_page", ""),
                "published_at": to_iso_date(j.get("publication_date", "")),
            })
        total_pages = payload.get("page_count", 1)
        if page >= total_pages:
            break
    return out


# --------------------------------------------------------------------------
# Remote OK — https://remoteok.com/api
# Confirmed live response shape (WebFetch, this build): a JSON list whose
# FIRST item is a legend/disclaimer object (no `id`), followed by job items
# with slug, id, epoch, date, company, position, tags(list), description,
# location, apply_url, salary_min, salary_max, url. Remote OK's own "region"
# text is used to decide worldwide vs region-restricted - the word "remote"
# alone is never treated as worldwide, per the project's own rule.
# --------------------------------------------------------------------------
def fetch_remoteok(tag="product"):
    r = requests.get("https://remoteok.com/api", params={"tags": tag}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    out = []
    for j in payload:
        if not isinstance(j, dict) or not j.get("id"):
            continue  # skip the legend/disclaimer item at index 0
        description = clean_html(j.get("description", ""))
        location = j.get("location", "") or ""
        tags = j.get("tags") or []
        salary_bits = [str(j.get("salary_min") or ""), str(j.get("salary_max") or "")]
        salary = "-".join(b for b in salary_bits if b and b != "0").strip("-")
        out.append({
            "source": "Remote OK",
            "source_id": str(j.get("id", "")),
            "title": j.get("position", ""),
            "company": j.get("company", ""),
            "location": location,
            # explicit=None -> falls through to text heuristics; Remote OK's
            # own "location" field is frequently just "Worldwide" or a
            # specific country, both already covered by guess_worldwide.
            "worldwide": guess_worldwide(location, description + " " + " ".join(tags)),
            "description": description + (" Tag: " + ", ".join(tags) if tags else ""),
            "employment_type": "",
            "seniority": "",
            "salary": salary,
            "url": j.get("apply_url") or j.get("url", ""),
            "published_at": to_iso_date(j.get("epoch", "")),
        })
    return out


# --------------------------------------------------------------------------
# Jooble — https://jooble.org/api/{key} (POST), OPTIONAL, separate keys for
# Italy and Switzerland (JOOBLE_API_KEY_IT / JOOBLE_API_KEY_CH env vars).
# Documented response shape: {"totalCount": N, "jobs": [{title, location,
# snippet, salary, source, type, link, updated, company}]}. Free tier has a
# limited daily quota, so results are cached by app.py's st.cache_data and
# this connector can be disabled entirely via the sources multiselect.
# NOT LIVE-TESTED in this build: no Jooble credentials were provided.
# --------------------------------------------------------------------------
def jooble_configured(market="it"):
    key = "JOOBLE_API_KEY_IT" if market == "it" else "JOOBLE_API_KEY_CH"
    return bool(os.environ.get(key))


def fetch_jooble(query="product manager", market="it"):
    key_env = "JOOBLE_API_KEY_IT" if market == "it" else "JOOBLE_API_KEY_CH"
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(f"non configurato: imposta {key_env} (vedi .env.example) per attivare Jooble {market.upper()} - quota gratuita limitata, usare con parsimonia")
    location = "Italy" if market == "it" else "Switzerland"
    body = {"keywords": query, "location": location}
    r = requests.post(f"https://jooble.org/api/{api_key}", json=body, headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    out = []
    for j in payload.get("jobs", []):
        description = clean_html(j.get("snippet", ""))
        location_text = j.get("location", "")
        out.append({
            "source": f"Jooble ({market.upper()})",
            "source_id": str(j.get("id") or j.get("link", "")),
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "location": location_text,
            "worldwide": guess_worldwide(location_text, description),
            "description": description,
            "employment_type": j.get("type", ""),
            "seniority": "",
            "salary": to_text(j.get("salary", "")),
            "url": j.get("link", ""),
            "published_at": to_iso_date(j.get("updated", "")),
        })
    remaining_quota = r.headers.get("X-RateLimit-Remaining")  # not guaranteed by Jooble; shown only if present
    if remaining_quota:
        out_meta = {"_quota_remaining": remaining_quota}
        if out:
            out[0]["_jooble_quota_remaining"] = remaining_quota
    return out


def fetch_wwr():
    out = []
    for url in WWR_FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries:
            description = clean_html(e.get("summary") or e.get("description") or "")
            title = e.get("title", "")
            company = ""
            if ":" in title:
                company, title = (part.strip() for part in title.split(":", 1))
            region = e.get("region", "") or ""
            location = region or "Remote"
            if region:
                explicit_worldwide = "anywhere in the world" in region.lower()
            else:
                explicit_worldwide = None
            out.append({
                "source": "We Work Remotely",
                "source_id": e.get("id") or e.get("guid") or e.get("link", ""),
                "title": title,
                "company": company,
                "location": location,
                "worldwide": guess_worldwide(location, description, explicit=explicit_worldwide),
                "description": description,
                "employment_type": _guess_employment_type(e.get("category", "") + " " + description[:400]),
                "seniority": "",
                "salary": extract_salary(description),
                "url": e.get("link", ""),
                "published_at": e.get("published", ""),
            })
    return out
