// M101: Passkey / WebAuthn (FIDO2) HITL-Verifizierung pro Benutzer
(function () {
  function b64uToBuf(b64u) {
    const pad = '='.repeat((4 - (b64u.length % 4)) % 4);
    const b64 = (b64u + pad).replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out.buffer;
  }

  function bufToB64u(buf) {
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  async function populatePasskeyUsersDropdown() {
    const sel = document.getElementById('passkey-user-select');
    if (!sel) return;
    const prev = sel.value || 'admin';
    try {
      const res = await fetch('/api/auth/users');
      if (res.ok) {
        const data = await res.json();
        const users = Array.isArray(data.users) ? data.users : (Array.isArray(data) ? data : []);
        if (users.length > 0) {
          sel.innerHTML = users.map(u => {
            const uid = u.id || u.username || 'admin';
            const label = u.username ? `${u.username} (${u.role || 'user'})` : uid;
            return `<option value="${esc(uid)}">${esc(label)}</option>`;
          }).join('');
          if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
        }
      }
    } catch (e) {}
  }

  function renderPasskeyCredentials(creds) {
    const listEl = document.getElementById('passkey-credentials-list');
    if (!listEl) return;
    if (!Array.isArray(creds) || creds.length === 0) {
      listEl.innerHTML = '<span class="text-[var(--muted-foreground)]">Noch kein Passkey registriert.</span>';
      return;
    }
    listEl.innerHTML = creds.map(c => `
      <div class="flex items-center justify-between gap-2 px-2 py-1 rounded border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]">
        <span class="truncate font-semibold">${esc(c.label || 'Passkey')} <span class="text-[10px] text-[var(--muted-foreground)]">(${esc((c.id || '').slice(0, 12))}…)</span></span>
        <button type="button" onclick="window.deleteUserPasskey('${esc(c.id)}')" class="text-rose-600 hover:underline text-[10px] cursor-pointer shrink-0">Entfernen</button>
      </div>
    `).join('');
  }

  function syncScopeVisibility(scope) {
    const box = document.getElementById('passkey-categories-box');
    if (!box) return;
    const isSel = scope === 'selected';
    box.style.opacity = isSel ? '1' : '0.45';
    box.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.disabled = !isSel; });
  }

  async function loadPasskeyHitlSettings(userId) {
    await populatePasskeyUsersDropdown();
    const sel = document.getElementById('passkey-user-select');
    const uid = userId || (sel && sel.value) || 'admin';
    try {
      const res = await fetch(`/api/auth/passkey/config?user_id=${encodeURIComponent(uid)}`);
      if (!res.ok) return;
      const cfg = await res.json();
      const enEl = document.getElementById('passkey-hitl-enabled');
      if (enEl) enEl.checked = !!cfg.enabled;
      const scEl = document.getElementById('passkey-hitl-scope');
      if (scEl) scEl.value = cfg.scope || 'all';
      syncScopeVisibility(cfg.scope || 'all');
      const cats = cfg.categories || {};
      ['payments', 'project_start', 'budget_overrun', 'destructive_actions'].forEach(k => {
        const cb = document.getElementById(`passkey-cat-${k}`);
        if (cb) cb.checked = cats[k] !== false;
      });
      renderPasskeyCredentials(cfg.credentials || []);
    } catch (e) {
      console.warn('[PasskeyHITL] Config load error:', e);
    }
  }
  window.loadPasskeyHitlSettings = loadPasskeyHitlSettings;

  function onPasskeyScopeChange(val) {
    syncScopeVisibility(val);
    savePasskeyHitlSettings();
  }
  window.onPasskeyScopeChange = onPasskeyScopeChange;

  async function savePasskeyHitlSettings() {
    const uid = document.getElementById('passkey-user-select')?.value || 'admin';
    const enabled = !!document.getElementById('passkey-hitl-enabled')?.checked;
    const scope = document.getElementById('passkey-hitl-scope')?.value || 'all';
    const categories = {};
    ['payments', 'project_start', 'budget_overrun', 'destructive_actions'].forEach(k => {
      categories[k] = !!document.getElementById(`passkey-cat-${k}`)?.checked;
    });
    try {
      const res = await fetch('/api/auth/passkey/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid, enabled, scope, categories }),
      });
      if (res.ok && typeof showNotification === 'function') {
        showNotification('Passkey HITL', 'Verifizierungs-Einstellungen gespeichert.', 'success');
      }
    } catch (e) {}
  }
  window.savePasskeyHitlSettings = savePasskeyHitlSettings;

  async function registerUserPasskey() {
    if (!window.PublicKeyCredential || !navigator.credentials) {
      alert('WebAuthn / Passkeys werden von diesem Browser oder Kontext (nur localhost/HTTPS) nicht unterstützt.');
      return;
    }
    const sel = document.getElementById('passkey-user-select');
    const uid = (sel && sel.value) || 'admin';
    const username = (sel && sel.selectedOptions[0]?.textContent) || uid;
    const label = prompt('Bezeichnung für diesen Passkey (z. B. Google Passkey / Windows Hello):', 'Mein Passkey');
    if (!label) return;
    try {
      const optRes = await fetch('/api/auth/passkey/register/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid, username }),
      });
      const optData = await optRes.json();
      if (!optRes.ok) throw new Error(optData.detail || 'Optionen fehlgeschlagen');
      const opts = optData.options;
      opts.challenge = b64uToBuf(opts.challenge);
      opts.user.id = b64uToBuf(opts.user.id);
      if (Array.isArray(opts.excludeCredentials)) {
        opts.excludeCredentials = opts.excludeCredentials.map(c => ({ ...c, id: b64uToBuf(c.id) }));
      }
      const cred = await navigator.credentials.create({ publicKey: opts });
      if (!cred || !cred.response || typeof cred.response.getPublicKey !== 'function') {
        throw new Error('Browser liefert getPublicKey() nicht (moderner Chromium/Firefox/Edge erforderlich).');
      }
      const spki = cred.response.getPublicKey();
      const alg = typeof cred.response.getPublicKeyAlgorithm === 'function' ? cred.response.getPublicKeyAlgorithm() : -7;
      const verRes = await fetch('/api/auth/passkey/register/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: uid,
          id: cred.id,
          label,
          alg,
          clientDataJSON: bufToB64u(cred.response.clientDataJSON),
          publicKeySpki: bufToB64u(spki),
        }),
      });
      const verData = await verRes.json();
      if (!verRes.ok) throw new Error(verData.detail || 'Registrierung fehlgeschlagen');
      renderPasskeyCredentials(verData.credentials || []);
      if (typeof showNotification === 'function') showNotification('Passkey', `Passkey '${label}' registriert.`, 'success');
    } catch (err) {
      if (typeof showNotification === 'function') showNotification('Passkey-Fehler', err.message, 'error');
      else alert(err.message);
    }
  }
  window.registerUserPasskey = registerUserPasskey;

  async function deleteUserPasskey(credId) {
    const uid = document.getElementById('passkey-user-select')?.value || 'admin';
    const res = await fetch(`/api/auth/passkey/credentials/${encodeURIComponent(credId)}?user_id=${encodeURIComponent(uid)}`, { method: 'DELETE' });
    if (res.ok) {
      const data = await res.json();
      renderPasskeyCredentials(data.credentials || []);
    }
  }
  window.deleteUserPasskey = deleteUserPasskey;

  async function requirePasskeyForHitl(category = 'all', actionLabel = 'HITL-Freigabe', force = false) {
    const uid = document.getElementById('passkey-user-select')?.value || 'admin';
    const optRes = await fetch('/api/auth/passkey/hitl/options', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: uid, category, action_label: actionLabel, force }),
    });
    const optData = await optRes.json();
    if (!optRes.ok) throw new Error(optData.detail || 'Passkey-Optionen fehlgeschlagen');
    if (!optData.required) return { required: false, verified: true };
    if (!window.PublicKeyCredential || !navigator.credentials) {
      throw new Error('Passkey-Verifizierung erforderlich, aber WebAuthn wird in diesem Browser nicht unterstützt.');
    }
    const opts = optData.options;
    opts.challenge = b64uToBuf(opts.challenge);
    if (Array.isArray(opts.allowCredentials)) {
      opts.allowCredentials = opts.allowCredentials.map(c => ({ ...c, id: b64uToBuf(c.id) }));
    }
    const assertion = await navigator.credentials.get({ publicKey: opts });
    if (!assertion || !assertion.response) throw new Error('Passkey-Verifizierung abgebrochen.');
    const verRes = await fetch('/api/auth/passkey/hitl/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: uid,
        id: assertion.id,
        clientDataJSON: bufToB64u(assertion.response.clientDataJSON),
        authenticatorData: bufToB64u(assertion.response.authenticatorData),
        signature: bufToB64u(assertion.response.signature),
      }),
    });
    const verData = await verRes.json();
    if (!verRes.ok) throw new Error(verData.detail || 'Signaturprüfung fehlgeschlagen');
    return { required: true, verified: true, proof: verData.proof };
  }
  window.requirePasskeyForHitl = requirePasskeyForHitl;

  async function testPasskeyHitlVerification() {
    try {
      const res = await requirePasskeyForHitl('all', 'Test-Verifizierung', true);
      if (res.verified && typeof showNotification === 'function') {
        showNotification('Passkey verifiziert', 'Kryptographische Signatur erfolgreich geprüft.', 'success');
      }
    } catch (err) {
      if (typeof showNotification === 'function') showNotification('Passkey-Fehler', err.message, 'error');
      else alert(err.message);
    }
  }
  window.testPasskeyHitlVerification = testPasskeyHitlVerification;

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => { loadPasskeyHitlSettings(); }, 1200);
  });
})();
