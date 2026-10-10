"""
Daniele's own Diamond / Gold / Silver rules (October 2026), applied on top of
scoring.assess(). scoring.py still does the hard filters (unpaid, senior
titles, title gate, country restrictions) and the compatibility score; this
module only decides which of the three tiers a job belongs to and prepares
what the carousel card shows (flag, full/part-time, yearly pay, sector image).

  💎 Diamond  full remote (anywhere / Europe / Italy) paying more than 30,000 a year
              OR Canton Ticino paying more than CHF 45,000 a year
  🥇 Gold     part-time paying more than 28,000 a year, in Italy, Canton Ticino
              or full remote (anywhere / Europe / Italy)
  🥈 Silver   any role at a watchlist company (PagoPA, Satispay, ...)
  📋 Other    everything else that passed the filters

Pay is never invented: a job without a readable salary can only be Silver or
Other. A salary range is compared using its midpoint. Monthly pay is x12;
hourly pay is annualised only when the weekly hours are stated. Currency
conversion is a rough fixed approximation, not live FX.
"""
import hashlib
import json
import os
import re

FX_TO_EUR = {"EUR": 1.0, "CHF": 1.06, "GBP": 1.15, "USD": 0.90}
DIAMOND_REMOTE_MIN_EUR = 30000
DIAMOND_TICINO_MIN_CHF = 45000
GOLD_PART_TIME_MIN_EUR = 28000

TIER_META = {
    "DIAMOND": ("💎 Diamond", "t-diamond"),
    "GOLD": ("🥇 Gold", "t-gold"),
    "SILVER": ("🥈 Silver", "t-silver"),
    "OTHER": ("📋 Altre", "t-other"),
}
TIER_ORDER = ["DIAMOND", "GOLD", "SILVER", "OTHER"]

# ---------------------------------------------------------------------------
# salary -> yearly amount
# ---------------------------------------------------------------------------
_NUM = r"(\d{1,3}(?:[.,'’ ]\d{3})+|\d+(?:[.,]\d{1,2})?)\s?(k|K|mila)?"
_CUR = r"(€|eur(?:o|os)?\b|chf\b|fr\.|sfr\.?|usd\b|us\$|\$|£|gbp\b)"
_SEP = r"\s?(?:-|–|—|to|a|bis|fino a)\s?"
_RX_CUR_FIRST = re.compile(_CUR + r"\s?" + _NUM + r"(?:" + _SEP + _CUR + r"?\s?" + _NUM + r")?", re.I)
_RX_CUR_AFTER = re.compile(_NUM + r"(?:\s?" + _CUR + r")?(?:" + _SEP + _NUM + r")?\s?" + _CUR, re.I)
_RX_KEYWORD = re.compile(r"(?:\bral\b|salary|stipendio|retribuzione|compenso|gehalt|lohn|lordo|gross)\D{0,20}?"
                         + _NUM + r"(?:" + _SEP + _NUM + r")?", re.I)
_PERIOD_MONTH = re.compile(r"(?:/|per|al|a|pro)\s?(?:month|mese|monat|mois)|mensil|monthly|monatlich|\bmo\b", re.I)
_PERIOD_HOUR = re.compile(r"(?:/|per|all'|a|pro)\s?(?:hour|ora|stunde|heure|h)\b|hourly|oraria|stündlich", re.I)
_HOURS_WEEK = re.compile(r"(\d{1,2})\s*(?:-\s*\d{1,2}\s*)?(?:hours?|ore|h|stunden)\s*(?:per|/|a|alla|pro)?\s*(?:week|settimana|woche)", re.I)
_CUR_CODE = {"€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "chf": "CHF", "fr.": "CHF", "sfr": "CHF",
             "sfr.": "CHF", "usd": "USD", "us$": "USD", "$": "USD", "£": "GBP", "gbp": "GBP"}


