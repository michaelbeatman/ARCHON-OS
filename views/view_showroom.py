"""
views/view_showroom.py - Operatives Modul "Showroom" für Archon OS

1. ZIELSETZUNG:
   50/50 geteilte Arbeitsfläche zur Begutachtung von Agenten-Outputs:
   - Linke Bildschirmhälfte (50% Breite): ERGEBNISSE & DOSSIERS (Markdown- & Textberichte)
   - Rechte Bildschirmhälfte (50% Breite): ARTEFAKTE & LIVE-APPS (Interaktive HTML-Webanwendungen via Iframe)

2. DESIGN-STANDARDS (STRIKTES HELL-DESIGN):
   - Globaler Hintergrund: #F8FAFC
   - Container-Karten: Reines Weiß (#FFFFFF), Rahmen: 1px solid #E2E8F0, Radius: 8px, Innenabstand: 16px
   - Textfarben: Primärtext #0F172A, Sekundärtext #64748B
   - Header: Roter Signalpunkt (● in #EF4444) vor dem Titel "SHOWROOM (ERGEBNISSE & ARTEFAKTE)"
   - Primärbuttons: #DC2626 mit weißem Text
   - Sekundärbuttons: Weiß mit Rahmen #E2E8F0 und Text #0F172A

3. TECHNISCHE ANFORDERUNGEN & DATENQUELLEN:
   A) Linke Hälfte (Ergebnisse & Dossiers):
      - Quellpfad: /projects/builds/reports/ (defensiv via pathlib anlegen)
      - Endungen: .md und .txt
      - Leere-Hinweiskarte: "Keine Berichte vorhanden. Generierte Dossiers erscheinen hier."
      - Dropdown zur Dateiauswahl + scrollbarer Markdown-Container (Höhe: calc(100vh - 240px))
      - Aktionsleiste:
        1. "In Obsidian archivieren": Kopiert nach /opt/data/obsidian/00_Notebook_Synthesen/ mit Erfolgsmeldung
        2. "Inhalt in Zwischenablage kopieren"
   B) Rechte Hälfte (Artefakte & Live-Apps):
      - Quellpfad: /projects/builds/apps/ (defensiv via pathlib anlegen)
      - Ordner mit index.html oder einzelne .html-Dateien
      - Leere-Hinweiskarte: "Keine Artefakte gefunden. Generierte Web-Apps erscheinen hier."
      - Dropdown zur Artefaktsauswahl + responsiver Iframe (sandbox: allow-scripts allow-forms allow-same-origin)
      - Aktionsleiste:
        1. "Im neuen Browser-Tab öffnen"
        2. "Quellcode einsehen" (aufklappbarer Code-Expander mit HTML/JS)

4. DUAL-KOMPATIBILITÄT:
   - render_showroom_view() für das Archon Web-OS Frontend (HTML/JS)
   - render_showroom_streamlit() für Streamlit-Umgebungen
"""

import os
import shutil
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


# =============================================================================
# DEFENSIVE PFADAUFLÖSUNG & DIRECTORY-INITIALISIERUNG
# =============================================================================

def get_reports_dir() -> Path:
    """Ermittelt und initialisiert defensiv das Verzeichnis für Berichte und Dossiers."""
    candidates = [
        Path("/projects/builds/reports"),
        Path("./agent_workspace/builds/reports"),
        Path("/app/agent_workspace/builds/reports"),
        Path(os.environ.get("REPORTS_DIR", "./agent_workspace/builds/reports"))
    ]
    for c in candidates:
        if c.exists():
            return c

    primary = candidates[0]
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[1]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_apps_dir() -> Path:
    """Ermittelt und initialisiert defensiv das Verzeichnis für Live-Apps und Artefakte."""
    candidates = [
        Path("/projects/builds/apps"),
        Path("./agent_workspace/builds/apps"),
        Path("/app/agent_workspace/builds/apps"),
        Path(os.environ.get("APPS_DIR", "./agent_workspace/builds/apps"))
    ]
    for c in candidates:
        if c.exists():
            return c

    primary = candidates[0]
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[1]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_obsidian_archive_dir() -> Path:
    """Ermittelt und initialisiert das Archivierungsziel im Obsidian Vault."""
    candidates = [
        Path("/opt/data/obsidian/00_Notebook_Synthesen"),
        Path("C:/Mein Obsidian/00_Notebook_Synthesen"),
        Path("./agent_workspace/obsidian_vault/00_Notebook_Synthesen"),
        Path("/app/data/obsidian/00_Notebook_Synthesen")
    ]
    for c in candidates:
        if c.exists():
            return c

    primary = candidates[0]
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[2]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# =============================================================================
# DATENABRUF: BERICHTE & LIVE-APPS
# =============================================================================

