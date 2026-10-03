import json
import os
import re
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import yaml

import ats_connectors
import connectors
import cv_parser
import db
import scoring
from email_parser import parse_eml_bytes

try:
    import gmail_connector
    import gmail_oauth
    GMAIL_MODULE_OK = True
except Exception:
    GMAIL_MODULE_OK = False

st.set_page_config(page_title="Job Radar", page_icon="🎯", layout="centered")

st.markdown("""
<style>
  .block-container {padding-top: 1.2rem; padding-bottom: 4rem; max-width: 760px;}
  div[data-testid="stVerticalBlockBorderWrapper"] {overflow-x: hidden;}
  div[data-testid="stButton"], div[data-testid="stLinkButton"], div[data-testid="stDownloadButton"],
  div[data-testid="stFormSubmitButton"],
  div[data-testid="stElementContainer"]:has(> div[data-testid="stButton"]),
  div[data-testid="stElementContainer"]:has(> div[data-testid="stLinkButton"]),
  div[data-testid="stElementContainer"]:has(> div[data-testid="stDownloadButton"]) {width: 100% !important;}
  div[data-testid="stButton"] button, div[data-testid="stLinkButton"] a, div[data-testid="stDownloadButton"] button,
  div[data-testid="stFormSubmitButton"] button {width: 100% !important; min-height: 2.5rem; border-radius: 10px;}
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {gap: 0.45rem;}
  .badge {display:inline-block; padding:2px 9px; border-radius:10px; font-size:0.75rem; font-weight:700; margin-right:6px;}
  .b-diamond {background:#c7d2fe; color:#1e1b4b;}
  .b-gold {background:#fde68a; color:#78350f;}
  .b-silver {background:#e2e8f0; color:#334155;}
  .b-intern {background:#bbf7d0; color:#064e3b;}
  .b-part {background:#fbcfe8; color:#831843;}
  .b-pot {border:1px dashed #7c3aed;}
  .score {font-weight:700; font-size:0.85rem; color:#0f172a;}
  .flag {font-size:0.8rem; color:#b45309;}
  div[data-testid="stPills"] button {border-radius: 999px;}
</style>
""", unsafe_allow_html=True)

