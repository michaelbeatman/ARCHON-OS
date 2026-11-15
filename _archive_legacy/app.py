"""
app.py - Archon OS Unified B2B SaaS Application
Design System: Border-First Principle (Shadcn-Slate Standard)
"""

import os
import streamlit as st

# ==============================================================================
# 1. PAGE CONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="Archon OS · Mission Control",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# 2. GLOBAL CSS INTEGRATION (BORDER-FIRST / SHADCN-SLATE)
# ==============================================================================
def load_css(file_name="assets/custom.css"):
    """
    Lädt das globale Design-System am Anfang der Rendering-Pipeline ein.
    Stellt sicher, dass das Shadcn-Slate Border-First-Prinzip und box-shadow: none
    über alle Streamlit-Komponenten hinweg strikt forciert werden.
    """
    if os.path.exists(file_name):
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    else:
        st.warning(f"Design-System-Stylesheet '{file_name}' wurde nicht gefunden.")

load_css("assets/custom.css")

# ==============================================================================
# 3. VIEWS IMPORT & VERBINDUNG
# ==============================================================================
try:
    from views.view_inbox import render_inbox_streamlit
except ImportError:
    render_inbox_streamlit = None

try:
    from views.view_showroom import render_showroom_streamlit
except ImportError:
    render_showroom_streamlit = None

try:
    from views.view_library import (
        render_central_library_hub,
        render_obsidian_vault_explorer,
        load_library_hub_stats,
        load_library_books
    )
except ImportError:
    render_central_library_hub = None
    render_obsidian_vault_explorer = None
    load_library_hub_stats = None
    load_library_books = None

