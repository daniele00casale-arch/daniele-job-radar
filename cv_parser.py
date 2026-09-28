"""
Optional CV-based keyword extraction for Daniele Job Radar.

Lets the user upload their own CV (PDF, Word .docx, or plain text) instead
of (or in addition to) hand-editing `config.yaml`'s profile lists. The text
is extracted, then a heuristic keyword extractor pulls out plausible
role/skill phrases, which the user reviews and can uncheck before they're
merged into the scoring profile for that session only - nothing is ever
silently added to config.yaml, and nothing is stored anywhere: the CV file
and its extracted text live only in Streamlit's in-memory session state for
the current browser session, never written to disk or the database.

This is honestly a heuristic, not an NLP model: it can't tell "Product
Manager" is a job title vs. just words in a sentence with certainty, so it
over-generates candidate keywords and lets the person doing the search
(who knows their own CV) be the filter, via a checklist in the app, rather
than silently deciding for them.
"""
import io
import re

STOPWORDS = set("""
a about above after again against all am an and any are aren as at be because been before
being below between both but by can could did do does doing down during each few for from
further had has have having he her here hers herself him himself his how i if in into is it
its itself just me more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should so some such than that the their theirs them themselves
then there these they this those through to too under until up very was we were what when
where which while who whom why will with you your yours yourself yourselves
il lo la i gli le un uno una di a da in con su per tra fra e o ma se non che chi cui quale
quali quanto quanti quanta quante come dove quando perche perché anche più piu meno molto poco
del della dello dei degli delle al allo alla ai agli alle nel nello nella nei negli nelle
sono stato stata stati state essere avere ho hai ha abbiamo avete hanno
""".split())

# Curated seed list of role/skill phrases worth checking for explicitly
# (multi-word phrases a naive frequency count would otherwise miss/split).
KNOWN_PHRASES = [
    "product management", "product manager", "product owner", "product operations",
    "product marketing", "product strategy", "digital product", "digital transformation",
    "business analyst", "business analysis", "business development", "innovation analyst",
    "marketing operations", "customer insights", "customer experience", "crm",
    "retail technology", "digital commerce", "process improvement", "category manager",
    "growth analyst", "conversion rate optimisation", "conversion rate optimization",
    "kpi monitoring", "kpi", "market analysis", "competitive benchmarking",
    "data visualisation", "data visualization", "data analysis", "market research",
    "stakeholder management", "stakeholder collaboration", "requirements gathering",
    "financial forecasting", "financial analysis", "audit", "auditing", "consulting",
    "mvp development", "mvp", "ux design", "user experience", "user-centred design",
    "user centered design", "ai", "artificial intelligence", "machine learning",
    "process automation", "sql", "python", "excel", "powerpoint", "power bi", "tableau",
    "firebase", "agile", "scrum", "roadmap", "go-to-market", "go to market", "a/b testing",
    "ab testing", "customer journey", "fintech", "saas", "e-commerce", "ecommerce",
    "retail", "fashion", "automotive", "travel technology", "venture building",
]

WORD_RX = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ+/\-]{2,}")


def extract_text(file_bytes, filename):
    """Returns plain text from a PDF, DOCX, or TXT file's raw bytes.
    Raises a clear RuntimeError with the format name on failure rather than
    a bare library traceback."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("libreria 'pypdf' non installata: aggiungi pypdf a requirements.txt") from e
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:
            raise RuntimeError(f"impossibile leggere il PDF ({e}) - se è una scansione/immagine senza testo selezionabile, prova a esportarlo come .docx o .txt") from e
    if name.endswith(".docx"):
        try:
            import docx
        except ImportError as e:
            raise RuntimeError("libreria 'python-docx' non installata: aggiungi python-docx a requirements.txt") from e
        try:
            d = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception as e:
            raise RuntimeError(f"impossibile leggere il file Word ({e})") from e
    if name.endswith(".txt") or name.endswith(".md"):
        return file_bytes.decode("utf-8", errors="ignore")
    raise RuntimeError(f"formato non supportato ({name}) - usa PDF, DOCX o TXT")


def extract_keywords(text, max_keywords=30):
    """Heuristic keyword extraction, returned as a de-duplicated list of
    plausible role/skill phrases, longest/most-specific-looking first.
    NOT a trained model - a human (the person whose CV this is) is meant
    to review the list in the app before it's used, which the app's UI
    always shows before merging anything into the scoring profile."""
    lower = text.lower()
    found = []
    seen = set()
    for phrase in KNOWN_PHRASES:
        if phrase in lower and phrase not in seen:
            found.append(phrase)
            seen.add(phrase)

    # Frequency-based fallback for anything the curated list missed: single
    # capitalised words that repeat (likely a tool/skill/domain name), never
    # invented, just counted from what's actually in the CV text.
    words = WORD_RX.findall(text)
    freq = {}
    for w in words:
        wl = w.lower()
        if wl in STOPWORDS or len(wl) < 4:
            continue
        freq[wl] = freq.get(wl, 0) + 1
    ranked = sorted((w for w, c in freq.items() if c >= 2), key=lambda w: -freq[w])
    for w in ranked:
        if w not in seen and len(found) < max_keywords:
            found.append(w)
            seen.add(w)
        if len(found) >= max_keywords:
            break
    return found[:max_keywords]


def build_augmented_profile(base_profile, accepted_keywords):
    """Returns a NEW profile dict (never mutates base_profile) with the
    user-approved CV keywords merged into `target_titles` and `strengths`.
    A keyword that looks like a role/title phrase (matches a common title
    word) goes into target_titles too, in addition to strengths, so it
    also counts toward the role-match score, not just the skills score."""
    TITLE_HINTS = ("manager", "owner", "analyst", "specialist", "lead", "coordinator",
                   "officer", "consultant", "associate", "director", "operations", "builder")
    profile = dict(base_profile)
    strengths = list(profile.get("strengths", []))
    titles = list(profile.get("target_titles", []))
    existing = {s.lower() for s in strengths} | {t.lower() for t in titles}
    for kw in accepted_keywords:
        if kw.lower() in existing:
            continue
        if any(h in kw.lower() for h in TITLE_HINTS):
            titles.append(kw)
        else:
            strengths.append(kw)
        existing.add(kw.lower())
    profile["strengths"] = strengths
    profile["target_titles"] = titles
    return profile
