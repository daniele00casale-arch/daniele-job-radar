"""
Company-career / ATS connectors for Daniele Job Radar (spec section 5).

Each watchlist company is configured in `config.yaml` under
`ats_directory: {CompanyName: {ats: greenhouse|lever|ashby|workable|
smartrecruiters|workday|teamtailor|recruitee, board_token/site_id/tenant: ...}}`.

Three ATS types have a verified-live, official public read-only endpoint and
are implemented for real below: Greenhouse, Lever, Ashby. Each was confirmed
reachable in this build via a live schema check (see connector_test_report.md)
against real companies (Canonical and GitLab on Greenhouse's public Job
Board API, Camunda on Ashby's public Job Postings API).

The other five ATS types (Workable, SmartRecruiters, Workday, Teamtailor,
Recruitee) do NOT have a universal, unauthenticated, cross-company public
endpoint that can be queried without per-company setup that could not be
verified for any specific watchlist company in this build. Per the
project's own rule ("do not silently return zero jobs" and "do not claim an
unsupported connector works"), each of these returns a clear STATUS object
instead of pretending to fetch anything - see `fetch_unsupported_ats()`.
Wire up a real one yourself by filling in the company's actual public
career-site JSON endpoint (documented per-vendor below) and it will start
returning real jobs the same way Greenhouse/Lever/Ashby do.

Every function returns the SAME normalised job dict shape used throughout
this project (see connectors.py's module docstring) so scoring.py needs no
changes to consume ATS-sourced jobs.
"""
import requests
from bs4 import BeautifulSoup

from connectors import UA, TIMEOUT, clean_html, to_text, to_iso_date, extract_salary, guess_worldwide

UNSUPPORTED_ATS = {"workable", "smartrecruiters", "workday", "teamtailor", "recruitee", "unconfigured"}

VENDOR_NOTES = {
    "unconfigured": "no board token/site id has been verified for this company yet - see "
                     "COMPANY_WATCHLIST_SETUP.md for how to find and add one.",
    "workable": "Workable public career pages are per-company HTML/JSON with no single documented "
                "cross-company read API confirmed for this build. Use only a company's own public "
                "career endpoint if you find one (usually apply.workable.com/api/v1/widget/accounts/<slug>).",
    "smartrecruiters": "SmartRecruiters exposes a public Posting API only for companies that have opted "
                        "in (https://api.smartrecruiters.com/v1/companies/<company_id>/postings) - "
                        "no company_id was verified for any watchlist company in this build.",
    "workday": "Workday career sites are tenant-specific (https://<tenant>.wd1.myworkdayjobs.com/wday/cxs/"
               "<tenant>/<site>/jobs) and change format per deployment; none was verified working in this "
               "build without browser automation, which this project explicitly does not use.",
    "teamtailor": "Teamtailor's public career-page JSON endpoint is per-company "
                  "(https://<company>.teamtailor.com/jobs.json in some deployments, not all) - not "
                  "verified for any watchlist company in this build.",
    "recruitee": "Recruitee's public careers API is per-company (https://<company>.recruitee.com/api/"
                 "offers/) - not verified for any watchlist company in this build.",
}


def fetch_unsupported_ats(company, ats):
    """Never silently returns zero jobs: raises with the exact, honest
    status the spec requires so the Connector Status dashboard can show
    'UNSUPPORTED OR REQUIRES MANUAL CONFIGURATION' (or the Workday-specific
    wording) with the real reason, per company."""
    label = "PUBLIC WORKDAY CONNECTOR UNAVAILABLE" if ats == "workday" else "UNSUPPORTED OR REQUIRES MANUAL CONFIGURATION"
    raise RuntimeError(f"{label} — {company} ({ats}): {VENDOR_NOTES.get(ats, 'no verified public endpoint')}")