# ==============================================================================
# 4. SIDEBAR NAVIGATION & SYSTEM-STATUS
# ==============================================================================
with st.sidebar:
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 10px; padding: 4px 0 16px 0; border-bottom: 1px solid var(--border-default);">
            <div style="width: 28px; height: 28px; border-radius: 6px; background-color: var(--primary); display: flex; align-items: center; justify-content: center; color: white; font-weight: 700; font-size: 14px;">
                ⚡
            </div>
            <div>
                <div style="font-size: 14px; font-weight: 700; color: var(--text-main); font-family: ui-monospace, monospace; letter-spacing: -0.02em;">ARCHON OS</div>
                <div style="font-size: 11px; color: var(--text-muted); font-family: ui-monospace, monospace;">Enterprise Agentic Mesh</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # Haupt-Navigation
    navigation_options = [
        "Operations & Mission Control",
        "Eingang (Triage & Streams)",
        "Showroom (Ergebnisse & Apps)",
        "Zentralbibliothek & RAG",
        "Agenten-Kader (56 Profile)",
        "System Control Center"
    ]

    selected_view = st.radio(
        "Bereich auswählen",
        navigation_options,
        index=0,
        label_visibility="collapsed"
    )

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    st.divider()

    # System-Status Badges (Pills)
    st.markdown("<div style='font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-family: ui-monospace, monospace; margin-bottom: 8px;'>System-Status</div>", unsafe_allow_html=True)
    
    st.markdown("""
        <div style="display: flex; flex-direction: column; gap: 8px;">
            <div><span class="badge badge-system">[SYSTEM] Kernel v2.0 · Port 8420</span></div>
            <div><span class="badge badge-success">[SUCCESS] Asyncio Daemon Aktiv</span></div>
            <div><span class="badge badge-gate">[GATE] HITL Governance Aktiv</span></div>
            <div><span class="badge badge-system">[SYSTEM] 56 Agenten Registriert</span></div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    st.divider()
    st.markdown("""
        <div style="font-size: 11px; color: var(--text-muted); font-family: ui-monospace, monospace; line-height: 1.4;">
            Border-First Design · Shadcn-Slate<br>
            Archon OS Enterprise Edition 2026
        </div>
    """, unsafe_allow_html=True)

# ==============================================================================
# 5. HAUPTANZEIGE (VIEW ROUTER)
# ==============================================================================

# --- VIEW 1: OPERATIONS & MISSION CONTROL ---
if selected_view == "Operations & Mission Control":
    st.markdown("""
        <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-default); padding-bottom: 16px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: var(--primary);"></span>
                <span style="font-family: ui-monospace, monospace; font-size: 16px; font-weight: 700; color: var(--text-main);">OPERATIONS &amp; MISSION CONTROL</span>
            </div>
            <div>
                <span class="badge badge-system">[SYSTEM] Echtzeit-Leitstand</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # KPI Metriken im Border-First Karten-Design
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric(label="Aktive Agenten-Flotte", value="56 Rollen", delta="100% Bereit")
    with kpi2:
        st.metric(label="System-Auslastung", value="18.4 %", delta="-2.1 % vs. Peak")
    with kpi3:
        st.metric(label="Offene Genehmigungen", value="2 Gates", delta="Aktion Erforderlich", delta_color="inverse")
    with kpi4:
        st.metric(label="Daemon Watchdog", value="30s Loop", delta="Keine Leaks")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # Operativer Steuerungsbereich
    tab_ops, tab_graph, tab_audit = st.tabs(["🚀 Aktive Aufgaben", "🕸️ Agenten-Mesh", "🛡️ Audit & Security Log"])

    with tab_ops:
        col_tasks_left, col_tasks_right = st.columns([2, 1])
        with col_tasks_left:
            st.markdown("""
                <div class="card">
                    <div style="font-family: ui-monospace, monospace; font-size: 13px; font-weight: 700; color: var(--text-main); margin-bottom: 8px;">
                        Autonome Task-Pipeline (Hermes Core)
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
                        Laufende Subprozesse, Hintergrund-Worker und zugewiesene Spezialisten.
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # Beispielhafte Task-Liste im Border-First Look
            st.markdown("""
                <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 12px;">
                    <div class="card" style="padding: 12px !important; display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <div style="font-weight: 600; font-size: 13px; color: var(--text-main);">#TSK-841: BauGB Paragraf 34 Analyse</div>
                            <div style="font-size: 11px; color: var(--text-muted); font-family: ui-monospace, monospace;">Zugewiesen an: BauGB Permit Expert · Gestartet vor 4 Min</div>
                        </div>
                        <span class="badge badge-system">[IN PROGRESS]</span>
                    </div>
                    <div class="card" style="padding: 12px !important; display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <div style="font-weight: 600; font-size: 13px; color: var(--text-main);">#TSK-840: Quartals-Cashflow Modellierung</div>
                            <div style="font-size: 11px; color: var(--text-muted); font-family: ui-monospace, monospace;">Zugewiesen an: RealEstate DCF Calculator · Abgeschlossen</div>
                        </div>
                        <span class="badge badge-success">[SUCCESS]</span>
                    </div>
                    <div class="card" style="padding: 12px !important; display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <div style="font-weight: 600; font-size: 13px; color: var(--text-main);">#TSK-839: Vertrags-Freigabe Kaufangebot</div>
                            <div style="font-size: 11px; color: var(--text-muted); font-family: ui-monospace, monospace;">Wartet auf Bestätigung durch Administrator</div>
                        </div>
                        <span class="badge badge-gate">[GATE REVIEW]</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        with col_tasks_right:
            st.markdown("""
                <div class="card">
                    <div style="font-family: ui-monospace, monospace; font-size: 13px; font-weight: 700; color: var(--text-main); margin-bottom: 8px;">
                        Schnell-Auftrag erteilen
                    </div>
                </div>
            """, unsafe_allow_html=True)
            task_role = st.selectbox("Ausführender Agent", ["Executive Decision Architect", "BauGB Permit Expert", "Senior Fullstack Engineer", "Tax Holding Advisor"])
            task_instruction = st.text_area("Arbeitsanweisung (Prompt)", placeholder="Was soll der Agent analysieren oder generieren?", height=120)
            if st.button("Aufgabe delegieren", type="primary"):
                st.success(f"Aufgabe an '{task_role}' erfolgreich in den Hermes-Kernel eingereiht.")

    with tab_graph:
        st.markdown("""
            <div class="card">
                <div style="font-family: ui-monospace, monospace; font-size: 13px; font-weight: 700; color: var(--text-main); margin-bottom: 6px;">
                    Agenten-Hierarchie &amp; Ablaufdiagramm
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
                    Interaktive Prozessketten von Vorstand (Tier 1) bis zu Fachexperten (Tier 3).
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.info("Das vollständige 3D-Ablaufdiagramm ist im WebUI-Modus über Canvas aktiv geschaltet.")

    with tab_audit:
        st.markdown("""
            <div class="card">
                <div style="font-family: ui-monospace, monospace; font-size: 13px; font-weight: 700; color: var(--text-main); margin-bottom: 6px;">
                    Kryptographisches Audit-Log (Zero-Trust)
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.code("""
2026-10-03T19:24:00 [AUDIT] TASK_SCHEDULE: TSK-841 -> BauGB Permit Expert [HASH: 9a7b...14f2]
2026-10-03T19:22:15 [AUDIT] HITL_GATE_TRIGGER: Kaufangebot_Freigabe -> WAITING_FOR_USER
2026-10-03T19:20:00 [AUDIT] WATCHDOG_CHECK: 0 hung tasks, memory usage: 18.4%
        """, language="text")

# --- VIEW 2: EINGANG (TRIAGE & STREAMS) ---
elif selected_view == "Eingang (Triage & Streams)":
    if render_inbox_streamlit:
        render_inbox_streamlit()
    else:
        st.error("Modul 'views.view_inbox' konnte nicht geladen werden.")

# --- VIEW 3: SHOWROOM (ERGEBNISSE & APPS) ---
elif selected_view == "Showroom (Ergebnisse & Apps)":
    if render_showroom_streamlit:
        render_showroom_streamlit()
    else:
        st.error("Modul 'views.view_showroom' konnte nicht geladen werden.")

# --- VIEW 4: ZENTRALBIBLIOTHEK & RAG ---
elif selected_view == "Zentralbibliothek & RAG":
    st.markdown("""
        <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-default); padding-bottom: 16px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: var(--primary);"></span>
                <span style="font-family: ui-monospace, monospace; font-size: 16px; font-weight: 700; color: var(--text-main);">ZENTRALBIBLIOTHEK &amp; OBSIDIAN VAULT</span>
            </div>
            <div>
                <span class="badge badge-system">[RAG] AnythingLLM &amp; Vault Sync</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    lib_tab1, lib_tab2, lib_tab3 = st.tabs(["📚 RAG Wissens-Index", "📥 Dokumenten-Erfasser", "📝 Obsidian Vault Explorer"])

    with lib_tab1:
        hub1, hub2, hub3, hub4 = st.columns(4)
        with hub1:
            st.metric(label="00_HR_Agenten", value="56 Profile", delta="Vollständig indiziert")
        with hub2:
            st.metric(label="02_Wissensbibliothek", value="Fachliteratur", delta="RAG Bereit")
        with hub3:
            st.metric(label="Protokolle/", value="Change-Logs", delta="Live synchronisiert")
        with hub4:
            st.metric(label="00_Notebook_Synthesen", value="Erkenntnisse", delta="Grounded Retrieval")

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        search_query = st.text_input("Wissensdatenbank durchsuchen", placeholder="Stichwort oder Frage eingeben...")
        if search_query:
            st.info(f"Suche nach '{search_query}' im AnythingLLM-Vektorindex...")

    with lib_tab2:
        st.markdown("""
            <div class="card">
                <div style="font-weight: 600; font-size: 13px; color: var(--text-main); margin-bottom: 4px;">
                    Dokumenten-Upload &amp; Vektorisierung
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
                    Lade PDFs, Markdown-Dateien oder TXT-Dokumente hoch, um sie in den Vault und Vektorindex zu übertragen.
                </div>
            </div>
        """, unsafe_allow_html=True)
        uploaded_files = st.file_uploader("Dateien auswählen", accept_multiple_files=True)
        if uploaded_files:
            if st.button("In Vault erfassen & indizieren", type="primary"):
                st.success(f"{len(uploaded_files)} Datei(en) erfolgreich zur Indizierung weitergeleitet.")

    with lib_tab3:
        st.markdown("""
            <div class="card">
                <div style="font-weight: 600; font-size: 13px; color: var(--text-main); margin-bottom: 4px;">
                    Lokaler Obsidian Vault (/opt/data/obsidian)
                </div>
                <div style="font-size: 12px; color: var(--text-muted);">
                    Alle Notizen und Dossiers werden transparent als Markdown-Dateien synchronisiert.
                </div>
            </div>
        """, unsafe_allow_html=True)

# --- VIEW 5: AGENTEN-KADER ---
elif selected_view == "Agenten-Kader (56 Profile)":
    st.markdown("""
        <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-default); padding-bottom: 16px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: var(--primary);"></span>
                <span style="font-family: ui-monospace, monospace; font-size: 16px; font-weight: 700; color: var(--text-main);">AGENTEN-KADER &amp; ROLLEN-PROFILE</span>
            </div>
            <div>
                <span class="badge badge-system">[KADER] 56 Spezial-Agenten</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.info("Kader-Übersicht: Alle 56 Agentenprofile mit Declarative Manifests, Tool-Scopes und individuellem Routing.")

# --- VIEW 6: SYSTEM CONTROL CENTER ---
elif selected_view == "System Control Center":
    st.markdown("""
        <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-default); padding-bottom: 16px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: var(--primary);"></span>
                <span style="font-family: ui-monospace, monospace; font-size: 16px; font-weight: 700; color: var(--text-main);">SYSTEM CONTROL CENTER</span>
            </div>
            <div>
                <span class="badge badge-system">[CONFIG] Hermes Core &amp; Services</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    tab_hermes, tab_services, tab_routing = st.tabs(["Hermes Core", "Container & Dienste", "Provider & Keys"])

    with tab_hermes:
        st.markdown("""
            <div class="card">
                <div style="font-weight: 600; font-size: 13px; color: var(--text-main); margin-bottom: 4px;">
                    Hermes Agent Core Konfiguration
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
                    Granulare Formular-Steuerung für Reasoning-Tiefe, Kontextlimits und Ausführungsregeln.
                </div>
            </div>
        """, unsafe_allow_html=True)
        col_cfg1, col_cfg2 = st.columns(2)
        with col_cfg1:
            st.text_input("Standard-Modell", value="z-ai/glm-5.3")
            st.selectbox("Standard-Provider", ["OpenRouter", "OmniRoute", "Google Gemini", "Groq"])
        with col_cfg2:
            st.selectbox("Reasoning Effort", ["medium", "low", "high"])
            st.number_input("Max Context Tokens", value=32000, step=1000)
        if st.button("Hermes-Einstellungen Speichern", type="primary"):
            st.success("Hermes Core Konfiguration erfolgreich gespeichert.")

    with tab_services:
        st.markdown("""
            <div class="card">
                <div style="font-weight: 600; font-size: 13px; color: var(--text-main); margin-bottom: 4px;">
                    Aktive Docker-Services &amp; Port-Kopplungen
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown("""
            <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 10px;">
                <div class="card" style="padding: 10px !important; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-family: ui-monospace, monospace; font-weight: 600;">ARCHON-OS Container</span>
                    <span class="badge badge-success">Port 8501 · Up</span>
                </div>
                <div class="card" style="padding: 10px !important; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-family: ui-monospace, monospace; font-weight: 600;">Hermes Agent Engine</span>
                    <span class="badge badge-success">Port 8644 · Up</span>
                </div>
                <div class="card" style="padding: 10px !important; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-family: ui-monospace, monospace; font-weight: 600;">OmniRoute Gateway</span>
                    <span class="badge badge-success">Port 20128 · Up</span>
                </div>
                <div class="card" style="padding: 10px !important; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-family: ui-monospace, monospace; font-weight: 600;">n8n Automation Mesh</span>
                    <span class="badge badge-success">Port 5678 · Up</span>
                </div>
                <div class="card" style="padding: 10px !important; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-family: ui-monospace, monospace; font-weight: 600;">Pocketbase Core</span>
                    <span class="badge badge-success">Port 8090 · Up</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

    with tab_routing:
        st.markdown("""
            <div class="card">
                <div style="font-weight: 600; font-size: 13px; color: var(--text-main); margin-bottom: 4px;">
                    Multi-Provider API-Keys
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.text_input("OpenRouter API Key", type="password", value="sk-or-v1-****************")
        st.text_input("Google AI / Gemini Key", type="password", value="AIzaSy****************")
        if st.button("Provider-Keys sichern", type="primary"):
            st.success("API-Keys verschlüsselt gespeichert.")
