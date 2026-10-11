"""
"📬 Processi" view: rebuilds the list of applications sent and selection
processes in progress from the confirmation / rejection / interview emails
in the connected Gmail account (read-only scope, same OAuth as the alerts).

Nothing is written to Gmail. Classification is heuristic (keywords in the
subject and snippet), so every row links to the original email.
"""
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DAYS_DEFAULT = 21

# Gmail search: application-related phrases, minus job alerts / suggestions / newsletters.
_PHRASES = [
    '"thanks for applying"', '"thank you for applying"', '"thank you for your application"',
    '"application received"', '"received your application"', '"your application"',
    '"application confirmation"', '"application submitted"', '"la tua candidatura"',
    '"candidatura ricevuta"', '"candidatura inviata"', '"grazie per la tua candidatura"',
    '"grazie per la candidatura"', '"grazie per esserti candidato"', '"conferma di registrazione"',
    '"è stata inviata"', '"è stata visualizzata"', '"next step"', '"case study"', "colloquio",
    "interview", "assessment", '"update on your application"', "candidatura",
]
_EXCLUDE_SENDERS = [
    "jobalerts-noreply@linkedin.com", "match.indeed.com", "jobalert.indeed.com",
    "newsletters-noreply@linkedin.com", "noreply@glassdoor.com", "adzuna", "messages-noreply@linkedin.com",
]


def gmail_query(days=DAYS_DEFAULT):
    inc = " OR ".join(_PHRASES)
    exc = " ".join(f"-from:{s}" for s in _EXCLUDE_SENDERS)
    return f"newer_than:{days}d ({inc}) {exc} -in:sent -in:chats"


# --- status ------------------------------------------------------------------
STATUS_ORDER = {"rejected": 4, "next_step": 3, "viewed": 2, "received": 1}
STATUS_LABEL = {"rejected": "❌ Rifiutata", "next_step": "🚀 Prossimo step", "viewed": "👀 Visualizzata",
                "received": "📨 Inviata / ricevuta"}

_REJECT = re.compile(
    r"won.?t be moving forward|not be moving forward|not moving forward|decided not to|unfortunately|"
    r"regret to inform|other candidates|not to proceed|unable to offer|position has been filled|"
    r"purtroppo|non proseguire|non procedere|non è stata selezionata|altri candidati|non siamo in grado|"
    r"we will not be|we won't be|while we (?:truly |really )?appreciate|after careful consideration|"
    r"not (?:been )?selected|have chosen|move forward with other", re.I)
_NEXT = re.compile(
    r"interview|colloquio|next step|prossimo step|prossima fase|case study|assessment|\btask\b|\btest\b|"
    r"invit|schedule|availability|disponibilit|video call|chiamata|call with|hackerrank|codility|"
    r"challenge|prova tecnica|esercizio", re.I)
_VIEWED = re.compile(r"è stata visualizzata|was viewed|viewed your application", re.I)
_RECEIVED = re.compile(
    r"received|thanks for applying|thank you for applying|thank you for your application|application is officially in|"
    r"ricevut|inviata|grazie per|registrazione|confirm", re.I)
# A "next step" that is really just the standard acknowledgement ("you may be invited to...")
_SOFT_NEXT = re.compile(r"you may be invited|may be contacted|if your profile|se il tuo profilo|"
                        r"we.ll get back|will be in touch|will review", re.I)


def classify(subject, snippet):
    text = f"{subject} {snippet}"
    if _REJECT.search(text):
        return "rejected"
    if _VIEWED.search(text):
        return "viewed"
    acknowledgement = _SOFT_NEXT.search(text) or re.search(
        r"thanks? (you )?for applying|received your application|application received|grazie per la tua candidatura", text, re.I)
    if _NEXT.search(text) and not acknowledgement:
        return "next_step"
    if _RECEIVED.search(text) or "application" in text.lower() or "candidatura" in text.lower():
        return "received"
    return None


# --- company / role extraction ----------------------------------------------
_ATS_DOMAINS = ("myworkday", "greenhouse", "lever.co", "ashbyhq", "smartrecruiters", "teamtailor", "jobvite",
                "workable", "recruitee", "personio", "successfactors", "icims", "taleo", "allibo", "inrecruiting",
                "bamboohr", "linkedin", "indeed", "gmail", "outlook", "zohorecruit", "breezy", "join.com")
