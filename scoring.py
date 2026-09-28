"""
Priority classification (Diamond/Gold/Silver/Strategic Internship/
High-Value Part-Time), compatibility scoring, and confidence labelling for
Daniele Job Radar.

Design principle followed throughout (per the project's own rules):
hard requirements are NEVER overridden by a high compatibility score, and
nothing is ever invented - a missing fact is always labelled as missing
("Salary not disclosed", "Remote arrangement requires confirmation",
"Experience requirement not clearly stated") rather than guessed.

Single entry point used by app.py: `assess(job, cfg)` -> dict with keys
title/priority/score/band/confidence/reasons/penalties/mandatory_found/
preferred_found/experience_required/remote_scope/country_restrictions/
compensation/compensation_guaranteed/contract_type/filtered_out_reason.
"""
import re

# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def to_text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(to_text(v) for v in value if v)
    return str(value)


def norm(s):
    return re.sub(r"[^a-z0-9+%]+", " ", to_text(s).lower()).strip()


def job_text(job, fields=("title", "description", "seniority", "location", "employment_type", "salary")):
    return norm(" ".join(to_text(job.get(f, "")) for f in fields))


def raw_job_text(job, fields=("title", "description", "seniority", "location", "employment_type", "salary")):
    """Lightly-cleaned (lowercased, whitespace-collapsed) text that KEEPS
    currency symbols, digits grouping (commas/dots) and punctuation intact.
    `job_text`/`norm` strip all of that for keyword matching, which is
    exactly wrong for money/hours regexes - this is what those use."""
    blob = " ".join(to_text(job.get(f, "")) for f in fields)
    return re.sub(r"\s+", " ", blob.lower()).strip()


# --------------------------------------------------------------------------
# payment / hard exclusions (never overridden by score, for any tier)
# --------------------------------------------------------------------------
BAD_PAYMENT_TERMS = ["unpaid", "volunteer", "equity only", "equity-only", "100% equity",
                      "commission only", "commission-only", "bounty only", "token only", "token-only", "no salary"]
INTERNSHIP_TERMS = ["intern", "internship", "stage", "tirocinio", "apprenticeship", "co-op"]


def payment_check(text):
    words = set(text.split())
    hit = next((x for x in BAD_PAYMENT_TERMS if x in text), None)
    if hit:
        return False, f"esclusa: compenso non ammesso ({hit})"
    return True, ""


def is_internship(text):
    words = set(text.split())
    return any(x in words or x in text for x in INTERNSHIP_TERMS)


# --------------------------------------------------------------------------
# experience
# --------------------------------------------------------------------------
EXPERIENCE_PATTERNS = [r"(\d+)\s*\+?\s*years?", r"minimum\s+(\d+)\s+years?", r"at least\s+(\d+)\s+years?"]
NO_EXPERIENCE_RX = re.compile(r"no experience|recent graduate|new graduate|fresh graduate|0\s*[-–]\s*1\s*years?")
PREFERRED_QUALIFIERS = ["preferred", "desirable", "nice to have", "a plus", "bonus if", "ideally"]


def parse_experience(text):
    """Return (min_years:int|None, is_only_preferred:bool). is_only_preferred
    is True when the only experience figure found sits within ~40 chars of
    a "preferred/desirable/nice to have" qualifier, meaning it is NOT a
    mandatory requirement - relevant for the Diamond/Gold "2 years allowed
    only if preferred" rule."""
    if NO_EXPERIENCE_RX.search(text):
        return 0, False
    vals = []
    for p in EXPERIENCE_PATTERNS:
        for m in re.finditer(p, text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 20)
            window = text[start:end]
            preferred = any(q in window for q in PREFERRED_QUALIFIERS)
            vals.append((int(m.group(1)), preferred))
    if not vals:
        return None, False
    vals.sort(key=lambda v: v[0])
    min_years, preferred = vals[0]
    return min_years, preferred


def experience_requirement_text(exp, preferred):
    if exp is None:
        return "Experience requirement not clearly stated"
    if preferred:
        return f"~{exp} anni (indicati come preferenziali, non obbligatori)"
    return f"~{exp} anni richiesti"


def experience_ok_for_tier(exp, preferred, max_years, max_years_if_preferred):
    if exp is None:
        return True  # unclear -> not a hard exclusion, but flagged via confidence elsewhere
    if exp <= max_years:
        return True
    if preferred and exp <= max_years_if_preferred:
        return True
    return False


