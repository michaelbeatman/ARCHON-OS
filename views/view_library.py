"""
views/view_library.py - Zentralbibliothek (3-Tab-Screen)

Reiter:
1. 📚 RAG Wissens-Index: AnythingLLM (http://localhost:3001) im Iframe mit defensiver Erreichbarkeitsprüfung
2. 📥 Dokumenten-Erfasser: Die 4 Kacheln, PDF-Upload-Zone & Tabelle der Werke aus der Wissensbasis
3. 📝 Obsidian Vault: Nativer Markdown-Explorer für /opt/data/obsidian (Links Tree, rechts Vorschau)

Design: Striktes Hell-Design (#F8FAFC Hintergrund, weiße Cards #FFFFFF, Text in #0F172A).
"""

import os
import json
import html
from typing import Optional, Dict, Any, List

# Standard-Pfad für den Obsidian Vault
OBSIDIAN_VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "/opt/data/obsidian")
ANYTHINGLLM_URL = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001")


def render_library_view() -> str:
    """
    Rendert den gesamten 3-Tab-Screen der Zentralbibliothek.
    Kann direkt im Frontend-Router eingebunden oder als View-Template gerendert werden.
    """
    return f"""
    <div id="view-library" class="flex-1 w-full min-h-screen flex flex-col p-6 select-none" style="background-color: #F8FAFC !important; color: #0F172A !important; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
      
      <!-- HEADER -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-5 border-b mb-6 gap-4" style="border-color: #E2E8F0 !important;">
        <div>
          <div class="flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full inline-block" style="background-color: #4F46E5 !important;"></span>
            <h1 class="text-sm font-bold uppercase tracking-wider font-mono" style="color: #0F172A !important; margin: 0;">ZENTRALBIBLIOTHEK</h1>
          </div>
          <p class="text-xs mt-1 font-mono" style="color: #64748B !important; margin: 0;">RAG Wissens-Index, Dokumenten-Erfasser & Lokaler Obsidian Vault</p>
        </div>

        <!-- 3-TAB BUTTON BAR -->
        <div class="flex items-center gap-1.5 p-1 rounded-lg border" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
          <button id="lib-tab-btn-1" onclick="switchCentralLibraryTab(1)" class="px-3.5 py-1.5 rounded text-xs font-mono font-medium transition-all" style="background-color: #4F46E5 !important; color: #FFFFFF !important;">
            📚 RAG Wissens-Index
          </button>
          <button id="lib-tab-btn-2" onclick="switchCentralLibraryTab(2)" class="px-3.5 py-1.5 rounded text-xs font-mono font-medium transition-all" style="background-color: transparent !important; color: #64748B !important;">
            📥 Dokumenten-Erfasser
          </button>
          <button id="lib-tab-btn-3" onclick="switchCentralLibraryTab(3)" class="px-3.5 py-1.5 rounded text-xs font-mono font-medium transition-all" style="background-color: transparent !important; color: #64748B !important;">
            📝 Obsidian Vault
          </button>
        </div>
      </div>

      <!-- ========================================================================= -->
      <!-- TAB 1: RAG WISSENS-INDEX (AnythingLLM Iframe & Defensive Fallback)        -->
      <!-- ========================================================================= -->
      <div id="lib-tab-pane-1" class="flex-1 flex flex-col w-full rounded-lg overflow-hidden relative" style="height: calc(100vh - 160px); background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 8px !important;">
        
        <!-- Fallback-Hinweis (wird eingeblendet, falls AnythingLLM nicht reagiert) -->
        <div id="anythingllm-fallback" class="hidden absolute inset-0 flex flex-col items-center justify-center p-8 text-center z-10" style="background-color: #FFFFFF !important;">
          <div class="w-12 h-12 rounded-full flex items-center justify-center mb-3" style="background-color: #FEE2E2 !important; color: #DC2626 !important;">
            <i data-lucide="alert-triangle" class="w-6 h-6"></i>
          </div>
          <h3 class="text-sm font-bold font-mono" style="color: #0F172A !important;">AnythingLLM RAG-Service nicht erreichbar</h3>
          <p class="text-xs max-w-md mt-1 font-mono" style="color: #64748B !important;">
            Der Vector-Index Container auf <code class="px-1.5 py-0.5 rounded border" style="background-color: #F8FAFC !important; border-color: #E2E8F0 !important;">{ANYTHINGLLM_URL}</code> antwortet derzeit nicht.
          </p>
          <div class="flex items-center gap-3 mt-4">
            <button onclick="checkAndReloadAnythingLLM()" class="px-4 py-2 rounded text-xs font-mono font-medium text-white shadow-xs" style="background-color: #0F172A !important;">
              Erneut prüfen
            </button>
            <a href="{ANYTHINGLLM_URL}" target="_blank" class="px-4 py-2 rounded text-xs font-mono font-medium border" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
              Direkt im Browser öffnen ↗
            </a>
          </div>
        </div>

        <iframe id="anythingllm-main-iframe" 
                src="{ANYTHINGLLM_URL}" 
                class="w-full h-full border-none"
                style="height: calc(100vh - 160px); width: 100%; border-radius: 8px;"
                title="AnythingLLM RAG Index"
                onerror="onAnythingLLMError()">
        </iframe>
      </div>

      <!-- ========================================================================= -->
      <!-- TAB 2: DOKUMENTEN-ERFASSER (4 Kacheln, PDF-Upload, Tabelle der Werke)    -->
      <!-- ========================================================================= -->
      <div id="lib-tab-pane-2" class="hidden flex-1 flex flex-col space-y-6 overflow-y-auto pr-1">
        {render_document_ingest_tab()}
      </div>

      <!-- ========================================================================= -->
      <!-- TAB 3: OBSIDIAN VAULT (Nativer Markdown Explorer für /opt/data/obsidian)  -->
      <!-- ========================================================================= -->
      <div id="lib-tab-pane-3" class="hidden flex-1 grid grid-cols-1 md:grid-cols-12 gap-6" style="height: calc(100vh - 160px);">
        {render_obsidian_vault_explorer_tab()}
      </div>

    </div>

    <!-- CLIENT CONTROLLER SCRIPT -->
    <script>
      {render_library_client_js()}
    </script>
    """