# --------------------------------------------------------------------------
# Greenhouse — public Job Board API, no auth for GET.
# Confirmed live shape: {jobs:[{id, title, absolute_url, location:{name},
# departments:[{name}], updated_at, content(HTML), company_name}]}.
# --------------------------------------------------------------------------
def fetch_greenhouse(board_token, company_label=None):
    r = requests.get(f"https://api.greenhouse.io/v1/boards/{board_token}/jobs", params={"content": "true"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        description = clean_html(j.get("content", ""))
        location = (j.get("location") or {}).get("name", "")
        departments = [d.get("name", "") for d in (j.get("departments") or [])]
        out.append({
            "source": f"Greenhouse ({company_label or board_token})",
            "source_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company": company_label or j.get("company_name") or board_token,
            "location": location,
            "worldwide": guess_worldwide(location, description),
            "description": description + (f" Dipartimento: {', '.join(departments)}." if departments else ""),
            "employment_type": "",
            "seniority": "",
            "salary": extract_salary(description),
            "url": j.get("absolute_url", ""),
            "published_at": to_iso_date(j.get("updated_at", "")),
        })
    return out


# --------------------------------------------------------------------------
# Lever — official public Postings API, global instance (api.lever.co) or
# EU instance (api.eu.lever.co) depending on the company's configuration.
# Confirmed live shape: a JSON list of {text(title), categories:{team,
# location, commitment, allLocations}, workplaceType, hostedUrl, applyUrl,
# createdAt(unix ms), descriptionPlain, country}.
# --------------------------------------------------------------------------
def fetch_lever(site_id, company_label=None, eu=False):
    base = "https://api.eu.lever.co" if eu else "https://api.lever.co"
    r = requests.get(f"{base}/v0/postings/{site_id}", params={"mode": "json"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json():
        categories = j.get("categories") or {}
        location = categories.get("location", "") or ""
        description = clean_html(j.get("descriptionPlain") or j.get("description", ""))
        workplace_type = j.get("workplaceType", "")
        worldwide = True if workplace_type == "remote" and not location else guess_worldwide(location, description)
        out.append({
            "source": f"Lever ({company_label or site_id})",
            "source_id": str(j.get("id", "")),
            "title": j.get("text", ""),
            "company": company_label or site_id,
            "location": location or workplace_type,
            "worldwide": worldwide,
            "description": description,
            "employment_type": categories.get("commitment", ""),
            "seniority": "",
            "salary": extract_salary(description),
            "url": j.get("hostedUrl") or j.get("applyUrl", ""),
            "published_at": to_iso_date(j.get("createdAt")),
        })
    return out


# --------------------------------------------------------------------------
# Ashby — official public Job Postings API.
# Confirmed live shape: {jobs:[{id, title, department, team, employmentType,
# location, secondaryLocations, publishedAt, isListed, isRemote,
# workplaceType, jobUrl, applyUrl, descriptionPlain}]}.
# --------------------------------------------------------------------------
def fetch_ashby(job_board_name, company_label=None):
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{job_board_name}",
                      params={"includeCompensation": "true"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        description = clean_html(j.get("descriptionPlain") or j.get("descriptionHtml", ""))
        location = j.get("location", "") or ""
        is_remote = bool(j.get("isRemote"))
        worldwide = True if (is_remote and not location) else guess_worldwide(location, description)
        out.append({
            "source": f"Ashby ({company_label or job_board_name})",
            "source_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company": company_label or job_board_name,
            "location": location or j.get("workplaceType", ""),
            "worldwide": worldwide,
            "description": description,
            "employment_type": j.get("employmentType", ""),
            "seniority": "",
            "salary": extract_salary(description),
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "published_at": to_iso_date(j.get("publishedAt", "")),
        })
    return out


def fetch_for_directory_entry(company, entry):
    """Dispatch a single ats_directory entry (from config.yaml) to the right
    fetcher. Returns (jobs_list, status_dict). Never raises past this point
    - callers get a structured status either way, per the Connector Status
    dashboard's requirement to distinguish success/zero/failed/unsupported."""
    ats = (entry or {}).get("ats", "").lower()
    try:
        if ats == "greenhouse":
            jobs = fetch_greenhouse(entry["board_token"], company_label=company)
        elif ats == "lever":
            jobs = fetch_lever(entry["site_id"], company_label=company, eu=entry.get("eu", False))
        elif ats == "ashby":
            jobs = fetch_ashby(entry["job_board_name"], company_label=company)
        elif ats in UNSUPPORTED_ATS:
            fetch_unsupported_ats(company, ats)
        else:
            raise RuntimeError(f"{company}: ATS '{ats}' non riconosciuto o non configurato in ats_directory")
        return jobs, {"company": company, "ats": ats, "status": "ok", "jobs_retrieved": len(jobs), "error": None}
    except Exception as e:
        return [], {"company": company, "ats": ats, "status": "failed_or_unsupported", "jobs_retrieved": 0, "error": str(e)}
