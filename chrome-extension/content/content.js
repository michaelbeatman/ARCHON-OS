/**
 * Archon CRM - LinkedIn Content Script
 * Extracts profile data from LinkedIn DOM, embeds an interactive CRM status widget,
 * and automatically saves the profile (incl. profile picture + contact info)
 * into the Archon CRM (PocketBase).
 *
 * FIX 2026-08-07:
 *  - fixed "'use me strict'" typo -> 'use strict'
 *  - added automatic profile save on view (no longer waits for button click)
 *  - added contact-info extraction (email, phone, website, address) from modal
 */

'use strict';

(function () {
  let currentProfileUrl = '';
  let widgetContainer = null;
  let currentContactRecord = null;
  let lastAutoSavedKey = ''; // dedupe auto-save per profile + payload hash

  // Status option metadata matching Archon CRM definition
  const STATUS_OPTIONS = [
    { id: 'Unvernetzt', label: '👤 Unvernetzt', color: '#64748b' },
    { id: 'Vernetzt', label: '🤝 Vernetzt', color: '#3b82f6' },
    { id: 'Erstnachricht', label: '💬 Erstnachricht', color: '#a855f7' },
    { id: 'Im Dialog', label: '🔄 Im Dialog', color: '#06b6d4' },
    { id: 'Interview vereinbart', label: '📅 Interview vereinbart', color: '#10b981' },
    { id: 'Regelmäßiger Kontakt', label: '🔁 Regelmäßiger Kontakt', color: '#14b8a6' },
    { id: 'Parkposition', label: '📁 Parkposition', color: '#f59e0b' },
    { id: 'Gesperrt_1Jahr', label: '⛔ Gesperrt (1 Jahr)', color: '#f43f5e' }
  ];

  // Clean LinkedIn URL
  function getCleanProfileUrl() {
    let url = window.location.href;
    url = url.split('?')[0].split('#')[0];
    if (url.endsWith('/')) url = url.slice(0, -1);
    return url;
  }

  // Small DOM helpers that tolerate LinkedIn's changing class names.
  function qText(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.trim()) return el.innerText.trim();
    }
    return '';
  }
  function metaContent(prop) {
    const el = document.querySelector('meta[property="' + prop + '"], meta[name="' + prop + '"]');
    return el ? (el.content || '').trim() : '';
  }

  // Extract contact information from LinkedIn Profile DOM.
  // LinkedIn frequently changes its CSS classes, so we use a layered approach:
  //   1. OpenGraph / meta tags (og:title, og:image, ...) - stable and always present
  //   2. Current DOM selectors (multiple fallbacks)
  //   3. <title> + description as last resort
  function extractProfileData() {
    let name = '';
    let headline = '';
    let company = '';
    let location = '';
    let profilbild = '';

    // ---- Name ----
    name = qText([
      'h1.text-heading-xlarge',
      'h1.inline.t-24',
      'main section h1',
      'main h1',
      '.pv-top-card--list h1',
      '.pv-text-details__left-panel h1',
      'h1'
    ]);

    // Remember the resolved name as early as possible — resolveProfileImgEl
    // uses payload_name as tiebreaker when choosing the profile photo.
    if (name) payload_name = name;

    // ---- Headline / Role ----
    headline = qText([
      'div.text-body-medium.break-words',
      '.pv-top-card--list .text-body-medium',
      '.pv-text-details__left-panel .text-body-medium',
      'main section .text-body-medium',
      '.text-body-medium.break-words',
      'div[data-generated-suggestion-target] + div'
    ]);

    // ---- Location / Region (only present in the DOM, not in meta tags) ----
    // Scoped to the top-card region: LinkedIn redesigns move these classes, so
    // we try several selectors but ALL are anchored to the profile top card.
    location = qText([
      'main .pv-text-details__left-panel .text-body-small',
      'main .pv-top-card-v2-section__info li:first-child span',
      'main .pv-top-card--list-bullet > li:first-child',
      'main .top-card-layout div.text-body-small',
      'main .top-card-layout__entity-info .text-body-small',
      'main section .text-body-small.inline.t-black--light.break-words',
      'main .pv-top-card-v2-section__info span.t-black--light'
    ]);
    // The previous generic `span.text-body-small` selector was removed — it
    // matched stray sidebar elements (e.g. a lone "N" character). Only accept
    // a location that looks like a real place (min length + letters).
    if (location && (location.length < 2 || /^[A-ZÄÖÜ]?\.?$/.test(location.trim()))) {
      location = '';
    }
    if (!location) {
      // Fallback: scan the top-card text for a typical city/region line.
      const topCard = document.querySelector(
        'main .pv-top-card, main .top-card-layout, main section'
      ) || document.body;
      const topText = topCard.innerText || '';
      // Prefer a line that clearly looks like a location
      const locLine = topText.split('\n').map(l => l.trim()).find(l =>
        l && /(Region|Umgebung|, (?:Deutschland|Germany)|, (?:Berlin|Hamburg|München|Köln|Frankfurt|Stuttgart|Düsseldorf|Dortmund|Essen|Leipzig|Bremen|Dresden|Hannover|Nürnberg|Bielefeld|Bochum|Bonn|Münster|Karlsruhe|Mannheim|Augsburg|Wiesbaden|Gelsenkirchen|Mönchengladbach|Braunschweig|Kiel|Chemnitz|Aachen|Halle|Magdeburg|Freiburg|Krefeld|Mainz|Lübeck|Erfurt|Oberhausen|Rostock|Kassel|Hagen|Potsdam|Saarbrücken|Hamm|Ludwigshafen|Oldenburg|Mülheim|Osnabrück|Leverkusen|Heidelberg|Darmstadt|Solingen|Regensburg|Herne|Paderborn|Neuss|Ingolstadt|Offenbach|Fürth|Würzburg|Ulm|Heilbronn|Pforzheim|Wolfsburg|Göttingen|Bottrop|Recklinghausen|Salzgitter|Koblenz|Siegen|Erlangen|Trier|Jena|Hildesheim)|^(?:[A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)*),\s*[A-ZÄÖÜ]|^\d{5}\s)/.test(l)
      );
      if (locLine && locLine.length < 80) location = locLine;
      if (!location) {
        // Last resort: first "City, Country" or "City und Umgebung" pattern
        const m = topText.match(/([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)*)(?:,\s*([A-ZÄÖÜ][a-zäöüß\-]+)|(?:\s+und\s+Umgebung))/);
        if (m) location = (m[1] + (m[2] ? ', ' + m[2] : '')).replace(/\n/g, ' ').trim();
      }
    }

    // ---- Company ----
    company = qText([
      'button[aria-label*="Current company"]',
      'button[aria-label="Aktuelles Unternehmen"]',
      '.pv-text-details__right-panel-item span',
      '.inline-show-more-text',
      'img[alt*="logo"] + span',
      'span.org-top-card-summary__info'
    ]);
    if (!company) {
      const m = headline.match(/\sbei\s(.+)$/i) || headline.match(/\sat\s(.+)$/i);
      if (m) company = m[1].split('|')[0].trim();
    }

    // ---- Profile Picture (prefer hi-res) ----
    // NOTE: og:image is the COVER/HEADER banner on LinkedIn, NOT the profile
    // photo. It is intentionally NOT used here — it silently saved the hero
    // banner instead of the round photo (2026-08-07 finding).
    const pickImg = (sel) => {
      const el = document.querySelector(sel);
      if (!el || !el.src || el.src.startsWith('data:image/svg')) return '';
      // HARD EXCLUSION: never take the logged-in user's own nav avatar
      // (it matches generic selectors too and sits in the header).
      if (el.closest('header, nav, #global-nav, .global-nav, [role="banner"]')) return '';
      return el.src;
    };
    profilbild =
      pickImg('img.pv-top-card-profile-picture__image--large') ||
      pickImg('img.pv-top-card-profile-picture__image--show') ||
      pickImg('img.pv-top-card-profile-picture__image') ||
      pickImg('img.presence-entity__image') ||
      pickImg('img[alt*="profile picture"]') ||
      pickImg('img[alt*="Profilbild"]') ||
      pickImg('img.ivm-view-attr__img--centered') ||
      pickImg('main img[width="200"]');
    // If a CSS-class hit failed, resolve the photo geometrically (left-most
    // round photo with profile-displayphoto marker). Do NOT fall back to og:image.
    if (!profilbild) {
      const imgEl = resolveProfileImgEl();
      if (imgEl) profilbild = imgEl.currentSrc || imgEl.src || '';
    }

    // ---- Fallback: meta tags (very reliable on LinkedIn) ----
    // (og:image is NOT used — it is the cover/header banner, not the photo)
    if (!name) {
      const ogTitle = metaContent('og:title') || document.title || '';
      // og:title is usually "Adam Faßbender" or "Adam Faßbender | LinkedIn"
      name = ogTitle.split(' - ')[0].split('|')[0].trim();
    }
    if (!headline) {
      const ogDesc = metaContent('og:description') || '';
      // og:description usually starts with the headline, e.g. "Geschäftsführer ... "
      headline = ogDesc.split('\n')[0].trim();
    }

    // (payload_name was already set right after name extraction above)

    return {
      name,
      rolle: headline,
      unternehmen: company,
      region: location,
      linkedin_url: getCleanProfileUrl(),
      profilbild,
      tags: ['LinkedIn Extension']
    };
  }

  // Convert an <img> element to a base64 data URL. Layered, robust approach:
  //   1. Canvas draw (reads the pixels the page already rendered - same as the
  //      user manually copying the image; immune to CORS because the <img> is
  //      already loaded in this page).
  //   2. fetch() with the page session as fallback.
  // Returns null if unusable - caller falls back to URL-only.
  async function imageToDataUrl(imgEl) {
    if (!imgEl) return null;
    const src = imgEl.currentSrc || imgEl.src;
    if (!src || src.startsWith('data:image/svg')) return null;

    // ---- Strategy 1: Canvas from the ALREADY-RENDERED <img> (most reliable) ----
    // Drawing the element that the page already displayed reads the pixels the
    // user sees — immune to CORS because no new network request is made.
    try {
      const dataUrl = await new Promise((resolve) => {
        try {
          const canvas = document.createElement('canvas');
          const w = Math.min(imgEl.naturalWidth || imgEl.width || 400, 800);
          const h = Math.min(imgEl.naturalHeight || imgEl.height || 400, 800);
          canvas.width = w; canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(imgEl, 0, 0, w, h);
          resolve(canvas.toDataURL('image/jpeg', 0.92));
        } catch (e) {
          console.warn('[Archon CRM] Canvas draw fehlgeschlagen:', e);
          resolve(null);
        }
      });
      if (dataUrl) return dataUrl;
    } catch (e) {
      console.warn('[Archon CRM] Canvas-Check fehlgeschlagen:', e);
    }

    // ---- Strategy 2: fresh Image() with CORS + canvas (works when the CDN
    //      sends Access-Control-Allow-Origin headers) ----
    try {
      const dataUrl = await new Promise((resolve) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        const timeout = setTimeout(() => resolve(null), 5000);
        img.onload = () => {
          clearTimeout(timeout);
          try {
            const canvas = document.createElement('canvas');
            const w = Math.min(img.naturalWidth || 400, 800);
            const h = Math.min(img.naturalHeight || 400, 800);
            canvas.width = w; canvas.height = h;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, w, h);
            resolve(canvas.toDataURL('image/jpeg', 0.92));
          } catch (e) {
            console.warn('[Archon CRM] Canvas draw fehlgeschlagen:', e);
            resolve(null);
          }
        };
        img.onerror = () => { clearTimeout(timeout); resolve(null); };
        img.src = src;
      });
      if (dataUrl) return dataUrl;
    } catch (e) {
      console.warn('[Archon CRM] Canvas-Check fehlgeschlagen:', e);
    }

    // ---- Strategy 3: fetch() with page session ----
    try {
      const url = imgEl.currentSrc || src;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      const res = await fetch(url, { credentials: 'include', mode: 'cors', signal: controller.signal });
      clearTimeout(timer);
      if (res.ok) {
        const blob = await res.blob();
        if (blob && blob.size > 0) {
          const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          });
          if (dataUrl) return dataUrl;
        }
      } else {
        console.warn('[Archon CRM] Bild-Fetch ', res.status, url.slice(0, 60));
      }
    } catch (e) {
      console.warn('[Archon CRM] Bild-Extraktion fehlgeschlagen:', e);
    }

    return null;
  }

  // Download an absolute image URL to a base64 data-URL using the page session.
  // This mirrors "copy image" - the browser has the cookies, so it can fetch
  // the real photo from LinkedIn even when the SW (no session) cannot.
  async function urlToDataUrl(url) {
    if (!url || !/^https?:\/\//i.test(url)) return null;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(url, { credentials: 'include', mode: 'cors', signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) return null;
      const blob = await res.blob();
      if (!blob || blob.size === 0) return null;
      return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    } catch (e) {
      console.warn('[Archon CRM] urlToDataUrl fehlgeschlagen:', e);
      return null;
    }
  }

  // A global used by findProfileImageUrl for name matching.
  let payload_name = '';

  // Resolve the CORRECT profile-photo <img> element.
  // The viewed person's profile photo sits on the LEFT of the page; the
  // logged-in user's own round nav avatar sits on the RIGHT (top). So we scan
  // all round profile photos and pick the LEFT-MOST one (smallest getBounding
  // ClientRect().left). Name matching is only a tiebreaker for narrow layouts.
  //
  // FIX 2026-08-09 (height cap): the "people also viewed" sidebar renders its
  // small photos with a layout offset that often puts them 1-2px FURTHER LEFT
  // than the real profile photo. Pure left-to-right selection then picks a
  // sidebar person (saved a woman's face for a male contact). The real photo
  // always lives inside the top-card (upper page region), the sidebar starts
  // below it. So we ONLY accept images whose document-relative top edge is
  // within the top-card's vertical span (or a fallback ~520px threshold).
  function resolveProfileImgEl() {
    const nameParts = (payload_name || '').toLowerCase();

    // Height cap: bottom edge of the top-card (scroll-independent)
    const topCardEl = document.querySelector(
      'main .pv-top-card, main .top-card-layout, main section .profile-card, main section .pv-top-card-v2-section'
    );
    let maxY = 520; // fallback: anything below ~520px is sidebar/feed
    if (topCardEl) {
      maxY = topCardEl.getBoundingClientRect().bottom + window.scrollY;
    }

    // EXCLUDE the logged-in user's own nav avatar (top-right header).
    // It also carries profile-displayphoto and sits ABOVE maxY, so without
    // this check it wins whenever the real profile photo is missing.
    const isOwnNavAvatar = (img) => !!img.closest(
      'header, nav, #global-nav, .global-nav, [role="banner"], [data-control-name="identity_welcome_message"]'
    );

    // Hard name check: if the img alt carries a person's name that does NOT
    // match the viewed contact, reject it (own avatar alt = "Michael Keller").
    const altMatchesContact = (img) => {
      const alt = (img.alt || '').trim();
      if (!alt || !nameParts) return null; // no info -> not a rejection
      const altLower = alt.toLowerCase();
      const firstName = (nameParts.split(' ')[0] || '').replace(/[^a-zäöüß]/g, '');
      const lastName = (nameParts.split(' ').slice(1).join(' ') || '').replace(/[^a-zäöüß ]/g, '').trim();
      // Looks like a person name? (>=2 words, first word capitalized)
      const looksLikeName = /^[A-ZÄÖÜ][a-zäöüß]+(\s+[A-ZÄÖÜ][a-zäöüß-]+)+/.test(alt.trim());
      if (!looksLikeName) return null;
      const hitFirstName = firstName && altLower.includes(firstName);
      const hitLastName = lastName && altLower.includes(lastName);
      if (hitFirstName || hitLastName) return true;
      return false; // person-name alt that does NOT match -> reject
    };

    const scored = [];
    const push = (img) => {
      if (!img || (img.currentSrc || img.src || '').includes('data:image')) return;
      const src = (img.currentSrc || img.src || '');
      if (/cover|banner|background/i.test(src) || /ghost_people|wp_|bg_|banner/i.test(src)) return;
      // HARD EXCLUSIONS (wrong photo is worse than no photo)
      if (isOwnNavAvatar(img)) return;
      const nameOk = altMatchesContact(img);
      if (nameOk === false) return; // alt carries a DIFFERENT person's name
      const r = img.getBoundingClientRect();
      // HEIGHT FILTER: document-relative, so it works at any scroll position.
      // Sidebar/feed images are below the top-card -> rejected before the
      // left-to-right comparison ever happens.
      const topDoc = r.top + window.scrollY;
      if (topDoc > maxY) return;
      // left coordinate (0 = left edge). Prefer the left-most round photo.
      let left = r.left >= 0 ? r.left : 99999;
      // strong bonus when the alt matches the contact name (nameOk === true)
      const alt = (img.alt || '');
      let nameBonus = 0;
      if (nameOk === true) {
        nameBonus = -300;
      } else if (nameParts && alt) {
        const first = (nameParts.split(' ')[0] || '').replace(/[^a-zäöüß]/g, '');
        const a = alt.toLowerCase().replace(/[^a-zäöüß]/g, ' ');
        if (first && a.startsWith(first)) nameBonus = -200; // strong left-shift
      }
      scored.push({ img, left: left + nameBonus });
    };

    document.querySelectorAll('img[src*="profile-displayphoto"], img[src*="profile_400x400"], img[src*="/profile/"]').forEach(push);
    document.querySelectorAll('main .pv-top-card-profile-picture__image, .top-card-layout img').forEach(push);

    scored.sort((a, b) => a.left - b.left);
    // If nothing survived the filters, return null -> NO image is saved at all
    // (a wrong photo is worse than none).
    return scored.length ? scored[0].img : null;
  }

  // Attach the correct profile photo to the payload.
  // Uses resolveProfileImgEl() (left-most round photo with profile-displayphoto
  // marker + name tie-breaker) and imageToDataUrl() (canvas draw — CORS-immune).
  // If no image can be resolved, the payload is returned unchanged so the
  // textual save is never blocked.
  async function attachProfileImage(payload) {
    const imgEl = resolveProfileImgEl();
    if (!imgEl) return payload;
    const dataUrl = await imageToDataUrl(imgEl);
    if (dataUrl && /^data:image\//.test(dataUrl)) {
      payload.profilbild_data = dataUrl;
      payload.profilbild = imgEl.currentSrc || imgEl.src || payload.profilbild || '';
    }
    return payload;
  }

  async function findProfileImageElFromAll() {
    const nameParts = (payload_name || '');
    const candidates = Array.from(document.querySelectorAll('img'));
    const score = (img) => {
      let s = 0;
      const src = (img.currentSrc || img.src || '');
      const alt = (img.alt || '');
      if (/profile-displayphoto|profile\b/.test(src) && !/cover|banner|background/i.test(src)) s += 4;
      if (/^http/.test(src) && !src.includes('data:image')) s += 1;
      if (img.naturalWidth && img.naturalHeight && img.naturalWidth < 400 && img.naturalWidth > 30) s += 2;
      if (nameParts && alt && nameParts.split(' ').length >= 2) {
        const n = nameParts.toLowerCase();
        const a = alt.toLowerCase();
        if (a.includes(n.split(' ')[0]) && a.split(' ').length <= 3) s += 3;
      }
      return s;
    };
    const sorted = candidates
      .filter(img => img.currentSrc || img.src)
      .map(img => ({ img, s: score(img) }))
      .filter(x => x.s > 0)
      .sort((a, b) => b.s - a.s);
    return sorted.length ? sorted[0].img : null;
  }

  // Find the VISIBLE contact-info modal. LinkedIn has many role="dialog"
  // elements (nav dropdowns etc.), so we require a visible dialog whose text
  // actually looks like contact info (mailto/tel/@/website/address labels).
  function findContactModal() {
    const selectors = [
      'section[aria-labelledby*="contact" i]',
      '[data-test-id*="contact-info" i]',
      '[data-test-id*="contact_info" i]',
      '.pv-contact-info',
      'div[role="dialog"]',
      '.artdeco-modal',
      '[role="dialog"]'
    ];
    for (const sel of selectors) {
      let els = [];
      try { els = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
      for (const el of els) {
        // skip hidden/cloned/offscreen dialogs
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const t = (el.innerText || '') + ' ' + (el.textContent || '');
        if (/mailto:|tel:|@[a-z0-9.-]+\.[a-z]{2,}|website|webseite|adresse|address|geburtstag|birthday|(?:\+[0-9]{1,3}[ \-\/.]?)?[0-9]{3,}[ \-\/.]?[0-9]{3,}/i.test(t)) {
          return el;
        }
      }
    }
    return null;
  }

  // LinkedIn renders email/phone inside the modal with invisible Unicode
  // control chars (U+200E LRM etc.) between the characters. Strip them before
  // any regex scan, or "name\u200e@example.com" never matches.
  function cleanModalText(el) {
    const raw = ((el.innerText || '') + ' ' + (el.textContent || '')) || '';
    return raw.replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069\u200b\ufeff]/g, '');
  }

  // Extract contact info (email, phone, website, address) from the "Contact info"
  // modal - OR style like you asked: read the VISIBLE text on screen (like OCR),
  // no fragile CSS classes. The user's idea applied lightweight:
  //   - scan the visible innerText of the modal/page for the patterns
  //   - plus try quick, stable attribute selectors (mailto:, tel:, href)
  function extractContactInfo() {
    // Narrow scope to the visible modal if open (faster + avoids page noise).
    // IMPORTANT: email/phone/website/address ONLY exist in the contact-info
    // modal — NEVER scan the whole page body, or sidebar noise (people also
    // viewed, feed links) gets saved as email/website. If no modal is open,
    // return empty; the modal observer triggers the save when it appears.
    const modal = findContactModal();
    if (!modal) return {};
    const text = cleanModalText(modal);
    const data = {};

    // 1) E-MAIL - mailto link, then text-regex scan (exactly what's on screen)
    const mailto = modal ? modal.querySelector('a[href^="mailto:"]') : null;
    if (mailto) data.email = (mailto.getAttribute('href') || '').replace(/^mailto:/i, '').split('?')[0].trim();
    if (!data.email) {
      const m = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
      if (m) data.email = m[0];
    }

    // 2) TELEFON - tel: link, then text-regex scan
    const tel = modal ? modal.querySelector('a[href^="tel:"]') : null;
    if (tel) data.telefon_1 = (tel.getAttribute('href') || tel.innerText || '').replace(/^tel:/i, '').trim();
    if (!data.telefon_1) {
      // Phone numbers on LinkedIn show as "+49 123 456789" or "0123 4567890".
      // Require at least 8 digits; capture the group incl. separators.
      const m = text.match(/(?:\+[0-9]{1,3}[ \-\/.]?)?(?:\([0-9]{2,5}\)[ \-\/.]?)?[0-9]{2,5}[ \-\/.]?[0-9]{3,7}[ \-\/.]?[0-9]{3,7}/);
      if (m && m[0]) {
        const digits = (m[0].match(/\d/g) || []).length;
        if (digits >= 8 && digits <= 16) {
          data.telefon_1 = m[0].replace(/\s+/g, ' ').trim();
        }
      }
    }

    // Label-based scan over the visible modal text: find a line that is (or
    // starts with) "Website" / "Adresse" and take the following line as value.
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

    // 3) WEBSEITE - label "Website" + following line, else URL regex
    if (!data.webseite) {
      const hasUrl = (s) => /^https?:\/\//i.test(s) || /^www\./i.test(s) ||
        /^[a-z0-9-]+\.[a-z]{2,}(\/[^\s]*)?$/i.test(s);
      for (let i = 0; i < lines.length - 1; i++) {
        const l = lines[i];
        if (/^(website|websites|webseite|my website)/i.test(l) && hasUrl(lines[i + 1])) {
          data.webseite = lines[i + 1];
          break;
        }
      }
      if (!data.webseite) {
        const m = text.match(/(?:https?:\/\/)?(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\/[^\s]*)?/);
        if (m) {
          const u = m[0];
          if (u && !/linkedin\.com/i.test(u) && !/\d{1,2}\.\d{1,2}\.\d{4}/.test(u)) {
            data.webseite = /^https?:\/\//i.test(u) ? u : 'https://' + u;
          }
        }
      }
    }

    // 4) ADRESSE - label "Adresse" + following line(s)
    if (!data.adresse) {
      for (let i = 0; i < lines.length - 1; i++) {
        const l = lines[i];
        if (/^(adresse|address)/i.test(l)) {
          const addrParts = [];
          for (let j = i + 1; j < lines.length; j++) {
            const v = lines[j];
            // stop at the next obvious label/headline or another section
            if (/^(website|telefon|email|e-mail|geburtstag|vernetzt|profil|kontakt)/i.test(v)) break;
            if (v && v.length < 80) addrParts.push(v);
            else break;
          }
          if (addrParts.length) { data.adresse = addrParts.join(', '); break; }
        }
      }
    }

    return data;
  }

  // Send a save call to the service worker. Returns a Promise.
  function sendSave(payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'SAVE_CONTACT', data: payload }, (res) => {
        if (chrome.runtime.lastError) {
          console.warn('[Archon CRM] save error:', chrome.runtime.lastError.message);
          resolve({ success: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(res || { success: false, error: 'Keine Antwort' });
      });
    });
  }

  // Create or reset the widget DOM container
  function ensureWidgetContainer() {
    if (document.getElementById('archon-crm-widget-root')) {
      return document.getElementById('archon-crm-widget-root');
    }

    const container = document.createElement('div');
    container.id = 'archon-crm-widget-root';
    container.className = 'archon-crm-widget';

    const targetParent = document.querySelector('main section .pv-top-card-v2-ctas, main section .ph5.pb5, main section .pv-top-card--list');
    if (targetParent) {
      targetParent.insertAdjacentElement('afterend', container);
    } else {
      const topSection = document.querySelector('main section');
      if (topSection) topSection.prepend(container);
    }
    return container;
  }

  // Render Widget UI based on CRM check result
  function renderWidget(contactData, record) {
    currentContactRecord = record;
    widgetContainer = ensureWidgetContainer();
    if (!widgetContainer) return;

    if (record) {
      const statusObj = STATUS_OPTIONS.find(s => s.id === record.status) || STATUS_OPTIONS[0];
      widgetContainer.innerHTML = `
        <div class="archon-card archon-card-exists">
          <div class="archon-header">
            <span class="archon-badge-title">⚡ Archon CRM Status</span>
            <span class="archon-id">ID: ${record.id.slice(0, 6)}</span>
          </div>
          <div class="archon-body">
            <div class="archon-status-selector">
              <label for="archon-status-select">Status:</label>
              <select id="archon-status-select" class="archon-select" style="border-color: ${statusObj.color}">
                ${STATUS_OPTIONS.map(s => `
                  <option value="${s.id}" ${s.id === record.status ? 'selected' : ''}>
                    ${s.label}
                  </option>
                `).join('')}
              </select>
            </div>
            <div class="archon-meta-row">
              <span class="archon-tag">${record.unternehmen || 'Kein Unternehmen'}</span>
              <span class="archon-date">Vernetzt: ${((record.vernetzt_am || record.created) || '').split('T')[0] || 'n/a'}</span>
            </div>
            <div class="archon-actions">
              <button id="archon-sync-btn" class="archon-btn archon-btn-secondary" title="Profil-Daten in CRM aktualisieren">
                🔄 Daten aktualisieren
              </button>
              <a href="http://localhost:8090/_/#/collections/kontakte/records/${record.id}" target="_blank" class="archon-btn archon-btn-link">
                ↗ In CRM öffnen
              </a>
            </div>
          </div>
          <div id="archon-msg-feedback" class="archon-feedback"></div>
        </div>
      `;

      const statusSelect = widgetContainer.querySelector('#archon-status-select');
      statusSelect.addEventListener('change', async (e) => {
        const newStatus = e.target.value;
        const feedback = widgetContainer.querySelector('#archon-msg-feedback');
        feedback.innerText = 'Speichere Status...';
        feedback.className = 'archon-feedback archon-feedback-info';
        chrome.runtime.sendMessage({ type: 'UPDATE_STATUS', id: record.id, status: newStatus }, (res) => {
          if (res && res.success) {
            feedback.innerText = '✓ Status aktualisiert!';
            feedback.className = 'archon-feedback archon-feedback-success';
            setTimeout(() => { feedback.innerText = ''; }, 2500);
          } else {
            feedback.innerText = '❌ Fehler beim Aktualisieren';
            feedback.className = 'archon-feedback archon-feedback-error';
          }
        });
      });

      const syncBtn = widgetContainer.querySelector('#archon-sync-btn');
      syncBtn.addEventListener('click', async () => {
        const freshData = extractProfileData();
        Object.assign(freshData, extractContactInfo()); // merge contact info on manual sync
        freshData.status = record.status; // preserve existing status
        freshData.force = true; // Manual sync forces field overrides
        syncBtn.innerText = '⏳ Aktualisiere...';
        syncBtn.disabled = true;
        await attachProfileImage(freshData);
        const res = await sendSave(freshData);
        if (res && res.success) {
          renderWidget(freshData, res.record);
        } else {
          syncBtn.innerText = '❌ Fehler';
          syncBtn.disabled = false;
        }
      });

    } else {
      widgetContainer.innerHTML = `
        <div class="archon-card archon-card-new">
          <div class="archon-new-content">
            <div class="archon-icon-box">⚡</div>
            <div class="archon-text-box">
              <div class="archon-title">Nicht in Archon CRM</div>
              <div class="archon-subtitle">Auto-Save aktiv - wird gespeichert...</div>
            </div>
            <button id="archon-save-btn" class="archon-btn archon-btn-primary">
              + In Archon CRM speichern
            </button>
          </div>
          <div id="archon-msg-feedback" class="archon-feedback"></div>
        </div>
      `;

      const saveBtn = widgetContainer.querySelector('#archon-save-btn');
      saveBtn.addEventListener('click', () => {
        saveBtn.innerText = '⏳ Speichere...';
        saveBtn.disabled = true;
        const dataToSave = extractProfileData();
        Object.assign(dataToSave, extractContactInfo());
        attachProfileImage(dataToSave).then(() => sendSave(dataToSave)).then((res) => {
          if (res && res.success) {
            renderWidget(dataToSave, res.record);
          } else {
            saveBtn.innerText = '❌ Fehler beim Speichern';
            saveBtn.disabled = false;
            const feedback = widgetContainer.querySelector('#archon-msg-feedback');
            if (feedback) { feedback.innerText = res && res.error ? res.error : ''; }
          }
        });
      });
    }
  }

  // Automatically save the profile (with contact info if available) - the app's core intent.
  async function autoSave(force) {
    const cleanUrl = getCleanProfileUrl();
    if (!cleanUrl.includes('/in/')) return;

    const profileData = extractProfileData();
    if (!profileData.name) {
      setStatus('Profil lädt noch...', '');
      return;
    }

    const contactInfo = extractContactInfo();
    const payload = Object.assign({}, profileData, contactInfo);
    // Diagnostic: show exactly what was extracted (self-debugging in the widget)
    const diag = [
      profileData.name ? 'Name ✓' : 'Name ✗',
      payload.email ? ('Mail ' + payload.email) : 'Mail ✗',
      payload.telefon_1 ? ('Tel ' + payload.telefon_1) : 'Tel ✗',
      payload.webseite ? 'Web ✓' : 'Web ✗',
      payload.region ? ('Reg ' + payload.region.slice(0, 24)) : 'Reg ✗',
    ].join(' | ');
    setStatus('Extraktion: ' + diag, '');

    // Attach image. imageToDataUrl has a built-in 5s timeout, so the save
    // can never hang on the picture, but the picture will be included.
    await attachProfileImage(payload);
    if (payload.profilbild_data && /^data:/.test(payload.profilbild_data)) {
      setStatus('Extraktion: Bild als Base64 ✓ lädt hoch', '');
    } else if (payload.profilbild) {
      setStatus('Extraktion: Bild-URL gefunden, lade im SW...', '');
    }

    // Dedupe: skip re-saving the identical payload for the same profile
    const key = cleanUrl + '|' + JSON.stringify(payload);
    if (!force && lastAutoSavedKey === key) return;
    lastAutoSavedKey = key;

    const res = await sendSave(payload);
    if (res && res.success) {
      const imageMsg = res.image ? ' + Bild' : '';
      console.log(`[Archon CRM] Auto-Save OK (${res.action})${imageMsg} für ${profileData.name}`);
      setStatus('Gespeichert (' + res.action + ')' + imageMsg + ' - ' + profileData.name, 'ok');
      // Re-check to update widget state (now exists)
      lastAutoSavedKey = '';
      initCheck(false);
    } else {
      const errMsg = (res && res.error) || 'Unbekannter Fehler';
      console.warn('[Archon CRM] Auto-Save fehlgeschlagen:', errMsg);
      setStatus('Fehler: ' + errMsg, 'err');
    }
  }

  // Initialize or re-check page
  async function initCheck(runAutoSave) {
    const cleanUrl = getCleanProfileUrl();
    if (!cleanUrl.includes('/in/')) return;

    currentProfileUrl = cleanUrl;
    const profileData = extractProfileData();

    if (runAutoSave !== false) {
      autoSave(false);
    }

    chrome.runtime.sendMessage(
      { type: 'CHECK_CONTACT', linkedinUrl: profileData.linkedin_url, name: profileData.name },
      (res) => {
        if (chrome.runtime.lastError) {
          console.warn('[Archon CRM] Extension communication error:', chrome.runtime.lastError.message);
          return;
        }
        if (res && res.success) {
          renderWidget(profileData, res.record);
        }
      }
    );
  }

  // Show a small, always-visible sync status on the LinkedIn page so the user
  // can see what the extension is doing (incl. the real error from the SW).
  function ensureStatusBar() {
    let bar = document.getElementById('archon-crm-statusbar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'archon-crm-statusbar';
      bar.style.cssText = 'position:fixed;top:100px;right:14px;z-index:2147483647;' +
        'background:rgba(15,23,42,0.92);color:#f8fafc;padding:8px 14px;border-radius:10px;' +
        'font:600 12px system-ui;box-shadow:0 8px 24px rgba(0,0,0,0.35);max-width:340px;' +
        'border:1px solid rgba(59,130,246,0.4);';
      document.body.appendChild(bar);
    }
    return bar;
  }
  function setStatus(message, kind) {
    try {
      const bar = ensureStatusBar();
      const color = kind === 'ok' ? '#34d399' : (kind === 'err' ? '#f87171' : '#60a5fa');
      bar.style.borderColor = color;
      bar.innerHTML = '⚡ Archon CRM: <span style="color:' + color + '">' + message + '</span>';
    } catch (e) {}
  }

  // Wait until LinkedIn has rendered the profile data (SPA), polling with
  // backoff, then run initCheck once. This fixes profiles that render slowly.
  function waitForProfileAndInit(maxAttempts) {
    let attempts = 0;
    const tryOnce = () => {
      const p = extractProfileData();
      if (p && p.name) {
        initCheck(true);
        return;
      }
      attempts++;
      if (attempts < maxAttempts) {
        setTimeout(tryOnce, 800 + attempts * 200);
      } else {
        setStatus('Profil-Daten nicht gefunden - Seite neu laden?', 'err');
      }
    };
    setTimeout(tryOnce, 500);
  }

  // Run on page load & watch for SPA route changes
  function observerRouteChanges() {
    waitForProfileAndInit(25);

    let lastUrl = window.location.href;
    const observer = new MutationObserver(() => {
      if (window.location.href !== lastUrl) {
        lastUrl = window.location.href;
        if (window.location.href.includes('/in/')) {
          setTimeout(() => waitForProfileAndInit(25), 300);
        } else if (widgetContainer) {
          widgetContainer.remove();
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Auto-save contact info once a "Contact info" modal appears.
    // The modal loads its content with a slight delay, so we POLL until data
    // is actually found (up to ~6s) instead of scanning once too early.
    let handledModalUrl = '';
    let modalSaveInFlight = false;
    let modalPollActive = false;
    function trySaveModalContactInfo(finalAttempt) {
      // Stop polling once the modal is closed again.
      if (!findContactModal()) return;
      const contactInfo = extractContactInfo();
      const any = contactInfo.email || contactInfo.telefon_1 || contactInfo.webseite || contactInfo.adresse;
      if (any) {
        handledModalUrl = window.location.href;
        modalSaveInFlight = true;
        autoSave(true).finally(() => { modalSaveInFlight = false; });
        return;
      }
      if (!finalAttempt) setTimeout(() => trySaveModalContactInfo(false), 900);
      // else: gave up after several polls (modal might just not contain data)
    }
    const modalObserver = new MutationObserver(() => {
      if (!window.location.href.includes('/in/')) return;
      if (modalSaveInFlight || modalPollActive) return;
      // Only react when a contact-info modal is actually present
      const modal = findContactModal();
      if (modal && handledModalUrl !== window.location.href) {
        // poll a few times to let modal content render
        modalPollActive = true;
        trySaveModalContactInfo(false);
        setTimeout(() => {
          if (!modalSaveInFlight) trySaveModalContactInfo(true);
          modalPollActive = false;
        }, 5000);
      }
    });
    modalObserver.observe(document.body, { childList: true, subtree: true });
  }

  // Respond to popup requests for the current profile data
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.action === 'GET_DOM_PROFILE') {
      const p = extractProfileData();
      sendResponse({ profile: p });
      return true;
    }
    return false;
  });

  // Initial execution after DOM load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', observerRouteChanges);
  } else {
    setTimeout(observerRouteChanges, 800);
  }
})();