def render_document_ingest_tab() -> str:
    """
    Rendert Tab 2 exakt gemäß der bestehenden Wissensbasis-Logik:
    - 4 Kacheln oben (HR & Agenten, Wissensbibliothek, Protokolle, Synthesen)
    - Upload-Zone für PDFs & Fachbücher (Auto-OCR & Markdown-Ingest)
    - Tabelle der Werke & Dokumente mit Filterung und Aktionen
    """
    return """
    <!-- 4 KACHELN (CORE HUBS) -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="p-4 rounded-xl border flex flex-col justify-between" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
        <div class="flex items-center justify-between text-xs font-mono" style="color: #64748B !important;">
          <span class="font-semibold">HR & AGENTEN</span>
          <i data-lucide="users" class="w-4 h-4 text-purple-600"></i>
        </div>
        <div class="text-base font-bold my-1 font-mono" style="color: #0F172A !important;">00_HR_Agenten</div>
        <div class="text-[11px] font-mono" style="color: #64748B !important;">Personalakten & Skill-Manifeste</div>
      </div>

      <div class="p-4 rounded-xl border flex flex-col justify-between" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
        <div class="flex items-center justify-between text-xs font-mono" style="color: #64748B !important;">
          <span class="font-semibold">WISSENSBIBLIOTHEK</span>
          <i data-lucide="book" class="w-4 h-4 text-amber-600"></i>
        </div>
        <div class="text-base font-bold my-1 font-mono" style="color: #0F172A !important;" id="lib-hub-books-count">02_Wissensbibliothek</div>
        <div class="text-[11px] font-mono" style="color: #64748B !important;">DIN-Normen, B-Pläne & Fachbücher</div>
      </div>

      <div class="p-4 rounded-xl border flex flex-col justify-between" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
        <div class="flex items-center justify-between text-xs font-mono" style="color: #64748B !important;">
          <span class="font-semibold">PROTOKOLLE</span>
          <i data-lucide="clipboard-list" class="w-4 h-4 text-emerald-600"></i>
        </div>
        <div class="text-base font-bold my-1 font-mono" style="color: #0F172A !important;">Protokolle/</div>
        <div class="text-[11px] font-mono" style="color: #64748B !important;">Sitzungen & Change-Logs</div>
      </div>

      <div class="p-4 rounded-xl border flex flex-col justify-between" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
        <div class="flex items-center justify-between text-xs font-mono" style="color: #64748B !important;">
          <span class="font-semibold">SYNTHESEN</span>
          <i data-lucide="sparkles" class="w-4 h-4 text-indigo-600"></i>
        </div>
        <div class="text-base font-bold my-1 font-mono" style="color: #0F172A !important;">00_Notebook_Synthesen</div>
        <div class="text-[11px] font-mono" style="color: #64748B !important;">Grounded Retrieval Erkenntnisse</div>
      </div>
    </div>

    <!-- UPLOAD-ZONE FÜR PDFS & DOKUMENTE -->
    <div class="p-5 rounded-xl border-2 border-dashed space-y-4 relative transition-all" 
         id="library-dropzone" 
         style="background-color: #FFFFFF !important; border-color: #CBD5E1 !important;"
         ondragover="onLibraryDragOver(event)" 
         ondragleave="onLibraryDragLeave(event)" 
         ondrop="onLibraryDrop(event)">
      
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-lg flex items-center justify-center border" style="background-color: #F1F5F9 !important; border-color: #E2E8F0 !important; color: #4F46E5 !important;">
            <i data-lucide="file-up" class="w-5 h-5"></i>
          </div>
          <div>
            <h4 class="font-bold text-sm flex items-center gap-2" style="color: #0F172A !important; margin: 0;">
              <span>PDF-Dokumente & Fachbücher erfassen</span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold" style="background-color: #EEF2FF !important; color: #4F46E5 !important;">Auto-OCR & Markdown</span>
            </h4>
            <p class="text-xs mt-0.5" style="color: #64748B !important; margin: 0;">
              Ziehe PDF-, DOCX- oder TXT-Dateien hier hinein oder klicke auf Durchsuchen.
            </p>
          </div>
        </div>

        <!-- Kategorie-Vorwahl -->
        <div class="flex flex-wrap items-center gap-2 font-mono text-xs">
          <span style="color: #64748B !important;">Kategorie:</span>
          <select id="library-upload-category" onchange="onLibraryCategorySelectChange(this.value)" class="border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            <option value="auto">🤖 Automatisch erkennen (KI-Themenklassifikation)</option>
            <option value="06_Cannabis_Wirtschaft_Medizin">🌿 06_Cannabis_Wirtschaft_Medizin</option>
            <option value="07_Betriebswirtschaft_Finanzen">💼 07_Betriebswirtschaft_Finanzen</option>
            <option value="08_Projektmanagement_Organisation">📋 08_Projektmanagement_Organisation</option>
            <option value="01_Immobilien_Modulbau">🏗️ 01_Immobilien_Modulbau</option>
            <option value="02_Recht_Steuern">⚖️ 02_Recht_Steuern</option>
            <option value="03_Strategie_Markt">📈 03_Strategie_Markt</option>
            <option value="09_Tech_Software_KI">💻 09_Tech_Software_KI</option>
            <option value="10_Medizin_Gesundheit">🩺 10_Medizin_Gesundheit</option>
            <option value="04_Allgemein">📚 04_Allgemein</option>
            <option value="custom">➕ Neues Thema anlegen...</option>
          </select>
          <input type="text" id="library-custom-category-input" placeholder="z. B. 11_Vertrieb" class="hidden border rounded-lg px-2.5 py-1 text-xs font-mono focus:outline-none w-44" style="background-color: #FFFFFF !important; border-color: #4F46E5 !important; color: #0F172A !important;">
        </div>
      </div>

      <!-- Verstecktes Dateiauswahl-Input -->
      <input type="file" id="library-file-input" multiple accept=".pdf,.docx,.doc,.txt,.md,.epub" class="hidden" onchange="onLibraryFileInputChange(event)">

      <!-- Klickbare Drop-Fläche -->
      <div class="py-6 border border-dashed rounded-lg text-center flex flex-col items-center justify-center gap-2 cursor-pointer hover:border-indigo-400 transition" 
           style="background-color: #F8FAFC !important; border-color: #CBD5E1 !important;" 
           onclick="document.getElementById('library-file-input').click()">
        <i data-lucide="upload-cloud" class="w-8 h-8" style="color: #4F46E5 !important;"></i>
        <div class="text-xs font-semibold" style="color: #0F172A !important;">
          Klicke hier zum Auswählen oder ziehe Dateien direkt in diesen Bereich
        </div>
        <div class="text-[11px] font-mono" style="color: #64748B !important;">
          Unterstützt: PDF (mit Auto-OCR), EPUB, DOCX, TXT, MD
        </div>
      </div>

      <!-- Ausgewählte Dateien Warteschlange -->
      <div id="library-selected-files-container" class="hidden space-y-2">
        <div class="flex items-center justify-between text-xs font-mono border-b pb-1" style="border-color: #E2E8F0 !important; color: #64748B !important;">
          <span id="library-files-count-label">0 Dateien ausgewählt:</span>
          <button type="button" onclick="clearLibrarySelectedFiles()" class="text-rose-500 hover:underline text-[11px]">Auswahl leeren</button>
        </div>
        <div id="library-selected-files-list" class="space-y-1.5 max-h-36 overflow-y-auto"></div>
        <div class="pt-2 flex flex-wrap items-center gap-3">
          <button type="button" id="btn-start-library-upload" onclick="startLibraryUploadAndIngest()" class="px-4 py-2 rounded text-white font-bold text-xs transition flex items-center gap-2" style="background-color: #4F46E5 !important; border: 1px solid #4F46E5 !important;">
            <i data-lucide="play" class="w-4 h-4"></i>
            <span>Jetzt erfassen & in Vault einlesen</span>
          </button>
        </div>
      </div>
    </div>

    <!-- TABELLE DER WERKE & DOKUMENTE -->
    <div class="p-5 rounded-xl border space-y-4" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h4 class="font-bold text-sm flex items-center gap-2" style="color: #0F172A !important; margin: 0;">
            <i data-lucide="file-search" class="w-4 h-4 text-indigo-600"></i>
            <span>Erfasste Werke in 02_Wissensbibliothek</span>
          </h4>
          <span class="text-[11px] font-mono" style="color: #64748B !important;">Thematisch sortiert und voll indiziert</span>
        </div>
        
        <div class="flex items-center gap-2">
          <div class="relative">
            <input type="text" id="library-search-input" placeholder="Nach Titel oder Stichwort suchen..." oninput="filterLibraryTable()" class="pl-3 pr-3 py-1.5 rounded-lg border text-xs font-mono w-48 sm:w-64 focus:outline-none" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
          </div>
          <button onclick="loadLibraryBooksList()" class="px-3 py-1.5 rounded-lg border text-xs flex items-center gap-1.5 transition hover:bg-slate-50" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
            <span>Aktualisieren</span>
          </button>
        </div>
      </div>

      <!-- Kategorie Filter-Pills -->
      <div id="library-category-filter-container" class="flex flex-wrap items-center gap-1.5 text-xs font-mono border-b pb-3" style="border-color: #E2E8F0 !important;">
        <button type="button" onclick="setLibraryCategoryFilter('ALL')" id="lib-filter-btn-ALL" class="lib-filter-btn px-3 py-1 rounded-full text-white font-bold transition" style="background-color: #0F172A !important;">
          Alle
        </button>
      </div>

      <!-- Dokumenten-Tabelle -->
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b font-mono text-[10px] uppercase" style="border-color: #E2E8F0 !important; color: #64748B !important;">
              <th class="py-2.5 px-3">Titel & Werk</th>
              <th class="py-2.5 px-3">Kategorie / Pfad</th>
              <th class="py-2.5 px-3">Umfang</th>
              <th class="py-2.5 px-3">Format / OCR</th>
              <th class="py-2.5 px-3 text-right">Aktionen</th>
            </tr>
          </thead>
          <tbody id="library-books-table-body" class="divide-y font-mono" style="border-color: #F1F5F9 !important;">
            <tr>
              <td colspan="5" class="py-6 text-center text-xs" style="color: #64748B !important;">Lade Werke...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    """


