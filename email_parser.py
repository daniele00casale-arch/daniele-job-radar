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

# "Company" job-alert emails (spec: a third Gmail label, JOB-ALERTS/Company,
# for job-board/ATS/company-careers-page alert emails that aren't LinkedIn
# or Indeed - e.g. a Greenhouse/Lever "new jobs matching your search" digest,
# or a company's own careers-page subscription). There is no single fixed
# template to match against like the two providers above, so this uses a
# generic heuristic instead: any link that isn't obviously navigation/legal/
# social, with distinct-enough anchor text, counted as one candidate job
# link per unique URL. Still never guesses when it can't tell jobs apart -
# same <2-distinct-links-found fallback rule as the other two providers.
COMPANY_GENERIC_LINK_EXCLUDE_RX = re.compile(
    r"(unsubscribe|preferences|privacy|terms|cookie|manage.?(alert|subscription)|"
    r"linkedin\.com/(company|in|school)/|twitter\.com|x\.com|facebook\.com|instagram\.com|"
    r"youtube\.com|mailto:|\.png$|\.jpg$|\.gif$)",
    re.I,
)


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


def parse_eml_bytes(raw, source="Email alert", forced_provider=None):
    """Returns a LIST of job dicts (possibly empty), one per vacancy found -
    never a single record standing in for the whole email. On failure to
    split, returns a single-item list carrying the honest fallback message
    in `description` and `parsing_failed=True` so app.py can route it to
    the Parsing Failures section instead of pretending it's a real job.

    `forced_provider` lets a caller that already knows where the message
    came from (e.g. gmail_connector.py, which read it out of a specific
    Gmail label) skip the From-header sniffing below and go straight to
    the right parsing rules - used for "Company" (spec's third label),
    which sniffing can't reliably detect since it covers many different
    senders."""
    msg = email.message_from_bytes(raw)
    body_html, body_text = _extract_body(msg)
    soup = BeautifulSoup(body_html or f"<pre>{body_text}</pre>", "html.parser")
    full_text = soup.get_text(" ", strip=True)
    provider = forced_provider or detect_provider(msg, full_text + " " + (msg.get("Subject") or ""))
    message_id = msg.get("Message-ID", msg.get("Date", ""))
    published_at = msg.get("Date", "")

    jobs = []
    if provider in ("LinkedIn", "Indeed"):
        link_rx = LINKEDIN_JOB_LINK_RX if provider == "LinkedIn" else INDEED_JOB_LINK_RX
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
    elif provider == "Company":
        # Generic heuristic: every distinct http(s) link whose anchor text
        # looks like a job title (not "unsubscribe", not a social icon, at
        # least a few characters of real text) is a job-link candidate.
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue
            if COMPANY_GENERIC_LINK_EXCLUDE_RX.search(href):
                continue
            anchor_text = a.get_text(" ", strip=True)
            if not anchor_text or len(anchor_text) < 4 or len(anchor_text) > 140:
                continue
            clean_url = strip_tracking_params(href)
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            _, context = _nearby_text(a)
            title, company, location = _split_title_company(anchor_text, context)
            jobs.append({
                "source": "Company", "source_id": f"{message_id}:{clean_url}", "gmail_message_id": message_id,
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
                      if provider in ("LinkedIn", "Indeed", "Company") else
                      "Unable to extract individual jobs from this alert format (unrecognised sender).")
    return [{
        "source": source, "source_id": message_id, "gmail_message_id": message_id, "parsing_failed": True,
        "title": msg.get("Subject", "Job alert"), "company": "", "location": "", "description": fallback_text,
        "employment_type": "", "seniority": "", "salary": "", "url": "", "published_at": published_at, "worldwide": False,
    }]
