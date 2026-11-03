/**
 * static/js/system_update_badge.js
 * Status-Pill (LED) in der Sidebar und System-Update-Dialog mit Versionsauskunft,
 * Liste verfügbarer Updates und Administrator-Update-Trigger.
 */

(function () {
  'use strict';

  let lastUpdateData = null;
  let isChecking = false;

  /**
   * Prüft den Update-Status im Hintergrund und aktualisiert die Status-LED.
   */
  async function checkUpdateStatus(silent = false) {
    if (isChecking) return lastUpdateData;
    isChecking = true;

    const dot = document.getElementById('dot-update');
    const badgeBtn = document.getElementById('status-badge-update');

    if (!silent && dot) {
      dot.className = 'w-1.5 h-1.5 rounded-full bg-sky-500 animate-pulse shrink-0 transition-colors';
    }

    try {
      const res = await fetch('/api/v1/system/update/check');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      lastUpdateData = data;

      if (dot) {
        if (data.update_available) {
          dot.className = 'w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse shrink-0 transition-colors';
          if (badgeBtn) {
            badgeBtn.title = `Update verfügbar: ${data.commits_behind} neue(s) Commit(s) auf origin/main`;
          }
          const label = document.getElementById('label-update-text');
          if (label) {
            label.innerText = `Update (${data.commits_behind})`;
            label.className = 'text-amber-500 font-bold';
          }
        } else {
          dot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0 transition-colors';
          if (badgeBtn) {
            badgeBtn.title = `Archon OS ist auf dem neuesten Stand (${data.version || ''})`;
          }
          const label = document.getElementById('label-update-text');
          if (label) {
            label.innerText = 'Update';
            label.className = '';
          }
        }
      }
      return data;
    } catch (err) {
      if (dot) {
        dot.className = 'w-1.5 h-1.5 rounded-full bg-zinc-400 shrink-0 transition-colors';
        if (badgeBtn) {
          badgeBtn.title = 'Update-Status: Offline oder Fehler beim Prüfen';
        }
      }
      return null;
    } finally {
      isChecking = false;
    }
  }

  /**
   * Öffnet den dedizierten Update-Dialog und aktualisiert die Daten.
   */
  async function openSystemUpdateDialog() {
    let modal = document.getElementById('system-update-dialog-modal');
    if (modal) {
      modal.classList.remove('hidden');
    }
    await renderUpdateDialogContent();
  }

  function closeSystemUpdateDialog() {
    const modal = document.getElementById('system-update-dialog-modal');
    if (modal) {
      modal.classList.add('hidden');
    }
  }

  /**
   * Lädt und rendert den Inhalt des Update-Dialogs.
   */
  async function renderUpdateDialogContent() {
    const verEl = document.getElementById('upd-modal-version');
    const badgeEl = document.getElementById('upd-modal-status-badge');
    const branchEl = document.getElementById('upd-modal-branch');
    const commitEl = document.getElementById('upd-modal-commit');
    const lastCommitEl = document.getElementById('upd-modal-last-commit');
    const updatesSec = document.getElementById('upd-modal-updates-section');
    const actionsArea = document.getElementById('upd-modal-actions-area');

    if (badgeEl) {
      badgeEl.innerText = 'Prüfe GitHub...';
      badgeEl.className = 'px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-neutral-500/15 text-[var(--muted-foreground)] border border-[var(--border)]';
    }

    const data = await checkUpdateStatus(false);

    if (!data) {
      if (badgeEl) {
        badgeEl.innerText = 'Offline / Fehler';
        badgeEl.className = 'px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/10 text-rose-500 border border-rose-500/20';
      }
      if (updatesSec) {
        updatesSec.innerHTML = `
          <div class="p-3 rounded-xl border border-rose-500/20 bg-rose-500/5 text-xs text-rose-500 font-mono">
            Konnte keine Verbindung zu GitHub herstellen. Bitte Internetverbindung prüfen.
          </div>
        `;
      }
      return;
    }

    // Version und Commit setzen
    if (verEl) {
      verEl.innerText = `${data.version || 'v0.3.8'}${data.version_codename ? ' · ' + data.version_codename : ''}`;
    }
    if (branchEl) {
      branchEl.innerText = data.branch || 'main';
    }
    if (commitEl) {
      commitEl.innerText = `${data.current_commit || '-'} (Remote: ${data.remote_commit || '-'})`;
    }
    if (lastCommitEl) {
      lastCommitEl.innerText = `Lokaler Stand: ${data.last_commit_info || 'Keine Details'}`;
    }

    // Status Badge & Updates Liste
    if (data.update_available) {
      if (badgeEl) {
        badgeEl.innerText = `${data.commits_behind} Update(s) bereit`;
        badgeEl.className = 'px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30';
      }

      const commitsListHtml = (data.incoming_commits || []).map(c => `
        <div class="flex items-start gap-1.5 text-xs font-mono py-1 border-b border-[var(--border)]/50 last:border-0">
          <span class="text-sky-500 font-bold shrink-0">›</span>
          <span class="text-[var(--foreground)] truncate">${escapeHtml(c)}</span>
        </div>
      `).join('');

      if (updatesSec) {
        updatesSec.innerHTML = `
          <div class="border border-amber-500/30 bg-amber-500/10 rounded-xl p-3 space-y-1.5">
            <div class="flex items-center justify-between text-xs font-bold text-amber-600 dark:text-amber-400">
              <span class="flex items-center gap-1.5">
                <i data-lucide="arrow-down-circle" class="w-4 h-4"></i>
                ${data.commits_behind} neue(s) Update(s) auf origin/main
              </span>
              <span class="text-[10px] font-mono font-normal">Zielversion: ${data.next_version || 'nächste'}</span>
            </div>
            <div class="bg-[var(--card)]/90 rounded-lg p-2 border border-[var(--border)] max-h-40 overflow-y-auto space-y-0.5 custom-scrollbar">
              ${commitsListHtml || '<div class="text-xs text-[var(--muted-foreground)]">Keine Commit-Details empfangen.</div>'}
            </div>
          </div>
        `;
      }
    } else {
      if (badgeEl) {
        badgeEl.innerText = 'System ist aktuell';
        badgeEl.className = 'px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30';
      }

      if (updatesSec) {
        updatesSec.innerHTML = `
          <div class="border border-emerald-500/20 bg-emerald-500/5 rounded-xl p-3 flex items-center gap-2.5 text-xs">
            <div class="w-7 h-7 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
              <i data-lucide="check-circle" class="w-4 h-4"></i>
            </div>
            <div>
              <div class="font-bold text-[var(--foreground)]">Archon OS ist auf dem neuesten Stand</div>
              <div class="text-[11px] text-[var(--muted-foreground)]">Alle Commits sind synchronisiert. Keine ausstehenden Updates.</div>
            </div>
          </div>
        `;
      }
    }

    // RBAC Rollenprüfung für den Update-Button
    const isAdmin = !window.currentUser || window.currentUser.role === 'admin' || window.currentUser.role === undefined;

    if (actionsArea) {
      if (isAdmin) {
        actionsArea.innerHTML = `
          <label class="flex items-center gap-2 text-xs font-mono cursor-pointer select-none">
            <input type="checkbox" id="upd-modal-make-backup" checked class="rounded border-zinc-400 text-emerald-600 focus:ring-emerald-500">
            <span class="text-[var(--muted-foreground)]">Automatischer Pre-Update Snapshot (DBs & Configs)</span>
          </label>
          <button 
            type="button" 
            id="btn-upd-dialog-apply" 
            onclick="window.executeSystemUpdateFromDialog()" 
            class="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-mono font-bold text-xs transition cursor-pointer flex items-center justify-center gap-2 shadow-xs"
          >
            <i data-lucide="cloud-download" class="w-4 h-4"></i>
            <span>${data.update_available ? 'Update jetzt einleiten & anwenden' : 'System-Sync erzwingen (Git Pull)'}</span>
          </button>
          <div id="upd-dialog-progress-msg" class="hidden text-center text-xs font-mono text-sky-500 animate-pulse"></div>
        `;
      } else {
        actionsArea.innerHTML = `
          <div class="p-2.5 rounded-xl bg-[var(--secondary)]/60 border border-[var(--border)] text-xs font-mono text-[var(--muted-foreground)] flex items-center gap-2">
            <i data-lucide="shield-alert" class="w-4 h-4 text-amber-500 shrink-0"></i>
            <span>Nur Administratoren dürfen System-Updates einleiten. Du bist als <strong>${window.currentUser?.role}</strong> angemeldet.</span>
          </div>
        `;
      }
    }

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  /**
   * Führt das System-Update aus (nur für Admins).
   */
  async function executeSystemUpdateFromDialog() {
    const backupCheckbox = document.getElementById('upd-modal-make-backup');
    const makeBackup = backupCheckbox ? backupCheckbox.checked : true;
    const btn = document.getElementById('btn-upd-dialog-apply');
    const progMsg = document.getElementById('upd-dialog-progress-msg');

    const confirmText = makeBackup
      ? 'System-Update jetzt ausführen?\n\nEs wird vorab ein automatischer Sicherheits-Snapshot aller Datenbanken und Einstellungen erstellt.'
      : 'System-Update jetzt ohne Backup ausführen?\n\nGit Pull origin/main wird gestartet.';

    if (!confirm(confirmText)) return;

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> <span>Update läuft... Bitte warten</span>';
    }
    if (progMsg) {
      progMsg.classList.remove('hidden');
      progMsg.innerText = 'Erstelle Snapshot & führe Git Pull aus...';
    }

    try {
      const res = await fetch('/api/v1/system/update/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup: makeBackup })
      });
      const data = await res.json();

      if (data.status === 'success') {
        if (progMsg) {
          progMsg.className = 'text-center text-xs font-mono text-emerald-500 font-bold';
          progMsg.innerText = `✅ Update erfolgreich! Neuer Commit: ${data.new_commit}. Starte neu...`;
        }
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      } else {
        alert(`Update fehlgeschlagen: ${data.message || 'Unbekannter Fehler'}`);
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i data-lucide="cloud-download" class="w-4 h-4"></i> <span>Erneut versuchen</span>';
        }
        if (progMsg) progMsg.classList.add('hidden');
      }
    } catch (err) {
      alert(`Netzwerkfehler beim Anwenden des Updates: ${err.message}`);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="cloud-download" class="w-4 h-4"></i> <span>Erneut versuchen</span>';
      }
      if (progMsg) progMsg.classList.add('hidden');
    }
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Exportiere Funktionen nach window
  window.openSystemUpdateDialog = openSystemUpdateDialog;
  window.closeSystemUpdateDialog = closeSystemUpdateDialog;
  window.checkSystemUpdateDialogStatus = renderUpdateDialogContent;
  window.executeSystemUpdateFromDialog = executeSystemUpdateFromDialog;
  window.checkUpdateStatus = checkUpdateStatus;

  // Initialer Check nach Start (verzögert um 2 Sekunden)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(() => checkUpdateStatus(true), 2000);
    });
  } else {
    setTimeout(() => checkUpdateStatus(true), 2000);
  }

  // Regelmäßige Hintergrundprüfung alle 5 Minuten
  setInterval(() => checkUpdateStatus(true), 5 * 60 * 1000);

})();
