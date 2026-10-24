

    // =========================================================================
    // WISSENSBIBLIOTHEK & PDF INGEST PIPELINE (Second Brain & Obsidian Mirror)
    // =========================================================================
    let libraryBooksList = [];
    let librarySelectedFiles = [];
    let libraryActiveCategoryFilter = 'ALL';
    function getSelectedObsidianVault() {
      return localStorage.getItem("archon_obsidian_vault_path") || "C:\\Mein Obsidian";
    }
    function onObsidianVaultChanged(val) {
      localStorage.setItem("archon_obsidian_vault_path", val);
      const lbl = document.getElementById("current-vault-path-label");
      if (lbl) lbl.innerText = val;
      renderLibraryBooksTable();
    }
    function openActiveObsidianVault() {
      const vPath = getSelectedObsidianVault();
      window.location.href = `obsidian://open?path=${encodeURIComponent(vPath)}`;
    }
    function getObsidianDocUri(relPath) {
      const vPath = getSelectedObsidianVault();
      const cleanRel = relPath.replace(/\//g, "\\");
      const fullPath = `${vPath}\\02_Wissensbibliothek\\${cleanRel}`;
      return `obsidian://open?path=${encodeURIComponent(fullPath)}`;
    }
    async function loadLibraryBooksList() {
      // Sync vault selector UI from storage
      const selector = document.getElementById("obsidian-vault-selector");
      const currentVault = getSelectedObsidianVault();
      if (selector) selector.value = currentVault;
      const lbl = document.getElementById("current-vault-path-label");
      if (lbl) lbl.innerText = currentVault;
      const tbody = document.getElementById("library-books-table-body-sub") || document.getElementById("library-books-table-body");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-muted-custom text-xs">Lade Vault-Bestand aus 02_Wissensbibliothek...</td></tr>`;
      }
      try {
        const res = await fetch("/api/v1/library/books");
        if (res.ok) {
          const data = await res.json();
          libraryBooksList = data.books || [];
          
          updateLibraryCategoryCounts();
          renderLibraryBooksTable();
        } else {
          if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-rose-400 text-xs">Fehler beim Laden der Bibliothek.</td></tr>`;
        }
      } catch (e) {
        console.error("Failed to load library books:", e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-rose-400 text-xs">Verbindungsfehler zur Bibliothek: ${e.message}</td></tr>`;
      }
    }
    function onLibraryCategorySelectChange(val) {
      const customInput = document.getElementById("library-custom-category-input");
      if (customInput) {
        if (val === "custom") {
          customInput.classList.remove("hidden");
          customInput.focus();
        } else {
          customInput.classList.add("hidden");
        }
      }
    }
    function updateLibraryCategoryCounts() {
      const container = document.getElementById("library-category-filter-container-sub") || document.getElementById("library-category-filter-container");
      const hubCount = document.getElementById("lib-hub-books-count-sub") || document.getElementById("lib-hub-books-count");
      if (hubCount) hubCount.innerText = `${libraryBooksList.length} Dokumente & Werke`;
      if (!container) return;
      // Group all books by category
      const catCounts = { "ALL": libraryBooksList.length };
      libraryBooksList.forEach(b => {
        const cat = b.category || "04_Allgemein";
        catCounts[cat] = (catCounts[cat] || 0) + 1;
      });
      const catIcons = {
        "01_Immobilien_Modulbau": "🏗️",
        "02_Recht_Steuern": "⚖️",
        "03_Strategie_Markt": "📈",
        "04_Allgemein": "📚",
        "05_Gesetze": "📜",
        "06_Cannabis_Wirtschaft_Medizin": "🌿",
        "07_Betriebswirtschaft_Finanzen": "💼",
        "08_Projektmanagement_Organisation": "📋",
        "09_Tech_Software_KI": "💻",
        "10_Medizin_Gesundheit": "🩺",
        "00_Notebook_Synthesen": "✨"
      };
      let html = `
        <button type="button" onclick="setLibraryCategoryFilter('ALL')" id="lib-filter-btn-ALL" class="lib-filter-btn px-3 py-1 rounded-full ${libraryActiveCategoryFilter === 'ALL' ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-bold' : 'bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] hover:opacity-80'} transition cursor-pointer">
          Alle (${libraryBooksList.length})
        </button>
      `;
      Object.keys(catCounts).forEach(cat => {
        if (cat === "ALL") return;
        const icon = catIcons[cat] || "📁";
        const cleanName = cat.replace(/^\d+_/, '').replace(/_/g, ' ');
        const count = catCounts[cat];
        const isActive = libraryActiveCategoryFilter === cat;
        html += `
          <button type="button" onclick="setLibraryCategoryFilter('${cat}')" id="lib-filter-btn-${cat}" class="lib-filter-btn px-3 py-1 rounded-full ${isActive ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-bold' : 'bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] hover:opacity-80'} transition cursor-pointer flex items-center gap-1">
            <span>${icon} ${cleanName}</span>
            <span class="opacity-75">(${count})</span>
          </button>
        `;
      });
      container.innerHTML = html;
    }
    function setLibraryCategoryFilter(cat) {
      libraryActiveCategoryFilter = cat;
      document.querySelectorAll(".lib-filter-btn").forEach(btn => {
        btn.className = "lib-filter-btn px-3 py-1 rounded-full bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] hover:opacity-80 transition cursor-pointer flex items-center gap-1";
      });
      const activeBtn = document.getElementById(`lib-filter-btn-${cat}`);
      if (activeBtn) {
        activeBtn.className = "lib-filter-btn px-3 py-1 rounded-full bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-bold transition cursor-pointer flex items-center gap-1";
      }
      filterLibraryTable();
    }
    function filterLibraryTable() {
      const searchInput = document.getElementById("library-search-input-sub") || document.getElementById("library-search-input");
      const searchVal = (searchInput?.value || "").toLowerCase().trim();
      
      let filtered = libraryBooksList.filter(book => {
        if (libraryActiveCategoryFilter !== 'ALL') {
          if (book.category !== libraryActiveCategoryFilter && !book.rel_path.startsWith(libraryActiveCategoryFilter)) {
            return false;
          }
        }
        if (searchVal) {
          const matchTitle = (book.title || "").toLowerCase().includes(searchVal);
          const matchFile = (book.filename || "").toLowerCase().includes(searchVal);
          const matchPath = (book.rel_path || "").toLowerCase().includes(searchVal);
          const matchCat = (book.category || "").toLowerCase().includes(searchVal);
          if (!matchTitle && !matchFile && !matchPath && !matchCat) return false;
        }
        return true;
      });
      renderLibraryBooksTable(filtered);
    }
    function renderLibraryBooksTable(books = null) {
      const list = books !== null ? books : libraryBooksList;
      const tbody = document.getElementById("library-books-table-body-sub") || document.getElementById("library-books-table-body");
      if (!tbody) return;
      if (list.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="5" class="py-8 text-center text-muted-custom text-xs">
              Keine Dokumente in dieser Kategorie gefunden. Ziehe oben neue Dokumente hinein, um dein Wissen zu erweitern.
            </td>
          </tr>
        `;
        return;
      }
      let html = "";
      list.forEach(book => {
        const isOcr = book.ocr_used;
        const pages = book.total_pages || 1;
        const sizeKb = Math.round((book.size_bytes || 0) / 1024);
        
        let catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">${book.category}</span>`;
        const catLow = (book.category || "").toLowerCase();
        if (catLow.includes("cannabis") || catLow.includes("hanf")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">🌿 Cannabis & Agrar</span>`;
        } else if (catLow.includes("betriebswirtschaft") || catLow.includes("finanz")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">💼 BWL & Finanzen</span>`;
        } else if (catLow.includes("projektmanagement") || catLow.includes("scrum")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">📋 Projektmanagement</span>`;
        } else if (catLow.includes("immo") || catLow.includes("modul")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">🏗️ Immo & Modulbau</span>`;
        } else if (catLow.includes("recht") || catLow.includes("steuer") || catLow.includes("gesetz")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">⚖️ Recht & Steuern</span>`;
        } else if (catLow.includes("strategie") || catLow.includes("markt")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">📈 Strategie</span>`;
        } else if (catLow.includes("tech") || catLow.includes("software")) {
          catBadge = `<span class="px-2 py-0.5 rounded text-[10px] bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-mono">💻 Tech & KI</span>`;
        }
        const formatBadge = isOcr
          ? `<span class="px-2 py-0.5 rounded bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] text-[10px] font-bold flex items-center gap-1 w-max"><i data-lucide="scan" class="w-3 h-3 text-black dark:text-white"></i> OCR Scan</span>`
          : `<span class="px-2 py-0.5 rounded bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] text-[10px] font-bold flex items-center gap-1 w-max"><i data-lucide="file-text" class="w-3 h-3 text-black dark:text-white"></i> Markdown</span>`;
        const obsidianUri = getObsidianDocUri(book.rel_path);
        html += `
          <tr class="hover:bg-[var(--secondary)] transition-colors">
            <td class="py-3 px-3">
              <div class="font-bold text-primary-custom text-xs flex items-center gap-2">
                <i data-lucide="${book.is_index ? 'book-open' : 'file-text'}" class="w-4 h-4 text-black dark:text-white shrink-0"></i>
                <span class="truncate max-w-[280px]" title="${book.title}">${book.title}</span>
              </div>
              <div class="text-[10px] text-muted-custom font-mono mt-0.5 truncate max-w-[280px]">${book.filename}</div>
            </td>
            <td class="py-3 px-3">${catBadge}</td>
            <td class="py-3 px-3 text-muted-custom text-xs">${pages} ${pages === 1 ? 'Seite' : 'Seiten'} <span class="text-[10px] opacity-70">(${sizeKb} KB)</span></td>
            <td class="py-3 px-3">${formatBadge}</td>
            <td class="py-3 px-3 text-right">
              <div class="flex items-center justify-end gap-1.5">
                <button type="button" onclick="previewLibraryBook('${book.rel_path}', '${book.title.replace(/'/g, "\\'")}')" class="px-2.5 py-1 rounded-lg bg-[var(--secondary)] hover:bg-[var(--border)] text-[var(--foreground)] text-xs font-medium border border-[var(--border)] transition flex items-center gap-1 cursor-pointer" title="Notiz im Browser lesen">
                  <i data-lucide="eye" class="w-3.5 h-3.5"></i> Vorschau
                </button>
                <a href="${obsidianUri}" class="px-2.5 py-1 rounded-lg bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-90 text-xs font-medium transition flex items-center gap-1 cursor-pointer" title="Direkt in Obsidian öffnen">
                  <i data-lucide="external-link" class="w-3.5 h-3.5"></i> Obsidian
                </a>
              </div>
            </td>
          </tr>
        `;
      });
      tbody.innerHTML = html;
      lucide.createIcons();
    }
    // ==========================================
    // DRAG & DROP AND UPLOAD HANDLERS
    // ==========================================
    function onLibraryDragOver(e) {
      e.preventDefault();
      const dropzones = [document.getElementById("library-dropzone"), document.getElementById("library-dropzone-sub")];
      dropzones.forEach(dz => {
        if (dz) dz.classList.add("border-indigo-500", "bg-indigo-50", "scale-[1.005]");
      });
    }
    function onLibraryDragLeave(e) {
      e.preventDefault();
      const dropzones = [document.getElementById("library-dropzone"), document.getElementById("library-dropzone-sub")];
      dropzones.forEach(dz => {
        if (dz) dz.classList.remove("border-indigo-500", "bg-indigo-50", "scale-[1.005]");
      });
    }
    function onLibraryDrop(e) {
      e.preventDefault();
      onLibraryDragLeave(e);
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        addFilesToLibraryQueue(Array.from(e.dataTransfer.files));
      }
    }
    function onLibraryFileInputChange(e) {
      if (e.target.files && e.target.files.length > 0) {
        addFilesToLibraryQueue(Array.from(e.target.files));
      }
    }
    function addFilesToLibraryQueue(files) {
      const allowedExts = [".pdf", ".docx", ".doc", ".txt", ".md", ".epub", ".mobi", ".azw"];
      const validFiles = files.filter(f => {
        const ext = "." + f.name.split('.').pop().toLowerCase();
        return allowedExts.includes(ext);
      });
      if (validFiles.length === 0) {
        alert("Bitte wähle gültige PDF-, Word- oder Textdokumente aus.");
        return;
      }
      librarySelectedFiles = [...librarySelectedFiles, ...validFiles];
      renderLibrarySelectedFiles();
    }
    function renderLibrarySelectedFiles() {
      const containers = [
        document.getElementById("library-selected-files-container"),
        document.getElementById("library-selected-files-container-sub")
      ].filter(Boolean);
      const lists = [
        document.getElementById("library-selected-files-list"),
        document.getElementById("library-selected-files-list-sub")
      ].filter(Boolean);
      const countLabels = [
        document.getElementById("library-files-count-label"),
        document.getElementById("library-files-count-label-sub")
      ].filter(Boolean);
      if (containers.length === 0) return;
      if (librarySelectedFiles.length === 0) {
        containers.forEach(c => c.classList.add("hidden"));
        return;
      }
      containers.forEach(c => c.classList.remove("hidden"));
      const labelText = `${librarySelectedFiles.length} ${librarySelectedFiles.length === 1 ? 'Datei' : 'Dateien'} ausgewählt:`;
      countLabels.forEach(l => l.innerText = labelText);
      let html = "";
      librarySelectedFiles.forEach((file, idx) => {
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        html += `
          <div class="flex items-center justify-between p-2 rounded-lg bg-slate-50 border border-slate-200 text-xs font-mono">
            <div class="flex items-center gap-2 min-w-0">
              <i data-lucide="file" class="w-4 h-4 text-indigo-500 shrink-0"></i>
              <span class="text-slate-800 font-bold truncate">${file.name}</span>
              <span class="text-slate-500 text-[11px] shrink-0">(${sizeMb} MB)</span>
            </div>
            <button type="button" onclick="removeLibraryFileFromQueue(${idx})" class="p-1 text-slate-400 hover:text-rose-500 transition cursor-pointer" title="Entfernen">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        `;
      });
      lists.forEach(list => list.innerHTML = html);
      lucide.createIcons();
    }
    function removeLibraryFileFromQueue(idx) {
      librarySelectedFiles.splice(idx, 1);
      renderLibrarySelectedFiles();
    }
    function clearLibrarySelectedFiles() {
      librarySelectedFiles = [];
      renderLibrarySelectedFiles();
      const inp1 = document.getElementById("library-file-input");
      if (inp1) inp1.value = "";
      const inp2 = document.getElementById("library-file-input-sub");
      if (inp2) inp2.value = "";
    }
    // ==========================================
    // UPLOAD & INGEST EXECUTION
    // ==========================================
    async function startLibraryUploadAndIngest() {
      if (librarySelectedFiles.length === 0) {
        alert("Keine Dateien ausgewählt! Bitte klicke auf die Dropzone oder ziehe Dokumente hinein.");
        return;
      }
      const statusBox = document.getElementById("library-ingest-status-box");
      const title = document.getElementById("library-ingest-status-title");
      const percent = document.getElementById("library-ingest-status-percent");
      const bar = document.getElementById("library-ingest-progress-bar");
      const log = document.getElementById("library-ingest-log");
      const btns = [
        document.getElementById("btn-start-library-upload"),
        document.querySelector("#library-selected-files-container-sub button[onclick='startLibraryUploadAndIngest()']")
      ].filter(Boolean);
      if (statusBox) statusBox.classList.remove("hidden");
      btns.forEach(b => {
        b.disabled = true;
        b.classList.add("opacity-50", "pointer-events-none");
      });
      try {
        let category = document.getElementById("library-upload-category-sub")?.value || document.getElementById("library-upload-category")?.value || "auto";
        if (category === "custom") {
          const customVal = document.getElementById("library-custom-category-input-sub")?.value.trim() || document.getElementById("library-custom-category-input")?.value.trim();
          category = customVal || "auto";
        }
        const total = librarySelectedFiles.length;
        let completedCount = 0;
        let logHtml = "";
        
        for (let i = 0; i < total; i++) {
          const file = librarySelectedFiles[i];
          const currentNum = i + 1;
          const currentPct = Math.round((i / total) * 100);
          
          if (title) title.innerHTML = `<span class="w-2 h-2 rounded-full bg-indigo-500 animate-ping"></span> <span>Verarbeite [${currentNum}/${total}]: ${file.name}...</span>`;
          if (bar) bar.style.width = `${Math.max(5, currentPct)}%`;
          if (percent) percent.innerText = `${currentPct}%`;
          
          const formData = new FormData();
          formData.append("files", file);
          formData.append("category", category);
          formData.append("auto_ingest", "true");
          
          try {
            const res = await fetch("/api/v1/library/upload", {
              method: "POST",
              body: formData
            });
            if (res.ok) {
              const result = await res.json();
              completedCount++;
              const ingest = (result.items && result.items[0] && result.items[0].ingest) || {};
              logHtml = `<div class="text-emerald-600 font-mono text-xs">✓ [${currentNum}/${total}] <b>${file.name}</b> (${ingest.total_pages || 1} Seiten, ${ingest.chapters_count || 1} Kapitel ➔ ${ingest.category || 'Wissen'})</div>` + logHtml;
              if (log) log.innerHTML = logHtml;
            } else {
              const err = await res.json().catch(() => ({}));
              logHtml = `<div class="text-rose-600 font-mono text-xs">✗ [${currentNum}/${total}] ${file.name}: ${err.detail || 'Fehler'}</div>` + logHtml;
              if (log) log.innerHTML = logHtml;
            }
          } catch (e) {
            logHtml = `<div class="text-rose-600 font-mono text-xs">✗ [${currentNum}/${total}] ${file.name}: ${e.message}</div>` + logHtml;
            if (log) log.innerHTML = logHtml;
          }
          
          const donePct = Math.round(((i + 1) / total) * 100);
          if (bar) bar.style.width = `${donePct}%`;
          if (percent) percent.innerText = `${donePct}%`;
        }
        
        if (title) title.innerHTML = `✅ <span>Fertig! ${completedCount} von ${total} Dokumenten erfolgreich in Obsidian eingelesen.</span>`;
        alert(`Erfassung abgeschlossen: ${completedCount} von ${total} Dokumenten wurden in Obsidian erfasst und sind bereit.`);
        clearLibrarySelectedFiles();
        await loadLibraryBooksList();
        if (typeof loadVaultTree === 'function') loadVaultTree();
      } catch (e) {
        console.error("Upload error:", e);
        if (title) title.innerHTML = `<span class="text-rose-500 font-bold">Fehler beim Upload: ${e.message}</span>`;
        alert(`Fehler beim Upload: ${e.message}`);
      } finally {
        btns.forEach(b => {
          b.disabled = false;
          b.classList.remove("opacity-50", "pointer-events-none");
        });
      }
    }
    async function runBatchLibraryIngest() {
      const statusBox = document.getElementById("library-ingest-status-box");
      const title = document.getElementById("library-ingest-status-title");
      const percent = document.getElementById("library-ingest-status-percent");
      const bar = document.getElementById("library-ingest-progress-bar");
      const log = document.getElementById("library-ingest-log");
      if (statusBox) statusBox.classList.remove("hidden");
      if (title) title.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-500 animate-ping"></span> <span>Scanne alle Rohdokumente in library/raw_docs/...</span>`;
      if (bar) bar.style.width = "50%";
      if (percent) percent.innerText = "50%";
      try {
        const res = await fetch("/api/v1/library/ingest", { method: "POST" });
        if (res.ok) {
          const summary = await res.json();
          if (bar) bar.style.width = "100%";
          if (percent) percent.innerText = "100%";
          if (title) title.innerHTML = `✅ <span>Batch-Ingest abgeschlossen (${summary.total_files} Dateien)!</span>`;
          if (log) {
            log.innerHTML = `
              <div class="text-emerald-400 font-bold">Ingest-Ergebnis:</div>
              <div>• Verarbeitete Dateien: ${summary.total_files}</div>
              <div>• Extrahierte Seiten: ${summary.processed_pages}</div>
              <div>• Abbildungen & Pläne: ${summary.extracted_images}</div>
              <div>• Erzeugte Kapitel: ${summary.created_chapters}</div>
            `;
          }
          await loadLibraryBooksList();
        } else {
          if (title) title.innerHTML = `<span class="text-rose-400">Fehler beim Ausführen des Batch-Ingests.</span>`;
        }
      } catch (e) {
        if (title) title.innerHTML = `<span class="text-rose-400">Fehler: ${e.message}</span>`;
      }
    }
    // ==========================================
    // LIVE NOTE PREVIEW DRAWER
    // ==========================================
    async function previewLibraryBook(relPath, title) {
      const drawer = document.getElementById("library-reader-drawer");
      const docTitle = document.getElementById("reader-doc-title");
      const docContent = document.getElementById("reader-doc-content");
      const obsidianLink = document.getElementById("reader-doc-obsidian-link");
      if (!drawer || !docContent) return;
      drawer.classList.remove("hidden");
      if (docTitle) docTitle.innerText = title;
      docContent.innerText = "Lade Dokumentinhalt aus Vault...";
      if (obsidianLink) {
        obsidianLink.href = getObsidianDocUri(relPath);
      }
      try {
        const res = await fetch(`/api/v1/library/book-content?rel_path=${encodeURIComponent(relPath)}`);
        if (res.ok) {
          const data = await res.json();
          docContent.innerText = data.content;
        } else {
          docContent.innerText = "Dokument konnte nicht geladen werden.";
        }
      } catch (e) {
        docContent.innerText = `Fehler beim Laden: ${e.message}`;
      }
      drawer.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    function closeLibraryReader() {
      const drawer = document.getElementById("library-reader-drawer");
      if (drawer) drawer.classList.add("hidden");
    }
      // CUSTOMIZER & CRM STYLE EXTRACTED TO js/customizer.js

      // SYSTEM CONTROL CENTER EXTRACTED TO js/system_settings.js


    // --- CONTEXT HELP SYSTEM ---
    let currentHelpViewId = "operations";
    let currentStarterPrompt = "";

    async function openContextHelp(viewId) {
      currentHelpViewId = viewId || "operations";
      const modal = document.getElementById("context-help-modal");
      if (!modal) return;
      modal.classList.remove("hidden");

      const titleEl = document.getElementById("help-modal-title");
      const subtitleEl = document.getElementById("help-modal-subtitle");
      const purposeEl = document.getElementById("help-modal-purpose");
      const actionsEl = document.getElementById("help-modal-actions");
      const starterTextEl = document.getElementById("help-modal-starter-text");
      const respEl = document.getElementById("help-chat-response");
      const inputEl = document.getElementById("help-chat-input");

      if (respEl) {
        respEl.classList.add("hidden");
        respEl.innerHTML = "";
      }
      if (inputEl) inputEl.value = "";

      if (purposeEl) purposeEl.innerText = "Lade Kontext...";
      if (actionsEl) actionsEl.innerHTML = "";

      try {
        const res = await fetch(`/api/help/context/${currentHelpViewId}`);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        if (titleEl) titleEl.innerText = data.title || "Bereichshilfe";
        if (subtitleEl) subtitleEl.innerText = data.subtitle || "System-Assistent";
        if (purposeEl) purposeEl.innerText = data.purpose || "";

        currentStarterPrompt = data.starter_prompt || "Was sind die wichtigsten Funktionen dieser Ansicht?";
        if (starterTextEl) starterTextEl.innerText = currentStarterPrompt;

        if (actionsEl && data.top_actions) {
          actionsEl.innerHTML = data.top_actions.map(act => `
            <div class="flex items-start gap-2 p-2 rounded-lg bg-[var(--card)] border border-[var(--border)] text-[11px] font-mono text-[var(--foreground)]">
              <span class="text-sky-500 font-bold">›</span>
              <span>${act}</span>
            </div>
          `).join("");
        }
      } catch (err) {
        console.error("Fehler beim Laden des Hilfe-Kontexts:", err);
        if (purposeEl) purposeEl.innerText = "Hilfe für diese Ansicht konnte nicht geladen werden.";
      }
      lucide.createIcons();
    }

    function closeContextHelp() {
      const modal = document.getElementById("context-help-modal");
      if (modal) modal.classList.add("hidden");
    }

    function applyHelpStarterPrompt() {
      const inputEl = document.getElementById("help-chat-input");
      if (inputEl) {
        inputEl.value = currentStarterPrompt;
        inputEl.focus();
      }
    }

    async function submitContextHelpQuestion() {
      const inputEl = document.getElementById("help-chat-input");
      const respEl = document.getElementById("help-chat-response");
      const submitBtn = document.getElementById("help-chat-submit-btn");
      if (!inputEl || !respEl) return;

      const question = inputEl.value.trim();
      if (!question) return;

      respEl.classList.remove("hidden");
      respEl.innerHTML = `<div class="flex items-center gap-2 text-[var(--muted-foreground)] font-mono text-[11px]"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-sky-500"></i> Assistent analysiert Ansicht & Kontext...</div>`;
      if (submitBtn) submitBtn.disabled = true;
      lucide.createIcons();

      try {
        const res = await fetch("/api/help/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            view_id: currentHelpViewId,
            question: question
          })
        });
        const data = await res.json();
        const answer = data.answer || "Keine Antwort erhalten.";
        respEl.innerHTML = `
          <div class="font-mono text-[10px] text-[var(--muted-foreground)] uppercase mb-1">Assistent (${data.source || 'Heuristik'}):</div>
          <div class="text-[12px] text-[var(--foreground)] leading-relaxed">${escapeHtmlHelp(answer)}</div>
        `;
      } catch (err) {
        respEl.innerHTML = `<span class="text-rose-500 font-mono text-[11px]">Fehler: ${err.message}</span>`;
      } finally {
        if (submitBtn) submitBtn.disabled = false;
        lucide.createIcons();
      }
    }

    function escapeHtmlHelp(str) {
      if (!str) return "";
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
    async function loadSmtpSettings() {
      const led = document.getElementById("smtp-status-led");
      const statusText = document.getElementById("smtp-status-text");
      try {
        const res = await fetch("/api/v1/settings/smtp");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        const cfg = data.config || {};
        const en = document.getElementById("setting-smtp-enabled");
        const auto = document.getElementById("setting-smtp-auto-send");
        const host = document.getElementById("setting-smtp-host");
        const port = document.getElementById("setting-smtp-port");
        const user = document.getElementById("setting-smtp-user");
        const pass = document.getElementById("setting-smtp-pass");
        const from = document.getElementById("setting-smtp-from");
        const to = document.getElementById("setting-smtp-to");
        const tls = document.getElementById("setting-smtp-tls");
        if (en) en.checked = !!cfg.enabled;
        if (auto) auto.checked = !!cfg.auto_send;
        if (host) host.value = cfg.host || "";
        if (port) port.value = cfg.port || 587;
        if (user) user.value = cfg.username || "";
        if (pass) pass.value = cfg.password || "";
        if (from) from.value = cfg.from_email || "";
        if (to) to.value = cfg.to_email || "";
        if (tls) tls.checked = cfg.use_tls !== false;
        if (led && statusText) {
          if (cfg.enabled && cfg.host) {
            led.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
            statusText.innerText = `Aktiv (${cfg.auto_send ? 'Auto-Versand AN' : 'Manuell'})`;
          } else {
            led.className = "w-2.5 h-2.5 rounded-full bg-zinc-400";
            statusText.innerText = "Inaktiv / Nicht konfiguriert";
          }
        }
      } catch (err) {
        console.error("Fehler beim Laden der SMTP-Settings:", err);
        if (statusText) statusText.innerText = "Fehler beim Laden";
      }
    }
    async function saveSmtpSettings() {
      const feedback = document.getElementById("smtp-feedback");
      const payload = {
        enabled: document.getElementById("setting-smtp-enabled")?.checked || false,
        auto_send: document.getElementById("setting-smtp-auto-send")?.checked || false,
        host: document.getElementById("setting-smtp-host")?.value.trim() || "",
        port: parseInt(document.getElementById("setting-smtp-port")?.value || "587", 10),
        username: document.getElementById("setting-smtp-user")?.value.trim() || "",
        password: document.getElementById("setting-smtp-pass")?.value || "",
        from_email: document.getElementById("setting-smtp-from")?.value.trim() || "",
        to_email: document.getElementById("setting-smtp-to")?.value.trim() || "",
        use_tls: document.getElementById("setting-smtp-tls")?.checked !== false
      };
      if (feedback) feedback.innerHTML = `<span class="text-zinc-500">Speichere...</span>`;
      try {
        const res = await fetch("/api/v1/settings/smtp", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Fehler beim Speichern");
        if (feedback) {
          feedback.innerHTML = `<span class="text-emerald-600 dark:text-emerald-400 font-semibold">Erfolgreich gespeichert!</span>`;
          setTimeout(() => { if (feedback) feedback.innerHTML = ""; }, 3000);
        }
        loadSmtpSettings();
        if (typeof window.showNotification === "function") {
          window.showNotification("SMTP Settings", "E-Mail Einstellungen erfolgreich aktualisiert.", "success");
        }
      } catch (err) {
        if (feedback) {
          feedback.innerHTML = `<span class="text-rose-600 dark:text-rose-400 font-semibold">Fehler: ${escapeHtml(err.message)}</span>`;
        }
      }
    }
    async function testSmtpConnection() {
      const feedback = document.getElementById("smtp-feedback");
      if (feedback) feedback.innerHTML = `<span class="text-blue-500 flex items-center gap-1 font-mono"><i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i> Sende Test-E-Mail...</span>`;
      if (window.lucide) lucide.createIcons();
      try {
        await saveSmtpSettings();
        const res = await fetch("/api/v1/settings/smtp/test", { method: "POST" });
        const data = await res.json();
        if (data.status === "sent") {
          if (feedback) {
            feedback.innerHTML = `<span class="text-emerald-600 dark:text-emerald-400 font-semibold">Test-Mail erfolgreich gesendet!</span>`;
          }
          if (typeof window.showNotification === "function") {
            window.showNotification("E-Mail Test", "Test-Mail wurde erfolgreich zugestellt!", "success");
          }
        } else {
          throw new Error(data.message || data.detail || "Senden fehlgeschlagen");
        }
      } catch (err) {
        if (feedback) {
          feedback.innerHTML = `<span class="text-rose-600 dark:text-rose-400 font-semibold">Fehler: ${escapeHtml(err.message)}</span>`;
        }
        if (typeof window.showNotification === "function") {
          window.showNotification("E-Mail Test", err.message, "error");
        }
      }
    }
    let currentConnectionMode = 'remote';
    function selectConnectionMode(mode) {
      currentConnectionMode = mode;
      const modes = ['local', 'cloud', 'remote', 'ssh'];
      modes.forEach(m => {
        const card = document.getElementById(`conn-card-${m}`);
        const check = document.getElementById(`conn-check-${m}`);
        if (m === mode) {
          if (card) card.className = "p-3.5 rounded-lg border-2 border-amber-500/80 bg-amber-500/5 cursor-pointer transition-all space-y-1.5 relative";
          if (check) check.classList.remove("hidden");
        } else {
          if (card) card.className = "p-3.5 rounded-lg border theme-border hover:border-amber-500/50 cursor-pointer transition-all space-y-1.5 relative opacity-80 hover:opacity-100";
          if (check) check.classList.add("hidden");
        }
      });
      lucide.createIcons();
    }
    async function testRemoteConnection() {
      return testOmniRouteConnection();
    }
    // --- MULTI-PROVIDER & GATEWAY MANAGEMENT ---
    async function loadLLMProvidersSettings() {
      const activeContainer = document.getElementById("llm-active-provider-banner");
      const listContainer = document.getElementById("llm-providers-cards-container");
      if (!listContainer) return;
      try {
        const res = await fetch("/api/llm-providers");
        if (!res.ok) throw new Error("HTTP Fehler " + res.status);
        const data = await res.json();
        if (data.status !== "ok") return;
        const activeCfg = data.active_config || {};
        const activeProvider = activeCfg.provider || "groq";
        const activeModel = activeCfg.model || "evey-session-guard:";
        const activeBaseUrl = activeCfg.base_url || "";
        if (activeContainer) {
          activeContainer.innerHTML = `
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between p-3.5 rounded-xl border border-emerald-500/30 bg-emerald-500/5 shadow-2xs gap-3">
              <div class="flex items-center gap-3">
                <span class="w-3 h-3 rounded-full bg-emerald-500 animate-pulse shrink-0"></span>
                <div>
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-xs font-bold text-[var(--foreground)] uppercase font-mono">Aktiver Live-Provider:</span>
                    <span class="text-xs font-bold text-emerald-600 dark:text-emerald-400 font-mono">${escapeHtml(activeProvider.toUpperCase())}</span>
                    ${activeBaseUrl ? `<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--secondary)] text-[var(--muted-foreground)] border border-[var(--border)]">${escapeHtml(activeBaseUrl)}</span>` : ''}
                  </div>
                  <div class="text-[11px] text-[var(--muted-foreground)] font-mono mt-0.5">
                    Aktives Modell: <span class="font-semibold text-[var(--foreground)]">${escapeHtml(activeModel)}</span>
                  </div>
                </div>
              </div>
              <button onclick="deployAllApiKeysToProfiles()" class="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[11px] font-mono font-medium hover:bg-[var(--secondary)] transition cursor-pointer flex items-center gap-1.5 shadow-2xs shrink-0" title="Verteilt alle Keys auf isolierte Profile (.env)">
                <i data-lucide="key" class="w-3.5 h-3.5"></i>
                <span>Keys auf Profile verteilen</span>
              </button>
            </div>
          `;
        }
        const providers = data.providers || [];
        listContainer.innerHTML = providers.map(p => {
          const isActive = p.is_active;
          const hasKey = p.has_key;
          const badgeClass = isActive 
            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 font-bold" 
            : (hasKey ? "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20" : "bg-neutral-500/10 text-neutral-500 border-neutral-500/20");
          const badgeText = isActive ? "● LIVE AKTIV" : (hasKey ? "BEREIT" : "KEIN KEY");
          return `
            <div class="p-3.5 rounded-xl border ${isActive ? 'border-emerald-500/40 bg-[var(--card)] ring-1 ring-emerald-500/20' : 'border-[var(--border)] bg-[var(--card)]'} shadow-xs flex flex-col justify-between space-y-3">
              <div>
                <div class="flex items-center justify-between pb-2 border-b border-[var(--border)]">
                  <div class="flex items-center gap-2">
                    <span class="font-bold text-xs font-mono text-[var(--foreground)]">${escapeHtml(p.name)}</span>
                    <span class="text-[9px] font-mono px-1.5 py-0.5 rounded border ${badgeClass}">${badgeText}</span>
                  </div>
                  <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${p.model_count ? p.model_count + ' Modelle' : ''}</span>
                </div>
                
                <div class="mt-2.5 space-y-2">
                  <div>
                    <label class="block text-[10px] font-mono uppercase font-bold text-[var(--muted-foreground)] mb-1">
                      API-Key (${escapeHtml(p.key_env)})
                    </label>
                    <div class="flex items-center gap-1.5">
                      <input type="password" id="key-input-${p.id}" placeholder="${p.key_masked ? 'Key gespeichert (' + p.key_masked + ')' : 'API-Key eintragen...'}" class="flex-1 bg-[var(--background)] border border-[var(--border)] rounded px-2 py-1 text-xs font-mono text-[var(--foreground)] focus:outline-none shadow-2xs">
                      <button type="button" onclick="saveProviderKey('${p.id}', '${p.key_env}')" class="px-2.5 py-1 rounded bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 text-[11px] font-mono font-semibold border border-[var(--border)] transition cursor-pointer shrink-0" title="Key speichern & verteilen">
                        Speichern
                      </button>
                    </div>
                  </div>
                  <div>
                    <label class="block text-[10px] font-mono uppercase font-bold text-[var(--muted-foreground)] mb-1">
                      Standard-Modell
                    </label>
                    <div class="flex items-center gap-1.5">
                      <select id="model-select-${p.id}" onchange="if(${isActive ? 'true' : 'false'}) activateLlmProvider('${p.id}')" class="flex-1 bg-[var(--background)] border border-[var(--border)] rounded px-2 py-1 text-xs font-mono text-[var(--foreground)] focus:outline-none cursor-pointer shadow-2xs truncate">
                        <option value="${escapeHtml(p.default_model || '')}">${escapeHtml(p.default_model || 'Modelle laden...')}</option>
                      </select>
                      <button type="button" onclick="fetchSettingsProviderModelsList('${p.id}')" class="p-1 rounded bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 border border-[var(--border)] transition cursor-pointer shrink-0" title="Modelle aktualisieren">
                        <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between">
                <span class="text-[10px] font-mono text-[var(--muted-foreground)] truncate max-w-[140px]">${p.api || 'Native SDK'}</span>
                ${isActive ? `
                  <button type="button" onclick="activateLlmProvider('${p.id}')" class="px-2.5 py-1 rounded-lg text-[11px] font-mono font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 flex items-center gap-1 transition cursor-pointer" title="Ausgewähltes Standard-Modell übernehmen">
                    <i data-lucide="check" class="w-3.5 h-3.5"></i> Aktiv (Modell übernehmen)
                  </button>
                ` : `
                  <button type="button" onclick="activateLlmProvider('${p.id}')" class="px-3 py-1 rounded-lg text-xs font-bold bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-90 transition cursor-pointer shadow-2xs">
                    Aktivieren
                  </button>
                `}
              </div>
            </div>
          `;
        }).join("");
        if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
        // Dynamically load models for each provider in background
        providers.forEach(p => {
          fetchSettingsProviderModelsList(p.id, p.default_model);
        });
      } catch (err) {
        console.warn("[LLM Providers] Fehler:", err);
      }
    }
    async function fetchSettingsProviderModelsList(providerId, currentModel) {
      try {
        const res = await fetch(`/api/llm-providers/models?provider=${encodeURIComponent(providerId)}`);
        if (!res.ok) return;
        const data = await res.json();
        const select = document.getElementById(`model-select-${providerId}`);
        if (!select || !data.models || !data.models.length) return;
        const activeVal = currentModel || select.value;
        select.innerHTML = data.models.map(m => {
          const isSel = (m === activeVal) ? "selected" : "";
          return `<option value="${escapeHtml(m)}" ${isSel}>${escapeHtml(m)}</option>`;
        }).join("");
      } catch (e) {}
    }
    async function activateLlmProvider(providerId) {
      const select = document.getElementById(`model-select-${providerId}`);
      const model = select ? select.value : null;
      try {
        const res = await fetch("/api/llm-providers/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: providerId, model: model })
        });
        const data = await res.json();
        if (data.status === "ok") {
          loadLLMProvidersSettings();
          if (typeof loadHermesFormSettings === "function") loadHermesFormSettings();
          if (typeof loadMasterChatModels === "function") loadMasterChatModels();
          if (typeof populateAgentTabModels === "function") populateAgentTabModels();
          if (typeof showNotification === "function") {
            showNotification("Provider & Modell", `Standard-Modell '${model || providerId}' aktiviert und mit Hermes Core synchronisiert.`, "success");
          }
        } else {
          alert("Fehler beim Aktivieren: " + (data.message || "Unbekannt"));
        }
      } catch (err) {
        alert("Netzwerkfehler: " + err.message);
      }
    }
    async function saveProviderKey(providerId, envName) {
      const input = document.getElementById(`key-input-${providerId}`);
      if (!input) return;
      const keyVal = input.value.trim();
      if (!keyVal) {
        alert("Bitte einen API-Key eingeben.");
        return;
      }
      try {
        const res = await fetch("/api/llm-providers/save-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ env_name: envName, key_value: keyVal })
        });
        const data = await res.json();
        if (data.status === "ok") {
          input.value = "";
          alert(data.message || "Key gespeichert!");
          loadLLMProvidersSettings();
        } else {
          alert("Fehler: " + (data.message || "Konnte Key nicht speichern"));
        }
      } catch (err) {
        alert("Netzwerkfehler: " + err.message);
      }
    }
    async function deployAllApiKeysToProfiles() {
      try {
        const res = await fetch("/api/llm-providers/save-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ env_name: "DEPLOY_TRIGGER", key_value: "1" })
        });
        alert("API-Keys wurden erfolgreich über alle isolierten Hermes-Profile synchronisiert.");
        loadLLMProvidersSettings();
      } catch (err) {
        alert("Fehler bei der Synchronisation: " + err.message);
      }
    }
    async function testOmniRouteConnection() {
      const gwUrl = (document.getElementById("setting-gateway-url").value.trim() || "http://localhost:20128/v1").replace(/\/+$/, '');
      const gwKey = document.getElementById("setting-gateway-key").value.trim() || "omniroute-local-key";
      const ledEl = document.getElementById("omniroute-status-led");
      const textEl = document.getElementById("omniroute-status-text");
      const modelListEl = document.getElementById("omniroute-model-list");
      if (ledEl) { ledEl.className = "inline-block w-2 h-2 rounded-full bg-zinc-400 dark:bg-zinc-500 animate-pulse"; }
      if (textEl) { textEl.textContent = "PRÜFE..."; textEl.className = "text-[9px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]"; }
      try {
        const resp = await fetch(gwUrl + "/models", {
          headers: { "Authorization": "Bearer " + gwKey },
          signal: AbortSignal.timeout(5000)
        });
        if (resp.ok) {
          const data = await resp.json();
          const models = (data.data || data || []).map(m => m.id || m);
          if (ledEl) { ledEl.className = "inline-block w-2 h-2 rounded-full bg-zinc-900 dark:bg-zinc-100"; }
          if (textEl) { textEl.textContent = "VERBUNDEN"; textEl.className = "text-[9px] font-bold uppercase tracking-wider text-zinc-900 dark:text-zinc-100 font-mono"; }
          if (modelListEl) {
            modelListEl.innerHTML = models.map(m =>
              `<span class="px-2 py-1 rounded border border-[var(--border)] text-[10px] font-mono text-[var(--foreground)] bg-[var(--card)]">${m}</span>`
            ).join("");
          }
        } else {
          if (ledEl) { ledEl.className = "inline-block w-2 h-2 rounded-full bg-zinc-400"; }
          if (textEl) { textEl.textContent = "HTTP " + resp.status; textEl.className = "text-[9px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]"; }
        }
      } catch (err) {
        if (ledEl) { ledEl.className = "inline-block w-2 h-2 rounded-full bg-zinc-400"; }
        if (textEl) { textEl.textContent = "FEHLER"; textEl.className = "text-[9px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]"; }
        console.error("OmniRoute test failed:", err);
      }
    }
    function toggleKeyVisibility() {
      const input = document.getElementById("setting-gateway-key");
      if (input.type === "password") {
        input.type = "text";
      } else {
        input.type = "password";
      }
    }
    function renderSettingsServices() {
      const container = document.getElementById("coupled-services-list");
      if (!container) return;
      container.innerHTML = "";
      servicesList.forEach(service => {
        const card = document.createElement("div");
        card.className = "p-3.5 rounded-xl border border-[var(--border)] flex items-start justify-between gap-4 bg-[var(--card)] hover:border-zinc-400 dark:hover:border-zinc-500 transition shadow-xs";
        const ledColor = service.online ? "bg-zinc-900 dark:bg-zinc-100" : "bg-zinc-400 dark:bg-zinc-600";
        let roleOptions = "";
        roles.forEach(r => {
          const sel = (service.role === r.name || service.role === r.id) ? "selected" : "";
          roleOptions += `<option value="${r.id}" ${sel}>${r.name}</option>`;
        });
        let modelOptions = "";
        modelsList.forEach(m => {
          const sel = service.model === m ? "selected" : "";
          modelOptions += `<option value="${m}" ${sel}>${m}</option>`;
        });
        card.innerHTML = `
          <div class="flex-1 space-y-1 text-xs">
            <div class="flex items-center gap-2">
              <span class="inline-block w-2 h-2 rounded-full ${ledColor}"></span>
              <span class="font-bold text-xs uppercase text-[var(--foreground)]">${service.name}</span>
              <span class="text-[9px] font-mono bg-[var(--secondary)] px-1.5 py-0.5 rounded text-[var(--muted-foreground)] border border-[var(--border)]">@${service.id}</span>
            </div>
            <p class="text-[10px] text-[var(--muted-foreground)] leading-tight">${service.description}</p>
            
            <div class="flex gap-2 mt-2 pt-2 border-t border-[var(--border)]">
              <div class="flex-1">
                <label class="block text-[8px] uppercase font-bold text-[var(--muted-foreground)] mb-0.5">Modell</label>
                <select onchange="updateServiceField('${service.id}', 'model', this.value)" class="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] rounded text-[10px] px-1.5 py-0.5 focus:outline-none cursor-pointer">
                  ${modelOptions}
                </select>
              </div>
              <div class="flex-1">
                <label class="block text-[8px] uppercase font-bold text-[var(--muted-foreground)] mb-0.5">Rolle</label>
                <select onchange="updateServiceField('${service.id}', 'role', this.value)" class="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] rounded text-[10px] px-1.5 py-0.5 focus:outline-none cursor-pointer">
                  ${roleOptions}
                </select>
              </div>
            </div>
          </div>
          <div class="flex flex-col items-end justify-between h-full gap-2 text-xs">
            <span class="text-[9px] font-bold uppercase tracking-wider ${service.active ? 'text-zinc-900 dark:text-zinc-100' : 'text-[var(--muted-foreground)]'}">
              ${service.active ? 'GEKOPPELT' : 'INAKTIV'}
            </span>
            <label class="relative inline-flex items-center cursor-pointer mt-1">
              <input type="checkbox" ${service.active ? 'checked' : ''} onchange="toggleServiceActive('${service.id}')" class="rounded bg-[var(--secondary)] border border-[var(--border)] w-4 h-4 accent-zinc-900 dark:accent-zinc-100 cursor-pointer">
            </label>
          </div>
        `;
        container.appendChild(card);
      });
    }
    function updateServiceField(serviceId, field, value) {
      const service = servicesList.find(s => s.id === serviceId);
      if (service) {
        if (field === "role") {
          const selectedRole = roles.find(r => r.id === value);
          service.role = selectedRole ? selectedRole.name : value;
        } else {
          service[field] = value;
        }
      }
    }
    function toggleServiceActive(serviceId) {
      const service = servicesList.find(s => s.id === serviceId);
      if (service) {
        service.active = !service.active;
        service.coupled = service.active;
        if (!service.active) {
          // If deactivated, we can remove any running instances
          agents = agents.filter(a => a.id !== service.id);
        }
        renderSettingsServices();
        renderMasterChatAgentTabs();
      }
    }
    async function saveSystemSettings() {
      const gwEl = document.getElementById("setting-gateway-url");
      const wsEl = document.getElementById("setting-workspace-dir");
      const gwUrl = gwEl ? gwEl.value.trim() : "http://localhost:20128/v1";
      const wsDir = wsEl ? wsEl.value.trim() : "";
      // JEV Settings auslesen
      const jevEnabledEl = document.getElementById("setting-jev-enabled");
      const jevProviderEl = document.getElementById("setting-jev-provider");
      const jevUrlEl = document.getElementById("setting-jev-url");
      const jevKeyEl = document.getElementById("setting-jev-key");
      const jevFastpathEl = document.getElementById("setting-jev-fastpath");
      const jevPruningEl = document.getElementById("setting-jev-pruning");
      const jevRoutingEl = document.getElementById("setting-jev-routing");
      const jevModelEl = document.getElementById("setting-jev-model");
      const jevConfig = {
        enabled: jevEnabledEl ? jevEnabledEl.checked : false,
        provider: jevProviderEl ? jevProviderEl.value : "openrouter",
        base_url: jevUrlEl ? jevUrlEl.value.trim() : "https://openrouter.ai/api/v1",
        api_key: jevKeyEl ? jevKeyEl.value.trim() : "",
        model: jevModelEl ? jevModelEl.value.trim() : "typesafe/jev-latest",
        fast_path_enabled: jevFastpathEl ? jevFastpathEl.checked : true,
        tool_pruning_enabled: jevPruningEl ? jevPruningEl.checked : true,
        agent_routing_enabled: jevRoutingEl ? jevRoutingEl.checked : true
      };
      // Memory Settings auslesen
      const memEnabledEl = document.getElementById("setting-memory-enabled");
      const memAutoLearnEl = document.getElementById("setting-memory-autolearn");
      const memApplyEl = document.getElementById("setting-memory-apply-lessons");
      const memMaxLessonsEl = document.getElementById("setting-memory-max-lessons");
      const memHalfLifeEl = document.getElementById("setting-memory-halflife");
      const memThresholdEl = document.getElementById("setting-memory-threshold");
      const memAutoEvictEl = document.getElementById("setting-memory-auto-evict");
      const memVaultEl = document.getElementById("setting-memory-vault");
      const memDailyEl = document.getElementById("setting-memory-daily");
      const memHoursEl = document.getElementById("setting-memory-hours");
      const memoryConfig = {
        enabled: memEnabledEl ? memEnabledEl.checked : true,
        auto_learn: memAutoLearnEl ? memAutoLearnEl.checked : true,
        apply_lessons: memApplyEl ? memApplyEl.checked : true,
        max_injected_lessons: memMaxLessonsEl ? parseInt(memMaxLessonsEl.value, 10) || 3 : 3,
        half_life_days: memHalfLifeEl ? parseInt(memHalfLifeEl.value, 10) || 14 : 14,
        eviction_threshold: memThresholdEl ? parseFloat(memThresholdEl.value) || 0.1 : 0.1,
        auto_evict: memAutoEvictEl ? memAutoEvictEl.checked : false,
        vault_path: memVaultEl ? memVaultEl.value.trim() : "C:\\Mein Obsidian",
        daily_consolidation: memDailyEl ? memDailyEl.checked : true,
        hours_back: memHoursEl ? parseInt(memHoursEl.value, 10) || 24 : 24
      };
      // Email Guard Config
      const egEnabledEl = document.getElementById("setting-email-guard-enabled");
      const egMailEl = document.getElementById("setting-guard-protect-email");
      const egTgEl = document.getElementById("setting-guard-protect-telegram");
      const egCrmEl = document.getElementById("setting-guard-protect-crm");
      const egSensEl = document.getElementById("setting-guard-sensitivity");
      const emailGuardConfig = {
        enabled: egEnabledEl ? egEnabledEl.checked : true,
        protect_email: egMailEl ? egMailEl.checked : true,
        protect_telegram: egTgEl ? egTgEl.checked : true,
        protect_crm: egCrmEl ? egCrmEl.checked : true,
        sensitivity: egSensEl ? egSensEl.value : "moderate",
        use_llm: false,
        model: "omniroute/free-forever"
      };
      // Quality Gate & Validation Config
      const valEnabledEl = document.getElementById("setting-validate-enabled");
      const valMinEl = document.getElementById("setting-validate-min-score");
      const valFailEl = document.getElementById("setting-validate-on-failure");
      const valHalluEl = document.getElementById("setting-validate-check-hallucination");
      const valCutoffEl = document.getElementById("setting-validate-check-cutoff");
      const valLlmEl = document.getElementById("setting-validate-use-llm");
      const validateConfig = {
        enabled: valEnabledEl ? valEnabledEl.checked : true,
        min_score: valMinEl ? parseInt(valMinEl.value, 10) || 7 : 7,
        on_failure: valFailEl ? valFailEl.value : "warn",
        check_hallucinations: valHalluEl ? valHalluEl.checked : true,
        check_cutoff: valCutoffEl ? valCutoffEl.checked : true,
        use_llm: valLlmEl ? valLlmEl.checked : false,
        judge_model: "omniroute/free-forever"
      };
      try {
        await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            gateway_url: gwUrl, 
            workspace_dir: wsDir,
            jev: jevConfig,
            memory: memoryConfig,
            email_guard: emailGuardConfig,
            validate: validateConfig
          })
        });
        updateJevStatusPill(jevConfig.enabled);
        await fetch("/api/v1/services", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(servicesList)
        });
      } catch (e) {
        console.error("Error saving settings:", e);
      }
      if (typeof window.saveHermesFormSettings === "function") {
        await window.saveHermesFormSettings(false);
      }
      if (typeof window.saveAutonomyModulesSettings === "function") {
        await window.saveAutonomyModulesSettings(false);
      }
      if (typeof window.saveMemoryConsolidationSettings === "function") {
        await window.saveMemoryConsolidationSettings();
      }
      await saveThemeToServer(true);
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
      renderMasterChatAgentTabs();
      if (typeof loadMasterChatModels === "function") loadMasterChatModels();
      closeSystemSettingsModal();
      
      if (typeof showNotification === "function") {
        showNotification("System Control Center", "Alle Einstellungen (inkl. Standard-Sprachmodell, Hermes Core & Autonomie-Module) erfolgreich gespeichert!", "success");
      } else {
        alert("Systemkonfiguration und Designeinstellungen erfolgreich gespeichert!");
      }
    }
    // --- JEV FAST-ROUTING HELPER FUNCTIONS ---
    function onJevToggleChanged(checked) {
      const lbl = document.getElementById("setting-jev-toggle-label");
      if (lbl) lbl.innerText = checked ? "Aktiviert" : "Inaktiv";
    }
    function onJevProviderChanged(val) {
      const urlEl = document.getElementById("setting-jev-url");
      if (!urlEl) return;
      if (val === "openrouter") urlEl.value = "https://openrouter.ai/api/v1";
      else if (val === "typesafe") urlEl.value = "https://api.typesafe.ai/v1/systemone";
      else if (val === "omniroute") urlEl.value = "http://localhost:20128/v1";
    }
    function updateJevStatusPill(enabled) {
      const stateEl = document.getElementById("master-chat-jev-state");
      const badge = document.getElementById("master-chat-jev-badge");
      if (stateEl) {
        stateEl.innerText = enabled ? "ON" : "OFF";
        stateEl.className = enabled ? "text-[var(--foreground)] font-bold" : "text-[var(--muted-foreground)]";
      }
      if (badge) {
        if (enabled) {
          badge.className = "flex items-center gap-1.5 px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-semibold cursor-pointer transition-all shadow-xs";
        } else {
          badge.className = "flex items-center gap-1.5 px-2 py-0.5 rounded border border-[var(--border)] bg-[var(--secondary)] hover:bg-[var(--card)] text-[var(--foreground)] font-mono text-[10px] font-semibold cursor-pointer transition-all shadow-xs";
        }
      }
      // Synchronisiere auch Agent-Tab JEV Badge
      const agentStateEl = document.getElementById("agent-tab-jev-state");
      const agentBadge = document.getElementById("agent-tab-jev-badge");
      if (agentStateEl) {
        agentStateEl.innerText = enabled ? "ON" : "OFF";
        agentStateEl.className = enabled ? "text-[var(--foreground)] font-bold" : "text-[var(--muted-foreground)]";
      }
      if (agentBadge) {
        if (enabled) {
          agentBadge.className = "flex items-center gap-1.5 px-2 py-0.5 rounded border border-[var(--border)] bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 font-mono text-[10px] font-semibold cursor-pointer transition-all shadow-xs";
        } else {
          agentBadge.className = "flex items-center gap-1.5 px-2 py-0.5 rounded border border-[var(--border)] bg-[var(--secondary)] hover:bg-[var(--card)] text-[var(--foreground)] font-mono text-[10px] font-semibold cursor-pointer transition-all shadow-xs";
        }
      }
    }
    async function toggleJevFromMasterChat() {
      try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        const currentJev = data.jev || {};
        const newState = !currentJev.enabled;
        currentJev.enabled = newState;
        await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jev: currentJev })
        });
        updateJevStatusPill(newState);
        const tog = document.getElementById("setting-jev-enabled");
        if (tog) {
          tog.checked = newState;
          onJevToggleChanged(newState);
        }
        if (typeof showNotification === 'function') {
          showNotification("⚡ PreDecision Routing", newState ? "PreDecision Fast-Routing & Tool-Pruning AKTIVIERT." : "PreDecision Fast-Routing DEAKTIVIERT.", newState ? "success" : "info");
        }
      } catch (err) {
        console.error("Fehler beim Umschalten von JEV:", err);
      }
    }
    async function testJevConnection() {
      const resultEl = document.getElementById("jev-test-result");
      const keyEl = document.getElementById("setting-jev-key");
      const urlEl = document.getElementById("setting-jev-url");
      if (resultEl) {
        resultEl.innerHTML = '<span class="text-amber-500 font-mono text-xs animate-pulse">Prüfe Verbindung zu JEV...</span>';
      }
      try {
        const res = await fetch("/api/v1/jev/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            api_key: keyEl ? keyEl.value.trim() : "",
            base_url: urlEl ? urlEl.value.trim() : ""
          })
        });
        const data = await res.json();
        if (data.status === "success" || data.status === "connected") {
          resultEl.innerHTML = `<span class="text-emerald-500 font-mono text-xs font-bold">✓ ${data.message}</span>`;
        } else {
          resultEl.innerHTML = `<span class="text-rose-500 font-mono text-xs font-bold">✕ ${data.message}</span>`;
        }
      } catch (err) {
        if (resultEl) {
          resultEl.innerHTML = `<span class="text-rose-500 font-mono text-xs font-bold">✕ Verbindungsfehler: ${err.message}</span>`;
        }
      }
    }
    // --- ADAPTIVE MEMORY HELPER FUNCTIONS ---
    function onMemoryToggleChanged(checked) {
      const lbl = document.getElementById("setting-memory-toggle-label");
      if (lbl) lbl.innerText = checked ? "Aktiv" : "Inaktiv";
    }
    async function refreshMemoryStats() {
      try {
        const res = await fetch("/api/v1/memory/stats");
        if (!res.ok) return;
        const data = await res.json();
        const lEl = document.getElementById("memory-stat-learnings");
        if (lEl) lEl.innerText = data.learnings_count ?? "--";
        const cEl = document.getElementById("memory-stat-convs");
        if (cEl) cEl.innerText = data.conversations_count ?? "--";
        const vEl = document.getElementById("memory-stat-vault");
        if (vEl) vEl.innerText = data.vault_notes_count ?? "--";
        const sEl = document.getElementById("memory-stat-stale");
        if (sEl) sEl.innerText = data.stale_count ?? "--";
      } catch (err) {
        console.warn("Fehler beim Abrufen der Memory-Statistiken:", err);
      }
    }
    async function consolidateMemoryNow() {
      const resultEl = document.getElementById("memory-consolidate-result");
      const hoursEl = document.getElementById("setting-memory-hours");
      const hoursBack = hoursEl ? parseInt(hoursEl.value, 10) || 24 : 24;
      if (resultEl) {
        resultEl.innerHTML = '<span class="text-purple-500 font-mono text-xs animate-pulse">Konsolidiere Chats und exportiere nach Obsidian...</span>';
      }
      try {
        const res = await fetch("/api/v1/memory/consolidate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hours_back: hoursBack })
        });
        const data = await res.json();
        if (data.status === "success") {
          const noteHint = data.note_file ? ` (Datei: ${data.note_file})` : "";
          if (resultEl) {
            resultEl.innerHTML = `<span class="text-emerald-500 font-mono text-xs font-bold">✓ ${data.message}${noteHint}</span>`;
          }
          if (typeof showNotification === "function") {
            showNotification("🧠 Memory", data.message, "success");
          }
          refreshMemoryStats();
        } else {
          if (resultEl) {
            resultEl.innerHTML = `<span class="text-amber-500 font-mono text-xs font-bold">ℹ ${data.message || "Keine neuen Daten"}</span>`;
          }
        }
      } catch (err) {
        if (resultEl) {
          resultEl.innerHTML = `<span class="text-rose-500 font-mono text-xs font-bold">✕ Fehler: ${err.message}</span>`;
        }
      }
    }
    async function evictStaleMemoryNow() {
      const resultEl = document.getElementById("memory-evict-result");
      const threshEl = document.getElementById("setting-memory-threshold");
      const threshold = threshEl ? parseFloat(threshEl.value) || 0.1 : 0.1;
      if (!confirm(`Sollen alle Notizen mit Relevanz-Score unter ${threshold} endgültig bereinigt werden?`)) {
        return;
      }
      if (resultEl) {
        resultEl.innerHTML = '<span class="text-amber-500 font-mono text-xs animate-pulse">Bereinige verblasste Einträge...</span>';
      }
      try {
        const res = await fetch("/api/v1/memory/evict", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ threshold: threshold, dry_run: false })
        });
        const data = await res.json();
        if (data.status === "success") {
          const totalPruned = (data.conversations_pruned || 0) + (data.learnings_pruned || 0);
          if (resultEl) {
            resultEl.innerHTML = `<span class="text-emerald-500 font-mono text-xs font-bold">✓ ${totalPruned} Einträge bereinigt (${data.conversations_pruned} Chats, ${data.learnings_pruned} Learnings).</span>`;
          }
          if (typeof showNotification === "function") {
            showNotification("🧠 Memory Eviction", `${totalPruned} veraltete Notizen bereinigt.`, "info");
          }
          refreshMemoryStats();
        } else {
          if (resultEl) {
            resultEl.innerHTML = `<span class="text-rose-500 font-mono text-xs font-bold">✕ ${data.message || "Bereinigung fehlgeschlagen"}</span>`;
          }
        }
      } catch (err) {
        if (resultEl) {
          resultEl.innerHTML = `<span class="text-rose-500 font-mono text-xs font-bold">✕ Fehler: ${err.message}</span>`;
        }
      }
    }
    // --- EMAIL GUARD HELPER FUNCTIONS ---
    function onEmailGuardToggleChanged(checked) {
      const lbl = document.getElementById("setting-email-guard-toggle-label");
      if (lbl) lbl.innerText = checked ? "Aktiv" : "Inaktiv";
    }
    async function refreshSecurityStats() {
      try {
        const res = await fetch("/api/v1/security/stats");
        if (!res.ok) return;
        const data = await res.json();
        const totEl = document.getElementById("guard-stat-total");
        if (totEl) totEl.innerText = data.total_scanned ?? "--";
        const safeEl = document.getElementById("guard-stat-safe");
        if (safeEl) safeEl.innerText = data.safe_count ?? "--";
        const suspEl = document.getElementById("guard-stat-suspicious");
        if (suspEl) suspEl.innerText = data.suspicious_count ?? "--";
        const blockEl = document.getElementById("guard-stat-blocked");
        if (blockEl) blockEl.innerText = data.blocked_count ?? "--";
      } catch (e) {
        console.warn("Fehler beim Abrufen der Security-Statistiken:", e);
      }
    }
    async function testEmailGuardInjection() {
      const inputEl = document.getElementById("guard-test-input");
      const resultEl = document.getElementById("guard-test-result");
      const sensEl = document.getElementById("setting-guard-sensitivity");
      const text = inputEl ? inputEl.value.trim() : "";
      if (!text) {
        if (resultEl) resultEl.innerHTML = '<span class="text-amber-500">Bitte Testtext eingeben.</span>';
        return;
      }
      if (resultEl) resultEl.innerHTML = '<span class="text-rose-500 animate-pulse">Scanne Text...</span>';
      try {
        const res = await fetch("/api/v1/security/scan-email", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, sensitivity: sensEl ? sensEl.value : "moderate" })
        });
        const data = await res.json();
        if (data.verdict === "safe") {
          resultEl.innerHTML = '<span class="text-emerald-500 font-bold">✓ SAFE: Keine Injektion erkannt.</span>';
        } else if (data.verdict === "suspicious") {
          const m = (data.pattern_matches || []).join(", ");
          resultEl.innerHTML = `<span class="text-amber-500 font-bold">⚠️ SUSPICIOUS: Verdächtige Muster (${m || 'Heuristik'})</span>`;
        } else {
          const m = (data.pattern_matches || []).join(", ");
          resultEl.innerHTML = `<span class="text-rose-600 font-bold">🛑 BLOCKED: Injektionsangriff erkannt (${m})</span>`;
        }
      } catch (err) {
        if (resultEl) resultEl.innerHTML = `<span class="text-rose-500">Fehler: ${err.message}</span>`;
      }
    }
    // --- QUALITY GATE / VALIDATE HELPER FUNCTIONS ---
    function onValidateToggleChanged(checked) {
      const lbl = document.getElementById("setting-validate-toggle-label");
      if (lbl) lbl.innerText = checked ? "Aktiv" : "Inaktiv";
    }
    async function testOutputValidation() {
      const taskEl = document.getElementById("validate-test-task");
      const resInpEl = document.getElementById("validate-test-result-input");
      const resultEl = document.getElementById("validate-test-result");
      const minEl = document.getElementById("setting-validate-min-score");
      const llmEl = document.getElementById("setting-validate-use-llm");
      const task = taskEl ? taskEl.value.trim() : "Test-Task";
      const resultText = resInpEl ? resInpEl.value.trim() : "";
      if (!resultText) {
        if (resultEl) resultEl.innerHTML = '<span class="text-amber-500">Bitte zu prüfende KI-Antwort eingeben.</span>';
        return;
      }
      if (resultEl) resultEl.innerHTML = '<span class="text-cyan-500 animate-pulse">Bewerte Zuverlässigkeit...</span>';
      try {
        const res = await fetch("/api/v1/security/validate-output", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task,
            result: resultText,
            min_score: minEl ? parseInt(minEl.value, 10) || 7 : 7,
            use_llm: llmEl ? llmEl.checked : false
          })
        });
        const data = await res.json();
        const score = data.score ?? 5;
        const color = score >= 7 ? "text-emerald-500" : score >= 4 ? "text-amber-500" : "text-rose-500";
        const flags = (data.pattern_flags || []).join(", ");
        const flagText = flags ? ` | Flags: ${flags}` : "";
        resultEl.innerHTML = `<span class="${color} font-bold">Score: ${score}/10 [${data.recommendation}]${flagText}</span>`;
      } catch (err) {
        if (resultEl) resultEl.innerHTML = `<span class="text-rose-500">Fehler: ${err.message}</span>`;
      }
    }
    async function resetSystemData() {
      if (confirm("Möchtest du wirklich alle Caches und konfigurierten Agenten zurücksetzen? Dies setzt das System in den Werkszustand zurück.")) {
        try {
          await fetch("/api/ticker/clear", { method: "POST" });
          agents = [];
          await saveAgentsToServer();
          location.reload();
        } catch (e) {
          alert("Fehler beim Zurücksetzen: " + e);
        }
      }
    }
    let selectedRoleCategoryFilter = "all";
    function filterRoleDropdownByCategory(category) {
      selectedRoleCategoryFilter = category;
      populateSettingsRoleDropdown();
      const select = document.getElementById("setting-role-select");
      if (select && select.options.length > 0) {
        loadRoleIntoSettingsEditor(select.options[0].value);
      }
    }
    function populateSettingsRoleDropdown() {
      const select = document.getElementById("setting-role-select");
      if (!select) return;
      select.innerHTML = "";
      let filteredRoles = roles;
      if (selectedRoleCategoryFilter && selectedRoleCategoryFilter !== "all") {
        filteredRoles = roles.filter(r => (r.category || "1. Management & Architektur") === selectedRoleCategoryFilter);
      }
      if (selectedRoleCategoryFilter === "all") {
        const categories = {};
        filteredRoles.forEach(role => {
          const cat = role.category || "1. Management & Architektur";
          if (!categories[cat]) categories[cat] = [];
          categories[cat].push(role);
        });
        for (const [catName, catRoles] of Object.entries(categories)) {
          const group = document.createElement("optgroup");
          group.label = catName;
          catRoles.forEach(role => {
            const opt = document.createElement("option");
            opt.value = role.id;
            opt.innerText = role.name;
            if (role.id === currentEditingRoleSettingsId) {
              opt.selected = true;
            }
            group.appendChild(opt);
          });
          select.appendChild(group);
        }
      } else {
        filteredRoles.forEach(role => {
          const opt = document.createElement("option");
          opt.value = role.id;
          opt.innerText = role.name;
          if (role.id === currentEditingRoleSettingsId) {
            opt.selected = true;
          }
          select.appendChild(opt);
        });
      }
      if (filteredRoles.length > 0 && !filteredRoles.some(r => r.id === currentEditingRoleSettingsId)) {
        currentEditingRoleSettingsId = filteredRoles[0].id;
        select.value = currentEditingRoleSettingsId;
      }
    }
    function loadRoleIntoSettingsEditor(roleId) {
      currentEditingRoleSettingsId = roleId;
      const role = roles.find(r => r.id === roleId);
      if (role) {
        document.getElementById("setting-role-name").value = role.name;
        document.getElementById("setting-role-prompt").value = role.prompt;
        const catSelect = document.getElementById("setting-role-category");
        if (catSelect) catSelect.value = role.category || "1. Management & Architektur";
      }
      const select = document.getElementById("setting-role-select");
      if (select) select.value = roleId;
    }
    function createNewRoleInSettings() {
      const newId = "role_" + Math.floor(Math.random()*100000);
      const cat = selectedRoleCategoryFilter !== "all" ? selectedRoleCategoryFilter : "1. Management & Architektur";
      const newRole = {
        id: newId,
        category: cat,
        name: "Neue Spezial-Rolle",
        prompt: "Beschreibe hier das Mandat und die System-Instruktion der neuen Rolle."
      };
      roles.push(newRole);
      populateSettingsRoleDropdown();
      loadRoleIntoSettingsEditor(newId);
    }
    function deleteSelectedRoleFromSettings() {
      if (!currentEditingRoleSettingsId) return;
      if (roles.length <= 1) {
        alert("Mindestens eine Systemrolle muss bestehen bleiben!");
        return;
      }
      roles = roles.filter(r => r.id !== currentEditingRoleSettingsId);
      currentEditingRoleSettingsId = roles[0].id;
      populateSettingsRoleDropdown();
      loadRoleIntoSettingsEditor(currentEditingRoleSettingsId);
    }
    async function saveRoleSettingsChanges() {
      const name = document.getElementById("setting-role-name").value.trim();
      const prompt = document.getElementById("setting-role-prompt").value.trim();
      const category = document.getElementById("setting-role-category").value;
      if (!name || !prompt) {
        alert("Bitte fülle Rollenname und System Prompt aus!");
        return;
      }
      const role = roles.find(r => r.id === currentEditingRoleSettingsId);
      if (role) {
        role.name = name;
        role.prompt = prompt;
        role.category = category;
      }
      
      try {
        await fetch("/api/roles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(roles)
        });
        alert("Rolle erfolgreich gespeichert!");
        populateSettingsRoleDropdown();
        renderAgentsSidebar();
      } catch (e) {
        alert("Fehler beim Speichern der Rollen: " + e);
      }
    }
    async function loadRolesFromServer() {
      try {
        const res = await fetch("/api/roles");
        if (res.ok) {
          roles = await res.json();
        }
      } catch (e) {
        console.error("Failed to load roles from server:", e);
      }
    }
    let categorizedFrameworksData = {};
    let selectedFrameworkCategoryFilter = "all";
    let currentEditingFrameworkName = "";
    async function loadFrameworksFromServer() {
      try {
        const res = await fetch("/api/boardroom/frameworks");
        if (res.ok) {
          categorizedFrameworksData = await res.json();
        }
      } catch (e) {
        console.error("Failed to load frameworks from server:", e);
      }
    }
    function filterFrameworkDropdownByCategory(category) {
      selectedFrameworkCategoryFilter = category;
      populateSettingsFrameworkDropdown();
      const select = document.getElementById("setting-framework-select");
      if (select && select.options.length > 0) {
        loadFrameworkIntoSettingsEditor(select.options[0].value);
      }
    }
    function populateSettingsFrameworkDropdown() {
      const select = document.getElementById("setting-framework-select");
      if (!select) return;
      select.innerHTML = "";
      let firstFw = "";
      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (selectedFrameworkCategoryFilter !== "all" && selectedFrameworkCategoryFilter !== catName) {
          continue;
        }
        const group = document.createElement("optgroup");
        group.label = catName;
        for (const [fwName, fwVal] of Object.entries(frameworks)) {
          if (!firstFw) firstFw = fwName;
          const opt = document.createElement("option");
          opt.value = fwName;
          opt.innerText = fwName;
          opt.setAttribute("data-category", catName);
          if (fwName === currentEditingFrameworkName) {
            opt.selected = true;
          }
          group.appendChild(opt);
        }
        select.appendChild(group);
      }
      if (!currentEditingFrameworkName && firstFw) {
        currentEditingFrameworkName = firstFw;
        select.value = firstFw;
      }
    }
    function loadFrameworkIntoSettingsEditor(fwName) {
      currentEditingFrameworkName = fwName;
      let foundCat = "1. Bisherige, Agile & Innovation";
      let foundInstruction = "";
      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (fwName in frameworks) {
          foundCat = catName;
          const fwVal = frameworks[fwName];
          foundInstruction = typeof fwVal === "string" ? fwVal : (fwVal.system_instruction || fwVal.summary || "");
          break;
        }
      }
      const nameInput = document.getElementById("setting-framework-name");
      const catSelect = document.getElementById("setting-framework-category");
      const instInput = document.getElementById("setting-framework-instruction");
      if (nameInput) nameInput.value = fwName;
      if (catSelect) catSelect.value = foundCat;
      if (instInput) instInput.value = foundInstruction;
      const select = document.getElementById("setting-framework-select");
      if (select) select.value = fwName;
    }
    function createNewFrameworkInSettings() {
      const newName = "Neues Methodik-Framework " + Math.floor(Math.random() * 1000);
      const targetCat = selectedFrameworkCategoryFilter !== "all" ? selectedFrameworkCategoryFilter : "1. Bisherige, Agile & Innovation";
      if (!categorizedFrameworksData[targetCat]) {
        categorizedFrameworksData[targetCat] = {};
      }
      categorizedFrameworksData[targetCat][newName] = "Beschreibe hier die methodischen Phasen und Anweisungen für die Agenten.";
      currentEditingFrameworkName = newName;
      populateSettingsFrameworkDropdown();
      loadFrameworkIntoSettingsEditor(newName);
    }
    function deleteSelectedFrameworkFromSettings() {
      if (!currentEditingFrameworkName) return;
      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (currentEditingFrameworkName in frameworks) {
          delete frameworks[currentEditingFrameworkName];
          break;
        }
      }
      currentEditingFrameworkName = "";
      populateSettingsFrameworkDropdown();
      const select = document.getElementById("setting-framework-select");
      if (select && select.options.length > 0) {
        loadFrameworkIntoSettingsEditor(select.options[0].value);
      }
    }
    async function saveFrameworkSettingsChanges() {
      const nameInput = document.getElementById("setting-framework-name").value.trim();
      const catSelect = document.getElementById("setting-framework-category").value;
      const instInput = document.getElementById("setting-framework-instruction").value.trim();
      if (!nameInput || !instInput) {
        alert("Bitte fülle den Framework-Namen und die System-Instruktion aus!");
        return;
      }
      if (currentEditingFrameworkName && currentEditingFrameworkName !== nameInput) {
        for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
          if (currentEditingFrameworkName in frameworks) {
            delete frameworks[currentEditingFrameworkName];
          }
        }
      }
      if (!categorizedFrameworksData[catSelect]) {
        categorizedFrameworksData[catSelect] = {};
      }
      categorizedFrameworksData[catSelect][nameInput] = instInput;
      currentEditingFrameworkName = nameInput;
      try {
        await fetch("/api/boardroom/frameworks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(categorizedFrameworksData)
        });
        alert("Methodik-Framework erfolgreich gespeichert!");
        populateSettingsFrameworkDropdown();
        loadBoardroomFrameworks();
      } catch (e) {
        alert("Fehler beim Speichern der Frameworks: " + e);
      }
    }
    async function resetFrameworksToDefault() {
      if (confirm("Möchtest du alle Methodik-Frameworks auf die 23 Basis-Standards zurücksetzen?")) {
        try {
          await fetch("/api/boardroom/frameworks/reset", { method: "POST" });
          await loadFrameworksFromServer();
          currentEditingFrameworkName = "";
          populateSettingsFrameworkDropdown();
          const select = document.getElementById("setting-framework-select");
          if (select && select.options.length > 0) {
            loadFrameworkIntoSettingsEditor(select.options[0].value);
          }
          loadBoardroomFrameworks();
          alert("Erfolgreich auf alle 23 Basis-Frameworks zurückgesetzt.");
        } catch (e) {
          alert("Fehler beim Zurücksetzen: " + e);
        }
      }
    }
    async function loadModelsFromServer() {
      try {
        const res = await fetch("/api/v1/models");
        if (res.ok) {
          modelsList = await res.json();
        }
      } catch (e) {
        console.error("Failed to load models from server:", e);
      }
      if (!modelsList || modelsList.length === 0) {
        modelsList = ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-r1", "hermes-3", "llama-3.3-70b"];
      }
    }
    async function loadKanbanFromServer() {
      try {
        const res = await fetch("/api/kanban");
        if (res.ok) {
          kanbanCards = await res.json();
        }
      } catch (e) {
        console.error("Failed to load kanban cards:", e);
      }
    }
    async function loadVaultFiles() {
      try {
        const res = await fetch("/api/vault/files");
        if (res.ok) {
          vaultFiles = await res.json();
        }
      } catch (e) {
        console.error("Failed to load vault files:", e);
      }
    }
    async function resetRolesToDefault() {
      if (confirm("Möchtest du die KI-Rollen wirklich auf alle 24 Basis-Standardrollen zurücksetzen?")) {
        try {
          const res = await fetch("/api/roles");
          // Re-fetch default roles by resetting roles.json on server or re-sending defaults
          roles = [
            { id: "orchestrator", category: "1. Management & Architektur", name: "Orchestrator & System-Architekt", prompt: "Du bist ein erfahrener Orchestrator & System-Architekt. Deine Aufgabe ist es, meisterhaft komplexe Problemstellungen zu analysieren, Aufgaben strukturiert auf Spezial-Agenten zu verteilen, Abhängigkeiten zu managen und Teilergebnisse zu einer schlüssigen Gesamtlösung zu synthetisieren." },
            { id: "product_manager", category: "1. Management & Architektur", name: "Product Manager / Requirements Engineer", prompt: "Du bist ein strikter Product Manager & Requirements Engineer. Du übersetzt vage Nutzerideen in glasklare, präzise technische User Stories, Akzeptanzkriterien und funktionale Spezifikationen (PRDs). Du verhinderst Scope Creep und forderst Messbarkeit in allen Anforderungen." },
            { id: "scrum_master", category: "1. Management & Architektur", name: "Agile Scrum Master / Task Triage Manager", prompt: "Du bist ein proaktiver Agile Scrum Master & Task Triage Manager. Du strukturierst Workflows in überschaubare Sprint-Tasks, identifizierst Blockaden, priorisierst das Backlog in der Kanban-Pipeline und verteilst Arbeitspakete effizient an ausführende Worker-Agenten." },
            { id: "enterprise_architect", category: "1. Management & Architektur", name: "Enterprise Architect", prompt: "Du bist ein pragmatischer Enterprise Architect. Du bewertest Systemarchitekturen auf langfristige Skalierbarkeit, Modulkopplung, Microservice-Muster und Technologie-Stacks. Du verhinderst technologische Sackgassen und achtest auf Zukunftsfähigkeit." },
            { id: "technical_writer", category: "1. Management & Architektur", name: "Technical Writer & Documentation Specialist", prompt: "Du bist ein präziser Technical Writer & Dokumentations-Spezialist. Du wandelst komplexen Code und Architekturentscheidungen in saubere, übersichtliche Markdown-Dokumentationen, API-Guides, READMEs und strukturierte Obsidian-Vault-Notizen um." },
            { id: "prompt_engineer", category: "1. Management & Architektur", name: "Prompt & AI Systems Engineer", prompt: "Du bist ein Prompt & AI Systems Engineer. Du analysierst und optimierst System-Prompts, Instruction Tuning, Context-Window-Nutzung und Output-Parsing (z.B. JSON/XML-Garantien) für maximale Genauigkeit der ausführenden LLM-Agenten." },
            { id: "senior_coder", category: "2. Software Development & Engineering", name: "Senior Coder / Software Engineer", prompt: "Du bist ein extrem kompetenter Senior Software Engineer. Du schreibst sauberen, modularen, objektorientierten und produktionsreifen Code (Python, TypeScript, Go). Du folgst strikt Best Practices (DRY, SOLID) und lieferst fehlerfreie Implementierungen." },
            { id: "frontend_architect", category: "2. Software Development & Engineering", name: "Frontend & UI/UX Architect", prompt: "Du bist ein visuell denkender Frontend & UI/UX Architect. Du entwirfst moderne, performante und ergonomische Benutzeroberflächen (Streamlit, React, CSS3, Tailwind). Du achtest penibel auf visuelle Hierarchien, responsive Grids und reibungslose User-Flows." },
            { id: "backend_db_designer", category: "2. Software Development & Engineering", name: "Backend & Database Designer", prompt: "Du bist ein hochspezialisierter Backend & Database Designer. Du entwickelst robuste API-Schnittstellen (REST, GraphQL, gRPC), optimierst SQL/NoSQL-Datenbankschemas, indizierst Tabellen und verhinderst Bottlenecks bei Abfragen." },
            { id: "clean_code_expert", category: "2. Software Development & Engineering", name: "Refactoring & Clean Code Expert", prompt: "Du bist ein kompromissloser Refactoring & Clean Code Expert. Du durchleuchtest bestehenden Code auf Code Smells, Redundanzen, hohe zyklomatische Komplexität und schlechte Benennungen, um die Wartbarkeit drastisch zu erhöhen." },
            { id: "devops_container", category: "2. Software Development & Engineering", name: "DevOps & Container Specialist", prompt: "Du bist ein erfahrener DevOps & Container Specialist. Du erstellst gehärtete Dockerfiles, Docker-Compose-Setups, Netzwerkkonfigurationen und CI/CD-Pipelines für eine nahtlose, isolierte und ausfallsichere Container-Laufzeitumgebung." },
            { id: "qa_test_engineer", category: "2. Software Development & Engineering", name: "QA & Automated Testing Engineer", prompt: "Du bist ein penibler QA & Automated Testing Engineer. Du entwirfst umfassende Unit-Tests, Integrationstests und E2E-Testsuites (PyTest, Jest). Du suchst gezielt nach Edge Cases, um Fehler vor dem Deployment abzufangen." },
            { id: "security_auditor", category: "3. Security, Data & Audit", name: "Security Auditor / DevSecOps", prompt: "Du bist ein akribischer Security Auditor & DevSecOps. Du analysierst Code und Systeme auf Sicherheitslücken (OWASP Top 10, Injection Risks, Secret Leaks, Insecure Deserialization) und verlangst harte Schutzmaßnahmen und Sanitization." },
            { id: "gdpr_compliance", category: "3. Security, Data & Audit", name: "Data Protection & Compliance Officer (DSGVO)", prompt: "Du bist ein Data Protection & Compliance Officer. Du stellst sicher, dass Systeme, Logs und Speichermethoden vollumfänglich DSGVO-konform sind, keine personenbezogenen Daten (PII) unverschlüsselt verarbeiten und Datenschutzprinzipien wahren." },
            { id: "performance_auditor", category: "3. Security, Data & Audit", name: "Performance & Benchmarking Auditor", prompt: "Du bist ein analytischer Performance & Benchmarking Auditor. Du misst Ausführungszeiten, Token-Effizienz, Memory Leaks und CPU-Last. Du identifizierst Ineffizienzen und machst konkrete Vorschläge zur Ressourcenminimierung." },
            { id: "fact_checker", category: "3. Security, Data & Audit", name: "Fact-Checker & Logic Validator", prompt: "Du bist ein unbestechlicher Fact-Checker & Logic Validator. Du prüfst Generierungen und Behauptungen anderer Agenten auf Halluzinationen, mathematische Fehler, logische Fehlschlüsse und verifizierst Quellen auf absolute Richtigkeit." },
            { id: "dependency_auditor", category: "3. Security, Data & Audit", name: "Dependency & Supply Chain Auditor", prompt: "Du bist ein wachsamer Dependency & Supply Chain Auditor. Du prüfst externe Bibliotheken (pip, npm), Lizenzen (MIT, GPL, Apache) und Paketabhängigkeiten auf Sicherheitsrisiken, veraltete Versionen und Deprecations." },
            { id: "devils_advocate", category: "3. Security, Data & Audit", name: "Skeptic / Devil's Advocate", prompt: "Du bist der kritische Skeptic & Devil's Advocate im Boardroom. Deine Aufgabe ist es, getroffene Entscheidungen, Pläne und Code-Entwürfe konstruktiv, aber schonungslos zu hinterfragen, um verdeckte Risiken und Denkfehler aufzudecken." },
            { id: "researcher", category: "4. Business, Research & Marketing", name: "Researcher & Data Analyst", prompt: "Du bist ein tiefgründiger Researcher & Data Analyst. Du durchsuchst das Web, Datenbanken und Fachliteratur, filterst Rauschen von Signalen und erstellst fundierte, evidenzbasierte Analysen und Zusammenfassungen." },
            { id: "market_intelligence", category: "4. Business, Research & Marketing", name: "Market & Competitor Intelligence Analyst", prompt: "Du bist ein strategischer Market & Competitor Intelligence Analyst. Du analysierst Marktsegmente, Mitbewerber-Tools, Preismodelle und Feature-Gaps, um Wettbewerbsvorteile und Differenzierungsmerkmale herauszuarbeiten." },
            { id: "seo_content", category: "4. Business, Research & Marketing", name: "SEO & Content Pipeline Specialist", prompt: "Du bist ein datengetriebener SEO & Content Pipeline Specialist. Du recherchierst High-Intent-Keywords, erstellst strukturierte Content-Pipelines und entwirfst suchmaschinenoptimierte Artikel und Veröffentlichungsstrategien." },
            { id: "outreach_automator", category: "4. Business, Research & Marketing", name: "Outreach & Lead Gen Automator", prompt: "Du bist ein fokussierter Outreach & Lead Gen Automator. Du konzipierst automatisierte B2B-Ansprachen, LinkedIn-Sequenzen und E-Mail-Kampagnen, inklusive Lead-Validierung und Triage für den Vertrieb." },
            { id: "financial_optimizer", category: "4. Business, Research & Marketing", name: "Financial & Cost Optimizer", prompt: "Du bist ein kostenbewusster Financial & Cost Optimizer. Du überwachst Token-Verbräuche, verglichst API-Kosten vs. Open-Source-Modelle und optimierst die Betriebskosten der gesamten Agenten-Infrastruktur." },
            { id: "growth_strategist", category: "4. Business, Research & Marketing", name: "Growth & UX Conversion Strategist", prompt: "Du bist ein ergebnisorientierter Growth & UX Conversion Strategist. Du analysierst Funnels, Onboarding-Abläufe und A/B-Test-Szenarien, um Reibungspunkte abzubauen und die Nutzeraktivierung zu maximieren." }
          ];
          await fetch("/api/roles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(roles)
          });
          alert("Erfolgreich auf alle 24 Basis-Standardrollen zurückgesetzt.");
          populateSettingsRoleDropdown();
          if (roles.length > 0) loadRoleIntoSettingsEditor(roles[0].id);
        } catch (e) {
          alert("Fehler beim Zurücksetzen der Rollen: " + e);
        }
      }
    }
    let boardroomRecognition = null;
    let isBoardroomDictating = false;
    function toggleBoardroomDictation() {
      const btn = document.getElementById("boardroom-mic-btn");
      const textarea = document.getElementById("boardroom-task");
      if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        alert("Spracherkennung wird von diesem Browser leider nicht unterstützt. Bitte nutze Google Chrome oder Edge.");
        return;
      }
      if (isBoardroomDictating) {
        if (boardroomRecognition) boardroomRecognition.stop();
        isBoardroomDictating = false;
        if (btn) {
          btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
          btn.title = "Aufgabe diktieren (Mikrofon)";
        }
        return;
      }
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      boardroomRecognition = new SpeechRecognition();
      boardroomRecognition.continuous = true;
      boardroomRecognition.interimResults = true;
      boardroomRecognition.lang = "de-DE";
      let baseText = textarea.value ? textarea.value.trim() + " " : "";
      boardroomRecognition.onresult = (event) => {
        let interimTranscript = "";
        let finalTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        textarea.value = baseText + finalTranscript + interimTranscript;
      };
      boardroomRecognition.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
      };
      boardroomRecognition.onend = () => {
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
      };
      boardroomRecognition.start();
      isBoardroomDictating = true;
      if (btn) {
        btn.classList.add("text-red-500", "animate-pulse", "border-red-500");
        btn.title = "Diktieren läuft... Klicken zum Stoppen";
      }
    }