with open("config.yaml", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

db.init_db()

# Gmail OAuth callback: Google redirects back here with ?code=&state= (new session).
if GMAIL_MODULE_OK:
    qp = st.query_params
    if "code" in qp and "state" in qp:
        try:
            gmail_oauth.exchange_code(qp["code"], qp["state"])
            st.session_state["gmail_wizard_message"] = ("success", "Gmail connesso.")
        except Exception as e:
            st.session_state["gmail_wizard_message"] = ("error", f"Connessione Gmail non riuscita: {e}")
        st.query_params.clear()
        st.rerun()
    if "error" in qp:
        st.session_state["gmail_wizard_message"] = ("error", f"Google ha segnalato un errore: {qp['error']}")
        st.query_params.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------
def chips(label, options, default, key, single=False, hide_label=False):
    """Pill chips where available (Streamlit >= 1.40), multiselect otherwise."""
    if hasattr(st, "pills"):
        val = st.pills(label, options, selection_mode="single" if single else "multi",
                       default=default, key=key,
                       label_visibility="collapsed" if hide_label else "visible")
        if single:
            return val
        return list(val or [])
    if single:
        return st.radio(label, options, index=options.index(default), horizontal=True, key=key)
    return st.multiselect(label, options, default=default, key=key)


def secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


# ---------------------------------------------------------------------------
# Geographic eligibility
# Remote job boards are full of "remote" roles that only accept one country
# (Germany only, US only, must be based in Portugal...). For someone living in
# Lombardy and open to Swiss cross-border work, those are noise.
# ---------------------------------------------------------------------------
OK_IT = "Italia"
OK_CH = "Svizzera"
OK_CH_GENERIC = "Svizzera (sede da verificare)"
CH_OUT = "Svizzera fuori dal Ticino"
OK_EU = "Europa/UE"
OK_WORLD = "Ovunque"
ALLOWED = {OK_IT, OK_CH, OK_CH_GENERIC, OK_EU, OK_WORLD}

# Comuni e località del Canton Ticino (nomi ambigui come "Riviera", "Claro", "Pura" esclusi apposta)
TICINO_PLACES = [
    "ticino", "tessin", "tessino", "canton ticino", "cantone ticino",
    "lugano", "chiasso", "mendrisio", "bellinzona", "locarno", "stabio", "biasca", "ascona", "losone",
    "balerna", "coldrerio", "novazzano", "vacallo", "morbio", "morbio inferiore", "castel san pietro",
    "riva san vitale", "capolago", "melano", "maroggia", "bissone", "melide", "arogno", "rovio", "breggia",
    "genestrerio", "ligornetto", "rancate", "besazio", "arzo", "meride", "brusino",
    "manno", "bioggio", "agno", "cadempino", "lamone", "vezia", "massagno", "savosa", "porza", "canobbio",
    "comano", "cureglia", "origlio", "capriasca", "tesserete", "ponte capriasca", "sigirino", "mezzovico",
    "taverne", "torricella", "bedano", "gravesano", "monteceneri", "camignolo", "bironico",
    "pregassona", "viganello", "breganzona", "sorengo", "muzzano", "collina d'oro", "montagnola",
    "gentilino", "grancia", "pambio", "noranco", "barbengo", "figino", "carabbia", "pazzallo",
    "caslano", "magliaso", "ponte tresa", "monteggio", "croglio", "novaggio", "neggio", "curio",
    "muralto", "minusio", "gordola", "brissago", "avegno", "maggia", "cevio", "gambarogno", "magadino",
    "giubiasco", "sant'antonino", "cadenazzo", "camorino", "arbedo", "castione", "lumino", "sementina",
    "airolo", "faido", "bodio", "giornico", "acquarossa", "blenio", "serravalle", "pollegio",
]
CH_OUTSIDE_TICINO = [
    "zurich", "zürich", "zuerich", "zurigo", "geneva", "genève", "geneve", "ginevra", "basel", "basilea",
    "bern", "berne", "berna", "lausanne", "losanna", "zug", "zugo", "lucerne", "luzern", "lucerna",
    "winterthur", "st. gallen", "st gallen", "san gallo", "aarau", "baden", "schaffhausen", "fribourg",
    "neuchâtel", "neuchatel", "sion", "chur", "coira", "thun", "biel", "bienne", "olten", "solothurn",
    "schwyz", "frauenfeld", "rapperswil", "wallisellen", "kloten", "dübendorf", "opfikon", "glattbrugg",
    "schlieren", "baar", "cham", "pfäffikon", "nyon", "vevey", "montreux", "yverdon",
]

PLACE_TERMS = {
    # allowed
    "italy": OK_IT, "italia": OK_IT, "italian": OK_IT, "milan": OK_IT, "milano": OK_IT, "lombardy": OK_IT,
    "lombardia": OK_IT, "rome": OK_IT, "roma": OK_IT, "turin": OK_IT, "torino": OK_IT, "bologna": OK_IT,
    "genoa": OK_IT, "genova": OK_IT, "como": OK_IT, "varese": OK_IT, "monza": OK_IT, "bergamo": OK_IT,
    # Switzerland: only Canton Ticino counts (generic "Switzerland" is kept but flagged to verify)
    "switzerland": OK_CH_GENERIC, "swiss": OK_CH_GENERIC, "schweiz": OK_CH_GENERIC,
    "suisse": OK_CH_GENERIC, "svizzera": OK_CH_GENERIC,
    **{t: OK_CH for t in TICINO_PLACES},
    **{t: CH_OUT for t in CH_OUTSIDE_TICINO},
    "europe": OK_EU, "european union": OK_EU, "emea": OK_EU, "eu": OK_EU, "eea": OK_EU, "cet": OK_EU,
    "cest": OK_EU, "european": OK_EU, "europa": OK_EU,
    "worldwide": OK_WORLD, "anywhere": OK_WORLD, "global": OK_WORLD, "globally": OK_WORLD,
    # not allowed
    "germany": "Germania", "deutschland": "Germania", "german": "Germania", "berlin": "Germania",
    "munich": "Germania", "münchen": "Germania", "hamburg": "Germania", "frankfurt": "Germania",
    "cologne": "Germania", "köln": "Germania", "stuttgart": "Germania", "düsseldorf": "Germania",
    "portugal": "Portogallo", "lisbon": "Portogallo", "lisboa": "Portogallo", "porto": "Portogallo",
    "spain": "Spagna", "españa": "Spagna", "madrid": "Spagna", "barcelona": "Spagna", "valencia": "Spagna",
    "france": "Francia", "paris": "Francia", "lyon": "Francia",
    "united kingdom": "Regno Unito", "great britain": "Regno Unito", "england": "Regno Unito",
    "london": "Regno Unito", "manchester": "Regno Unito", "scotland": "Regno Unito", "british": "Regno Unito",
    "ireland": "Irlanda", "dublin": "Irlanda",
    "netherlands": "Paesi Bassi", "amsterdam": "Paesi Bassi", "rotterdam": "Paesi Bassi", "dutch": "Paesi Bassi",
    "belgium": "Belgio", "brussels": "Belgio", "austria": "Austria", "vienna": "Austria", "wien": "Austria",
    "poland": "Polonia", "warsaw": "Polonia", "krakow": "Polonia", "czech": "Rep. Ceca", "prague": "Rep. Ceca",
    "sweden": "Svezia", "stockholm": "Svezia", "denmark": "Danimarca", "copenhagen": "Danimarca",
    "norway": "Norvegia", "oslo": "Norvegia", "finland": "Finlandia", "helsinki": "Finlandia",
    "romania": "Romania", "bucharest": "Romania", "greece": "Grecia", "athens": "Grecia",
    "hungary": "Ungheria", "budapest": "Ungheria", "estonia": "Estonia", "tallinn": "Estonia",
    "latvia": "Lettonia", "lithuania": "Lituania", "croatia": "Croazia", "serbia": "Serbia",
    "bulgaria": "Bulgaria", "ukraine": "Ucraina", "turkey": "Turchia", "istanbul": "Turchia",
    "luxembourg": "Lussemburgo", "slovakia": "Slovacchia", "slovenia": "Slovenia", "cyprus": "Cipro",
    "malta": "Malta",
    "united states": "USA", "u.s.": "USA", "america": "USA", "american": "USA", "new york": "USA",
    "san francisco": "USA", "california": "USA", "texas": "USA", "seattle": "USA", "boston": "USA",
    "chicago": "USA", "austin": "USA", "los angeles": "USA", "north america": "Nord America",
    "canada": "Canada", "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "latam": "America Latina", "latin america": "America Latina", "mexico": "Messico", "brazil": "Brasile",
    "argentina": "Argentina", "colombia": "Colombia", "americas": "Americhe",
    "india": "India", "bangalore": "India", "apac": "Asia-Pacifico", "asia": "Asia", "singapore": "Singapore",
    "philippines": "Filippine", "japan": "Giappone", "australia": "Australia", "sydney": "Australia",
    "new zealand": "Nuova Zelanda", "israel": "Israele", "tel aviv": "Israele", "dubai": "EAU",
    "united arab emirates": "EAU", "south africa": "Sudafrica", "nigeria": "Nigeria", "kenya": "Kenya",
    "pakistan": "Pakistan", "egypt": "Egitto",
}
# Short codes are only trusted inside location fields ("us" is a common English word).
CODE_TERMS = {"us": "USA", "usa": "USA", "uk": "Regno Unito", "de": "Germania", "pt": "Portogallo",
              "es": "Spagna", "fr": "Francia", "nl": "Paesi Bassi", "ch": OK_CH, "it": OK_IT,
              "ca": "Canada", "gb": "Regno Unito", "ie": "Irlanda", "pl": "Polonia", "est": "USA",
              "pst": "USA", "emea": OK_EU}


def _rx(terms):
    alts = sorted(terms, key=len, reverse=True)
    return re.compile(r"(?<![a-z])(" + "|".join(re.escape(t) for t in alts) + r")(?![a-z])")


PLACE_RX = _rx(PLACE_TERMS)
CODE_RX = _rx(CODE_TERMS)

RESTRICTION_PATTERNS = [
    r"([a-z][a-z .\-]{1,30}?)[\s\-]+only\b",
    r"only (?:for |open to )?(?:candidates|applicants|people|residents)? ?(?:based|located|living|residing) in ([^.;\n]{2,60})",
    r"(?:must|need to|needs to|required to|should|have to) (?:be )?(?:currently )?(?:based|located|living|reside|residing|resident|live) in (?:the )?([^.;\n]{2,60})",
    r"(?:candidates|applicants) (?:must be |need to be )?(?:based|located|residing) in (?:the )?([^.;\n]{2,60})",
    r"(?:right|authori[sz]ation|authori[sz]ed|eligible|eligibility|permit) to work in (?:the )?([^.;\n]{2,40})",
    r"remote\s*[\(\-–:]\s*([^\)\n,;]{2,40})",
    r"(?:open|available) (?:only )?to (?:residents|citizens) of (?:the )?([^.;\n]{2,40})",
]
RESTRICTION_RX = [re.compile(p) for p in RESTRICTION_PATTERNS]

REMOTE_SOURCES = ("himalayas", "remotive", "we work remotely", "remote ok", "remoteok")


def places_in(text, allow_codes=False):
    t = (text or "").lower()
    found = {PLACE_TERMS[m.group(1)] for m in PLACE_RX.finditer(t)}
    if allow_codes:
        found |= {CODE_TERMS[m.group(1)] for m in CODE_RX.finditer(t)}
    return found


def location_text(j, r):
    parts = [j.get(k) for k in ("location", "candidate_required_location", "job_location", "locations",
                                "country", "region", "city")]
    parts += [r.get("remote_scope"), r.get("country_restrictions")]
    out = []
    for p in parts:
        if isinstance(p, (list, tuple)):
            out.extend(str(x) for x in p)
        elif p:
            out.append(str(p))
    return " | ".join(out)


def geo_check(j, r):
    """Return dict(eligible, where=set of 'remote'/'ch'/'it', reason, unverified)."""
    loc = location_text(j, r)
    desc = " ".join(str(j.get(k) or "") for k in ("title", "description", "summary", "snippet"))
    low_all = (loc + " \n " + desc).lower()

    # 1) explicit single-country restrictions anywhere in the text
    blocked = set()
    for rx in RESTRICTION_RX:
        for m in rx.finditer(low_all):
            clause = m.group(1)
            pl = places_in(clause, allow_codes=True)
            if pl and not (pl & ALLOWED):
                blocked |= pl

    loc_places = places_in(loc, allow_codes=True)
    title_places = places_in(j.get("title") or "")
    source = (j.get("source") or "").lower()
    is_remote = (any(s in source for s in REMOTE_SOURCES) or "remote" in low_all[:400]
                 or "remote" in loc.lower() or OK_WORLD in loc_places)

    where = set()
    ticino = OK_CH in loc_places or OK_CH in title_places
    ch_generic = (OK_CH_GENERIC in loc_places or OK_CH_GENERIC in title_places
                  or (j.get("source") or "").lower().startswith(("adzuna ch", "jooble (ch")))
    outside = CH_OUT in loc_places and not ticino
    if outside and not is_remote:
        return {"eligible": False, "where": set(),
                "reason": "Svizzera fuori dal Ticino", "unverified": False}
    if ticino or (ch_generic and not outside):
        where.add("ch")
    if OK_IT in loc_places or OK_IT in title_places:
        where.add("it")

    if blocked and not (where & {"ch", "it"}):
        return {"eligible": False, "where": where,
                "reason": "Solo per " + ", ".join(sorted(blocked)), "unverified": False}

    if is_remote:
        if loc_places and not (loc_places & ALLOWED):
            return {"eligible": False, "where": where,
                    "reason": "Remoto solo da " + ", ".join(sorted(loc_places)), "unverified": False}
        where.add("remote")
        return {"eligible": True, "where": where, "reason": "",
                "unverified": not (loc_places & ALLOWED)}

    # on-site / hybrid: only Italy (Lombardy commute) or Canton Ticino make sense
    if where & {"ch", "it"}:
        return {"eligible": True, "where": where, "reason": "",
                "unverified": "ch" in where and not ticino and "it" not in where}
    if loc_places:
        return {"eligible": False, "where": where,
                "reason": "In sede a " + ", ".join(sorted(loc_places)), "unverified": False}
    return {"eligible": True, "where": where, "reason": "", "unverified": True}


# ---------------------------------------------------------------------------
# Swiss sources (the remote boards above barely cover Ticino/Zurich)
# ---------------------------------------------------------------------------
def adzuna_ch_configured():
    return bool(secret("ADZUNA_APP_ID") and secret("ADZUNA_APP_KEY"))


def fetch_adzuna_ch(query, where="Ticino"):
    params = {"app_id": secret("ADZUNA_APP_ID"), "app_key": secret("ADZUNA_APP_KEY"),
              "what": query, "where": where, "results_per_page": 50, "content-type": "application/json"}
    resp = requests.get("https://api.adzuna.com/v1/api/jobs/ch/search/1", params=params, timeout=20)
    resp.raise_for_status()
    out = []
    for it in resp.json().get("results", []):
        sal = ""
        if it.get("salary_min") or it.get("salary_max"):
            sal = f"CHF {int(it.get('salary_min') or 0):,}–{int(it.get('salary_max') or 0):,}".replace(",", "'")
        out.append({
            "title": it.get("title", ""),
            "company": (it.get("company") or {}).get("display_name", ""),
            "location": (it.get("location") or {}).get("display_name")
                        or ", ".join((it.get("location") or {}).get("area", [])) or "Ticino",
            "description": it.get("description", ""),
            "url": it.get("redirect_url", ""),
            "source": "Adzuna CH",
            "published_at": (it.get("created") or "")[:10],
            "salary": sal,
        })
    return out


# ---------------------------------------------------------------------------
# Header + search controls
# ---------------------------------------------------------------------------
st.title("🎯 Job Radar")

ROLE_OPTIONS = ["junior product manager", "associate product manager", "product owner",
                "product manager", "product operations", "product marketing", "junior business analyst", "business analyst",
                "pricing analyst", "revenue management", "digital transformation", "ai builder",
                "marketing operations", "customer insights", "crm analyst", "innovation analyst",
                "growth analyst", "category manager", "retail technology", "process improvement"]
DEFAULT_ROLES = ["junior product manager", "associate product manager", "product owner", "product operations",
                 "junior business analyst", "pricing analyst", "digital transformation"]

base_sources = ["Himalayas", "Arbeitnow", "Remotive", "We Work Remotely", "The Muse", "Remote OK"]
optional_sources = []
if connectors.adzuna_configured():
    optional_sources.append("Adzuna")
if adzuna_ch_configured():
    optional_sources.append("Adzuna Ticino")
if connectors.jooble_configured("it"):
    optional_sources.append("Jooble Italia")
if connectors.jooble_configured("ch"):
    optional_sources.append("Jooble Ticino")
gmail_ok = GMAIL_MODULE_OK and gmail_connector.gmail_connected()
if gmail_ok:
    optional_sources.append("Gmail alert")
all_sources = base_sources + optional_sources
swiss_sources_available = adzuna_ch_configured() or connectors.jooble_configured("ch")

WHERE_OPTIONS = ["Tutte", "🌍 Remoto", "🇨🇭 Ticino", "🇮🇹 Italia"]
where_choice = chips("Dove", WHERE_OPTIONS, "Tutte", key="where", single=True) or "Tutte"

with st.expander("🔎 Ruoli e fonti"):
    roles = chips("Ruoli da cercare", ROLE_OPTIONS, DEFAULT_ROLES, key="roles")
    extra = st.text_input("Aggiungi altri ruoli", placeholder="es. revenue analyst, pricing manager",
                          key="extra_roles")
    roles += [r.strip().lower() for r in extra.split(",") if r.strip()]
    sources_enabled = chips("Fonti", all_sources, all_sources, key="sources")
    include_ats = st.toggle("Pagine carriere delle aziende in watchlist", value=True)
    if not swiss_sources_available:
        st.caption("Per gli annunci in Ticino serve una chiave gratuita Adzuna "
                   "(ADZUNA_APP_ID / ADZUNA_APP_KEY) o Jooble (JOOBLE_API_KEY_CH) nei Secrets di Streamlit.")

with st.expander("⚙️ Filtri"):
    include_potential = st.toggle("Includi i 'Potential'", value=True)
    only_today = st.toggle("Solo nuovi di oggi", value=False)
    threshold = st.slider("Compatibilità minima", 0, 100, 45, step=5, format="%d%%")

with st.expander("📧 Gmail" + (" · connesso" if gmail_ok else " · non connesso"), expanded=not gmail_ok):
    if not GMAIL_MODULE_OK:
        st.error("Librerie Gmail mancanti: controlla requirements.txt e riavvia il deploy.")
    else:
        msg = st.session_state.pop("gmail_wizard_message", None)
        if msg:
            (st.success if msg[0] == "success" else st.error)(msg[1])
        connected = gmail_connector.gmail_connected()
        if connected:
            email = st.session_state.get("gmail_connected_email")
            if email is None:
                try:
                    email = gmail_oauth.connected_email_address()
                except Exception as e:
                    email = f"(non verificabile: {e})"
                st.session_state["gmail_connected_email"] = email
            st.write(f"Account: **{email}**")
            if st.button("Disconnetti Gmail"):
                gmail_connector.disconnect_gmail()
                st.session_state.pop("gmail_connected_email", None)
                st.rerun()
            st.link_button("Revoca accesso su Google ↗", gmail_oauth.REVOKE_URL)
        else:
            st.caption("Accesso di sola lettura, dalla pagina ufficiale di Google.")
            st.markdown("**1. Crea queste etichette in Gmail**")
            for lbl in gmail_oauth.DEFAULT_LABELS.values():
                st.code(lbl, language=None)
            st.link_button("Etichette Gmail ↗", "https://mail.google.com/mail/u/0/#settings/labels")

            st.markdown("**2. Client ID e Secret di Google Cloud**")
            client_source = gmail_oauth.client_config_source()
            if client_source in ("streamlit_secrets", "env") or gmail_oauth.has_client_config():
                st.caption("✅ Configurati.")
                if client_source not in ("streamlit_secrets", "env") and st.button("Rimuovi credenziali"):
                    gmail_oauth.clear_client_config()
                    st.rerun()
            else:
                st.link_button("Google Cloud → Credenziali ↗", gmail_oauth.GOOGLE_CLOUD_CREDENTIALS_URL)
                with st.form("gmail_client_config_form", clear_on_submit=True):
                    in_id = st.text_input("Client ID")
                    in_secret = st.text_input("Client Secret", type="password")
                    if st.form_submit_button("Salva (cifrato)"):
                        try:
                            gmail_oauth.save_client_config(in_id, in_secret)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Non salvate: {e}")

            st.markdown("**3. URI di reindirizzamento da autorizzare**")
            base = gmail_oauth.detect_redirect_base_url()
            if not base:
                base = st.text_input("URL dell'app", value=st.session_state.get("gmail_manual_base_url", ""),
                                     placeholder="https://tuo-progetto.streamlit.app")
                st.session_state["gmail_manual_base_url"] = base
            redirect_uri = gmail_oauth.redirect_uri_from_base(base) if base else None
            if redirect_uri:
                st.code(redirect_uri, language=None)

            st.markdown("**4. Connetti**")
            if gmail_oauth.has_client_config() and redirect_uri:
                try:
                    auth_url, _ = gmail_oauth.build_authorization_url(redirect_uri)
                    st.link_button("🔐 Connetti Gmail", auth_url, type="primary")
                except Exception as e:
                    st.error(f"Connessione non preparata: {e}")
            else:
                st.caption("Completa i passi 2 e 3.")

refresh = st.button("🔄 Aggiorna", type="primary")


# ---------------------------------------------------------------------------
# Settings in the sidebar (CV, manual import, privacy)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Impostazioni")

    with st.expander("📄 CV per il matching"):
        st.caption("Letto solo in questa sessione, non viene salvato.")
        cv_file = st.file_uploader("CV (PDF, DOCX, TXT)", type=["pdf", "docx", "txt", "md"], key="cv_upload")
        if cv_file is not None:
            cv_sig = f"{cv_file.name}:{cv_file.size}"
            if st.session_state.get("cv_sig") != cv_sig:
                try:
                    cv_text = cv_parser.extract_text(cv_file.getvalue(), cv_file.name)
                    st.session_state.cv_keywords_found = cv_parser.extract_keywords(cv_text)
                    st.session_state.cv_sig = cv_sig
                    st.session_state.cv_error = None
                except Exception as e:
                    st.session_state.cv_error = str(e)
                    st.session_state.cv_keywords_found = []
            if st.session_state.get("cv_error"):
                st.warning(f"CV non leggibile: {st.session_state['cv_error']}")
            elif st.session_state.get("cv_keywords_found"):
                found = st.session_state["cv_keywords_found"]
                st.session_state.cv_keywords_accepted = chips("Parole chiave da usare", found, found, key="cvkw")
                if st.button("Rimuovi CV"):
                    for k in ("cv_sig", "cv_keywords_found", "cv_keywords_accepted", "cv_error", "cvkw"):
                        st.session_state.pop(k, None)
                    st.rerun()

    with st.expander("📥 Importa alert (.eml)"):
        uploaded = st.file_uploader("Email LinkedIn/Indeed salvate", type=["eml"], accept_multiple_files=True)

    with st.expander("🔒 Dati"):
        if st.button("Esporta i miei dati"):
            st.download_button("Scarica JSON", json.dumps(db.export_all_data(), indent=2, default=str).encode("utf-8"),
                               file_name="job_radar_export.json", mime="application/json")
        if st.button("Elimina storico posizioni"):
            db.delete_all_job_history()
            st.success("Storico eliminato.")
        if GMAIL_MODULE_OK and st.button("Elimina dati email importati"):
            db.delete_gmail_processed_ids()
            st.success("Eliminati.")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load(qs, sources, include_ats_flag, ats_directory_json):
    jobs, errors, statuses = [], [], []

    def run(name, fn):
        try:
            result = fn()
            statuses.append({"fonte": name, "stato": "ok" if result else "0 risultati",
                             "annunci": len(result), "errore": None})
            jobs.extend(result)
        except Exception as e:
            errors.append(f"{name}: {e}")
            statuses.append({"fonte": name, "stato": "errore", "annunci": 0, "errore": str(e)})

    for q in qs:
        if "Himalayas" in sources:
            run(f"Himalayas · {q}", lambda q=q: connectors.fetch_himalayas(q, pages=2))
        if "Remotive" in sources:
            run(f"Remotive · {q}", lambda q=q: connectors.fetch_remotive(q))
        if "Adzuna" in sources:
            run(f"Adzuna · {q}", lambda q=q: connectors.fetch_adzuna(q))
        if "Adzuna Ticino" in sources:
            run(f"Adzuna Ticino · {q}", lambda q=q: fetch_adzuna_ch(q))
        if "Jooble Italia" in sources:
            run(f"Jooble IT · {q}", lambda q=q: connectors.fetch_jooble(q, market="it"))
        if "Jooble Ticino" in sources:
            run(f"Jooble Ticino · {q}", lambda q=q: connectors.fetch_jooble(q, market="ch", location="Ticino"))
    if "The Muse" in sources:
        run("The Muse", lambda: connectors.fetch_the_muse(pages=1))
    if "Remote OK" in sources:
        run("Remote OK", lambda: connectors.fetch_remoteok("product"))
    if "Arbeitnow" in sources:
        run("Arbeitnow", lambda: connectors.fetch_arbeitnow(pages=2))
    if "We Work Remotely" in sources:
        run("We Work Remotely", lambda: connectors.fetch_wwr())

    gmail_failures = []
    if "Gmail alert" in sources and GMAIL_MODULE_OK:
        try:
            gmail_jobs, gmail_failures = gmail_connector.fetch_gmail_job_alerts()
            statuses.append({"fonte": "Gmail", "stato": "ok" if gmail_jobs else "0 risultati",
                             "annunci": len(gmail_jobs), "errore": None})
            jobs.extend(gmail_jobs)
        except Exception as e:
            errors.append(f"Gmail: {e}")
            statuses.append({"fonte": "Gmail", "stato": "errore", "annunci": 0, "errore": str(e)})

    if include_ats_flag:
        for company, entry in json.loads(ats_directory_json).items():
            ats_jobs, status = ats_connectors.fetch_for_directory_entry(company, entry)
            jobs.extend(ats_jobs)
            statuses.append({"fonte": f"{company} ({status['ats']})", "stato": status["status"],
                             "annunci": status["jobs_retrieved"], "errore": status["error"]})
            if status["error"]:
                errors.append(f"{company}: {status['error']}")

    return jobs, errors, statuses, gmail_failures


if refresh:
    load.clear()  # il tasto forza davvero un nuovo download invece della cache di 30 min
if refresh or "jobs" not in st.session_state:
    with st.spinner("Cerco e valuto le posizioni..."):
        jobs, errors, statuses, gmail_failures = load(tuple(roles), tuple(sources_enabled), include_ats,
                                                      json.dumps(CFG.get("ats_directory", {})))
        eml_failures = []
        for uf in uploaded or []:
            try:
                for rec in parse_eml_bytes(uf.getvalue(), "Email alert"):
                    (eml_failures if rec.get("parsing_failed") else jobs).append(rec)
            except Exception as e:
                errors.append(f"Import {uf.name}: {e}")
        st.session_state.update(jobs=jobs, errors=errors, statuses=statuses,
                                gmail_parsing_failures=gmail_failures, eml_parsing_failures=eml_failures,
                                refreshed_at=datetime.now().strftime("%H:%M"))
        for s in statuses:
            db.record_connector_status(s["fonte"], s["stato"], jobs_retrieved=s["annunci"],
                                       connection_error=s["errore"], configured=True)

jobs = st.session_state.get("jobs", [])

# --- dedup ---
unique = {}
for j in jobs:
    key = ((j.get("company") or "").lower().strip(), (j.get("title") or "").lower().strip(),
           (j.get("url") or "").split("?")[0])
    unique[key] = j

# --- scoring (CV keywords merged into a copy of the config, never written to disk) ---
EFFECTIVE_CFG = CFG
cv_kw = st.session_state.get("cv_keywords_accepted", [])
if cv_kw:
    EFFECTIVE_CFG = dict(CFG)
    EFFECTIVE_CFG["profile"] = cv_parser.build_augmented_profile(CFG["profile"], cv_kw)

assessed, filtered_out, geo_excluded, diagnostics = [], [], [], []
watchlist = EFFECTIVE_CFG.get("watchlist_companies", [])
for j in unique.values():
    try:
        result = scoring.assess(j, EFFECTIVE_CFG, watchlist_companies=watchlist)
    except Exception as e:
        filtered_out.append({"title": j.get("title"), "company": j.get("company"),
                             "filtered_out_reason": f"errore di valutazione: {e}"})
        diagnostics.append({"source": j.get("source"), "title": j.get("title"), "company": j.get("company"),
                            "fields_missing": [], "score_before_hard_filters": None, "hard_filters_passed": False,
                            "classification": "PARSING_FAILURE", "exclusion_reason": str(e),
                            "confidence": "Low", "rejection_tags": []})
        continue
    diagnostics.append(scoring.diagnose(j, result))
    if result.get("priority") is None:
        filtered_out.append(result)
        continue

    geo = geo_check(j, result)
    result["geo"] = geo
    result["location"] = j.get("location") or ""
    result["source_url"] = j.get("url")
    if not geo["eligible"]:
        result["filtered_out_reason"] = geo["reason"]
        geo_excluded.append(result)
        continue
    if result["score"] < threshold and result["priority"] not in ("STRATEGIC_INTERNSHIP", "HIGH_VALUE_PART_TIME"):
        result["filtered_out_reason"] = f"Compatibilità {result['score']}% sotto la soglia del {threshold}%"
        filtered_out.append(result)
        continue
    result["job_id"] = db.upsert_job(j, result["priority"], result["score"])
    assessed.append(result)

db.log_refresh(len(jobs), len(assessed), len(filtered_out) + len(geo_excluded), len(st.session_state.get("errors", [])))

status_map = db.get_status_map()
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
for r in assessed:
    row = status_map.get(r["job_id"], {})
    r["status"] = row.get("status", "new")
    r["notes"] = row.get("notes", "")
    r["date_first_seen"] = row.get("date_first_seen", today)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
BADGES = {
    "DIAMOND": ("💎 Diamond", "b-diamond"), "POTENTIAL_DIAMOND": ("💎 Potential", "b-diamond b-pot"),
    "GOLD": ("🥇 Gold", "b-gold"), "POTENTIAL_GOLD": ("🥇 Potential", "b-gold b-pot"),
    "SILVER": ("🥈 Silver", "b-silver"), "POTENTIAL_SILVER": ("🥈 Potential", "b-silver b-pot"),
    "STRATEGIC_INTERNSHIP": ("🎓 Stage", "b-intern"), "HIGH_VALUE_PART_TIME": ("⏱️ Part-time", "b-part"),
}
STATUS_LABELS = {"new": "Nuovo", "saved": "Salvato", "applied": "Candidato", "interviewing": "Colloquio",
                 "rejected": "Rifiutato", "archived": "Archiviato"}


def where_label(r):
    w = r.get("geo", {}).get("where", set())
    loc = (r.get("location") or "").strip()
    if "ch" in w:
        return "🇨🇭 " + (loc or "Ticino")
    if "it" in w:
        return "🇮🇹 " + (loc or "Italia")
    if "remote" in w:
        return "🌍 Remoto" + (f" · {loc}" if loc and loc.lower() not in ("remote", "anywhere") else "")
    return loc


def useful(v):
    v = (v or "").strip()
    return v and not any(x in v.lower() for x in ("not disclosed", "not clearly stated", "n/d", "unknown"))


def render_card(r):
    label, cls = BADGES.get(r["priority"], (r["priority"] or "", "b-silver"))
    with st.container(border=True):
        st.markdown(f'<span class="badge {cls}">{label}</span><span class="score">{r.get("score", "?")}%</span>',
                    unsafe_allow_html=True)
        st.markdown(f"**{r.get('title', '')}**  \n{r.get('company', '')}")
        meta = [where_label(r)]
        if useful(r.get("compensation")):
            meta.append(r["compensation"])
        if r.get("published_at"):
            meta.append(str(r["published_at"])[:10])
        st.caption(" · ".join(m for m in meta if m))
        if r.get("geo", {}).get("unverified"):
            st.markdown('<span class="flag">📍 Paesi ammessi non indicati: verifica nell\'annuncio</span>',
                        unsafe_allow_html=True)

        c1, c2 = st.columns([3, 2])
        if r.get("source_url"):
            c1.link_button("Apri annuncio ↗", r["source_url"])
        statuses = list(db.VALID_STATUSES)
        cur = r.get("status", "new")
        new_status = c2.selectbox("Stato", statuses, index=statuses.index(cur) if cur in statuses else 0,
                                  format_func=lambda s: STATUS_LABELS.get(s, s),
                                  key=f"status_{r['job_id']}", label_visibility="collapsed")
        if new_status != cur:
            db.set_status(r["job_id"], new_status)
            st.rerun()

        with st.expander("Dettagli"):
            rows = [("Esperienza", r.get("experience_required")), ("Contratto", r.get("contract_type")),
                    ("Remoto", r.get("remote_scope")), ("Fonte", r.get("source"))]
            for k, v in rows:
                if useful(v):
                    st.markdown(f"**{k}:** {v}")
            if r.get("reasons"):
                st.markdown("**Perché è compatibile:** " + " · ".join(r["reasons"]))
            if r.get("penalties"):
                st.markdown("**Punti deboli:** " + " · ".join(r["penalties"]))
            notes = st.text_input("Note", value=r.get("notes", ""), key=f"notes_{r['job_id']}")
            if notes != r.get("notes", ""):
                db.set_notes(r["job_id"], notes)


def render_excluded(r):
    st.markdown(f"**{r.get('title') or '(senza titolo)'}** · {r.get('company') or ''}  \n"
                f"<span style='color:#64748b;font-size:0.85rem'>{r.get('filtered_out_reason', '')}</span>",
                unsafe_allow_html=True)


# --- filtering for the main list ---
TIER_GROUPS = [
    ("💎 Diamond", ["DIAMOND", "POTENTIAL_DIAMOND"]),
    ("🥇 Gold", ["GOLD", "POTENTIAL_GOLD"]),
    ("🥈 Silver", ["SILVER", "POTENTIAL_SILVER"]),
    ("🎓 Stage", ["STRATEGIC_INTERNSHIP"]),
    ("⏱️ Part-time", ["HIGH_VALUE_PART_TIME"]),
]
TIER_OF = {p: name for name, ps in TIER_GROUPS for p in ps}
WHERE_KEY = {"🌍 Remoto": "remote", "🇨🇭 Ticino": "ch", "🇮🇹 Italia": "it"}


def visible(r):
    if r["priority"] not in TIER_OF:
        return False
    if not include_potential and r["priority"].startswith("POTENTIAL_"):
        return False
    if only_today and r.get("date_first_seen") != today:
        return False
    k = WHERE_KEY.get(where_choice)
    return not k or k in r["geo"]["where"]


to_review = sorted([r for r in assessed if r["status"] in ("new", "saved") and visible(r)],
                   key=lambda r: r.get("score", 0), reverse=True)
pipeline = [r for r in assessed if r["status"] in ("applied", "interviewing", "rejected", "archived")]

summary = f"{len(to_review)} da vedere · {len(pipeline)} candidature"
if geo_excluded:
    summary += f" · {len(geo_excluded)} nascoste perché limitate ad altri paesi"
if st.session_state.get("refreshed_at"):
    summary += f" · aggiornato alle {st.session_state['refreshed_at']}"
st.caption(summary)

VIEWS = ["Da vedere", "Candidature", "Escluse", "🔌 Connettori"]
view = chips("Vista", VIEWS, VIEWS[0], key="view", single=True, hide_label=True) or VIEWS[0]

if view == VIEWS[0]:
    if not to_review:
        if where_choice == "🇨🇭 Ticino" and not swiss_sources_available:
            st.info("Nessuna fonte svizzera attiva. Aggiungi la chiave gratuita Adzuna (developer.adzuna.com) "
                    "nei Secrets di Streamlit come ADZUNA_APP_ID e ADZUNA_APP_KEY, poi premi Aggiorna.")
        else:
            st.info("Nessuna posizione con questi filtri. Prova ad abbassare la compatibilità minima o ad "
                    "aggiungere ruoli.")
    else:
        groups = {name: [r for r in to_review if TIER_OF[r["priority"]] == name] for name, _ in TIER_GROUPS}
        tier_labels = ["Tutti"] + [name for name, _ in TIER_GROUPS if groups[name]]
        st.caption("  ·  ".join(f"{name} **{len(groups[name])}**" for name, _ in TIER_GROUPS if groups[name]))
        tier_choice = chips("Livello", tier_labels, "Tutti", key="tier_view", single=True, hide_label=True) or "Tutti"
        shown = 0
        for name, _ in TIER_GROUPS:
            if tier_choice not in ("Tutti", name) or not groups[name]:
                continue
            st.subheader(f"{name} · {len(groups[name])}")
            for r in groups[name][:max(0, 150 - shown)]:
                render_card(r)
            shown += len(groups[name])
        df = pd.DataFrame([{"titolo": r.get("title"), "azienda": r.get("company"), "dove": where_label(r),
                            "livello": r.get("priority"), "compatibilità": r.get("score"),
                            "stipendio": r.get("compensation"), "link": r.get("source_url")} for r in to_review])
        st.download_button("⬇️ Esporta CSV", df.to_csv(index=False).encode("utf-8"),
                           file_name="job_radar.csv", mime="text/csv")

elif view == VIEWS[1]:
    if not pipeline:
        st.info("Qui compaiono le posizioni che segni come Candidato, Colloquio, Rifiutato o Archiviato.")
    order = {"interviewing": 0, "applied": 1, "rejected": 2, "archived": 3}
    for r in sorted(pipeline, key=lambda r: order.get(r["status"], 9)):
        render_card(r)

elif view == VIEWS[2]:
    if geo_excluded:
        st.markdown(f"**Limitate ad altri paesi ({len(geo_excluded)})**")
        for r in geo_excluded:
            render_excluded(r)
    if filtered_out:
        st.markdown(f"**Non compatibili ({len(filtered_out)})**")
        for r in filtered_out[:300]:
            render_excluded(r)

else:
    rows = st.session_state.get("statuses", [])
    agg = {}
    for row in rows:
        name = row["fonte"].split(" · ")[0]
        if "(unconfigured)" in name:
            continue  # aziende in watchlist senza pagina carriere configurata: non sono connettori
        a = agg.setdefault(name, {"annunci": 0, "ok": 0, "zero": 0, "err": 0, "errore": None})
        a["annunci"] += row.get("annunci") or 0
        if row["stato"] in ("errore", "failed", "failed_or_unsupported") or row.get("errore"):
            a["err"] += 1
            a["errore"] = a["errore"] or row.get("errore")
        elif row.get("annunci"):
            a["ok"] += 1
        else:
            a["zero"] += 1
    table = []
    for name, a in agg.items():
        if a["err"] and not a["ok"]:
            icon, stato = "❌", "Non funziona"
        elif a["err"]:
            icon, stato = "⚠️", "Funziona in parte"
        elif a["annunci"]:
            icon, stato = "✅", "Funziona"
        else:
            icon, stato = "⚪", "Nessun annuncio trovato"
        table.append({"": icon, "connettore": name, "stato": stato, "annunci": a["annunci"],
                      "dettaglio": (a["errore"] or "")[:160]})
    queried = set(agg)
    NOT_CONFIGURED = [
        ("Adzuna Ticino", adzuna_ch_configured(), "Aggiungi ADZUNA_APP_ID e ADZUNA_APP_KEY nei Secrets"),
        ("Adzuna", connectors.adzuna_configured(), "Aggiungi ADZUNA_APP_ID e ADZUNA_APP_KEY nei Secrets"),
        ("Jooble Italia", connectors.jooble_configured("it"), "Aggiungi la chiave Jooble Italia nei Secrets"),
        ("Jooble Ticino", connectors.jooble_configured("ch"), "Aggiungi JOOBLE_API_KEY_CH nei Secrets"),
        ("Gmail", gmail_ok, "Collega Gmail dalla sezione 📧 Gmail"),
    ]
    for name, ok, how in NOT_CONFIGURED:
        if not ok and name not in queried:
            table.append({"": "🔌", "connettore": name, "stato": "Non configurato", "annunci": 0, "dettaglio": how})
    if table:
        order = {"❌": 0, "⚠️": 1, "⚪": 2, "✅": 3, "🔌": 4}
        table.sort(key=lambda t: (order[t[""]], -t["annunci"]))
        n_ok = sum(t[""] == "✅" for t in table)
        n_bad = sum(t[""] in ("❌", "⚠️") for t in table)
        c1, c2, c3 = st.columns(3)
        c1.metric("Funzionano", n_ok)
        c2.metric("Con errori", n_bad)
        c3.metric("Annunci raccolti", sum(t["annunci"] for t in table))
        st.dataframe(pd.DataFrame(table), hide_index=True)
        st.caption("⚪ significa che la fonte risponde ma non ha annunci per questi ruoli: non è per forza un guasto.")
    else:
        st.info("Premi 🔄 Aggiorna per controllare i connettori.")
    if rows:
        with st.expander("Dettaglio per singola ricerca"):
            st.dataframe(pd.DataFrame(rows), hide_index=True)
    parsing_failures = [d for d in diagnostics if d.get("classification") == "PARSING_FAILURE"]
    parsing_failures += st.session_state.get("eml_parsing_failures", []) + st.session_state.get("gmail_parsing_failures", [])
    if parsing_failures:
        with st.expander(f"Annunci non leggibili ({len(parsing_failures)})"):
            for d in parsing_failures:
                st.markdown(f"- {d.get('title') or '(n/d)'} · {d.get('source') or ''}: "
                            f"{d.get('exclusion_reason') or d.get('description') or ''}")
    if diagnostics:
        with st.expander("Diagnostica completa"):
            df_d = pd.DataFrame([{
                "fonte": d.get("source"), "titolo": d.get("title"), "azienda": d.get("company"),
                "classificazione": d.get("classification"), "motivo": d.get("exclusion_reason"),
                "punteggio": d.get("score_before_hard_filters"),
                "tag": ", ".join(d.get("rejection_tags") or []),
            } for d in diagnostics])
            st.dataframe(df_d, hide_index=True)
            st.download_button("⬇️ Esporta diagnostica", df_d.to_csv(index=False).encode("utf-8"),
                               file_name="diagnostica.csv", mime="text/csv")
