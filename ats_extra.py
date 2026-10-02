"""
Extra ATS connectors for Daniele Job Radar: Workable and Teamtailor.

Both use PUBLIC, unauthenticated feeds that companies expose for their careers pages:
  - Workable:   https://apply.workable.com/api/v1/widget/accounts/<account>?details=true  (JSON)
  - Teamtailor: https://<subdomain>.teamtailor.com/jobs.rss                              (RSS/XML)

Config (config.yaml -> ats_directory):
  360dialog:     {ats: workable,   account: 360dialog-gmbh}
  Launchmetrics: {ats: teamtailor, subdomain: launchmetrics}

Entry point `fetch_for_directory_entry(company, entry, default_fn)` keeps the same return shape as
ats_connectors.fetch_for_directory_entry -> (jobs: list[dict], status: dict(ats,status,jobs_retrieved,error)),
and delegates every other ATS (greenhouse/lever/ashby/unconfigured) to `default_fn`.
Job dicts use the same keys scoring.py reads: title, company, location, description, employment_type,
seniority, salary, url, published_at, source.
"""
import re
import html
import xml.etree.ElementTree as ET

import requests

TIMEOUT = 20
HEADERS = {"User-Agent": "DanieleJobRadar/1.0 (personal job search)"}


def _clean(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _status(ats, jobs, error=None):
    if error:
        return {"ats": ats, "status": "failed", "jobs_retrieved": 0, "error": error}
    return {"ats": ats, "status": "ok" if jobs else "ok_zero_results", "jobs_retrieved": len(jobs), "error": None}


def fetch_workable(company, account):
    url = f"https://apply.workable.com/api/v1/widget/accounts/{account}"
    r = requests.get(url, params={"details": "true"}, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data.get("jobs", []) or []:
        loc_parts = [j.get("city"), j.get("state"), j.get("country")]
        location = ", ".join(p for p in loc_parts if p)
        if j.get("telecommuting"):
            location = ("Remote - " + location) if location else "Remote"
        jobs.append({
            "title": j.get("title"), "company": company, "location": location,
            "description": _clean(j.get("description")),
            "employment_type": j.get("employment_type") or "",
            "seniority": j.get("experience") or "",
            "salary": "", "url": j.get("url") or j.get("shortlink"),
            "published_at": j.get("published_on") or j.get("created_at"),
            "source": f"{company} (workable)",
        })
    return jobs


def fetch_teamtailor(company, subdomain):
    url = f"https://{subdomain}.teamtailor.com/jobs.rss"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    jobs = []
    for item in root.iter("item"):
        def g(tag):
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        locs = []
        for el in item.iter():
            if el.tag.endswith("}locations") or el.tag == "tt:locations":
                locs.append(", ".join(t.strip() for t in el.itertext() if t and t.strip()))
        remote = g("remoteStatus")
        location = "; ".join(l for l in locs if l)
        if remote and remote.lower() not in ("none", "onsite", "on-site"):
            location = f"{remote.capitalize()} - {location}" if location else remote.capitalize()
        jobs.append({
            "title": g("title"), "company": company, "location": location,
            "description": _clean(g("description")), "employment_type": "", "seniority": "",
            "salary": "", "url": g("link"), "published_at": g("pubDate"),
            "source": f"{company} (teamtailor)",
        })
    return jobs


def fetch_for_directory_entry(company, entry, default_fn):
    ats = (entry or {}).get("ats")
    try:
        if ats == "workable":
            jobs = fetch_workable(company, entry["account"])
            return jobs, _status("workable", jobs)
        if ats == "teamtailor":
            jobs = fetch_teamtailor(company, entry["subdomain"])
            return jobs, _status("teamtailor", jobs)
    except Exception as e:  # never crash the app because one company failed
        return [], _status(ats, [], error=str(e)[:200])
    return default_fn(company, entry)
