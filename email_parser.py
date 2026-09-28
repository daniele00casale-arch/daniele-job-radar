"""
LinkedIn / Indeed job-alert email parser (spec sections 7-9).

CRITICAL RULE FROM THE SPEC: never import a whole alert email as one
generic vacancy record. Each email normally contains several individual
job postings; this module tries to split them apart into one record per
job. This is inherently heuristic - LinkedIn and Indeed do not publish a
stable schema for their alert emails and change the HTML periodically -
so when the heuristics find fewer than 2 plausible per-job links, this
returns the honest fallback message instead of guessing:
    "Unable to extract individual jobs from this LinkedIn alert format."
    "Unable to extract individual jobs from this Indeed alert format."
NOT LIVE-TESTED against a real inbox in this build (see
GMAIL_OAUTH_SETUP.md / test_report.md) - only against a handwritten sample
.eml fixture with a realistic multi-job structure. Treat the parsing
accuracy as unverified until you run it against your own real alert email.
"""
import email
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from bs4 import BeautifulSoup

LINKEDIN_JOB_LINK_RX = re.compile(r"linkedin\.com/(jobs/(view|collections)|comm/jobs)/", re.I)
INDEED_JOB_LINK_RX = re.compile(r"indeed\.com/(rc/clk|viewjob|pagead)", re.I)
TRACKING_PARAMS = {"trk", "trkEmail", "refId", "midToken", "midSig", "trackingId", "eid", "toolbar_src",
                    "utm_source", "utm_medium", "utm_campaign", "from", "recommended"}


def detect_provider(msg, text):
    frm = (msg.get("From") or "").lower()
    if "linkedin" in frm or "linkedin.com" in text.lower():
        return "LinkedIn"
    if "indeed" in frm or "indeed.com" in text.lower():
        return "Indeed"
    return "Unknown"


def strip_tracking_params(url):
    """Remove tracking query parameters without breaking the URL (spec
    section 7, item 15) - keeps job-identifying parameters intact."""
    try:
        parts = urlparse(url)
        q = [(k, v) for k, v in parse_qsl(parts.query) if k not in TRACKING_PARAMS]
        return urlunparse(parts._replace(query=urlencode(q)))
    except Exception:
        return url


def _extract_body(msg):
    body_html, body_text = "", ""
    if msg.is_multipart():
        for p in msg.walk():
            ctype = p.get_content_type()
            if "attachment" in str(p.get("Content-Disposition", "")):
                continue
            try:
                payload = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", errors="ignore")
            except Exception:
                continue
            if ctype == "text/html":
                body_html += payload
            elif ctype == "text/plain":
                body_text += payload
    else:
        try:
            payload = (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            payload = ""
        if msg.get_content_type() == "text/html":
            body_html = payload
        else:
            body_text = payload
    return body_html, body_text


def _nearby_text(anchor_tag, max_chars=300):
    """Grab plain text from the anchor's own text plus its parent block, as
    a best-effort source for company/location that usually sits right next
    to the job title link in these alert templates."""
    own = anchor_tag.get_text(" ", strip=True)
    parent = anchor_tag.find_parent(["td", "div", "tr", "table"])
    context = parent.get_text(" ", strip=True) if parent else own
    return own, context[:max_chars]


LOCATION_HINT_RX = re.compile(r"([A-Za-zÀ-ÿ\.\s]+,\s*[A-Za-zÀ-ÿ\.\s]+(?:\([A-Za-z]+\))?)")


def _split_title_company(anchor_text, context_text):
    title = anchor_text.strip()
    company, location = "", ""
    # Common template pattern: "<title>\n<company>\n<location>" collapses
    # into one whitespace-joined string; try to peel company/location off
    # the tail of the surrounding block text after the title.
    tail = context_text.replace(title, "", 1).strip(" -|·•")
    bits = [b.strip() for b in re.split(r"[•|·\n]| - ", tail) if b.strip()]
    if bits:
        company = bits[0][:120]
    if len(bits) > 1:
        location = bits[1][:120]
    return title, company, location


def parse_eml_bytes(raw, source="Email alert"):
    """Returns a LIST of job dicts (possibly empty), one per vacancy found -
    never a single record standing in for the whole email. On failure to
    split, returns a single-item list carrying the honest fallback message
    in `description` and `parsing_failed=True` so app.py can route it to
    the Parsing Failures section instead of pretending it's a real job."""
    msg = email.message_from_bytes(raw)
    body_html, body_text = _extract_body(msg)
    soup = BeautifulSoup(body_html or f"<pre>{body_text}</pre>", "html.parser")
    full_text = soup.get_text(" ", strip=True)
    provider = detect_provider(msg, full_text + " " + (msg.get("Subject") or ""))
    message_id = msg.get("Message-ID", msg.get("Date", ""))
    published_at = msg.get("Date", "")

    link_rx = LINKEDIN_JOB_LINK_RX if provider == "LinkedIn" else INDEED_JOB_LINK_RX if provider == "Indeed" else None
    jobs = []
    if link_rx:
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not link_rx.search(href):
                continue
            clean_url = strip_tracking_params(href)
            if clean_url in seen_urls:
                continue
            anchor_text = a.get_text(" ", strip=True)
            if not anchor_text or len(anchor_text) < 3:
                continue  # tracking pixels / icon links with no title text
            seen_urls.add(clean_url)
            _, context = _nearby_text(a)
            title, company, location = _split_title_company(anchor_text, context)
            jobs.append({
                "source": provider, "source_id": f"{message_id}:{clean_url}", "gmail_message_id": message_id,
                "title": title, "company": company or "n/d (verificare annuncio originale)",
                "location": location, "description": context, "employment_type": "", "seniority": "",
                "salary": "", "url": clean_url, "published_at": published_at,
                "worldwide": bool(re.search(r"worldwide|anywhere in the world|work from anywhere|remote", context, re.I)),
            })

    if len(jobs) >= 2:
        return jobs

    # Fewer than 2 distinguishable per-job links -> don't guess. Return the
    # spec's exact honest fallback message as a non-job diagnostic record.
    fallback_text = (f"Unable to extract individual jobs from this {provider} alert format."
                      if provider in ("LinkedIn", "Indeed") else
                      "Unable to extract individual jobs from this alert format (unrecognised sender).")
    return [{
        "source": source, "source_id": message_id, "gmail_message_id": message_id, "parsing_failed": True,
        "title": msg.get("Subject", "Job alert"), "company": "", "location": "", "description": fallback_text,
        "employment_type": "", "seniority": "", "salary": "", "url": "", "published_at": published_at, "worldwide": False,
    }]