_GENERIC_LOCAL = {"no-reply", "noreply", "notification", "notifications", "donotreply", "do-not-reply", "jobs",
                  "careers", "career", "talent", "recruiting", "recruitment", "hr", "selezione", "info",
                  "mail_delivery_service", "no-reply-talent", "hiring", "apply"}


def _clean(s):
    s = re.sub(r"\s+", " ", (s or "")).strip(" -–—:|.!\"'“”✉️🚀")
    return s[:80]


def _sender_parts(from_header):
    m = re.match(r'\s*"?([^"<]*)"?\s*<([^>]+)>', from_header or "")
    name, addr = (m.group(1).strip(), m.group(2).strip().lower()) if m else ("", (from_header or "").strip().lower())
    local, _, domain = addr.partition("@")
    return name, local, domain


_GENERIC_WORDS = re.compile(r"candidatura|application|conferma|thank|grazie|your |we have|we.ve|received|ricevuta|"
                            r"next step|update|daniele|annuncio|registrazione", re.I)


def _ok_company(c):
    return c and len(c.split()) <= 4 and not _GENERIC_WORDS.search(c) and c.lower() not in ("you", "the", "our", "us", "noi")


def company_from(subject, snippet, from_header):
    subj_pats = [
        r"\b(?:at|presso|to|per)\s+([A-Z][\w&.\-']*(?: [A-Z][\w&.\-']*){0,3})",
        r"^([\w&.\-']+(?: [\w&.\-']+){0,3})\s*[|:]\s",
        r"^([\w&.\-']+(?: [\w&.\-']+){0,3})\s+-\s+",
        r"inviata a ([A-Z][\w&.\-' ]{1,40}?)$",
        r"visualizzata da ([A-Z][\w&.\-' ]{1,40}?)$",
    ]
    snip_pats = [
        r"interest in ([A-Z][\w&.\-']*(?: [A-Z][\w&.\-']*){0,3})",
        r"\bat ([A-Z][\w&.\-']*(?: [A-Z][\w&.\-']*){0,3})[!.,]",
        r"\bwith ([A-Z][\w&.\-']*(?: [A-Z][\w&.\-']*){0,3})[!.,]",
    ]
    for src, pats in ((subject, subj_pats), (snippet, snip_pats)):
        for p in pats:
            m = re.search(p, src)
            if m and _ok_company(_clean(m.group(1))):
                return _clean(m.group(1))
    name, local, domain = _sender_parts(from_header)
    if name and not any(w in name.lower() for w in ("no-reply", "noreply", "notification", "do not reply", "daniele")):
        n = _clean(re.sub(r"\b(careers?|talent|recruiting|team|hr|jobs)\b", "", name, flags=re.I))
        if _ok_company(n):
            return n
    host = domain.split(".")
    if "myworkday" in domain and local not in _GENERIC_LOCAL:
        return local.upper() if len(local) <= 4 else local.capitalize()
    if any(x in domain for x in _ATS_DOMAINS):
        sub = host[0] if len(host) > 2 else ""
        if sub and sub not in ("mail", "hire", "us", "eu", "www", "careers"):
            return sub.capitalize()
        return "n/d"
    core = host[-2] if len(host) >= 2 else domain
    return core.capitalize()


_ROLE_PREFIX = re.compile(r"^.*?\b(?:applying|apply|be our next|partecipazione al|candidarti (?:per|al)|domanda (?:per|al))"
                          r"\s+(?:for |to |as )?(?:the |our |il |la |al |a )?", re.I)


def role_from(subject, snippet, company=""):
    pats = [
        r"(?:for|per|to|as|al) (?:the |our |il |la |our next )?(?:ruolo (?:di )?|posizione (?:di )?|position of )?[“\"']?([A-Z][^“\"'|!]{2,70}?)[”\"']? (?:role|position|ruolo|posizione)\b",
        r"(?:applying|apply) (?:for|to) (?:the )?([A-Z][^|!]{2,70}?)(?: with | at | position| role|[.!,]|$)",
        r"(?:application|candidatura) (?:for|as|per) (?:the |our |il |la )?([A-Z][^|!]{2,70}?)(?: role| position| at | with |[.!,]|$)",
        r"(?:ruolo|annuncio|posizione) (?:di |per )?[“\"']?([A-Z][^“\"'|!]{2,70}?)[”\"']?(?: è| presso|[.!,]|$)",
        r"Thank You for Your Application\s*[–-]\s*(.+)$",
        r"\|\s*([^|]+?)\s*[–—-]\s*Update on Your Application",
        r"next (?:Product[^.!]{0,60}?)\.",
    ]
    for src in (subject, snippet):
        for p in pats:
            for m in re.finditer(p, src, re.I):
                r = _clean(_ROLE_PREFIX.sub("", m.group(1)))
                if 2 < len(r) < 80 and not (company and r.lower().startswith(company.lower())) and not r.lower().startswith(("your ", "our ", "la tua", "this ", "applying")):
                    return r
    return ""