def _num(s, k):
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}(?:[.,'’ ]\d{3})+", s):
        v = float(re.sub(r"[.,'’ ]", "", s))
    else:
        v = float(s.replace(",", "."))
    if k:
        v *= 1000
    return v


def _cur(s):
    return _CUR_CODE.get((s or "").lower().strip(), None)


_NOT_SALARY = re.compile(r"bonus|budget|allowance|equipment|learning|training|customers|clients|users|funding|raised|"
                         r"revenue|\barr\b|valuation|series [a-d]|welfare|buoni|ticket|relocation|signing", re.I)


_SALARY_WORD = re.compile(r"\bral\b|salary|stipendio|retribuzione|compenso|gehalt|lohn|pay range|compensation", re.I)


def _range(n1, k1, n2, k2):
    lo = _num(n1, k1 or (k2 if n2 and _num(n1, None) < 1000 else None))
    hi = _num(n2, k2 or k1) if n2 else lo
    return lo, hi


def _candidates(text):
    """Yield (low, high, currency, end_index) for every salary-looking match."""
    found = []
    for m in _RX_CUR_FIRST.finditer(text):
        c1, n1, k1, c2, n2, k2 = m.groups()
        found.append((*_range(n1, k1, n2, k2), _cur(c1) or _cur(c2), m))
    for m in _RX_CUR_AFTER.finditer(text):
        n1, k1, c1, n2, k2, c2 = m.groups()
        found.append((*_range(n1, k1, n2, k2), _cur(c2) or _cur(c1), m))
    for m in _RX_KEYWORD.finditer(text):
        n1, k1, n2, k2 = m.groups()
        found.append((*_range(n1, k1, n2, k2), None, m))
    for lo, hi, cur, m in found:
        before = text[max(0, m.start() - 20):m.start()]
        around = text[max(0, m.start() - 30):m.end() + 30]
        if _NOT_SALARY.search(around) and not _SALARY_WORD.search(before):
            continue
        yield lo, hi, cur, m.end()


def annual_pay(text, default_currency="EUR"):
    """Best readable yearly pay in `text`. Returns dict(low, high, mid, currency,
    mid_eur, period, display) or None. Never guesses a number that isn't there."""
    if not text:
        return None
    best = None
    for lo, hi, cur, end in _candidates(text):
        if not lo:
            continue
        if hi and hi < lo:
            lo, hi = hi, lo
        tail = text[end:end + 30]
        period = "year"
        if _PERIOD_HOUR.search(tail):
            period = "hour"
        elif _PERIOD_MONTH.search(tail):
            period = "month"
        elif hi < 12000:
            continue  # small figure with no stated period: too ambiguous to be a yearly salary
        mult = 1
        if period == "month":
            mult = 12
        elif period == "hour":
            hw = _HOURS_WEEK.search(text)
            if not hw:
                continue  # hourly rate without guaranteed hours: not annualised
            mult = int(hw.group(1)) * 52
        y_lo, y_hi = lo * mult, (hi or lo) * mult
        if not (6000 <= y_hi <= 500000):
            continue
        cur = cur or default_currency
        mid = (y_lo + y_hi) / 2
        cand = {"low": y_lo, "high": y_hi, "mid": mid, "currency": cur, "period": period,
                "mid_eur": mid * FX_TO_EUR.get(cur, 1.0)}
        # prefer explicit currency + yearly figures, then the first one found
        rank = (cur is not None, period == "year")
        if best is None or rank > best[0]:
            best = (rank, cand)
    if not best:
        return None
    c = best[1]
    c["display"] = format_pay(c)
    return c


def format_pay(c):
    def k(v):
        return f"{v / 1000:.0f}k" if v >= 10000 else f"{v:,.0f}".replace(",", ".")
    rng = k(c["low"]) if abs(c["high"] - c["low"]) < 1 else f"{k(c['low'])}–{k(c['high'])}"
    note = {"month": " (da mensile)", "hour": " (da orario)"}.get(c["period"], "")
    return f"{c['currency']} {rng}/anno{note}"


# ---------------------------------------------------------------------------
# full-time / part-time, full remote
# ---------------------------------------------------------------------------
_PART_RX = re.compile(r"part[\s-]?time|teilzeit|tempo parziale|temps partiel|mezza giornata|"
                      r"(?:workload|pensum|grado di occupazione|tasso di occupazione|arbeitspensum)\s*:?\s*[1-6]0\s?%", re.I)
_FULL_RX = re.compile(r"full[\s-]?time|tempo pieno|vollzeit|temps plein|"
                      r"(?:workload|pensum|grado di occupazione|tasso di occupazione|arbeitspensum)\s*:?\s*(?:[89]0|100)\s?%", re.I)
_TITLE_PCT = re.compile(r"(\d{2,3})\s?%(?:\s?[-–]\s?(\d{2,3})\s?%)?(?!\s*remot)")
_HYBRID_RX = re.compile(r"hybrid|ibrid|in office \d|days? (?:a week |per week )?in (?:the )?office|giorni in (?:ufficio|sede)|"
                        r"in presenza|on[\s-]?site|onsite|in sede|vor ort", re.I)


def employment(job, text):
    et = (job.get("employment_type") or "").lower()
    if "part" in et or "teilzeit" in et:
        return "Part-time"
    if "full" in et or "vollzeit" in et:
        return "Full-time"
    m = _TITLE_PCT.search(job.get("title") or "")
    if m:
        top = int(m.group(2) or m.group(1))
        return "Part-time" if top <= 70 else "Full-time"
    part, full = bool(_PART_RX.search(text)), bool(_FULL_RX.search(text))
    if part and full:
        return "Full-time / Part-time"
    if part:
        return "Part-time"
    if full:
        return "Full-time"
    return None


def is_full_remote(geo, text):
    return "remote" in (geo or {}).get("where", set()) and not _HYBRID_RX.search(text or "")


# ---------------------------------------------------------------------------
# sector -> Unsplash image (images chosen once and stored in sector_images.json)
# ---------------------------------------------------------------------------
COMPANY_SECTOR = {
    "satispay": "fintech", "revolut": "fintech", "scalapay": "fintech", "nexi": "fintech", "edenred": "fintech",
    "pagopa": "public_sector", "bmw": "automotive", "ferrari": "automotive", "stellantis": "automotive",
    "pirelli": "automotive", "prometeon": "automotive", "lastminute": "travel", "booking": "travel",
    "medacta": "healthcare", "amplifon": "healthcare", "ferring": "healthcare", "ibsa": "healthcare",
    "gi life sciences": "healthcare", "sentinel diagnostics": "healthcare", "1000farmacie": "healthcare",
    "vf corporation": "fashion", "kering": "fashion", "damiani": "fashion", "prada": "fashion", "armani": "fashion",
    "launchmetrics": "fashion", "prima": "insurance", "generali": "insurance", "allianz": "insurance", "axa": "insurance",
    "thefork": "food", "glovo": "food", "deliveroo": "food", "ion": "finance", "ubs": "finance", "unicredit": "finance",
    "intesa": "finance", "yougov": "marketing", "canonical": "software", "gitlab": "software", "automattic": "software",
    "camunda": "software", "storyblok": "software", "sysdig": "software", "remote": "software", "jet hr": "software",
    "bending spoons": "software", "hyland": "software", "360dialog": "telecom", "swisscom": "telecom",
    "vodafone": "telecom", "tim": "telecom", "shippypro": "logistics", "dsv": "logistics", "product people": "consulting",
    "deloitte": "consulting", "accenture": "consulting", "pwc": "consulting", "kpmg": "consulting", "ey": "consulting",
    "endress": "industrial", "abb": "industrial", "te connectivity": "industrial", "liebherr": "industrial",
    "hitachi energy": "energy", "switcho": "energy", "enel": "energy", "a2a": "energy", "dazn": "media_entertainment",
    "amazon": "ecommerce", "zalando": "ecommerce", "datapizza": "ai_data",
}
SECTOR_KEYWORDS = [
    ("fintech", ["payment", "payments", "fintech", "wallet", "pagamenti", "bnpl", "neobank", "banking app"]),
    ("insurance", ["insurance", "insurtech", "assicura", "versicherung", "polizza"]),
    ("automotive", ["automotive", "vehicle", "vehicles", "veicoli", "car dealer", "cars", "motor"]),
    ("mobility", ["mobility", "mobilità", "transport", "trasporti"]),
    ("healthcare", ["health", "healthcare", "medical", "pharma", "pharmaceutical", "medtech", "clinical", "hospital",
                    "salute", "farmaci", "biotech", "life sciences"]),
    ("ai_data", ["artificial intelligence", "machine learning", "llm", "genai", "generative ai", "data platform"]),
    ("software", ["saas", "software", "cloud", "platform", "b2b", "developer tools"]),
    ("ecommerce", ["e-commerce", "ecommerce", "marketplace", "online shop"]),
    ("retail", ["retail", "store", "stores", "grocery", "supermarket", "gdo"]),
    ("fashion", ["fashion", "luxury", "apparel", "moda", "beauty", "cosmetic", "cosmetics", "jewellery", "jewelry"]),
    ("travel", ["travel", "hotel", "hospitality", "tourism", "airline", "viaggi", "turismo"]),
    ("food", ["food", "restaurant", "restaurants", "delivery", "ristorazione", "beverage"]),
    ("energy", ["energy", "solar", "renewable", "renewables", "utility", "energia", "power grid"]),
    ("industrial", ["manufacturing", "industrial", "machinery", "factory", "automation", "engines", "industriale"]),
    ("consulting", ["consulting", "consultancy", "advisory", "consulenza"]),
    ("finance", ["bank", "banking", "investment", "asset management", "trading", "wealth", "finanza", "banca"]),
    ("marketing", ["marketing", "advertising", "agency", "brand", "media buying"]),
    ("logistics", ["logistics", "shipping", "supply chain", "freight", "warehouse", "spedizioni"]),
    ("telecom", ["telecom", "telco", "5g", "connectivity", "telecomunicazioni"]),
    ("real_estate", ["real estate", "property", "immobiliare", "proptech"]),
    ("education", ["education", "edtech", "learning", "university", "formazione"]),
    ("media_entertainment", ["media", "entertainment", "streaming", "gaming", "music", "sport"]),
    ("public_sector", ["public sector", "government", "pubblica amministrazione", "citizens", "cittadini"]),
]
_SECTOR_RX = [(s, re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")\b", re.I)) for s, kws in SECTOR_KEYWORDS]

_IMAGES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_images.json")
try:
    with open(_IMAGES_PATH, encoding="utf-8") as _f:
        SECTOR_IMAGES = {k: v for k, v in json.load(_f).items() if not k.startswith("_")}
except Exception:
    SECTOR_IMAGES = {}


def sector_of(job):
    company = (job.get("company") or "").lower()
    for name, sec in COMPANY_SECTOR.items():
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", company):
            return sec
    text = " ".join(str(job.get(k) or "") for k in ("title", "company", "description"))[:3000]
    best, best_n = "generic", 0
    for sec, rx in _SECTOR_RX:
        n = len(rx.findall(text))
        if n > best_n:
            best, best_n = sec, n
    return best


def image_for(job, sector):
    pool = SECTOR_IMAGES.get(sector) or SECTOR_IMAGES.get("generic") or []
    if not pool:
        return None
    key = (job.get("company") or job.get("title") or "").lower().encode("utf-8")
    return pool[int(hashlib.md5(key).hexdigest(), 16) % len(pool)]


# ---------------------------------------------------------------------------
# the tier decision
# ---------------------------------------------------------------------------
def is_watchlisted(company, watchlist):
    c = (company or "").lower()
    return any(re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", c) for w in watchlist or [])


def classify(job, geo, watchlist):
    """Return the card info dict: tier, pay, employment, full_remote, flag, sector, image, watchlisted, why."""
    text = " ".join(str(job.get(k) or "") for k in ("title", "description", "summary", "employment_type"))
    where = (geo or {}).get("where", set())
    default_cur = "CHF" if "ch" in where else "EUR"
    pay = annual_pay(job.get("salary") or "", default_cur) or annual_pay(text, default_cur)
    emp = employment(job, text)
    full_remote = is_full_remote(geo, text)
    watch = is_watchlisted(job.get("company"), watchlist)
    in_ticino = "ch" in where
    in_italy = "it" in where

    tier, why = None, ""
    if pay:
        eur = pay["mid_eur"]
        chf = eur / FX_TO_EUR["CHF"]
        if full_remote and eur > DIAMOND_REMOTE_MIN_EUR:
            tier, why = "DIAMOND", f"Full remote, ~{eur / 1000:.0f}k EUR/anno (> 30k)"
        elif in_ticino and chf > DIAMOND_TICINO_MIN_CHF:
            tier, why = "DIAMOND", f"Canton Ticino, ~{chf / 1000:.0f}k CHF/anno (> 45k)"
        elif emp and "Part-time" in emp and eur > GOLD_PART_TIME_MIN_EUR and (in_italy or in_ticino or full_remote):
            tier, why = "GOLD", f"Part-time, ~{eur / 1000:.0f}k EUR/anno (> 28k)"
    if tier is None and watch:
        tier, why = "SILVER", "Azienda nella tua watchlist"
    if tier is None:
        tier = "OTHER"

    if full_remote or ("remote" in where and not (in_italy or in_ticino)):
        flag, place = "🌏", "Remoto"
    elif in_ticino:
        flag, place = "🇨🇭", "Ticino"
    elif in_italy:
        flag, place = "🇮🇹", "Italia"
    else:
        flag, place = "🌏", "Da verificare"

    sector = sector_of(job)
    return {"tier": tier, "why": why, "pay": pay, "employment": emp, "full_remote": full_remote,
            "flag": flag, "place": place, "sector": sector, "image": image_for(job, sector),
            "watchlisted": watch}
