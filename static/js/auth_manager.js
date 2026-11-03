/**
 * static/js/auth_manager.js
 * Meilenstein 4: Multi-User-Architektur & Rollenbasierte Zugriffskontrolle (RBAC).
 * Client-seitiges Identitäts-, Session- und Rollenmanagement.
 * Unterstützt Zero-Disruption Einzelplatz-Modus und Multi-User-Modus.
 */

class AuthManager {
  constructor() {
    this.currentUser = null;
    this.authEnabled = false;
    this.users = [];
  }

  async init() {
    try {
      await this.loadCurrentUser();
      this.renderTopbarBadge();
    } catch (e) {
      console.warn('[Auth] Error initializing auth manager:', e);
    }
  }

  async loadCurrentUser() {
    try {
      const res = await fetch('/api/auth/me');
      const data = await res.json();
      if (data.status === 'success' && data.user) {
        this.currentUser = data.user;
        this.authEnabled = typeof data.auth_enabled !== 'undefined' ? !!data.auth_enabled : !!data.user.auth_enabled;
        window.currentUser = data.user;
        this.applyRoleRestrictions(data.user);
        this.renderTopbarBadge();
        return data.user;
      }
    } catch (err) {
      console.warn('[Auth] Could not load current user:', err);
    }
    return null;
  }

  renderTopbarBadge() {
    const badge = document.getElementById('topbar-user-badge');
    if (!badge || !this.currentUser) return;

    const roleColors = {
      admin: 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20',
      operator: 'bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/20',
      viewer: 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20'
    };

    const roleBadgeClass = roleColors[this.currentUser.role] || roleColors.operator;
    const initial = (this.currentUser.display_name || this.currentUser.username || 'U')[0].toUpperCase();
    const roleLabel = !this.authEnabled ? 'Admin · Einzelplatz' : this.currentUser.role;
    const title = !this.authEnabled ? 'Einzelplatz-Modus: Volle Admin-Rechte ohne Login-Zwang' : `Angemeldet als ${this.currentUser.role}`;

    badge.innerHTML = `
      <div onclick="window.authManager.openProfileModal()" title="${title}" class="flex items-center gap-1.5 px-2 py-[2px] rounded-lg bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 border border-[var(--border)] transition cursor-pointer select-none shadow-2xs">
        <div class="w-4 h-4 rounded-full bg-zinc-800 text-white flex items-center justify-center font-mono font-bold text-[9px] shrink-0">
          ${initial}
        </div>
        <span class="text-[11px] font-bold font-sans text-[var(--foreground)] truncate flex-1 leading-tight">
          ${this.currentUser.display_name || this.currentUser.username}
        </span>
        <span class="text-[9px] font-mono px-1 py-0.2 rounded border ${roleBadgeClass} uppercase font-bold tracking-wider shrink-0 leading-tight">
          ${roleLabel}
        </span>
      </div>
    `;
  }

  applyRoleRestrictions(user) {
    if (!user) return;
    const isViewer = user.role === 'viewer';
    const isOperator = user.role === 'operator';

    // Wenn Viewer: Buttons mit data-rbac-write verbergen oder deaktivieren
    document.querySelectorAll('[data-rbac-write]').forEach(el => {
      if (isViewer) {
        el.style.display = 'none';
      } else {
        el.style.display = '';
      }
    });

    // Wenn nicht Admin: Buttons mit data-rbac-admin verbergen
    document.querySelectorAll('[data-rbac-admin]').forEach(el => {
      if (user.role !== 'admin') {
        el.style.display = 'none';
      } else {
        el.style.display = '';
      }
    });
  }

  syncAuthModeUI() {
    const toggle = document.getElementById('auth-mode-toggle');
    const badge = document.getElementById('auth-mode-badge');
    const toggleText = document.getElementById('auth-mode-toggle-text');
    if (toggle) {
      toggle.checked = this.authEnabled;
    }
    if (badge) {
      if (this.authEnabled) {
        badge.className = 'px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30';
        badge.textContent = 'Multi-User aktiv (Login erforderlich)';
      } else {
        badge.className = 'px-2 py-0.5 rounded text-[10.5px] font-mono font-bold bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30';
        badge.textContent = 'Einzelplatz (Keine Anmeldung nötig)';
      }
    }
    if (toggleText) {
      toggleText.textContent = this.authEnabled ? 'Multi-User aktiv' : 'Multi-User aktivieren';
    }
  }