# --------------------------------------------------------------------------
# worldwide / location scope
# --------------------------------------------------------------------------
def diamond_worldwide(text, cfg):
    evidence = [e.strip('"') for e in cfg["diamond"]["worldwide_evidence"]]
    exclusions = cfg["diamond"]["worldwide_exclusions"]
    if any(x in text for x in exclusions):
        return False
    return any(x in text for x in evidence)


def gold_location_ok(job_location_text, cfg):
    locs = cfg["gold"]["preferred_locations"]
    return any(loc in job_location_text for loc in locs)


def silver_remote_scope(text, cfg):
    """Returns 'italy_or_europe', 'other', or None (unclear)."""
    if any(x in text for x in ["italy", "italia"]):
        return "italy_or_europe"
    if any(x in text for x in ["europe", "european union", "eu remote", "emea"]) and "italy" not in text and "excluding italy" not in text:
        # explicit europe-wide remote with no exclusion of Italy mentioned
        if "not italy" in text or "excluding italy" in text or "except italy" in text:
            return "other"
        return "italy_or_europe"
    return None


OFFICE_DAYS_RX = re.compile(r"(\d)\s*(?:days?|giorni)\s*(?:a|per|/)\s*week", re.I)


# --------------------------------------------------------------------------
# compensation - never invented, never annualised from an unguaranteed rate
# --------------------------------------------------------------------------
SALARY_RANGE_RX = re.compile(
    r"(?P<cur>USD|EUR|CHF|GBP|\$|€|£|Fr\.?)\s?(?P<min>\d[\d,\.]{2,})\s?(?:[-–to]{1,3}\s?(?P<cur2>USD|EUR|CHF|GBP|\$|€|£|Fr\.?)?\s?(?P<max>\d[\d,\.]{2,}))?"
    r"\s?(?:/|per)?\s?(?P<period>year|yr|annum|month|hour|hr)?",
    re.I,
)
SALARY_SUFFIX_RX = re.compile(
    r"(?P<min>\d[\d,\.]{2,})\s?(?:[-–]\s?(?P<max>\d[\d,\.]{2,}))?\s?(?P<cur>USD|EUR|CHF|GBP)\b(?:\s?(?:/|per)?\s?(?P<period>year|yr|annum|month|hour|hr))?",
    re.I,
)  # matches the connectors' own structured-field format, e.g. "40000-55000 EUR"
HOURLY_RATE_RX = re.compile(r"(?P<cur>USD|EUR|CHF|GBP|\$|€|£)\s?(?P<rate>\d[\d,\.]{0,6})\s?(?:/|per)\s?(?:hour|hr)", re.I)
GUARANTEED_HOURS_RX = re.compile(r"(\d{1,3})\s*(?:\+)?\s*hours?\s*(?:per|/|a)\s*week|(\d{1,3})\s*%\s*(?:workload|fte|time)", re.I)

CURRENCY_MAP = {"$": "USD", "€": "EUR", "£": "GBP", "fr": "CHF", "fr.": "CHF"}


def _clean_number(s):
    """Normalise a captured number like "40,000", "40.000" (EU thousands
    separator) or "45000.50" into a float. A dot is treated as a decimal
    point only when it's followed by exactly 1-2 digits at the very end;
    otherwise (EU-style thousands grouping) it's stripped like a comma."""
    s = s.strip()
    s = s.replace(",", "")
    if re.search(r"\.\d{1,2}$", s):
        return float(s)
    return float(s.replace(".", ""))