def parse_message(msg, account=None):
    """msg: Gmail API message resource (format='metadata'). Returns a row dict or None."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject, frm = headers.get("subject", ""), headers.get("from", "")
    snippet = (msg.get("snippet") or "").replace("&#39;", "'").replace("&amp;", "&").replace("&quot;", '"')
    status = classify(subject, snippet)
    if not status:
        return None
    try:
        when = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, timezone.utc)
    except Exception:
        try:
            when = parsedate_to_datetime(headers.get("date", ""))
        except Exception:
            when = None
    company = company_from(subject, snippet, frm)
    return {"company": company, "role": role_from(subject, snippet, company), "status": status,
            "date": when, "subject": subject, "snippet": snippet[:220], "thread_id": msg.get("threadId"),
            "link": (f"https://mail.google.com/mail/?authuser={account}#all/{msg.get('threadId')}" if account
                     else f"https://mail.google.com/mail/u/0/#all/{msg.get('threadId')}")}


def _key(r):
    c = re.sub(r"[^a-z0-9]", "", r["company"].lower())
    role = re.sub(r"[^a-z0-9]", "", (r["role"] or "").lower())[:30]
    return c, role


def merge(rows):
    """One row per (company, role): highest status wins, keep first & last email dates and all links."""
    out = {}
    for r in sorted([r for r in rows if r], key=lambda r: r["date"] or datetime.min.replace(tzinfo=timezone.utc)):
        k = _key(r)
        # same company, unknown role on one side -> merge into the existing row
        if not k[1]:
            k = next((kk for kk in out if kk[0] == k[0]), k)
        else:
            k = next((kk for kk in out if kk[0] == k[0] and kk[1] and (kk[1] in k[1] or k[1] in kk[1])), k)
            if (k[0], "") in out and k not in out:
                out[k] = out.pop((k[0], ""))
                out[k]["role"] = r["role"]
        cur = out.get(k)
        if not cur:
            out[k] = dict(r, first_date=r["date"], emails=1)
            continue
        cur["emails"] += 1
        if STATUS_ORDER[r["status"]] >= STATUS_ORDER[cur["status"]]:
            cur.update(status=r["status"], subject=r["subject"], snippet=r["snippet"], link=r["link"])
        cur["date"] = r["date"]
        cur["role"] = cur["role"] or r["role"]
    return sorted(out.values(), key=lambda r: (-STATUS_ORDER[r["status"]] if r["status"] != "rejected" else 9,
                                               -(r["date"].timestamp() if r["date"] else 0)))


def fetch_rows(service, days=DAYS_DEFAULT, max_messages=200, account=None):
    """Read-only: list matching messages and fetch only their metadata + snippet."""
    ids, token = [], None
    while len(ids) < max_messages:
        kw = dict(userId="me", q=gmail_query(days), maxResults=100)
        if token:
            kw["pageToken"] = token
        resp = service.users().messages().list(**kw).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            break
    rows = []
    for mid in ids[:max_messages]:
        msg = service.users().messages().get(userId="me", id=mid, format="metadata",
                                             metadataHeaders=["Subject", "From", "Date"]).execute()
        rows.append(parse_message(msg, account))
    return rows


def fetch_applications(service, days=DAYS_DEFAULT, max_messages=200, account=None):
    return merge(fetch_rows(service, days, max_messages, account))


def fetch_applications_multi(accounts, days=DAYS_DEFAULT, max_messages=200):
    """accounts: list of (service, email). Merges all accounts into one list (duplicates collapse)."""
    rows = []
    for service, email in accounts:
        rows += fetch_rows(service, days, max_messages, email)
    return merge(rows)
