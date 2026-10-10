/**
 * Archon CRM - LinkedIn Extension Service Worker
 * Handles communication between LinkedIn content script, Popup UI, and PocketBase REST API.
 *
 * FIX 2026-08-07: profile picture (`profilbild`) is a FILE field in PocketBase.
 * It cannot be set via a JSON URL string - PocketBase rejects it with
 * 400 validation_invalid_file. We now download the image and upload it as a
 * real multipart/form-data file part.
 */

const DEFAULT_POCKETBASE_URL = 'http://localhost:8090';

// Retrieve configured PocketBase URL from chrome storage
async function getPocketBaseUrl() {
  const result = await chrome.storage.local.get(['pbUrl']);
  let url = result.pbUrl || DEFAULT_POCKETBASE_URL;
  if (url.endsWith('/')) url = url.slice(0, -1);
  return url;
}

// Normalize LinkedIn URL for accurate match comparison
function normalizeLinkedInUrl(url) {
  if (!url) return '';
  let u = url.trim().toLowerCase();
  u = u.replace(/^https?:\/\/(www\.)?linkedin\.com\/in\//, '');
  u = u.split('?')[0].split('#')[0];
  if (u.endsWith('/')) u = u.slice(0, -1);
  return u;
}

// Helper for PocketBase JSON API calls (read / non-file operations)
async function fetchPocketBase(endpoint, options = {}) {
  const baseUrl = await getPocketBaseUrl();
  const fullUrl = `${baseUrl}${endpoint}`;

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {})
  };

  try {
    const res = await fetch(fullUrl, { ...options, headers });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`PocketBase API Error (${res.status}): ${errorText}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`[Archon CRM SW] Fetch Error for ${fullUrl}:`, err);
    throw err;
  }
}

// Convert a base64 data URL (supplied by the content script, which has the
// live LinkedIn session) into a File object for the file-field upload.
// Returns null if the value is unusable - never blocks the rest of the save.
function dataUrlToFile(dataUrl) {
  if (!dataUrl || typeof dataUrl !== 'string') return null;
  const m = dataUrl.match(/^data:([^;,]+)[;,]?(base64)?,(.*)$/s);
  if (!m) return null;
  const mime = m[1] || 'image/jpeg';
  let binary;
  if (m[2] === 'base64') {
    try {
      binary = atob(m[3]);
    } catch (e) {
      console.warn('[Archon CRM SW] base64 decode fehlgeschlagen:', e);
      return null;
    }
  } else {
    // URL-encoded data URI (rare); fall back to trying fetch of the raw value
    try { binary = decodeURIComponent(m[3]); } catch (e) { binary = m[3]; }
  }
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const ext = (mime.split('/')[1] || 'jpg').split(';')[0].split('+')[0] || 'jpg';
  const filename = `profil_${Date.now()}.${ext}`;
  return new File([bytes], filename, { type: mime });
}

// Helper for PocketBase file uploads (multipart/form-data).
async function postPocketBaseMultipart(endpoint, method, fields, file) {
  const baseUrl = await getPocketBaseUrl();
  const fullUrl = `${baseUrl}${endpoint}`;

  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value) || typeof value === 'object') {
      form.append(key, JSON.stringify(value));
    } else {
      form.append(key, String(value));
    }
  }
  if (file) form.append('profilbild', file);

  const res = await fetch(fullUrl, { method, body: form });
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`PocketBase Upload Error (${res.status}): ${errorText}`);
  }
  return await res.json();
}

// Download an image from the given URL directly in the service worker.
// Because the manifest grants host_permissions for *.licdn.com / *.linkedin.com,
// this cross-origin fetch is allowed and not subject to the page's CORS.
// Returns a File or null on failure (never blocks the textual save).
async function downloadImageFromUrl(imageUrl) {
  if (!imageUrl || typeof imageUrl !== 'string') return null;
  if (!/^https?:\/\//i.test(imageUrl)) return null;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const res = await fetch(imageUrl, { credentials: 'include', signal: controller.signal, mode: 'cors' });
    clearTimeout(timer);
    if (!res.ok) {
      console.warn('[Archon CRM SW] Bild-Download ', res.status, (imageUrl||'').slice(0,60));
      return null;
    }
    const blob = await res.blob();
    if (!blob || blob.size === 0) return null;
    const ext = (blob.type.split('/')[1] || 'jpg').split(';')[0].split('+')[0] || 'jpg';
    const filename = `profil_${Date.now()}.${ext}`;
    return new File([blob], filename, { type: blob.type || 'image/jpeg' });
  } catch (e) {
    console.warn('[Archon CRM SW] Bild-Download fehlgeschlagen:', e);
    return null;
  }
}

// Decode a LinkedIn profile handle/URL for umlaut-safe comparison.
// Stored URLs may contain percent-encoding (e.g. bj%C3%B6rn for "björn").
// We compare decoded forms so Björn != bj%C3%B6rn is never a false negative.
function decodeHandle(u) {
  try {
    return decodeURIComponent(u || '');
  } catch (e) {
    return u || '';
  }
}

// Check if contact exists by LinkedIn URL or Name.
// IMPORTANT (umlaut fix): PocketBase treats '%' in filters as a LIKE wildcard,
// so matching on the full encoded handle breaks for URLs with umlauts
// (e.g. bj%C3%B6rn-...). Strategy:
//   1. Match by NAME first (reliable, language-agnostic).
//   2. Then match by URL using BOTH encoded and decoded handles.
async function findContact(linkedinUrl, fullName) {
  const normTarget = normalizeLinkedInUrl(linkedinUrl);
  const decodedTarget = decodeHandle(normTarget);

  // 1. NAME-FIRST search (most reliable; side-steps all URL/encoding issues)
  if (fullName && fullName.trim()) {
    try {
      const cleanName = fullName.trim().toLowerCase();
      const filter = `name ~ "${cleanName}"`;
      const data = await fetchPocketBase(`/api/collections/kontakte/records?filter=${encodeURIComponent(filter)}&perPage=20`);
      if (data.items && data.items.length > 0) {
        const exactName = data.items.find(item => (item.name || '').trim().toLowerCase() === cleanName);
        if (exactName) return exactName;
        return data.items[0];
      }
    } catch (e) {
      console.warn('[Archon CRM SW] Name filter search failed:', e);
    }
  }

  // 2. URL search: match on a distinctive, UMlaut-FREE substring that exists
  //    verbatim in the stored URL. LinkedIn /in/ URLs end in a numeric-ish id
  //    (e.g. ...-babbe-174b29194). We search on the trailing id segment, which
  //    has no '%' and no umlauts, so PocketBase's LIKE wildcard never interferes.
  if (normTarget) {
    try {
      // candidates in priority order:
      //   a) last '-' token that is purely [a-z0-9] and >= 4 chars (the id)
      //   b) a 6-char alnum slice of the encoded handle as a last resort
      const tokens = normTarget.split('-').filter(Boolean);
      let safePart = '';
      for (let i = tokens.length - 1; i >= 0; i--) {
        if (/^[a-z0-9]{4,}$/.test(tokens[i])) { safePart = tokens[i]; break; }
        if (/^[a-z0-9]{2,}$/.test(tokens[i]) && i === tokens.length - 1) safePart = tokens[i];
      }
      if (!safePart || safePart.length < 3) safePart = (normTarget.match(/[a-z0-9]{6,}/) || [''])[0];

      if (safePart && safePart.length >= 3) {
        const filter = `linkedin_url ~ "${safePart}"`;
        const data = await fetchPocketBase(`/api/collections/kontakte/records?filter=${encodeURIComponent(filter)}&perPage=20`);
        if (data.items && data.items.length > 0) {
          // prefer exact match on DECODED url or name
          const exact = data.items.find(item => {
            const nameMatch = item.name && fullName && (item.name || '').trim().toLowerCase() === fullName.trim().toLowerCase();
            const urlMatch = decodeHandle(normalizeLinkedInUrl(item.linkedin_url)) === decodedTarget;
            return nameMatch || urlMatch;
          });
          if (exact) return exact;
          return data.items[0];
        }
      }
    } catch (e) {
      console.warn('[Archon CRM SW] URL filter search failed:', e);
    }
  }

  return null;
}

// Upsert (Create or Update) contact record in PocketBase.
// Now uploads the profile picture as a real file part.
async function saveContact(contactData) {
  const existing = await findContact(contactData.linkedin_url, contactData.name);
  const force = !!contactData.force;

  // Normalize tags
  let tags = Array.isArray(contactData.tags) ? contactData.tags : ['LinkedIn Extension'];
  if (existing && Array.isArray(existing.tags)) {
    tags = Array.from(new Set([...existing.tags, ...tags]));
  }

  // Build a payload using EXACTLY the column names that exist in the
  // 'Kontakte' collection. PocketBase silently DROPS unknown fields
  // (e.g. lowercase 'webseite', 'adresse'), so we map carefully:
  //   - website field is named 'Webseite' (capital W)
  //   - there is NO 'adresse' column -> address is appended to 'kommentar'
  let commentParts = [];
  if (existing && existing.kommentar) commentParts.push(existing.kommentar);
  if (contactData.kommentar) commentParts.push(contactData.kommentar);
  if (contactData.adresse && (!existing || !existing.kommentar || !existing.kommentar.includes(contactData.adresse))) {
    commentParts.push(`Adresse: ${contactData.adresse}`);
  }
  let kommentar = commentParts.filter(Boolean).join('\n---\n');

  const fields = {
    name: (existing && existing.name && !force) ? existing.name : (contactData.name || 'Unbekannt'),
    unternehmen: (existing && existing.unternehmen && !force) ? existing.unternehmen : (contactData.unternehmen || ''),
    rolle: (existing && existing.rolle && !force) ? existing.rolle : (contactData.rolle || ''),
    region: (existing && existing.region && !force) ? existing.region : (contactData.region || ''),
    linkedin_url: (existing && existing.linkedin_url && !force) ? existing.linkedin_url : (contactData.linkedin_url || ''),
    email: (existing && existing.email && !force) ? existing.email : (contactData.email || ''),
    telefon_1: (existing && existing.telefon_1 && !force) ? existing.telefon_1 : (contactData.telefon_1 || ''),
    telefon_2: (existing && existing.telefon_2 && !force) ? existing.telefon_2 : (contactData.telefon_2 || ''),
    'Webseite': (existing && existing.Webseite && !force) ? existing.Webseite : (contactData.webseite || ''),
    status: (existing && existing.status && !force) ? existing.status : (contactData.status || 'Unvernetzt'),
    tags,
    vernetzt_am: (existing && existing.vernetzt_am && !force) ? existing.vernetzt_am : (contactData.vernetzt_am || ''),
    kommentar
  };

  // Convert the base64 data-URL image (if the content script supplied one) to
  // a File. The content script fetches the image inside the live page session,
  // so no CORS/cookie problems here. Never blocks the textual save.
  // Get the profile image as a File via BEST of two paths:
  //   1. base64 data-URL from the content script (page session)
  //   2. direct SW download (host_permissions bypass page CORS)
  // Prefer the base64 data-URL supplied by the content script (real pixels,
  // with session). Only if that is absent, fall back to downloading the URL.
  let imageFile = null;
  // Only upload a new profile picture if the contact has no image yet OR if we are forcing the sync
  if (!existing || !existing.profilbild || force) {
    if (contactData.profilbild_data && contactData.profilbild_data.startsWith('data:')) {
      imageFile = dataUrlToFile(contactData.profilbild_data);
    }
    if (!imageFile && contactData.profilbild) {
      imageFile = await downloadImageFromUrl(contactData.profilbild);
    }
  }

  // Save contact. If the image upload fails for any reason, RETRY without the
  // image so the textual data (region, email, phone, etc.) is never lost.
  const doSave = (withImage) => {
    const file = withImage ? imageFile : null;
    if (existing) {
      return postPocketBaseMultipart(
        `/api/collections/kontakte/records/${existing.id}`, 'PATCH', fields, file
      ).then(r => ({ action: 'updated', record: r, image: !!file }));
    } else {
      return postPocketBaseMultipart(
        `/api/collections/kontakte/records`, 'POST', fields, file
      ).then(r => ({ action: 'created', record: r, image: !!file }));
    }
  };

  if (imageFile) {
    try {
      return await doSave(true);
    } catch (e) {
      console.warn('[Archon CRM SW] Save with image failed, retrying without image:', e);
      return await doSave(false);
    }
  }
  return await doSave(false);
}

// Quick status update for an existing record (JSON is fine - no file field)
async function updateContactStatus(id, newStatus) {
  const result = await fetchPocketBase(`/api/collections/kontakte/records/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: newStatus })
  });
  return result;
}