def render_obsidian_vault_explorer_tab() -> str:
    """
    Rendert Tab 3: Nativer Markdown-Explorer für /opt/data/obsidian.
    - Links: Verzeichnisbaum
    - Rechts: Formatierte Text-/Markdown-Anzeige
    """
    return """
    <!-- Linke Spalte: Verzeichnisbaum -->
    <div class="md:col-span-4 rounded-lg border p-4 flex flex-col overflow-hidden" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
      <div class="flex items-center justify-between pb-3 border-b mb-3" style="border-color: #E2E8F0 !important;">
        <div class="flex items-center gap-2">
          <i data-lucide="folder-tree" class="w-4 h-4 text-indigo-600"></i>
          <h3 class="text-xs font-bold uppercase tracking-wider font-mono" style="color: #0F172A !important; margin: 0;">Vault Explorer</h3>
        </div>
        <button onclick="loadVaultTree()" class="p-1 rounded hover:bg-slate-100 transition" style="color: #64748B !important;" title="Neu laden">
          <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
        </button>
      </div>
      <div class="text-[11px] font-mono truncate mb-2 px-1" style="color: #64748B !important;" title="/opt/data/obsidian">
        Pfad: <span class="font-bold text-slate-800">/opt/data/obsidian</span>
      </div>
      <div id="vault-tree-container" class="flex-1 overflow-y-auto font-mono text-xs space-y-1 pr-1">
        <div class="p-2 text-xs font-mono" style="color: #64748B !important;">Lade Verzeichnisstruktur...</div>
      </div>
    </div>

    <!-- Rechte Spalte: Formatierte Textanzeige -->
    <div class="md:col-span-8 rounded-lg border p-5 flex flex-col overflow-hidden" style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
      <div class="flex items-center justify-between pb-3 border-b mb-3" style="border-color: #E2E8F0 !important;">
        <div class="flex items-center gap-2 min-w-0">
          <i data-lucide="file-text" class="w-4 h-4 text-slate-500 shrink-0"></i>
          <span id="vault-viewer-filename" class="text-xs font-bold font-mono truncate" style="color: #0F172A !important;">Keine Datei ausgewählt</span>
        </div>
        <span id="vault-viewer-path" class="text-[11px] font-mono truncate max-w-[280px]" style="color: #64748B !important;"></span>
      </div>
      <div id="vault-viewer-content" class="flex-1 overflow-y-auto p-4 rounded border font-mono text-xs whitespace-pre-wrap leading-relaxed select-text" style="background-color: #F8FAFC !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
Wähle eine Notiz oder Markdown-Datei aus dem Vault-Verzeichnis links aus.
      </div>
    </div>
    """