  async handleToggleAuth(enabled) {
    try {
      const res = await fetch('/api/auth/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !!enabled })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Fehler beim Ändern des Authentifizierungsmodus.');
        this.syncAuthModeUI();
        return;
      }
      this.authEnabled = !!data.auth_enabled;
      if (this.currentUser) {
        this.currentUser.auth_enabled = this.authEnabled;
      }
      this.syncAuthModeUI();
      this.renderTopbarBadge();
    } catch (e) {
      alert('Netzwerkfehler beim Umschalten des Modus.');
      this.syncAuthModeUI();
    }
  }

  openProfileModal() {
    let modal = document.getElementById('auth-profile-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'auth-profile-modal';
      modal.className = 'fixed inset-0 z-[99999] flex items-center justify-center bg-black/60 backdrop-blur-xs p-4';
      document.body.appendChild(modal);
    }

    const u = this.currentUser || { username: 'Unbekannt', role: 'viewer', display_name: 'Gast' };
    modal.innerHTML = `
      <div class="w-full max-w-sm bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-2xl p-5 text-sans text-[var(--foreground)] space-y-4 animate-in zoom-in-95 duration-150">
        <div class="flex items-center justify-between border-b border-[var(--border)] pb-3">
          <div class="flex items-center gap-2.5">
            <div class="w-10 h-10 rounded-full bg-zinc-800 text-white font-bold flex items-center justify-center text-sm font-mono shadow-xs">
              ${(u.display_name || u.username)[0].toUpperCase()}
            </div>
            <div>
              <h4 class="text-sm font-black">${u.display_name}</h4>
              <p class="text-xs text-[var(--muted-foreground)] font-mono">@${u.username} · ${u.email || 'Lokal'}</p>
            </div>
          </div>
          <button onclick="document.getElementById('auth-profile-modal').classList.add('hidden')" class="w-7 h-7 rounded-lg hover:bg-[var(--secondary)] flex items-center justify-center text-[var(--muted-foreground)] cursor-pointer">✕</button>
        </div>

        <div class="bg-[var(--secondary)]/40 p-3 rounded-xl border border-[var(--border)] text-xs font-mono space-y-1.5">
          <div class="flex justify-between">
            <span class="text-[var(--muted-foreground)]">Betriebsmodus:</span>
            <span class="font-bold ${this.authEnabled ? 'text-emerald-500' : 'text-amber-500'}">
              ${this.authEnabled ? 'Multi-User (Login aktiv)' : 'Einzelplatz (Offen)'}
            </span>
          </div>
          <div class="flex justify-between">
            <span class="text-[var(--muted-foreground)]">Rolle:</span>
            <span class="font-bold uppercase text-sky-500">${u.role}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-[var(--muted-foreground)]">System-Rechte:</span>
            <span>${u.role === 'admin' ? 'Vollzugriff (Admin)' : (u.role === 'operator' ? 'Operativ (Tasks & CRM)' : 'Nur-Lesen (Viewer)')}</span>
          </div>
        </div>

        <div class="pt-2 flex items-center gap-2">
          ${u.role === 'admin' ? `
            <button onclick="document.getElementById('auth-profile-modal').classList.add('hidden'); openSystemSettingsModal(); setTimeout(() => setSettingsTab('users'), 200);" class="flex-1 py-2 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-xs font-mono font-bold transition cursor-pointer">
              Benutzer & RBAC
            </button>
          ` : ''}
          <button onclick="window.authManager.openLoginDialog()" class="flex-1 py-2 rounded-xl bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 text-[var(--foreground)] text-xs font-mono font-bold border border-[var(--border)] transition cursor-pointer">
            Konto wechseln
          </button>
        </div>
      </div>
    `;
    modal.classList.remove('hidden');
  }

  openLoginDialog() {
    const modal = document.getElementById('auth-profile-modal');
    if (!modal) return;
    modal.innerHTML = `
      <div class="w-full max-w-sm bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-2xl p-5 text-sans text-[var(--foreground)] space-y-4">
        <div class="flex items-center justify-between border-b border-[var(--border)] pb-3">
          <h4 class="text-sm font-black">Benutzeranmeldung</h4>
          <button onclick="document.getElementById('auth-profile-modal').classList.add('hidden')" class="w-7 h-7 rounded-lg hover:bg-[var(--secondary)] flex items-center justify-center text-[var(--muted-foreground)] cursor-pointer">✕</button>
        </div>
        <form onsubmit="event.preventDefault(); window.authManager.handleLoginSubmit();" class="space-y-3">
          <div>
            <label class="block text-[10px] font-mono uppercase text-[var(--muted-foreground)] mb-1">Benutzername</label>
            <input type="text" id="auth-login-username" required class="w-full bg-[var(--background)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono text-[var(--foreground)] focus:outline-none focus:border-sky-500">
          </div>
          <div>
            <label class="block text-[10px] font-mono uppercase text-[var(--muted-foreground)] mb-1">Passwort</label>
            <input type="password" id="auth-login-password" required class="w-full bg-[var(--background)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono text-[var(--foreground)] focus:outline-none focus:border-sky-500">
          </div>
          <div id="auth-login-error" class="hidden text-xs text-rose-500 font-mono"></div>
          <button type="submit" class="w-full py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs transition cursor-pointer">
            Anmelden
          </button>
        </form>
      </div>
    `;
    modal.classList.remove('hidden');
  }

  async handleLoginSubmit() {
    const u = document.getElementById('auth-login-username').value.trim();
    const p = document.getElementById('auth-login-password').value;
    const errEl = document.getElementById('auth-login-error');

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p })
      });
      const data = await res.json();
      if (!res.ok) {
        errEl.textContent = data.detail || 'Anmeldung fehlgeschlagen.';
        errEl.classList.remove('hidden');
        return;
      }
      document.getElementById('auth-profile-modal').classList.add('hidden');
      await this.loadCurrentUser();
    } catch (e) {
      errEl.textContent = 'Netzwerkfehler beim Anmelden.';
      errEl.classList.remove('hidden');
    }
  }

  async renderSettingsUsersTable(containerId = 'settings-users-table-body') {
    this.syncAuthModeUI();
    const tbody = document.getElementById(containerId);
    if (!tbody) return;

    try {
      const res = await fetch('/api/auth/users');
      const data = await res.json();
      if (data.status === 'success') {
        this.users = data.users;
        if (this.users.length === 0) {
          tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-xs text-[var(--muted-foreground)] font-mono">Keine Benutzer gefunden.</td></tr>';
          return;
        }

        tbody.innerHTML = this.users.map(u => `
          <tr class="hover:bg-[var(--secondary)]/40 border-b border-[var(--border)] transition text-xs">
            <td class="p-3 font-bold flex items-center gap-2">
              <span class="w-6 h-6 rounded-full bg-zinc-800 text-white flex items-center justify-center font-mono font-bold text-[10px]">
                ${(u.display_name || u.username)[0].toUpperCase()}
              </span>
              <div>
                <div class="text-[var(--foreground)] font-medium">${u.display_name}</div>
                <div class="text-[10px] font-mono text-[var(--muted-foreground)]">@${u.username}</div>
              </div>
            </td>
            <td class="p-3 font-mono text-[11px] text-[var(--muted-foreground)]">${u.email || '-'}</td>
            <td class="p-3">
              <select onchange="window.authManager.handleRoleChange('${u.id}', this.value)" class="bg-[var(--background)] border border-[var(--border)] rounded px-2 py-1 text-xs font-mono font-bold ${u.role === 'admin' ? 'text-rose-500' : (u.role === 'operator' ? 'text-sky-500' : 'text-zinc-400')}">
                <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                <option value="operator" ${u.role === 'operator' ? 'selected' : ''}>Operator</option>
                <option value="viewer" ${u.role === 'viewer' ? 'selected' : ''}>Viewer</option>
              </select>
            </td>
            <td class="p-3">
              <span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${u.is_active ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20' : 'bg-zinc-500/10 text-zinc-400 border border-zinc-500/20'}">
                ${u.is_active ? 'Aktiv' : 'Deaktiviert'}
              </span>
            </td>
            <td class="p-3 text-right">
              ${u.role !== 'admin' ? `
                <button onclick="window.authManager.handleDeleteUser('${u.id}', '${u.username}')" class="p-1 text-zinc-400 hover:text-rose-500 transition cursor-pointer" title="Benutzer löschen">
                  🗑️
                </button>
              ` : '<span class="text-[10px] text-zinc-400 font-mono">Haupt-Admin</span>'}
            </td>
          </tr>
        `).join('');
      }
    } catch (e) {
      console.warn('[Auth] Error rendering users table:', e);
    }
  }

  async handleRoleChange(userId, newRole) {
    try {
      const res = await fetch(`/api/auth/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Fehler beim Ändern der Rolle.');
        this.renderSettingsUsersTable();
      } else {
        await this.loadCurrentUser();
      }
    } catch (e) {
      alert('Netzwerkfehler.');
    }
  }

  async handleDeleteUser(userId, username) {
    if (!confirm(`Soll der Benutzer '${username}' wirklich gelöscht werden?`)) return;
    try {
      const res = await fetch(`/api/auth/users/${userId}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Konnte Benutzer nicht löschen.');
      } else {
        this.renderSettingsUsersTable();
      }
    } catch (e) {
      alert('Netzwerkfehler.');
    }
  }

  async handleCreateUserSubmit(event) {
    event.preventDefault();
    const u = document.getElementById('new-user-username').value.trim();
    const d = document.getElementById('new-user-displayname').value.trim();
    const e = document.getElementById('new-user-email').value.trim();
    const p = document.getElementById('new-user-password').value;
    const r = document.getElementById('new-user-role').value;

    try {
      const res = await fetch('/api/auth/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, display_name: d, email: e, password: p, role: r })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Fehler beim Anlegen des Benutzers.');
        return;
      }
      document.getElementById('new-user-modal').classList.add('hidden');
      this.renderSettingsUsersTable();
    } catch (err) {
      alert('Netzwerkfehler beim Anlegen des Benutzers.');
    }
  }
}

window.authManager = new AuthManager();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.authManager.init());
} else {
  window.authManager.init();
}