// Handle incoming Extension messages
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      switch (message.type) {
        case 'HEALTH_CHECK': {
          const baseUrl = await getPocketBaseUrl();
          try {
            const data = await fetchPocketBase('/api/collections/kontakte/records?perPage=1');
            sendResponse({ success: true, url: baseUrl, totalRecords: data.totalItems || 0 });
          } catch (err) {
            sendResponse({ success: false, url: baseUrl, error: err.message });
          }
          break;
        }

        case 'CHECK_CONTACT': {
          const contact = await findContact(message.linkedinUrl, message.name);
          sendResponse({ success: true, exists: !!contact, record: contact });
          break;
        }

        case 'SAVE_CONTACT': {
          const res = await saveContact(message.data);
          sendResponse({ success: true, action: res.action, record: res.record, image: res.image });
          break;
        }

        case 'UPDATE_STATUS': {
          const updated = await updateContactStatus(message.id, message.status);
          sendResponse({ success: true, record: updated });
          break;
        }

        case 'SEARCH_CONTACTS': {
          const query = message.query || '';
          const filter = `name ~ "${query}" || unternehmen ~ "${query}" || rolle ~ "${query}"`;
          const data = await fetchPocketBase(`/api/collections/kontakte/records?filter=${encodeURIComponent(filter)}&perPage=20&sort=-created`);
          sendResponse({ success: true, items: data.items || [] });
          break;
        }

        default:
          sendResponse({ success: false, error: 'Unknown message type' });
      }
    } catch (err) {
      console.error('[Archon CRM SW] Error processing message:', message, err);
      sendResponse({ success: false, error: err.message });
    }
  })();

  return true; // Keep message channel open for async response
});
