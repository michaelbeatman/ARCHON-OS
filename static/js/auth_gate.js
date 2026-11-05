/**
 * static/js/auth_gate.js
 * Blockierendes Login-Gate für den Multi-User-Modus.
 *
 * Aktiv nur, wenn settings.auth.enabled = true. Im Einzelplatz-Modus
 * (auth disabled) ist dieses Skript wirkungslos: keine Overlay, kein Eingriff
 * in fetch-Aufrufe.
 */
(function () {
  const OVERLAY_ID = 'archon-auth-gate';

  async function status() {
    try {
      const r = await fetch('/api/auth/status');
      return await r.json();
    } catch (e) {
      return { auth_enabled: false };
    }
  }

  function buildOverlay() {
    const el = document.createElement('div');
    el.id = OVERLAY_ID;
    el.style.cssText = 'position:fixed;inset:0;z-index:99999;display:none;align-items:center;justify-content:center;background:rgba(2,6,23,.94);backdrop-filter:blur(6px);font-family:Outfit,sans-serif';
    el.innerHTML = `
      <form id="archon-auth-form" style="width:340px;max-width:92vw;background:#0f172a;border:1px solid #1e293b;border-radius:16px;padding:22px;display:flex;flex-direction:column;gap:12px;box-shadow:0 20px 60px rgba(0,0,0,.5)">
        <div style="font-size:13px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#e2e8f0">Archon OS</div>
        <div style="font-size:12px;color:#94a3b8;margin-bottom:4px">Bitte anmelden — Multi-User-Modus ist aktiv.</div>
        <input id="archon-auth-user" placeholder="Benutzername" autocomplete="username" required
          style="background:#020617;border:1px solid #1e293b;border-radius:10px;padding:10px 12px;color:#e2e8f0;font-family:JetBrains Mono,monospace;font-size:12px;outline:none">
        <input id="archon-auth-pass" type="password" placeholder="Passwort" autocomplete="current-password" required
          style="background:#020617;border:1px solid #1e293b;border-radius:10px;padding:10px 12px;color:#e2e8f0;font-family:JetBrains Mono,monospace;font-size:12px;outline:none">
        <div id="archon-auth-error" style="display:none;color:#f87171;font-size:11px;font-family:JetBrains Mono,monospace"></div>
        <button type="submit" style="background:#0284c7;color:#fff;border:0;border-radius:10px;padding:10px;font-weight:800;font-size:12px;cursor:pointer">Anmelden</button>
      </form>`;
    document.body.appendChild(el);
    el.querySelector('#archon-auth-form').addEventListener('submit', onSubmit);
    return el;
  }

  function show(message) {
    let el = document.getElementById(OVERLAY_ID) || buildOverlay();
    el.style.display = 'flex';
    if (message) {
      const err = el.querySelector('#archon-auth-error');
      err.textContent = message;
      err.style.display = 'block';
    }
  }

  function hide() {
    const el = document.getElementById(OVERLAY_ID);
    if (el) el.style.display = 'none';
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    const user = document.getElementById('archon-auth-user').value.trim();
    const pass = document.getElementById('archon-auth-pass').value;
    const err = document.getElementById('archon-auth-error');
    err.style.display = 'none';
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: user, password: pass })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        err.textContent = data.detail || 'Anmeldung fehlgeschlagen.';
        err.style.display = 'block';
        return;
      }
      window.location.reload();
    } catch (e) {
      err.textContent = 'Netzwerkfehler beim Anmelden.';
      err.style.display = 'block';
    }
  }

  async function check() {
    const s = await status();
    if (!s.auth_enabled) return;
    try {
      const r = await fetch('/api/auth/me');
      const d = await r.json();
      if (d && d.user && d.user.role && d.user.role !== 'anonymous') return;
    } catch (e) { /* Gate zeigen */ }
    show();
  }

  // 401 aus normalen API-Aufrufen -> Gate einblenden
  const originalFetch = window.fetch.bind(window);
  window.fetch = async function (...args) {
    const res = await originalFetch(...args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
      if (res.status === 401 && url.indexOf('/api/') !== -1 && url.indexOf('/api/auth/') === -1) {
        show('Sitzung abgelaufen — bitte erneut anmelden.');
      }
    } catch (e) { /* ignorieren */ }
    return res;
  };

  window.archonAuthGate = { check: check, show: show, hide: hide };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', check);
  } else {
    check();
  }
})();