def parse_compensation(text):
    """Best-effort salary extraction. Returns a dict:
        {found: bool, min, max, currency, period, annualised_ok: bool,
         guaranteed: bool, display: str}
    NEVER invents a number. A bare hourly rate with no stated weekly hours
    or workload % is reported but NOT annualised (guaranteed=False,
    display keeps the hourly rate as-is) per the project's explicit rule
    against annualising "up to" rates without guaranteed hours."""
    m = SALARY_RANGE_RX.search(text)
    if not m or not m.group("min"):
        m = SALARY_SUFFIX_RX.search(text)
    if not m or not m.group("min"):
        # maybe a bare hourly rate
        hm = HOURLY_RATE_RX.search(text)
        if hm:
            cur = CURRENCY_MAP.get(hm.group("cur").lower(), hm.group("cur").upper())
            rate = hm.group("rate")
            guaranteed = bool(GUARANTEED_HOURS_RX.search(text))
            return {"found": True, "min": None, "max": None, "currency": cur, "period": "hour",
                    "guaranteed": guaranteed, "display": f"{rate} {cur}/ora" + ("" if guaranteed else " (ore non garantite - non annualizzato)")}
        return {"found": False, "min": None, "max": None, "currency": None, "period": None,
                "guaranteed": False, "display": "Salary not disclosed"}

    groups = m.groupdict()
    cur_raw = groups.get("cur") or groups.get("cur2") or "EUR"
    currency = CURRENCY_MAP.get(cur_raw.lower(), cur_raw.upper())
    try:
        min_v = _clean_number(m.group("min")) if m.group("min") else None
    except ValueError:
        min_v = None
    try:
        max_v = _clean_number(m.group("max")) if m.group("max") else min_v
    except ValueError:
        max_v = min_v
    period = (m.group("period") or "year").lower()
    guaranteed = period in ("year", "yr", "annum", "month") or bool(GUARANTEED_HOURS_RX.search(text))
    display = f"{int(min_v):,}".replace(",", ".") if min_v else "?"
    if max_v and max_v != min_v:
        display += f" - {int(max_v):,}".replace(",", ".")
    display += f" {currency}"
    if period in ("hour", "hr"):
        display += "/ora" + ("" if guaranteed else " (ore non garantite - non annualizzato)")
    return {"found": True, "min": min_v, "max": max_v, "currency": currency, "period": period,
            "guaranteed": guaranteed, "display": display}


def meets_annual_minimum(comp, min_eur):
    """Rough EUR/CHF/USD/GBP parity approximation - documented as such,
    never presented as exact FX. Returns True/False/None (unclear)."""
    if not comp["found"] or comp["min"] is None:
        return None
    if comp["period"] not in ("year", "yr", "annum"):
        return None  # monthly/hourly figures are not compared to an annual threshold here
    return comp["min"] >= min_eur


# --------------------------------------------------------------------------
# role keyword matching, sector, language, growth, brand
# --------------------------------------------------------------------------
def role_match(text, keywords):
    hits = [k for k in keywords if norm(k) in text]
    return hits


def tier_role_keywords(cfg, tier):
    """Union of the tier's own role_keywords with the candidate's
    target_titles list. The tier lists use broader category phrases
    ("product management"); target_titles has the exact role names from
    the candidate's preferred-role-family list ("junior product manager",
    "product owner", ...). A job titled "Product Manager" should count as
    a role match for every tier even though that exact phrase isn't
    repeated in each tier's own keyword list - checking only one list was
    a real gap that silently dropped obviously-relevant titles."""
    seen, out = set(), []
    for k in list(cfg[tier]["role_keywords"]) + list(cfg["profile"]["target_titles"]):
        nk = norm(k)
        if nk not in seen:
            seen.add(nk)
            out.append(k)
    return out


LANGUAGES_REQUIRED_RX = {
    "french": re.compile(r"(fluent|native|professional|advanced|working)\s+french|french\s+(fluency|required|native|speaker)", re.I),
    "german": re.compile(r"(fluent|native|professional|advanced|working)\s+german|german\s+(fluency|required|native|speaker)", re.I),
}


def language_fit(text, profile):
    """Profile: italian/english/spanish = strong, french = basic only.
    A role requiring fluent/professional French or German (or any language
    outside the profile) at a working level is a language gap."""
    gaps = []
    if LANGUAGES_REQUIRED_RX["french"].search(text):
        gaps.append("francese a livello professionale (il profilo ha solo francese base)")
    if LANGUAGES_REQUIRED_RX["german"].search(text):
        gaps.append("tedesco richiesto (non nel profilo)")
    covered = [l for l in ("italian", "english", "spanish") if l in text]
    return gaps, covered


GROWTH_HINTS = ["mentorship", "training programme", "training program", "career development", "learning budget",
                "structured onboarding", "fast growing", "scale up", "rotational programme", "graduate programme"]
BRAND_TIER_HINTS = ["y combinator", "unicorn", "fortune 500", "listed company", "publicly traded", "series b", "series c", "series d"]


