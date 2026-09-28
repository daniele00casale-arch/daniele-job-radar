import io
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import yaml

import connectors
import db
import scoring
from email_parser import parse_eml_bytes

try:
    import gmail_connector
    GMAIL_MODULE_OK = True
except Exception:
    GMAIL_MODULE_OK = False

st.set_page_config(page_title="Daniele Job Radar", page_icon="🎯", layout="centered")

# ---------------------------------------------------------------------------
# Mobile-first CSS: bigger tap targets, no forced horizontal scroll, compact
# cards. Streamlit is already responsive (sidebar collapses to a hamburger
# menu on phones automatically); this just tightens things up further.
# ---------------------------------------------------------------------------
st.markdown("""
<style>
  .block-container {padding-top: 1rem; padding-bottom: 4rem; max-width: 760px;}
  div[data-testid="stVerticalBlockBorderWrapper"] {overflow-x: hidden;}
  button, .stButton>button, .stDownloadButton>button, .stLinkButton>a {
      min-height: 2.6rem; font-size: 0.95rem; border-radius: 10px; width: 100%;
  }
  .badge {display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.78rem; font-weight:700; margin-right:6px;}
  .badge-diamond {background:#c7d2fe; color:#1e1b4b;}
  .badge-gold {background:#fde68a; color:#78350f;}
  .badge-silver {background:#e2e8f0; color:#334155;}
  .badge-intern {background:#bbf7d0; color:#064e3b;}
  .badge-parttime {background:#fbcfe8; color:#831843;}
  .badge-band {background:#0f172a; color:#e2e8f0;}
  .small-muted {color:#64748b; font-size:0.82rem;}
  img {max-width: 100%;}
</style>
""", unsafe_allow_html=True)