def load_showroom_reports() -> List[Dict[str, Any]]:
    """
    Scannt defensiv nach .md und .txt Dateien in /projects/builds/reports/.
    Sortiert: Neueste oben.
    """
    reports_path = get_reports_dir()
    reports: List[Dict[str, Any]] = []

    if not reports_path.exists():
        return reports

    for file_path in reports_path.iterdir():
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        if ext in [".md", ".txt"]:
            mtime = file_path.stat().st_mtime
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                content = "(Inhalt konnte nicht geladen werden)"

            reports.append({
                "id": file_path.name,
                "filename": file_path.name,
                "title": file_path.stem.replace("-", " ").replace("_", " ").title(),
                "content": content,
                "path": str(file_path),
                "mtime": mtime,
                "date": dt_str,
                "size_bytes": file_path.stat().st_size
            })

    reports.sort(key=lambda x: x["mtime"], reverse=True)
    return reports


def load_showroom_apps() -> List[Dict[str, Any]]:
    """
    Scannt defensiv nach Unterordnern mit index.html oder einzelnen .html Dateien
    in /projects/builds/apps/.
    Sortiert: Neueste oben.
    """
    apps_path = get_apps_dir()
    apps: List[Dict[str, Any]] = []

    if not apps_path.exists():
        return apps

    for item in apps_path.iterdir():
        if item.is_dir():
            index_html = item / "index.html"
            if index_html.exists() and index_html.is_file():
                mtime = index_html.stat().st_mtime
                dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                try:
                    with open(index_html, "r", encoding="utf-8", errors="ignore") as f:
                        code_content = f.read()
                except Exception:
                    code_content = "(HTML-Quellcode konnte nicht geladen werden)"

                apps.append({
                    "id": item.name,
                    "name": item.name.replace("-", " ").replace("_", " ").title(),
                    "folder": item.name,
                    "entry_file": "index.html",
                    "url": f"/builds/apps/{item.name}/index.html",
                    "code": code_content,
                    "path": str(index_html),
                    "mtime": mtime,
                    "date": dt_str
                })
        elif item.is_file() and item.suffix.lower() == ".html":
            mtime = item.stat().st_mtime
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            try:
                with open(item, "r", encoding="utf-8", errors="ignore") as f:
                    code_content = f.read()
            except Exception:
                code_content = "(HTML-Quellcode konnte nicht geladen werden)"

            apps.append({
                "id": item.name,
                "name": item.stem.replace("-", " ").replace("_", " ").title(),
                "folder": None,
                "entry_file": item.name,
                "url": f"/builds/apps/{item.name}",
                "code": code_content,
                "path": str(item),
                "mtime": mtime,
                "date": dt_str
            })

    apps.sort(key=lambda x: x["mtime"], reverse=True)
    return apps


def archive_report_to_obsidian(filename: str) -> Dict[str, Any]:
    """
    Kopiert einen Bericht aus /projects/builds/reports/ nach
    /opt/data/obsidian/00_Notebook_Synthesen/.
    """
    reports_path = get_reports_dir()
    src_file = reports_path / filename

    if not src_file.exists():
        # Versuche Basename-Matching
        src_file = reports_path / os.path.basename(filename)

    if not src_file.exists():
        return {
            "success": False,
            "message": f"Quelldatei '{filename}' existiert nicht in {reports_path}."
        }

    dest_dir = get_obsidian_archive_dir()
    dest_file = dest_dir / src_file.name

    try:
        shutil.copy2(src_file, dest_file)
        return {
            "success": True,
            "source": str(src_file),
            "destination": str(dest_file),
            "message": f"Bericht '{src_file.name}' erfolgreich nach Obsidian (00_Notebook_Synthesen) archiviert."
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Fehler beim Kopieren nach Obsidian: {str(e)}"
        }