# --------------------------------------------------------------------------
# main assessment
# --------------------------------------------------------------------------
def compatibility_score(text, title, cfg, raw=""):
    profile = cfg["profile"]
    weights = cfg["scoring"]
    reasons = []

    title_hits = role_match(title + " " + text[:800], profile["target_titles"])
    role_score = min(weights["role_weight"], len(title_hits) * 6 + (6 if title_hits else 0))
    if title_hits:
        reasons.append(f"ruolo allineato ({', '.join(title_hits[:2])})")

    skill_hits = role_match(text, profile["strengths"])
    skills_score = min(weights["skills_weight"], round(len(skill_hits) / max(1, len(profile["strengths"])) * weights["skills_weight"] * 2.2))
    if skill_hits:
        reasons.append(f"{len(skill_hits)} competenze rilevanti ({', '.join(skill_hits[:4])})")

    exp, preferred = parse_experience(raw or text)
    entry_terms = ["entry level", "entry-level", "junior", "graduate", "associate", "no experience"]
    entry_hits = [t for t in entry_terms if t in text]
    if exp is not None and exp <= 1:
        seniority_score = weights["seniority_weight"]
        reasons.append(f"esperienza compatibile (~{exp} anni)")
    elif exp is None and entry_hits:
        seniority_score = weights["seniority_weight"]
        reasons.append("descritta come entry-level/junior")
    elif exp is not None and exp <= 2 and preferred:
        seniority_score = round(weights["seniority_weight"] * 0.8)
        reasons.append("esperienza extra indicata come preferenziale, non obbligatoria")
    else:
        seniority_score = round(weights["seniority_weight"] * 0.3) if exp is None else 0

    worldwide = diamond_worldwide(text, cfg)
    location_score = weights["location_weight"] if worldwide else round(weights["location_weight"] * 0.4)
    if worldwide:
        reasons.append("remote worldwide con evidenza esplicita")

    comp = parse_compensation(raw or text)
    contract_score = weights["contract_compensation_weight"] if comp["found"] else round(weights["contract_compensation_weight"] * 0.4)

    sector_hits = role_match(text, profile["sectors"])
    sector_score = min(weights["sector_weight"], len(sector_hits) * 2)
    if sector_hits:
        reasons.append(f"settore affine ({', '.join(sector_hits[:2])})")

    growth_hits = [h for h in GROWTH_HINTS if h in text]
    growth_score = min(weights["growth_weight"], len(growth_hits) * 2)

    lang_gaps, lang_covered = language_fit(text, profile["languages_spoken"])
    if lang_gaps:
        language_score = 0
        reasons.append(f"gap linguistico: {lang_gaps[0]}")
    elif lang_covered:
        language_score = weights["language_weight"]
        reasons.append(f"lingue coperte ({', '.join(lang_covered)})")
    else:
        language_score = round(weights["language_weight"] * 0.6)

    brand_hits = [h for h in BRAND_TIER_HINTS if h in text]
    brand_score = min(weights["brand_weight"], len(brand_hits) * 3)

    total = min(100, role_score + skills_score + seniority_score + location_score + contract_score + sector_score + growth_score + language_score + brand_score)
    return total, reasons, exp, preferred, comp, worldwide


def office_days_estimate(raw_text):
    m = OFFICE_DAYS_RX.search(raw_text)
    if m:
        return int(m.group(1))
    return None


def score_band(score, cfg):
    b = cfg["scoring"]["bands"]
    if score >= b["apply_now"]:
        return "Apply Now"
    if score >= b["strong_opportunity"]:
        return "Strong Opportunity"
    if score >= b["consider"]:
        return "Consider"
    if score >= b["stretch"]:
        return "Stretch"
    return "Hidden"


def confidence_level(exp_known, remote_known, comp_known):
    known = sum([exp_known, remote_known, comp_known])
    if known == 3:
        return "High"
    if known == 2:
        return "Medium"
    return "Low"