def render_library_client_js() -> str:
    """
    Client-seitige JavaScript-Funktionen für Tab-Switching,
    defensive AnythingLLM-Prüfung, Vault-Tree und Ingest.
    """
    return """
    let currentLibraryTab = 1;

    function switchCentralLibraryTab(tabIndex) {
      currentLibraryTab = tabIndex;
      
      for (let i = 1; i <= 3; i++) {
        const pane = document.getElementById(`lib-tab-pane-${i}`);
        const btn = document.getElementById(`lib-tab-btn-${i}`);
        
        if (i === tabIndex) {
          if (pane) pane.classList.remove('hidden');
          if (btn) {
            btn.style.setProperty('background-color', '#0F172A', 'important');
            btn.style.setProperty('color', '#FFFFFF', 'important');
          }
        } else {
          if (pane) pane.classList.add('hidden');
          if (btn) {
            btn.style.setProperty('background-color', 'transparent', 'important');
            btn.style.setProperty('color', '#64748B', 'important');
          }
        }
      }

      if (tabIndex === 1) {
        checkAndReloadAnythingLLM();
      } else if (tabIndex === 2) {
        if (typeof loadLibraryBooksList === 'function') {
          loadLibraryBooksList();
        }
      } else if (tabIndex === 3) {
        loadVaultTree();
      }

      if (window.lucide) window.lucide.createIcons();
    }

    function checkAndReloadAnythingLLM() {
      const iframe = document.getElementById('anythingllm-main-iframe');
      const fallback = document.getElementById('anythingllm-fallback');
      
      fetch('http://localhost:3001/api/ping', { mode: 'no-cors' })
        .then(() => {
          if (fallback) fallback.classList.add('hidden');
          if (iframe && (!iframe.src || iframe.src === 'about:blank')) {
            iframe.src = 'http://localhost:3001';
          }
        })
        .catch(() => {
          // Timeout oder Offline defensiv abfangen
          if (fallback) fallback.classList.remove('hidden');
        });
    }

    function onAnythingLLMError() {
      const fallback = document.getElementById('anythingllm-fallback');
      if (fallback) fallback.classList.remove('hidden');
    }

    async function loadVaultTree() {
      const container = document.getElementById('vault-tree-container');
      if (!container) return;
      try {
        const res = await fetch('/api/views/library/vault/tree');
        if (!res.ok) throw new Error('Status: ' + res.status);
        const data = await res.json();
        const tree = data.tree || [];

        if (tree.length === 0) {
          container.innerHTML = '<div class="text-xs font-mono p-2" style="color: #64748B !important;">Keine Markdown-Dokumente im Vault gefunden.</div>';
          return;
        }

        const renderNodes = (nodes) => {
          return nodes.map(node => {
            if (node.type === 'directory') {
              return `
                <div class="mb-1">
                  <div class="flex items-center gap-1.5 py-1 px-2 rounded text-slate-700 font-semibold hover:bg-slate-100 cursor-pointer">
                    <i data-lucide="folder" class="w-3.5 h-3.5 text-amber-500 shrink-0"></i>
                    <span class="truncate">${node.name}</span>
                  </div>
                  <div class="pl-3.5 border-l border-slate-200 ml-2 mt-0.5 space-y-0.5">
                    ${node.children ? renderNodes(node.children) : ''}
                  </div>
                </div>
              `;
            } else {
              return `
                <div onclick="selectVaultFile('${encodeURIComponent(node.path)}', '${node.name.replace(/'/g, "\\\\'")}')" class="flex items-center gap-1.5 py-1 px-2 rounded hover:bg-slate-100 cursor-pointer text-slate-600 transition-colors">
                  <i data-lucide="file-text" class="w-3.5 h-3.5 text-indigo-500 shrink-0"></i>
                  <span class="truncate">${node.name}</span>
                </div>
              `;
            }
          }).join('');
        };

        container.innerHTML = renderNodes(tree);
        if (window.lucide) window.lucide.createIcons();
      } catch (e) {
        container.innerHTML = `<div class="text-xs font-mono p-2 text-rose-500">Fehler beim Laden des Vaults: ${e.message}</div>`;
      }
    }

    async function selectVaultFile(encodedPath, fileName) {
      const filenameEl = document.getElementById('vault-viewer-filename');
      const pathEl = document.getElementById('vault-viewer-path');
      const contentEl = document.getElementById('vault-viewer-content');

      if (filenameEl) filenameEl.innerText = fileName;
      if (pathEl) pathEl.innerText = decodeURIComponent(encodedPath);
      if (contentEl) contentEl.innerText = "Lade Dokumentinhalt...";

      try {
        const res = await fetch(`/api/views/library/vault/file?path=${encodedPath}`);
        if (!res.ok) throw new Error('Status: ' + res.status);
        const data = await res.json();
        if (contentEl) contentEl.innerText = data.content || "(Datei ist leer)";
      } catch (e) {
        if (contentEl) contentEl.innerText = "Fehler beim Laden: " + e.message;
      }
    }
    """


# Standalone Ausführung zum Testen
if __name__ == "__main__":
    rendered = render_library_view()
    print(f"[OK] Zentralbibliothek gerendert ({len(rendered)} Zeichen).")