# =============================================================================
# CENTRAL OPERATIONAL SCREEN RENDERER (HTML / WEB-OS CONTRACT)
# =============================================================================

def render_showroom_view() -> str:
    """
    Rendert die vollständige 50/50 geteilte Arbeitsfläche gemäß Spezifikation:
    - Hintergrund: #F8FAFC
    - Container-Karten: #FFFFFF, Rahmen 1px solid #E2E8F0, Radius 8px, Innenabstand 16px
    - Text: #0F172A / #64748B
    - Header: Signalpunkt #EF4444 vor "SHOWROOM (ERGEBNISSE & ARTEFAKTE)"
    - Linke Hälfte: Markdown-/Textberichte mit Obsidian-Archivierung & Clipboard
    - Rechte Hälfte: Iframe Live-Apps mit Tab-Öffnung & Quellcode-Expander
    """
    reports = load_showroom_reports()
    apps = load_showroom_apps()

    # Linke Hälfte: Reports Dropdown & Initial-Zustand
    if not reports:
        reports_options_html = '<option value="">Keine Berichte vorhanden</option>'
        reports_content_initial = """<div class="p-6 text-center text-xs font-mono" style="color: #64748B;">
            Keine Berichte vorhanden. Generierte Dossiers erscheinen hier.
        </div>"""
        left_actions_disabled = "disabled"
    else:
        options = []
        for r in reports:
            options.append(f'<option value="{r["filename"]}">{r["filename"]} ({r["date"]})</option>')
        reports_options_html = "\n".join(options)
        reports_content_initial = reports[0]["content"]
        left_actions_disabled = ""

    # Rechte Hälfte: Apps Dropdown & Initial-Zustand
    if not apps:
        apps_options_html = '<option value="">Keine Artefakte gefunden</option>'
        right_placeholder_initial = """<div class="p-6 text-center text-xs font-mono" style="color: #64748B;">
            Keine Artefakte gefunden. Generierte Web-Apps erscheinen hier.
        </div>"""
        initial_iframe_src = "about:blank"
        initial_iframe_hidden = "hidden"
        initial_code = "(Kein Quellcode vorhanden)"
        right_actions_disabled = "disabled"
    else:
        options = []
        for a in apps:
            options.append(f'<option value="{a["url"]}">{a["name"]} ({a["entry_file"]})</option>')
        apps_options_html = "\n".join(options)
        right_placeholder_initial = ""
        initial_iframe_src = apps[0]["url"]
        initial_iframe_hidden = ""
        initial_code = apps[0]["code"]
        right_actions_disabled = ""

    return f"""
    <div id="view-showroom" class="flex-1 w-full min-h-screen flex flex-col p-6 select-none" 
         style="background-color: #F8FAFC !important; color: #0F172A !important; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
      
      <!-- HEADER GEMÄSS DESIGN-STANDARDS -->
      <div class="flex items-center justify-between pb-5 border-b mb-6" style="border-color: #E2E8F0 !important;">
        <div>
          <div class="flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full inline-block" style="background-color: #4F46E5 !important;"></span>
            <h1 class="text-sm font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
              SHOWROOM (ERGEBNISSE & ARTEFAKTE)
            </h1>
          </div>
          <p class="text-xs mt-1 font-mono m-0" style="color: #64748B !important;">
            50/50 Arbeitsfläche: Dossiers & Textanalysen (links) vs. Live Web-Apps (rechts)
          </p>
        </div>
        <div class="flex items-center gap-3">
          <span class="px-2.5 py-1 rounded text-xs font-mono font-medium border" 
                style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            {len(reports)} Dossiers &nbsp;|&nbsp; {len(apps)} Apps
          </span>
          <button onclick="if(typeof loadShowroomView === 'function') loadShowroomView(); else window.location.reload();" 
                  class="px-3 py-1.5 rounded text-xs font-mono font-medium border flex items-center gap-1.5 hover:bg-slate-50 transition-colors cursor-pointer" 
                  style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
            <span>Aktualisieren</span>
          </button>
        </div>
      </div>

      <!-- 50/50 GETEILTE ARBEITSFLÄCHE -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 items-start">
        
        <!-- =================================================================== -->
        <!-- LINKE HÄLFTE (50%): ERGEBNISSE & DOSSIERS                           -->
        <!-- =================================================================== -->
        <div class="flex flex-col rounded-lg border shadow-xs" 
             style="background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 8px !important; padding: 16px !important;">
          
          <div class="flex items-center justify-between pb-3 border-b mb-4" style="border-color: #E2E8F0 !important;">
            <div class="flex items-center gap-2">
              <i data-lucide="file-check-2" class="w-4 h-4 text-emerald-600"></i>
              <h3 class="text-xs font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
                ERGEBNISSE & DOSSIERS
              </h3>
            </div>
            
            <div class="w-64 max-w-[60%]">
              <select id="showroom-reports-select" onchange="onSelectShowroomReport(this.value)" 
                      class="w-full text-xs font-mono rounded border px-2.5 py-1.5 outline-none focus:border-red-400" 
                      style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
                {reports_options_html}
              </select>
            </div>
          </div>

          <!-- Formatierter, scrollbarer Markdown-Container (Höhe: calc(100vh - 240px)) -->
          <div id="showroom-report-container" 
               class="overflow-y-auto p-4 rounded border font-mono text-xs whitespace-pre-wrap leading-relaxed select-text" 
               style="height: calc(100vh - 240px); background-color: #F8FAFC !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            <div id="showroom-report-content">{reports_content_initial}</div>
          </div>

          <!-- Aktionsleiste Linke Hälfte -->
          <div class="flex items-center justify-between pt-4 mt-3 border-t gap-3" style="border-color: #E2E8F0 !important;">
            <button id="btn-archive-obsidian" onclick="archiveCurrentReportToObsidian()" {left_actions_disabled}
                    class="px-3.5 py-1.5 rounded text-xs font-mono font-medium text-white flex items-center gap-1.5 transition hover:opacity-90 cursor-pointer" 
                    style="background-color: #4F46E5 !important; border: 1px solid #4F46E5 !important;">
              <i data-lucide="archive" class="w-3.5 h-3.5"></i>
              <span>In Obsidian archivieren</span>
            </button>
            
            <button id="btn-copy-report" onclick="copyCurrentReportContent()" {left_actions_disabled}
                    class="px-3.5 py-1.5 rounded text-xs font-mono font-medium border flex items-center gap-1.5 hover:bg-slate-50 transition cursor-pointer" 
                    style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
              <i data-lucide="copy" class="w-3.5 h-3.5"></i>
              <span>Inhalt in Zwischenablage kopieren</span>
            </button>
          </div>

          <div id="showroom-report-toast" class="hidden mt-2 p-2 rounded text-xs font-mono border text-center transition-all" 
               style="background-color: #ECFDF5; border-color: #A7F3D0; color: #065F46;">
          </div>
        </div>

        <!-- =================================================================== -->
        <!-- RECHTE HÄLFTE (50%): ARTEFAKTE & LIVE-APPS                          -->
        <!-- =================================================================== -->
        <div class="flex flex-col rounded-lg border" 
             style="background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 8px !important; padding: 16px !important;">
          
          <div class="flex items-center justify-between pb-3 border-b mb-4" style="border-color: #E2E8F0 !important;">
            <div class="flex items-center gap-2">
              <i data-lucide="globe" class="w-4 h-4 text-sky-600"></i>
              <h3 class="text-xs font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
                ARTEFAKTE & LIVE-APPS
              </h3>
            </div>
            
            <div class="w-64 max-w-[60%]">
              <select id="showroom-apps-select" onchange="onSelectShowroomApp(this.value)" 
                      class="w-full text-xs font-mono rounded border px-2.5 py-1.5 outline-none focus:border-red-400" 
                      style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
                {apps_options_html}
              </select>
            </div>
          </div>

          <!-- Responsiver Iframe (Höhe: calc(100vh - 240px)) mit sicheren Attributen -->
          <div class="rounded border overflow-hidden relative flex flex-col" 
               style="height: calc(100vh - 240px); background-color: #F8FAFC !important; border-color: #E2E8F0 !important; border-radius: 8px !important;">
            <div id="showroom-app-placeholder" class="my-auto { 'hidden' if not right_placeholder_initial else '' }">
              {right_placeholder_initial}
            </div>
            <iframe id="showroom-app-iframe" 
                    src="{initial_iframe_src}" 
                    sandbox="allow-scripts allow-forms allow-same-origin"
                    class="w-full h-full border-none {initial_iframe_hidden}" 
                    style="border: 1px solid #E2E8F0; border-radius: 8px; width: 100%; height: 100%;" 
                    title="Live App Viewer">
            </iframe>
          </div>

          <!-- Aktionsleiste Rechte Hälfte -->
          <div class="flex items-center justify-between pt-4 mt-3 border-t gap-3" style="border-color: #E2E8F0 !important;">
            <button id="btn-open-new-tab" onclick="openCurrentAppInNewTab()" {right_actions_disabled}
                    class="px-3.5 py-1.5 rounded text-xs font-mono font-medium border flex items-center gap-1.5 hover:bg-slate-50 transition cursor-pointer" 
                    style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
              <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
              <span>Im neuen Browser-Tab öffnen</span>
            </button>
            
            <button id="btn-toggle-code" onclick="toggleSourceCodeExpander()" {right_actions_disabled}
                    class="px-3.5 py-1.5 rounded text-xs font-mono font-medium border flex items-center gap-1.5 hover:bg-slate-50 transition cursor-pointer" 
                    style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
              <i data-lucide="code" class="w-3.5 h-3.5"></i>
              <span>Quellcode einsehen</span>
            </button>
          </div>

          <!-- Quellcode-Expander (ausklappbar) -->
          <div id="showroom-code-expander" class="hidden mt-3 p-3 rounded border font-mono text-xs overflow-x-auto max-h-56 bg-slate-900 text-slate-100" 
               style="border-color: #CBD5E1;">
            <pre id="showroom-code-content" class="m-0 select-text whitespace-pre leading-relaxed">{initial_code}</pre>
          </div>

        </div>

      </div>

    </div>

    <!-- CLIENT CONTROLLER SCRIPT -->
    <script>
      async function onSelectShowroomReport(filename) {{
        const contentEl = document.getElementById('showroom-report-content');
        if (!contentEl) return;
        if (!filename) {{
          contentEl.innerText = "Keine Berichte vorhanden. Generierte Dossiers erscheinen hier.";
          return;
        }}
        contentEl.innerText = "Lade Dossier...";
        try {{
          const res = await fetch(`/api/views/showroom/report-content?filename=${{encodeURIComponent(filename)}}`);
          if (!res.ok) throw new Error('HTTP ' + res.status);
          const data = await res.json();
          contentEl.innerText = data.content || "(Leerer Inhalt)";
        }} catch (e) {{
          contentEl.innerText = "Fehler beim Laden des Berichts: " + e.message;
        }}
      }}

      async function archiveCurrentReportToObsidian() {{
        const select = document.getElementById('showroom-reports-select');
        const filename = select ? select.value : '';
        const toast = document.getElementById('showroom-report-toast');
        if (!filename) return;

        try {{
          const res = await fetch(`/api/views/showroom/archive-to-obsidian?filename=${{encodeURIComponent(filename)}}`, {{
            method: 'POST'
          }});
          const data = await res.json();
          if (toast) {{
            toast.innerText = data.message || "Erfolgreich nach Obsidian archiviert!";
            toast.style.backgroundColor = data.success ? "#ECFDF5" : "#FEF2F2";
            toast.style.color = data.success ? "#065F46" : "#991B1B";
            toast.style.borderColor = data.success ? "#A7F3D0" : "#FECACA";
            toast.classList.remove('hidden');
            setTimeout(() => toast.classList.add('hidden'), 4000);
          }}
        }} catch (e) {{
          if (toast) {{
            toast.innerText = "Archivierungsfehler: " + e.message;
            toast.style.backgroundColor = "#FEF2F2";
            toast.style.color = "#991B1B";
            toast.classList.remove('hidden');
          }}
        }}
      }}

      function copyCurrentReportContent() {{
        const contentEl = document.getElementById('showroom-report-content');
        const toast = document.getElementById('showroom-report-toast');
        if (!contentEl) return;
        const text = contentEl.innerText || "";
        navigator.clipboard.writeText(text).then(() => {{
          if (toast) {{
            toast.innerText = "Inhalt erfolgreich in die Zwischenablage kopiert!";
            toast.style.backgroundColor = "#ECFDF5";
            toast.style.color = "#065F46";
            toast.style.borderColor = "#A7F3D0";
            toast.classList.remove('hidden');
            setTimeout(() => toast.classList.add('hidden'), 2500);
          }}
        }}).catch(err => {{
          alert("Fehler beim Kopieren: " + err);
        }});
      }}

      function onSelectShowroomApp(url) {{
        const iframe = document.getElementById('showroom-app-iframe');
        const placeholder = document.getElementById('showroom-app-placeholder');
        if (!iframe) return;

        if (!url) {{
          iframe.src = 'about:blank';
          iframe.classList.add('hidden');
          if (placeholder) placeholder.classList.remove('hidden');
          return;
        }}

        iframe.src = url;
        iframe.classList.remove('hidden');
        if (placeholder) placeholder.classList.add('hidden');

        // Quellcode synchronisieren
        fetch(url).then(r => r.text()).then(code => {{
          const codeEl = document.getElementById('showroom-code-content');
          if (codeEl) codeEl.innerText = code;
        }}).catch(() => {{}});
      }}

      function openCurrentAppInNewTab() {{
        const select = document.getElementById('showroom-apps-select');
        if (select && select.value) {{
          window.open(select.value, '_blank');
        }}
      }}

      function toggleSourceCodeExpander() {{
        const expander = document.getElementById('showroom-code-expander');
        if (expander) {{
          expander.classList.toggle('hidden');
        }}
      }}
    </script>
    """


