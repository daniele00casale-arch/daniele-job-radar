import io
import json
import os
from datetime import datetime, timezone

import pandas as pd
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
  .badge-potential {background:#ede9fe; color:#4c1d95; border:1px dashed #7c3aed;}
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

# ---------------------------------------------------------------------------
# Gmail OAuth callback - Google redirects the browser back to THIS app's own
# URL with ?code=...&state=... after the person approves the consent screen
# (wizard step 5). This is a brand-new page load (a new Streamlit session),
# so it's handled unconditionally at the top of every run, before any UI is
# built, using only what gmail_oauth.py stored server-side (never
# session_state, which would already be gone by now).
# ---------------------------------------------------------------------------
if GMAIL_MODULE_OK:
    qp = st.query_params
    if "code" in qp and "state" in qp:
        try:
            gmail_oauth.exchange_code(qp["code"], qp["state"])
            st.session_state["gmail_wizard_message"] = ("success", "✅ Gmail connesso correttamente.")
        except Exception as e:
            st.session_state["gmail_wizard_message"] = ("error", f"Connessione Gmail non riuscita: {e}")
        st.query_params.clear()
        st.rerun()
    if "error" in qp:  # Google itself reports a denial/error via ?error=...
        st.session_state["gmail_wizard_message"] = ("error", f"Google ha segnalato un errore: {qp['error']}")
        st.query_params.clear()
        st.rerun()

PRIORITY_BADGES = {
    "DIAMOND": ("💎 DIAMOND", "badge-diamond"),
    "POTENTIAL_DIAMOND": ("💎 POTENTIAL DIAMOND", "badge-potential"),
    "GOLD": ("🥇 GOLD", "badge-gold"),
    "POTENTIAL_GOLD": ("🥇 POTENTIAL GOLD", "badge-potential"),
    "SILVER": ("🥈 SILVER", "badge-silver"),
    "POTENTIAL_SILVER": ("🥈 POTENTIAL SILVER", "badge-potential"),
    "STRATEGIC_INTERNSHIP": ("🎓 STRATEGIC INTERNSHIP", "badge-intern"),
    "HIGH_VALUE_PART_TIME": ("⏱️ HIGH-VALUE PART-TIME", "badge-parttime"),
}

st.title("🎯 Daniele Job Radar")
st.caption("Diamond · Gold · Silver (+ Potential) · Strategic Internships · High-Value Part-Time — "
           "filtri obbligatori sempre attivi, nessuna informazione mancante viene inventata.")

DEFAULT_QUERIES = ["product manager", "product operations", "product marketing", "business analyst",
                    "digital transformation", "ai builder", "marketing operations", "customer insights"]

with st.expander("🔎 Filtri e fonti", expanded=False):
    threshold = st.slider("Compatibilità minima per essere mostrata (%)", 0, 100, 40, step=5,
                           help="Abbassala se vedi poche posizioni: Diamond/Gold/Silver hanno comunque le loro regole obbligatorie separate, non vengono mai bypassate da questo slider.")
    queries = st.multiselect("Parole chiave di ricerca", DEFAULT_QUERIES + ["crm analyst", "innovation analyst", "retail technology", "process improvement", "category manager", "growth analyst"], default=DEFAULT_QUERIES)
    base_sources = ["Himalayas", "Arbeitnow", "Remotive", "We Work Remotely", "The Muse", "Remote OK"]
    optional_sources = []
    if connectors.adzuna_configured():
        optional_sources.append("Adzuna")
    else:
        st.caption("⚪ Adzuna: non configurato (opzionale — imposta ADZUNA_APP_ID/ADZUNA_APP_KEY, vedi CONNECTOR_SETUP.md)")
    if connectors.jooble_configured("it") or connectors.jooble_configured("ch"):
        optional_sources.append("Jooble")
    else:
        st.caption("⚪ Jooble: non configurato (opzionale — imposta JOOBLE_API_KEY_IT/JOOBLE_API_KEY_CH, vedi CONNECTOR_SETUP.md)")
    if GMAIL_MODULE_OK and gmail_connector.gmail_connected():
        optional_sources.append("Gmail (LinkedIn/Indeed/Company alert)")
    else:
        st.caption("⚪ Gmail: non connesso — apri **🔗 Configura Gmail** qui sotto per collegarlo in pochi passi.")
    include_ats = st.checkbox("Includi connettori aziendali watchlist (Greenhouse/Lever/Ashby/...)", value=True)
    sources_enabled = st.multiselect("Fonti aggregatore attive", base_sources + optional_sources, default=base_sources + optional_sources)
    uploaded = st.file_uploader("Importa manualmente un alert LinkedIn/Indeed/azienda (.eml) — fallback se non usi Gmail",
                                 type=["eml"], accept_multiple_files=True)

    st.divider()
    st.markdown("**📄 Usa il tuo CV per il matching (opzionale)**")
    st.caption("Carica il tuo CV: viene letto solo in questa sessione del browser (non viene salvato da nessuna parte) "
               "ed estrae parole chiave di ruolo/competenza da confrontare con le descrizioni degli annunci, "
               "in aggiunta a quelle già scritte in config.yaml. Rivedi tu quali tenere prima che vengano usate.")
    cv_file = st.file_uploader("Il tuo CV (PDF, DOCX o TXT)", type=["pdf", "docx", "txt", "md"], key="cv_upload")
    cv_keywords_accepted = st.session_state.get("cv_keywords_accepted", [])
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
            st.warning(f"Non sono riuscito a leggere il CV: {st.session_state['cv_error']}")
        elif st.session_state.get("cv_keywords_found"):
            st.caption("Parole chiave trovate nel CV — togli la spunta a quelle che non vuoi usare per il matching:")
            cv_keywords_accepted = []
            for i, kw in enumerate(st.session_state["cv_keywords_found"]):
                if st.checkbox(kw, value=True, key=f"cvkw_{i}"):
                    cv_keywords_accepted.append(kw)
            st.session_state.cv_keywords_accepted = cv_keywords_accepted
            if st.button("🗑️ Rimuovi CV e parole chiave da questa sessione"):
                for k in ("cv_sig", "cv_keywords_found", "cv_keywords_accepted", "cv_error"):
                    st.session_state.pop(k, None)
                st.rerun()

    st.divider()
    st.markdown("**Privacy e dati (sezione 29)**")
    pcol1, pcol2 = st.columns(2)
    if pcol1.button("🗑️ Elimina storico posizioni locale"):
        db.delete_all_job_history()
        st.success("Storico posizioni eliminato.")
    if pcol2.button("📤 Esporta i miei dati"):
        data = db.export_all_data()
        st.download_button("⬇️ Scarica JSON", json.dumps(data, indent=2, default=str).encode("utf-8"),
                            file_name="job_radar_export.json", mime="application/json")
    if GMAIL_MODULE_OK:
        if st.button("🗑️ Elimina dati email importati"):
            db.delete_gmail_processed_ids()
            st.success("ID messaggi Gmail elaborati eliminati (i messaggi stessi non vengono mai toccati).")

# ---------------------------------------------------------------------------
# Gmail setup wizard (spec: OAuth, gmail.readonly only, three labels,
# Connect/Disconnect buttons, no file editing, no terminal, no password).
# ---------------------------------------------------------------------------
with st.expander("🔗 Configura Gmail (wizard guidato, 5 passi)", expanded=not (GMAIL_MODULE_OK and gmail_connector.gmail_connected())):
    if not GMAIL_MODULE_OK:
        st.error("Le librerie Gmail non sono installate in questo ambiente. Verifica che requirements.txt contenga "
                 "google-api-python-client, google-auth-oauthlib, google-auth-httplib2, cryptography e riavvia il deploy.")
    else:
        msg = st.session_state.pop("gmail_wizard_message", None)
        if msg:
            (st.success if msg[0] == "success" else st.error)(msg[1])

        st.caption("La tua password Gmail non viene mai richiesta né vista da questa app. L'accesso e l'autorizzazione "
                   "avvengono sempre sulla pagina ufficiale di Google (accounts.google.com). L'unico permesso richiesto è "
                   "**di sola lettura** (gmail.readonly): questa app non può modificare, etichettare, inviare, inoltrare, "
                   "archiviare o eliminare nessuna email.")

        connected = gmail_connector.gmail_connected()

        st.markdown("#### Passo 1 — Crea o conferma le tre etichette Gmail")
        st.caption("Vanno create nella tua casella Gmail (una sola volta). Copia esattamente questi tre nomi:")
        for lbl in gmail_oauth.DEFAULT_LABELS.values():
            st.code(lbl, language=None)
        st.link_button("Apri Impostazioni Gmail → Etichette ↗", "https://mail.google.com/mail/u/0/#settings/labels",
                        use_container_width=True)
        st.caption("Suggerimento: crea anche un filtro per ciascuna (Impostazioni → Filtri) che applichi automaticamente "
                   "l'etichetta corrispondente alle email di LinkedIn/Indeed/altre aziende — vedi GMAIL_OAUTH_SETUP.md.")
        labels_confirmed = st.checkbox("✅ Ho creato/confermato le tre etichette", value=st.session_state.get("gmail_labels_confirmed", False))
        st.session_state["gmail_labels_confirmed"] = labels_confirmed

        st.markdown("#### Passo 2 — Client ID e Client Secret di Google")
        client_source = gmail_oauth.client_config_source()
        if client_source in ("streamlit_secrets", "env"):
            where = "Streamlit Secrets" if client_source == "streamlit_secrets" else "variabili d'ambiente (.env)"
            st.success(f"Client ID/Secret trovati in {where} — il wizard li userà automaticamente, non serve altro qui.")
        else:
            st.caption("Da creare una sola volta nel tuo progetto Google Cloud (vedi GMAIL_OAUTH_SETUP.md per la procedura "
                       "passo-passo con screenshot). Il Client Secret viene salvato **cifrato** nel database locale di questa "
                       "app, non in chiaro, e non viene mai più mostrato dopo il salvataggio.")
            st.link_button("Apri Google Cloud Console → Credenziali ↗", gmail_oauth.GOOGLE_CLOUD_CREDENTIALS_URL,
                            use_container_width=True)
            with st.form("gmail_client_config_form", clear_on_submit=True):
                in_client_id = st.text_input("Client ID")
                in_client_secret = st.text_input("Client Secret", type="password")
                saved = st.form_submit_button("💾 Salva credenziali OAuth")
            if saved:
                try:
                    gmail_oauth.save_client_config(in_client_id, in_client_secret)
                    st.success("Credenziali salvate (cifrate).")
                    st.rerun()
                except Exception as e:
                    st.error(f"Non salvate: {e}")
            if gmail_oauth.has_client_config():
                st.success("✅ Client ID/Secret già configurati per questa app (valore non mostrato per sicurezza).")
                if st.button("🗑️ Rimuovi credenziali OAuth salvate"):
                    gmail_oauth.clear_client_config()
                    st.rerun()

        st.markdown("#### Passo 3 — Copia l'URI di reindirizzamento esatto in Google Cloud")
        detected_base = gmail_oauth.detect_redirect_base_url()
        if detected_base:
            redirect_base = detected_base
            st.caption("Rilevato automaticamente dall'app in esecuzione:")
        else:
            st.caption("Non sono riuscito a rilevare automaticamente l'URL di questa app (succede in alcuni ambienti locali). "
                       "Incolla qui l'URL con cui apri l'app nel browser (es. https://tuo-progetto.streamlit.app):")
            redirect_base = st.text_input("URL di questa app", value=st.session_state.get("gmail_manual_base_url", ""))
            st.session_state["gmail_manual_base_url"] = redirect_base
        redirect_uri = gmail_oauth.redirect_uri_from_base(redirect_base) if redirect_base else None
        if redirect_uri:
            st.code(redirect_uri, language=None)
            st.caption("In Google Cloud Console → Credenziali → il tuo Client OAuth → 'URI di reindirizzamento autorizzati' → "
                       "'Aggiungi URI' → incolla esattamente il valore sopra → Salva.")

        st.markdown("#### Passo 4 — Connetti Gmail")
        if connected:
            st.success("✅ Gmail è già connesso.")
        elif not gmail_oauth.has_client_config():
            st.info("Completa prima il passo 2.")
        elif not redirect_uri:
            st.info("Completa prima il passo 3.")
        else:
            try:
                auth_url, _ = gmail_oauth.build_authorization_url(redirect_uri)
                st.link_button("🔐 Connetti Gmail (apre la schermata di autorizzazione Google)", auth_url, use_container_width=True)
            except Exception as e:
                st.error(f"Non riesco a preparare la connessione: {e}")

        st.markdown("#### Passo 5 — Approva la schermata di autorizzazione Google")
        st.caption("Dopo aver cliccato 'Connetti Gmail', Google mostrerà la sua pagina ufficiale con il permesso richiesto "
                   "('Visualizza i messaggi email e le impostazioni' — di sola lettura). Approvandolo, Google reindirizza "
                   "automaticamente qui e questa pagina mostrerà '✅ Gmail connesso correttamente'.")

        st.divider()
        if connected:
            connected_email = st.session_state.get("gmail_connected_email")
            if connected_email is None:
                try:
                    connected_email = gmail_oauth.connected_email_address()
                except Exception as e:
                    connected_email = f"(non verificabile ora: {e})"
                st.session_state["gmail_connected_email"] = connected_email
            st.write(f"**Account Gmail connesso:** {connected_email}")
            gcol1, gcol2 = st.columns(2)
            if gcol1.button("🔌 Disconnetti Gmail", use_container_width=True):
                gmail_connector.disconnect_gmail()
                st.session_state.pop("gmail_connected_email", None)
                st.success("Token Gmail rimosso da questa app.")
                st.rerun()
            gcol2.link_button("Revoca l'accesso su Google ↗", gmail_oauth.REVOKE_URL, use_container_width=True)
            st.caption("'Disconnetti Gmail' rimuove solo il token salvato da questa app. Per rimuovere del tutto l'accesso "
                       "dal tuo account Google, usa 'Revoca l'accesso su Google'.")

refresh = st.button("🔄 Aggiorna posizioni", type="primary", use_container_width=True)


@st.cache_data(ttl=1800, show_spinner=False)
def load(qs, sources, include_ats_flag, ats_directory_json):
    jobs, errors, statuses = [], [], []

    def run(source_name, fn):
        try:
            result = fn()
            statuses.append({"source": source_name, "status": "ok" if result else "ok_zero_results",
                              "jobs_retrieved": len(result), "error": None})
            jobs.extend(result)
        except Exception as e:
            errors.append(f"{source_name}: {e}")
            statuses.append({"source": source_name, "status": "failed", "jobs_retrieved": 0, "error": str(e)})

    if "Himalayas" in sources:
        for q in qs:
            run(f"Himalayas ({q})", lambda q=q: connectors.fetch_himalayas(q, pages=2))
    if "Remotive" in sources:
        for q in qs:
            run(f"Remotive ({q})", lambda q=q: connectors.fetch_remotive(q))
    if "The Muse" in sources:
        run("The Muse", lambda: connectors.fetch_the_muse(pages=1))
    if "Remote OK" in sources:
        run("Remote OK", lambda: connectors.fetch_remoteok("product"))
    if "Adzuna" in sources:
        for q in qs:
            run(f"Adzuna ({q})", lambda q=q: connectors.fetch_adzuna(q))
    if "Jooble" in sources:
        if connectors.jooble_configured("it"):
            run("Jooble (IT)", lambda: connectors.fetch_jooble("product manager", market="it"))
        if connectors.jooble_configured("ch"):
            run("Jooble (CH)", lambda: connectors.fetch_jooble("product manager", market="ch"))
    if "Arbeitnow" in sources:
        run("Arbeitnow", lambda: connectors.fetch_arbeitnow(pages=2))
    if "We Work Remotely" in sources:
        run("We Work Remotely", lambda: connectors.fetch_wwr())
    gmail_failures = []
    if "Gmail (LinkedIn/Indeed/Company alert)" in sources and GMAIL_MODULE_OK:
        try:
            gmail_jobs, gmail_failures = gmail_connector.fetch_gmail_job_alerts()
            statuses.append({"source": "Gmail", "status": "ok" if gmail_jobs else "ok_zero_results",
                              "jobs_retrieved": len(gmail_jobs), "error": None})
            jobs.extend(gmail_jobs)
        except Exception as e:
            errors.append(f"Gmail: {e}")
            statuses.append({"source": "Gmail", "status": "failed", "jobs_retrieved": 0, "error": str(e)})

    if include_ats_flag:
        ats_directory = json.loads(ats_directory_json)
        for company, entry in ats_directory.items():
            ats_jobs, status = ats_connectors.fetch_for_directory_entry(company, entry)
            jobs.extend(ats_jobs)
            statuses.append({"source": f"{company} ({status['ats']})", "status": status["status"],
                              "jobs_retrieved": status["jobs_retrieved"], "error": status["error"]})
            if status["error"]:
                errors.append(f"{company} ({status['ats']}): {status['error']}")

    return jobs, errors, statuses, gmail_failures


if refresh or "jobs" not in st.session_state:
    with st.spinner("Raccolgo e valuto le posizioni..."):
        jobs, errors, statuses, gmail_parsing_failures = load(tuple(queries), tuple(sources_enabled), include_ats, json.dumps(CFG.get("ats_directory", {})))
        st.session_state.gmail_parsing_failures = gmail_parsing_failures
        eml_parsing_failures = []
        for uf in uploaded or []:
            try:
                for rec in parse_eml_bytes(uf.getvalue(), "Email alert"):
                    if rec.get("parsing_failed"):
                        eml_parsing_failures.append(rec)
                    else:
                        jobs.append(rec)
            except Exception as e:
                errors.append(f"Import email {uf.name}: {e}")
        st.session_state.eml_parsing_failures = eml_parsing_failures
        st.session_state.jobs = jobs
        st.session_state.errors = errors
        st.session_state.statuses = statuses
        for s in statuses:
            db.record_connector_status(s["source"], s["status"], jobs_retrieved=s["jobs_retrieved"],
                                        connection_error=s["error"], configured=True)

jobs = st.session_state.get("jobs", [])

# --- dedup ---
unique = {}
duplicates_removed = 0
for j in jobs:
    key = ((j.get("company") or "").lower().strip(), (j.get("title") or "").lower().strip(), (j.get("url") or "").split("?")[0])
    if key in unique:
        duplicates_removed += 1
    unique[key] = j

# --- assess + persist ---
# If the user uploaded a CV and approved some extracted keywords, score
# against a COPY of the config with those keywords merged into the profile
# - config.yaml on disk is never modified, and nothing about the CV is
# persisted anywhere (session-only, per cv_parser.py's own docstring).
EFFECTIVE_CFG = CFG
cv_keywords_accepted = st.session_state.get("cv_keywords_accepted", [])
if cv_keywords_accepted:
    EFFECTIVE_CFG = dict(CFG)
    EFFECTIVE_CFG["profile"] = cv_parser.build_augmented_profile(CFG["profile"], cv_keywords_accepted)
    st.caption(f"🎯 Matching arricchito con {len(cv_keywords_accepted)} parole chiave dal tuo CV.")

assessed, filtered_out, diagnostics = [], [], []
watchlist = EFFECTIVE_CFG.get("watchlist_companies", [])
for j in unique.values():
    try:
        result = scoring.assess(j, EFFECTIVE_CFG, watchlist_companies=watchlist)
    except Exception as e:
        result = {"title": j.get("title"), "company": j.get("company"), "filtered_out_reason": f"errore di valutazione: {e}", "priority": None}
        filtered_out.append(result)
        diagnostics.append({"source": j.get("source"), "title": j.get("title"), "company": j.get("company"),
                             "fields_received": [], "fields_missing": [], "score_before_hard_filters": None,
                             "hard_filters_passed": False, "hard_filters_failed": ["exception during scoring"],
                             "classification": "PARSING_FAILURE", "exclusion_reason": str(e), "confidence": "Low", "rejection_tags": []})
        continue
    diagnostics.append(scoring.diagnose(j, result))
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

db.log_refresh(len(jobs), len(assessed), len(filtered_out), len(st.session_state.get("errors", [])))

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
st.caption(f"Duplicati rimossi in questo aggiornamento: {duplicates_removed}")

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


watchlist_not_qualified = [r for r in filtered_out if r.get("is_watchlisted")]
experience_to_verify = [r for r in assessed if "not clearly stated" in (r.get("experience_required") or "")]
parsing_failures = [d for d in diagnostics if d["classification"] == "PARSING_FAILURE"]
parsing_failures += [{"source": r.get("source"), "title": r.get("title"), "company": "",
                       "exclusion_reason": r.get("description")} for r in st.session_state.get("eml_parsing_failures", [])]
parsing_failures += [{"source": r.get("source"), "title": r.get("title"), "company": "",
                       "exclusion_reason": r.get("description")} for r in st.session_state.get("gmail_parsing_failures", [])]

sections = {
    f"🆕 New Today ({count(lambda r: r.get('date_first_seen') == today)})": lambda: [r for r in assessed if r.get("date_first_seen") == today],
    f"💎 Diamond ({count(lambda r: r['priority']=='DIAMOND' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "DIAMOND" and r["status"] in ("new", "saved")],
    f"💎 Potential Diamond ({count(lambda r: r['priority']=='POTENTIAL_DIAMOND' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "POTENTIAL_DIAMOND" and r["status"] in ("new", "saved")],
    f"🥇 Gold ({count(lambda r: r['priority']=='GOLD' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "GOLD" and r["status"] in ("new", "saved")],
    f"🥇 Potential Gold ({count(lambda r: r['priority']=='POTENTIAL_GOLD' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "POTENTIAL_GOLD" and r["status"] in ("new", "saved")],
    f"🥈 Silver ({count(lambda r: r['priority']=='SILVER' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "SILVER" and r["status"] in ("new", "saved")],
    f"🥈 Potential Silver ({count(lambda r: r['priority']=='POTENTIAL_SILVER' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r["priority"] == "POTENTIAL_SILVER" and r["status"] in ("new", "saved")],
    f"🎓 Strategic Internships ({count(lambda r: r['priority']=='STRATEGIC_INTERNSHIP')})": lambda: [r for r in assessed if r["priority"] == "STRATEGIC_INTERNSHIP"],
    f"⏱️ High-Value Part-Time ({count(lambda r: r['priority']=='HIGH_VALUE_PART_TIME')})": lambda: [r for r in assessed if r["priority"] == "HIGH_VALUE_PART_TIME"],
    f"🏷️ Company Watchlist ({count(lambda r: r.get('is_watchlisted') and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r.get("is_watchlisted") and r["status"] in ("new", "saved")],
    f"🏷️ Watchlist Matches, Not Qualified ({len(watchlist_not_qualified)})": None,
    f"💰 Salary Not Disclosed ({count(lambda r: r.get('compensation')=='Salary not disclosed' and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if r.get("compensation") == "Salary not disclosed" and r["status"] in ("new", "saved")],
    f"📍 Remote Scope to Verify ({count(lambda r: 'requires confirmation' in (r.get('remote_scope') or '') and r['status'] in ('new','saved'))})": lambda: [r for r in assessed if "requires confirmation" in (r.get("remote_scope") or "") and r["status"] in ("new", "saved")],
    f"🧭 Experience to Verify ({len(experience_to_verify)})": lambda: experience_to_verify,
    f"✅ Applied ({count(lambda r: r['status']=='applied')})": lambda: [r for r in assessed if r["status"] == "applied"],
    f"🗣️ Interviewing ({count(lambda r: r['status']=='interviewing')})": lambda: [r for r in assessed if r["status"] == "interviewing"],
    f"❌ Rejected ({count(lambda r: r['status']=='rejected')})": lambda: [r for r in assessed if r["status"] == "rejected"],
    f"📦 Archived ({count(lambda r: r['status']=='archived')})": lambda: [r for r in assessed if r["status"] == "archived"],
    f"🚫 Filtered Out with Reasons ({len(filtered_out)})": "filtered",
    f"🔌 Connector Status ({len(st.session_state.get('statuses', []))})": "connector_status",
    f"⚠️ Parsing Failures ({len(parsing_failures)})": "parsing_failures",
    f"🩺 Diagnostic Report ({len(diagnostics)})": "diagnostic",
}

section_name = st.selectbox("Sezione", list(sections.keys()))
st.divider()

target = sections[section_name]

if target == "filtered":
    if not filtered_out:
        st.caption("Nessuna posizione esclusa in questa sessione.")
    else:
        for r in filtered_out:
            render_filtered_row(r)
elif section_name.startswith("🏷️ Watchlist Matches"):
    if not watchlist_not_qualified:
        st.caption("Nessuna azienda in watchlist con vacancy non qualificata in questa sessione.")
    for r in watchlist_not_qualified:
        render_filtered_row(r)
elif target == "connector_status":
    st.caption("Distingue: successo/zero risultati, fallito, non configurato, non supportato, rate-limited. "
               "Zero risultati NON è automaticamente prova che un connettore funzioni.")
    rows = st.session_state.get("statuses", [])
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    last = db.last_refresh()
    if last:
        st.caption(f"Ultimo refresh: {last['ts']} · raccolte {last['total_collected']} · valutate {last['total_assessed']} · escluse {last['total_filtered']} · errori {last['errors_count']}")
elif target == "parsing_failures":
    if not parsing_failures:
        st.caption("Nessun errore di parsing in questa sessione.")
    for d in parsing_failures:
        with st.container(border=True):
            st.markdown(f"**{d.get('title') or '(n/d)'}** — {d.get('company') or ''} ({d.get('source') or ''})")
            st.caption(d.get("exclusion_reason", ""))
elif target == "diagnostic":
    st.caption("Una riga per ogni posizione raccolta: fonte, campi ricevuti/mancanti, punteggio pre-filtri, "
               "filtri obbligatori superati/falliti, classificazione, motivo di esclusione, confidenza.")
    if diagnostics:
        rows = [{
            "source": d["source"], "title": d["title"], "company": d["company"],
            "fields_missing": ", ".join(d["fields_missing"]),
            "score_pre_filters": d["score_before_hard_filters"],
            "hard_filters_passed": d["hard_filters_passed"],
            "classification": d["classification"], "exclusion_reason": d["exclusion_reason"],
            "confidence": d["confidence"], "rejection_tags": ", ".join(d["rejection_tags"]),
        } for d in diagnostics]
        df_diag = pd.DataFrame(rows)
        st.dataframe(df_diag, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Esporta diagnostica CSV", df_diag.to_csv(index=False).encode("utf-8"),
                            file_name="diagnostic_report.csv", mime="text/csv", use_container_width=True)
        st.markdown("**Riepilogo motivi di esclusione:**")
        tag_counts = {}
        for d in diagnostics:
            for t in d["rejection_tags"]:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        if tag_counts:
            st.dataframe(pd.DataFrame(sorted(tag_counts.items(), key=lambda x: -x[1]), columns=["motivo", "conteggio"]),
                         use_container_width=True, hide_index=True)
else:
    rows = target()
    rows = sorted(rows, key=lambda r: r.get("score", 0), reverse=True)
    if not rows:
        st.info("Nessuna posizione in questa sezione al momento. Prova ad abbassare la soglia di compatibilità, "
                "controlla 'Connector Status' per vedere se una fonte ha fallito, o guarda 'Filtered Out with Reasons'.")
    for r in rows[:150]:
        render_card(r)

st.divider()
st.caption(
    "Fonti aggregatore: Himalayas, Arbeitnow, Remotive, We Work Remotely (RSS), The Muse, Remote OK"
    + (", Adzuna" if connectors.adzuna_configured() else "")
    + (", Jooble" if (connectors.jooble_configured('it') or connectors.jooble_configured('ch')) else "")
    + ". Connettori aziendali diretti (watchlist): Greenhouse/Lever/Ashby dove configurato in config.yaml. "
      "Lo scoring è euristico e i requisiti obbligatori non vengono mai superati da un punteggio alto. "
      "Nessuna informazione mancante viene inventata: quando manca, viene esplicitamente segnalata."
)