def assess(job, cfg, watchlist_companies=None):
    """Full pipeline for a single job: hard exclusions -> priority tier
    classification -> compatibility score -> confidence. Returns a rich
    dict; app.py decides which dashboard section(s) to place it in."""
    text = job_text(job)
    raw = raw_job_text(job)
    title = norm(job.get("title", ""))
    company = job.get("company") or ""
    watchlist_companies = watchlist_companies or []
    is_watchlisted = any(w.lower() in company.lower() for w in watchlist_companies)

    ok, why = payment_check(text)
    if not ok:
        return {"filtered_out_reason": why, "priority": None, "title": job.get("title"), "company": company, "is_watchlisted": is_watchlisted}

    internship = is_internship(text)

    score, reasons, exp, preferred, comp, worldwide_evidence = compatibility_score(text, title, cfg, raw=raw)
    band = score_band(score, cfg)

    exp_text = experience_requirement_text(exp, preferred)
    comp_min_ok_eur = meets_annual_minimum(comp, cfg["diamond"]["min_annual_salary_eur"])

    remote_scope_label = "Genuinely worldwide" if worldwide_evidence else "Remote arrangement requires confirmation"
    if is_watchlisted and not worldwide_evidence:
        remote_scope_label = "Remote arrangement requires confirmation (watchlist company - verify per-vacancy, do not assume company-wide policy)"

    country_restrictions = "Nessuna evidenza di restrizione geografica" if worldwide_evidence else "Non determinabile dal testo - verificare l'annuncio originale"

    confidence = confidence_level(exp is not None, worldwide_evidence or (not worldwide_evidence and "must be based in" in text), comp["found"])

    mandatory_found, preferred_found, penalties = [], [], []
    priority = None

    # ---------------- STRATEGIC INTERNSHIP (only path an internship can take) ----------------
    if internship:
        conditions_cfg = cfg["strategic_internship"]["conditions"]
        met = []
        if is_watchlisted or any(h in text for h in BRAND_TIER_HINTS):
            met.append("internationally recognised company")
        if role_match(text, cfg["diamond"]["role_keywords"] + cfg["gold"]["role_keywords"]):
            met.append("direct relevance to product/ai/digital/retail technology")
        if any(h in text for h in ["structured programme", "structured program", "rotational", "graduate programme"]):
            met.append("structured development programme")
        if comp["found"]:
            met.append("clear compensation")
        if len(text) > 400:
            met.append("clear responsibilities (detailed description)")
        if any(h in text for h in GROWTH_HINTS):
            met.append("strong employability after completion")
        if gold_location_ok(text, cfg) or worldwide_evidence:
            met.append("canton ticino or highly flexible remote arrangement")
        if score >= 70:
            met.append("meaningfully stronger learning value than a generic internship")
        if len(met) >= cfg["strategic_internship"]["minimum_conditions_met"]:
            priority = "STRATEGIC_INTERNSHIP"
            mandatory_found = met
        else:
            return {"filtered_out_reason": f"esclusa: stage che non soddisfa i criteri di Strategic Internship ({len(met)}/8 condizioni)",
                    "priority": None, "title": job.get("title"), "company": company, "is_watchlisted": is_watchlisted}

    # ---------------- HIGH-VALUE PART-TIME (checked before full-time tiers) ----------------
    hvpt_hint = re.search(r"(\d{1,2})\s*(?:[-–]\s*(\d{1,2}))?\s*hours?\s*(?:per|/|a)\s*week|(\d{1,3})\s*%\s*(?:workload|fte)", raw)
    if priority is None and hvpt_hint and role_match(text, cfg["high_value_part_time"]["role_keywords"]):
        rate_m = HOURLY_RATE_RX.search(raw)
        hours_stated = bool(hvpt_hint)
        if not hours_stated:
            penalties.append("nessun numero di ore garantito indicato -> Supplementary income only")
        elif rate_m:
            try:
                rate_val = float(rate_m.group("rate").replace(",", ""))
                if rate_val >= cfg["high_value_part_time"]["min_contractor_hourly_rate_eur_usd"]:
                    priority = "HIGH_VALUE_PART_TIME"
                    mandatory_found = [f"hours/workload stated", f"hourly rate {rate_val} meets EUR/USD 25 minimum"]
                else:
                    penalties.append(f"tariffa oraria {rate_val} sotto la soglia minima di 25 EUR/USD")
            except ValueError:
                pass
        elif hours_stated:
            priority = "HIGH_VALUE_PART_TIME"
            mandatory_found = ["hours/workload explicitly stated"]

    # ---------------- DIAMOND ----------------
    if priority is None and not internship:
        role_hits = role_match(text, tier_role_keywords(cfg, "diamond"))
        exp_ok = experience_ok_for_tier(exp, preferred, cfg["diamond"]["max_experience_years"], cfg["diamond"]["max_experience_years_if_preferred"])
        if role_hits and worldwide_evidence and exp_ok and comp_min_ok_eur is True:
            priority = "DIAMOND"
            mandatory_found = [f"role: {', '.join(role_hits[:3])}", "genuinely worldwide remote (explicit evidence)",
                                f"seniority: {exp_text}", f"compensation: {comp['display']} (>= EUR 40,000)"]
        elif role_hits and exp_ok:
            # record WHY it didn't reach Diamond, then fall through to Gold/Silver checks below
            if not worldwide_evidence:
                penalties.append("non Diamond: remote worldwide non confermato esplicitamente")
            if comp_min_ok_eur is None:
                penalties.append("non Diamond: compenso non dichiarato (richiesto esplicitamente per Diamond)")
            elif comp_min_ok_eur is False:
                penalties.append(f"non Diamond: compenso sotto EUR 40.000 ({comp['display']})")

    # ---------------- GOLD ----------------
    if priority is None and not internship:
        role_hits = role_match(text, tier_role_keywords(cfg, "gold"))
        location_ok = gold_location_ok(text, cfg)
        exp_ok = experience_ok_for_tier(exp, preferred, cfg["gold"]["max_experience_years"], cfg["gold"]["max_experience_years_if_preferred"])
        if role_hits and location_ok and exp_ok:
            days = office_days_estimate(raw)
            if days is not None:
                if days <= 2:
                    preferred_found.append(f"~{days} giorni/settimana in ufficio (stima) - ottimo")
                elif days == 3:
                    preferred_found.append(f"~{days} giorni/settimana in ufficio (stima) - accettabile")
                else:
                    penalties.append(f"~{days} giorni/settimana in ufficio (stima) - pesa negativamente")
            priority = "GOLD"
            mandatory_found = [f"role: {', '.join(role_hits[:3])}", "location: Ticino/Milano area", f"seniority: {exp_text}"]
            if not comp["found"]:
                penalties.append("Salary not disclosed - riduce la confidenza ma non esclude il ruolo da Gold")
        elif role_hits and exp_ok and not location_ok:
            penalties.append("non Gold: location fuori dall'area Ticino/Milano")

    # ---------------- SILVER ----------------
    if priority is None and not internship:
        role_hits = role_match(text, tier_role_keywords(cfg, "silver"))
        remote_scope = silver_remote_scope(text, cfg)
        exp_ok = experience_ok_for_tier(exp, False, cfg["silver"]["max_experience_years"], cfg["silver"]["max_experience_years"])
        if role_hits and remote_scope == "italy_or_europe" and exp_ok:
            if comp["found"]:
                if comp_min_ok_eur:
                    priority = "SILVER"
                    mandatory_found = [f"role: {', '.join(role_hits[:3])}", "remote scope: Italy/Europe (Italy eligible)",
                                        f"seniority: {exp_text}", f"compensation: {comp['display']}"]
                else:
                    penalties.append(f"non Silver: compenso sotto EUR 40.000 ({comp['display']})")
            else:
                if score >= cfg["silver"]["min_compatibility_if_salary_missing"]:
                    priority = "SILVER"
                    mandatory_found = [f"role: {', '.join(role_hits[:3])}", "remote scope: Italy/Europe (Italy eligible)",
                                        f"seniority: {exp_text}", "compensation unverified but compatibility >= 90%"]
                    penalties.append("Salary not disclosed - mantenuta solo per compatibilità >= 90%")
                else:
                    penalties.append(f"non Silver: Salary not disclosed e compatibilità {score}% < 90% richiesto senza stipendio")

    if priority is None:
        reason = "nessun livello di priorità soddisfa tutte le condizioni obbligatorie"
        if internship:
            reason = "stage non qualificato come Strategic Internship"
        return {"filtered_out_reason": reason, "priority": None, "title": job.get("title"), "company": company,
                "score": score, "penalties": penalties, "is_watchlisted": is_watchlisted}

    return {
        "title": job.get("title"), "company": company, "source": job.get("source"), "url": job.get("url"),
        "published_at": job.get("published_at"), "priority": priority, "score": score, "band": band,
        "confidence": confidence, "reasons": reasons, "penalties": penalties,
        "mandatory_found": mandatory_found, "preferred_found": preferred_found,
        "experience_required": exp_text, "remote_scope": remote_scope_label,
        "country_restrictions": country_restrictions, "compensation": comp["display"],
        "compensation_guaranteed": comp["guaranteed"], "contract_type": job.get("employment_type") or "n/d",
        "is_watchlisted": is_watchlisted, "filtered_out_reason": None,
    }