# =============================================================================
# STREAMLIT INTEGRATION (FALLS IN STREAMLIT RUNTIME GELADEN)
# =============================================================================

def render_showroom_streamlit():
    """
    Rendert die 50/50 Arbeitsfläche nativ in Streamlit.
    Verwendet st.columns(2), st.components.v1.iframe und Aktions-Buttons.
    """
    try:
        import streamlit as st
        import streamlit.components.v1 as components
    except ImportError:
        return

    st.markdown("""
        <style>
            .stApp { background-color: #F8FAFC !important; }
            .showroom-card {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 16px;
            }
        </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; margin-bottom: 20px;">
            <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #4F46E5;"></span>
            <span style="font-family: monospace; font-size: 16px; font-weight: bold; color: #0F172A;">SHOWROOM (ERGEBNISSE & ARTEFAKTE)</span>
        </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns(2)

    reports = load_showroom_reports()
    apps = load_showroom_apps()

    # Linke Hälfte: ERGEBNISSE & DOSSIERS
    with col_left:
        st.markdown("### 📄 Ergebnisse & Dossiers")
        if not reports:
            st.info("Keine Berichte vorhanden. Generierte Dossiers erscheinen hier.")
        else:
            report_names = [r["filename"] for r in reports]
            selected_report_name = st.selectbox("Bericht auswählen:", report_names, key="sr_report_select")
            selected_report = next((r for r in reports if r["filename"] == selected_report_name), reports[0])

            st.text_area(
                "Dossier-Inhalt",
                value=selected_report["content"],
                height=480,
                disabled=True,
                key="sr_report_content_area"
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("In Obsidian archivieren", type="primary", key="btn_arch_st"):
                    res = archive_report_to_obsidian(selected_report["filename"])
                    if res.get("success"):
                        st.success(res.get("message"))
                    else:
                        st.error(res.get("message"))
            with c2:
                st.code(selected_report["path"], language="text")

    # Rechte Hälfte: ARTEFAKTE & LIVE-APPS
    with col_right:
        st.markdown("### 🌐 Artefakte & Live-Apps")
        if not apps:
            st.info("Keine Artefakte gefunden. Generierte Web-Apps erscheinen hier.")
        else:
            app_names = [a["name"] for a in apps]
            selected_app_name = st.selectbox("Artefakt auswählen:", app_names, key="sr_app_select")
            selected_app = next((a for a in apps if a["name"] == selected_app_name), apps[0])

            # HTML Rendering / Iframe
            components.html(selected_app["code"], height=480, scrolling=True)

            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                st.link_button("Im neuen Tab öffnen", selected_app["url"])
            with c_btn2:
                with st.expander("Quellcode einsehen"):
                    st.code(selected_app["code"], language="html")


# Standalone-Test
if __name__ == "__main__":
    html_out = render_showroom_view()
    print(f"[OK] views/view_showroom.py erfolgreich gerendert ({len(html_out)} Zeichen).")
