/**
 * Archon CRM - Extension Background Worker
 * PocketBase REST API at http://127.0.0.1:8090
 */

const POCKETBASE_URL = 'http://127.0.0.1:8090';

function cleanUrl(url) {
  if (!url) return '';
  let u = url.trim().toLowerCase();
  u = u.replace(/^https?:\/\/(www\.)?linkedin\.com\/in\//, '');
  u = u.split('?')[0].split('#')[0];
  if (u.endsWith('/')) u = u.slice(0, -1);
  return u;
}

async function findExistingContact(linkedinUrl, name) {
  const normUrl = cleanUrl(linkedinUrl);

  if (normUrl) {
    try {
      const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records?filter=${encodeURIComponent(`linkedin_url ~ "${normUrl}"`)}&perPage=5`);
      if (res.ok) {
        const data = await res.json();
        if (data.items && data.items.length > 0) {
          const exact = data.items.find(item => cleanUrl(item.linkedin_url) === normUrl);
          if (exact) return exact;
          return data.items[0];
        }
      }
    } catch (e) {
      console.warn('[Archon Background] Search by URL failed:', e);
    }
  }

  if (name && name.trim()) {
    try {
      const cleanName = name.trim().toLowerCase();
      const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records?filter=${encodeURIComponent(`name ~ "${cleanName}"`)}&perPage=5`);
      if (res.ok) {
        const data = await res.json();
        if (data.items && data.items.length > 0) {
          return data.items.find(item => (item.name || '').trim().toLowerCase() === cleanName) || data.items[0];
        }
      }
    } catch (e) {
      console.warn('[Archon Background] Search by name failed:', e);
    }
  }

  return null;
}

async function saveProfile(data) {
  const name = data.name || `${data.vorname || ''} ${data.nachname || ''}`.trim() || 'LinkedIn Kontakt';
  const existing = await findExistingContact(data.linkedin_url, name);

  if (existing) {
    const patchPayload = {};
    if (!existing.name && name) patchPayload.name = name;
    if (data.unternehmen && existing.unternehmen !== data.unternehmen) patchPayload.unternehmen = data.unternehmen;
    if (data.position && existing.rolle !== data.position) patchPayload.rolle = data.position;
    if (data.region && existing.region !== data.region) patchPayload.region = data.region;
    if (data.linkedin_url && !existing.linkedin_url) patchPayload.linkedin_url = data.linkedin_url;
    if (data.profilbild && existing.profilbild !== data.profilbild) patchPayload.profilbild = data.profilbild;
    if (data.email && existing.email !== data.email) patchPayload.email = data.email;
    if (data.telefon_1 && existing.telefon_1 !== data.telefon_1) patchPayload.telefon_1 = data.telefon_1;
    if (data.webseite && existing.webseite !== data.webseite) patchPayload.webseite = data.webseite;
    if (data.adresse && existing.adresse !== data.adresse) patchPayload.adresse = data.adresse;

    const existingTags = Array.isArray(existing.tags) ? existing.tags : [];
    const newTags = Array.from(new Set([...existingTags, 'LinkedIn Import']));
    if (newTags.length !== existingTags.length) patchPayload.tags = newTags;

    if (Object.keys(patchPayload).length > 0) {
      const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records/${existing.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patchPayload)
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`PATCH failed (${res.status}): ${errText}`);
      }
      return { action: 'patched', message: `Kontakt "${name}" im CRM aktualisiert.` };
    } else {
      return { action: 'unchanged', message: `Kontakt "${name}" ist im CRM auf dem neuesten Stand.` };
    }
  } else {
    const postPayload = {
      name: name,
      unternehmen: data.unternehmen || '',
      rolle: data.position || data.rolle || '',
      region: data.region || '',
      linkedin_url: data.linkedin_url || '',
      profilbild: data.profilbild || '',
      email: data.email || '',
      telefon_1: data.telefon_1 || '',
      webseite: data.webseite || '',
      adresse: data.adresse || '',
      status: 'Unvernetzt',
      tags: ['LinkedIn Import'],
      nachrichtenverlauf: [],
      vernetzt_am: ''
    };

    const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(postPayload)
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`POST failed (${res.status}): ${errText}`);
    }

    return { action: 'created', message: `Kontakt "${name}" automatisch im CRM angelegt.` };
  }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'SAVE_PROFILE') {
    saveProfile(request.data)
      .then(result => sendResponse({ success: true, message: result.message }))
      .catch(err => sendResponse({ success: false, message: err.message }));
    return true;
  }
});