with open("config.yaml", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

db.init_db()

PRIORITY_BADGES = {
    "DIAMOND": ("💎 DIAMOND", "badge-diamond"),
    "GOLD": ("🥇 GOLD", "badge-gold"),
    "SILVER": ("🥈 SILVER", "badge-silver"),
    "STRATEGIC_INTERNSHIP": ("🎓 STRATEGIC INTERNSHIP", "badge-intern"),
    "HIGH_VALUE_PART_TIME": ("⏱️ HIGH-VALUE PART-TIME", "badge-parttime"),
}

st.title("🎯 Daniele Job Radar")
st.caption("Diamond · Gold · Silver · Strategic Internships · High-Value Part-Time — filtri obbligatori sempre attivi, nessuna informazione mancante viene inventata.")

DEFAULT_QUERIES = ["product manager", "product operations", "product marketing", "business analyst",
                    "digital transformation", "ai builder", "marketing operations", "customer insights"]

with st.expander("🔎 Filtri e fonti", expanded=False):
    threshold = st.slider("Compatibilità minima per essere mostrata (%)", 0, 100, 50, step=5)
    queries = st.multiselect("Parole chiave di ricerca", DEFAULT_QUERIES + ["crm analyst", "innovation analyst", "retail technology", "process improvement"], default=DEFAULT_QUERIES)
    base_sources = ["Himalayas", "Arbeitnow", "Remotive", "We Work Remotely"]
    optional_sources = []
    if connectors.adzuna_configured():
        optional_sources.append("Adzuna")
    else:
        st.caption("⚪ Adzuna: non configurato (opzionale — imposta ADZUNA_APP_ID/ADZUNA_APP_KEY per attivarlo, vedi .env.example)")
    if GMAIL_MODULE_OK and gmail_connector.gmail_configured():
        optional_sources.append("Gmail (LinkedIn/Indeed alert)")
    else:
        st.caption("⚪ Gmail: non configurato (opzionale e MAI testato in questo ambiente — vedi gmail_connector.py per l'attivazione)")
    sources_enabled = st.multiselect("Fonti attive", base_sources + optional_sources, default=base_sources + optional_sources)
    uploaded = st.file_uploader("Importa alert LinkedIn/Indeed (.eml)", type=["eml"], accept_multiple_files=True)

refresh = st.button("🔄 Aggiorna posizioni", type="primary", use_container_width=True)


@st.cache_data(ttl=1800, show_spinner=False)
def load(qs, sources):
    jobs, errors = [], []
    if "Himalayas" in sources:
        for q in qs:
            try:
                jobs.extend(connectors.fetch_himalayas(q, pages=2))
            except Exception as e:
                errors.append(f"Himalayas ({q}): {e}")
    if "Remotive" in sources:
        for q in qs:
            try:
                jobs.extend(connectors.fetch_remotive(q))
            except Exception as e:
                errors.append(f"Remotive ({q}): {e}")
    if "Adzuna" in sources:
        for q in qs:
            try:
                jobs.extend(connectors.fetch_adzuna(q))
            except Exception as e:
                errors.append(f"Adzuna ({q}): {e}")
    if "Arbeitnow" in sources:
        try:
            jobs.extend(connectors.fetch_arbeitnow(pages=2))
        except Exception as e:
            errors.append(f"Arbeitnow: {e}")
    if "We Work Remotely" in sources:
        try:
            jobs.extend(connectors.fetch_wwr())
        except Exception as e:
            errors.append(f"We Work Remotely: {e}")
    if "Gmail (LinkedIn/Indeed alert)" in sources and GMAIL_MODULE_OK:
        try:
            jobs.extend(gmail_connector.fetch_gmail_job_alerts())
        except Exception as e:
            errors.append(f"Gmail: {e}")
    return jobs, errors


if refresh or "jobs" not in st.session_state:
    with st.spinner("Raccolgo e valuto le posizioni..."):
        jobs, errors = load(tuple(queries), tuple(sources_enabled))
        for uf in uploaded or []:
            try:
                jobs.append(parse_eml_bytes(uf.getvalue(), "Email alert"))
            except Exception as e:
                errors.append(f"Import email {uf.name}: {e}")
        st.session_state.jobs = jobs
        st.session_state.errors = errors

jobs = st.session_state.get("jobs", [])

# --- dedup ---
unique = {}
for j in jobs:
    key = ((j.get("company") or "").lower().strip(), (j.get("title") or "").lower().strip(), (j.get("url") or "").split("?")[0])
    unique[key] = j

# --- assess + persist ---
assessed, filtered_out = [], []
watchlist = CFG.get("watchlist_companies", [])
for j in unique.values():
    try:
        result = scoring.assess(j, CFG, watchlist_companies=watchlist)
    except Exception as e:
        filtered_out.append({"title": j.get("title"), "company": j.get("company"), "filtered_out_reason": f"errore di valutazione: {e}"})
        continue
    if result.get("priority") is None:
        filtered_out.append(result)
    else:
        if result["score"] < threshold and result["priority"] not in ("STRATEGIC_INTERNSHIP", "HIGH_VALUE_PART_TIME"):
            result["penalties"] = result.get("penalties", []) + [f"punteggio {result['score']}% sotto la soglia visualizzata ({threshold}%)"]
            filtered_out.append(result)
            continue
        job_id = db.upsert_job(j, result["priority"], result["score"])
        result["job_id"] = job_id
        result["source_url"] = j.get("url")
        assessed.append(result)

status_map = db.get_status_map()
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
for r in assessed:
    row = status_map.get(r["job_id"], {})
    r["status"] = row.get("status", "new")
    r["notes"] = row.get("notes", "")
    r["date_first_seen"] = row.get("date_first_seen", today)

if st.session_state.get("errors"):
    with st.expander(f"⚠️ Avvisi connettori ({len(st.session_state['errors'])})"):
        for e in st.session_state["errors"]:
            st.warning(e)

# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------
def render_card(r, show_status_actions=True):
    badge_label, badge_class = PRIORITY_BADGES.get(r["priority"], (r["priority"] or "", "badge-silver"))
    with st.container(border=True):
        st.markdown(f'<span class="badge {badge_class}">{badge_label}</span> <span class="badge badge-band">{r.get("band","")} · {r.get("score","?")}%</span>', unsafe_allow_html=True)
        st.markdown(f"**{r.get('title','')}** — {r.get('company','')}")
        st.caption(f"Fonte: {r.get('source','')} · Confidenza: {r.get('confidence','')} · Pubblicato: {r.get('published_at') or 'n/d'}")
        st.write(f"**Esperienza richiesta:** {r.get('experience_required','')}")
        st.write(f"**Remote scope:** {r.get('remote_scope','')}")
        st.write(f"**Restrizioni geografiche:** {r.get('country_restrictions','')}")
        st.write(f"**Compenso:** {r.get('compensation','')}" + ("" if r.get("compensation_guaranteed") else "  \n_(non garantito/annualizzato automaticamente)_"))
        st.write(f"**Tipo di contratto:** {r.get('contract_type','')}")
        if r.get("is_watchlisted"):
            st.info("🏷️ Azienda nella watchlist — verificare comunque la singola vacancy per la reale politica di remote/ufficio.")
        if r.get("mandatory_found"):
            st.markdown("**Condizioni obbligatorie riscontrate:** " + "; ".join(r["mandatory_found"]))
        if r.get("preferred_found"):
            st.markdown("**Condizioni preferenziali riscontrate:** " + "; ".join(r["preferred_found"]))
        if r.get("reasons"):
            st.caption("Motivi del punteggio: " + " · ".join(r["reasons"]))
        if r.get("penalties"):
            st.caption("⚠️ " + " · ".join(r["penalties"]))
        if r.get("source_url"):
            st.link_button("Apri vacancy originale ↗", r["source_url"], use_container_width=True)
        summary = (f"{r.get('title')} — {r.get('company')} | {badge_label} | Fit {r.get('score')}% ({r.get('band')}) | "
                   f"{r.get('experience_required')} | {r.get('compensation')} | {r.get('remote_scope')} | {r.get('source_url')}")
        with st.expander("📋 Copia riepilogo posizione"):
            st.code(summary, language=None)
        if show_status_actions and r.get("job_id"):
            cols = st.columns(2)
            new_status = cols[0].selectbox("Stato", db.VALID_STATUSES, index=db.VALID_STATUSES.index(r.get("status", "new")), key=f"status_{r['job_id']}")
            if new_status != r.get("status"):
                db.set_status(r["job_id"], new_status)
                st.rerun()
            notes = cols[1].text_input("Note", value=r.get("notes", ""), key=f"notes_{r['job_id']}")
            if notes != r.get("notes", ""):
                db.set_notes(r["job_id"], notes)


def render_filtered_row(r):
    with st.container(border=True):
        st.markdown(f"**{r.get('title') or '(titolo non disponibile)'}** — {r.get('company') or ''}")
        st.caption(r.get("filtered_out_reason", ""))


# ---------------------------------------------------------------------------
# metrics + CSV export
# ---------------------------------------------------------------------------
c1, c2, c3 = st.columns(3)
c1.metric("Raccolte", len(jobs))
c2.metric("Valutate", len(assessed))
c3.metric("Escluse", len(filtered_out))

if assessed:
    df = pd.DataFrame([{k: r.get(k) for k in ["title", "company", "source", "priority", "score", "band", "confidence",
                                                 "experience_required", "compensation", "remote_scope", "contract_type",
                                                 "status", "source_url"]} for r in assessed])
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Esporta CSV", csv_bytes, file_name="daniele_job_radar_export.csv", mime="text/csv", use_container_width=True)

# ---------------------------------------------------------------------------
# section selector (single dropdown -> no horizontal scrolling, phone-friendly)
# ---------------------------------------------------------------------------
def count(pred):
    return sum(1 for r in assessed if pred(r))


sections = {
    f"🆕 New Today ({count(lambda r: r.get('date_first_seen') == today)})": lambda: [r for r in assessed if r.get("date_first_seen") == today],
    f"💎 Diamond ({count(lambda r: r['priority']=='DIAMOND' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "DIAMOND" and r["status"] in ("new", "saved")],
    f"🥇 Gold ({count(lambda r: r['priority']=='GOLD' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "GOLD" and r["status"] in ("new", "saved")],
    f"🥈 Silver ({count(lambda r: r['priority']=='SILVER' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "SILVER" and r["status"] in ("new", "saved")],
    f"🎓 Strategic Internships ({count(lambda r: r['priority']=='STRATEGIC_INTERNSHIP')})": lambda: [r for r in assessed if r["priority"] == "STRATEGIC_INTERNSHIP"],
    f"⏱️ High-Value Part-Time ({count(lambda r: r['priority']=='HIGH_VALUE_PART_TIME')})": lambda: [r for r in assessed if r["priority"] == "HIGH_VALUE_PART_TIME"],
    f"🏷️ Watchlist Companies ({count(lambda r: r.get('is_watchlisted') and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r.get("is_watchlisted") and r["status"] in ("new", "saved")],
    f"💰 Salary Not Disclosed ({count(lambda r: r.get('compensation')=='Salary not disclosed' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r.get("compensation") == "Salary not disclosed" and r["status"] in ("new", "saved")],
    f"📍 Remote Arrangement to Verify ({count(lambda r: 'requires confirmation' in (r.get('remote_scope') or '') and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if "requires confirmation" in (r.get("remote_scope") or "") and r["status"] in ("new", "saved")],
    f"✅ Applied ({count(lambda r: r['status']=='applied')})": lambda: [r for r in assessed if r["status"] == "applied"],
    f"🗣️ Interviewing ({count(lambda r: r['status']=='interviewing')})": lambda: [r for r in assessed if r["status"] == "interviewing"],
    f"❌ Rejected ({count(lambda r: r['status']=='rejected')})": lambda: [r for r in assessed if r["status"] == "rejected"],
    f"📦 Archived ({count(lambda r: r['status']=='archived')})": lambda: [r for r in assessed if r["status"] == "archived"],
    f"🚫 Filtered Out with Reasons ({len(filtered_out)})": lambda: None,  # handled separately below
}

section_name = st.selectbox("Sezione", list(sections.keys()))
st.divider()

if section_name.startswith("🚫 Filtered Out"):
    if not filtered_out:
        st.caption("Nessuna posizione esclusa in questa sessione.")
    else:
        for r in filtered_out:
            render_filtered_row(r)
else:
    rows = sections[section_name]()
    rows = sorted(rows, key=lambda r: r.get("score", 0), reverse=True)
    if not rows:
        st.info("Nessuna posizione in questa sezione al momento. Prova ad abbassare la soglia di compatibilità o ad aggiornare le posizioni.")
    for r in rows[:150]:
        render_card(r)

st.divider()
st.caption(
    "Fonti: Himalayas, Arbeitnow, Remotive (attribuzione richiesta), We Work Remotely (RSS ufficiali)"
    + (", Adzuna" if connectors.adzuna_configured() else "")
    + ". Lo scoring è euristico e i requisiti obbligatori non vengono mai superati da un punteggio alto. "
      "Nessuna informazione mancante viene inventata: quando manca, viene esplicitamente segnalata."
)
