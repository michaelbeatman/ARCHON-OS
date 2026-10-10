import { NextRequest, NextResponse } from 'next/server';

const POCKETBASE_URL = process.env.INTERNAL_POCKETBASE_URL || process.env.POCKETBASE_URL || 'http://pocketbase:8090';

// Robust CSV Parser supporting multiline double-quoted fields
function parseCSV(text: string): string[][] {
  if (text.charCodeAt(0) === 0xfeff) {
    text = text.slice(1);
  }
  const rows: string[][] = [];
  let row: string[] = [];
  let cur = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (inQuotes && text[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (c === ',' && !inQuotes) {
      row.push(cur);
      cur = '';
    } else if ((c === '\n' || c === '\r') && !inQuotes) {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cur);
      cur = '';
      if (row.some(x => x.trim())) rows.push(row);
      row = [];
    } else {
      cur += c;
    }
  }
  if (cur || row.length) {
    row.push(cur);
    if (row.some(x => x.trim())) rows.push(row);
  }
  return rows;
}

function parseISODate(dateStr: string): string {
  if (!dateStr || !dateStr.trim()) return '';
  const str = dateStr.trim();
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    return d.toISOString().split('T')[0];
  }
  const monthMap: Record<string, string> = {
    jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06',
    jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12'
  };
  const parts = str.split(/\s+|,/);
  if (parts.length >= 3) {
    const day = parts[0].padStart(2, '0');
    const month = monthMap[parts[1].toLowerCase().slice(0, 3)] || '01';
    const year = parts[2].length === 2 ? `20${parts[2]}` : parts[2];
    return `${year}-${month}-${day}`;
  }
  return '';
}

function parseMessageDate(dateStr: string): string {
  if (!dateStr || !dateStr.trim()) return '';
  const str = dateStr.trim();
  const d = new Date(str);
  if (isNaN(d.getTime())) return str;
  try {
    const parts = new Intl.DateTimeFormat('de-DE', {
      timeZone: 'Europe/Berlin',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).formatToParts(d);
    const m: Record<string, string> = {};
    parts.forEach(p => { m[p.type] = p.value; });
    return `${m.year}-${m.month}-${m.day} ${m.hour}:${m.minute}`;
  } catch {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  }
}

function normalizeText(text?: string): string {
  if (!text) return '';
  return String(text)
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/[\u00a0\u200B-\u200D\uFEFF]/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function parseTs(dStr?: string): number {
  if (!dStr) return 0;
  const s = String(dStr).trim();
  let d = new Date(s);
  if (!isNaN(d.getTime())) return d.getTime();
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) {
    d = new Date(s.replace(' ', 'T'));
    if (!isNaN(d.getTime())) return d.getTime();
  }
  return 0;
}

function isUserSender(s?: string): boolean {
  if (!s) return false;
  const lower = s.trim().toLowerCase();
  return lower === 'ich' || lower === 'user' || lower === 'me' || lower.includes('michael keller');
}

function isSameSender(senderA?: string, senderB?: string): boolean {
  const isUserA = isUserSender(senderA);
  const isUserB = isUserSender(senderB);
  if (isUserA && isUserB) return true;
  if (isUserA !== isUserB) return false;
  return true;
}

function mergeDuplicateMessages(a: any, b: any): any {
  const timeA = parseTs(a.date || a.timestamp || a.time);
  const timeB = parseTs(b.date || b.timestamp || b.time);

  const base = timeA >= timeB ? { ...b, ...a } : { ...a, ...b };

  const senders = [a.sender, b.sender].filter(Boolean);
  let bestSender = base.sender;
  for (const s of senders) {
    if (s === 'Ich') {
      bestSender = 'Ich';
      break;
    }
    if (s !== 'user' && s !== 'contact' && s !== 'kontakt') {
      bestSender = s;
    }
  }

  const dateA = a.date || a.timestamp || '';
  const dateB = b.date || b.timestamp || '';
  let bestDate = base.date || base.timestamp;
  if (timeA > timeB) {
    bestDate = dateA;
  } else if (timeB > timeA) {
    bestDate = dateB;
  }

  return {
    ...base,
    sender: bestSender,
    date: bestDate
  };
}

function dedupeMessages(messages: any[]): any[] {
  if (!Array.isArray(messages) || messages.length <= 1) {
    return Array.isArray(messages) ? messages : [];
  }

  const sorted = [...messages].sort((a, b) => {
    return parseTs(a.date || a.timestamp || a.time) - parseTs(b.date || b.timestamp || b.time);
  });

  const result: any[] = [];

  for (const current of sorted) {
    const curText = normalizeText(current.text);
    if (!curText) continue;

    const curTime = parseTs(current.date || current.timestamp || current.time);
    let isDup = false;

    for (let j = 0; j < result.length; j++) {
      const existing = result[j];
      const exText = normalizeText(existing.text);
      if (curText !== exText) continue;

      if (!isSameSender(current.sender, existing.sender)) continue;

      const exTime = parseTs(existing.date || existing.timestamp || existing.time);
      const diffHours = (curTime && exTime) ? Math.abs(curTime - exTime) / (1000 * 60 * 60) : 0;

      if (diffHours <= 4 || !curTime || !exTime) {
        isDup = true;
        result[j] = mergeDuplicateMessages(existing, current);
        break;
      }
    }

    if (!isDup) {
      result.push(current);
    }
  }

  return result;
}


function normalizeUrl(url?: string): string {
  if (!url) return '';
  return url.trim().toLowerCase().replace(/\/+$/, '');
}

export async function POST(request: NextRequest) {
  try {
    const contentType = request.headers.get('content-type') || '';
    if (!contentType.includes('multipart/form-data')) {
      return NextResponse.json(
        { error: 'Anfrage muss multipart/form-data mit den 3 Dateien enthalten.' },
        { status: 400 }
      );
    }

    const formData = await request.formData();
    const connectionsFile = formData.get('connections') as File | null;
    const invitationsFile = formData.get('invitations') as File | null;
    const messagesFile = formData.get('messages') as File | null;

    if (!connectionsFile || !invitationsFile || !messagesFile) {
      return NextResponse.json(
        { error: 'Alle 3 Dateien (Connections.csv, Invitations.csv, messages.csv) werden benötigt.' },
        { status: 400 }
      );
    }

    const [connText, invText, msgText] = await Promise.all([
      connectionsFile.text(),
      invitationsFile.text(),
      messagesFile.text(),
    ]);

    // -------------------------------------------------------------
    // STEP 1: PARSE MESSAGES.CSV
    // -------------------------------------------------------------
    const msgRows = parseCSV(msgText);
    const messagesMap = new Map<string, Array<{ date: string; sender: string; text: string }>>();

    for (let i = 1; i < msgRows.length; i++) {
      const r = msgRows[i];
      const fromName = r[2] || '';
      const fromUrl = normalizeUrl(r[3]);
      const toName = r[4] || '';
      const toUrls = (r[5] || '').split(';').map(u => normalizeUrl(u)).filter(Boolean);
      const dateRaw = r[6] || '';
      const text = r[8] || '';

      if (!text.trim()) continue;

      const isUserSender = fromUrl.includes('michael-keller') || fromName.toLowerCase().includes('michael keller');
      const targetUrl = isUserSender ? (toUrls[0] || '') : fromUrl;
      const targetName = isUserSender ? toName : fromName;
      const senderLabel = isUserSender ? 'Ich' : (fromName || 'Kontakt');

      const msgObj = {
        date: parseMessageDate(dateRaw),
        sender: senderLabel,
        text: text.trim()
      };

      if (targetUrl) {
        if (!messagesMap.has(targetUrl)) messagesMap.set(targetUrl, []);
        messagesMap.get(targetUrl)!.push(msgObj);
      }
      if (targetName) {
        const keyName = targetName.trim().toLowerCase();
        if (!messagesMap.has(keyName)) messagesMap.set(keyName, []);
        messagesMap.get(keyName)!.push(msgObj);
      }
    }

    messagesMap.forEach((msgList, key) => {
      messagesMap.set(key, dedupeMessages(msgList));
    });

    // -------------------------------------------------------------
    // STEP 2: PARSE CONNECTIONS.CSV
    // -------------------------------------------------------------
    const connRows = parseCSV(connText);
    const headerIdx = connRows.findIndex(r => r[0] && (r[0].includes('First Name') || r[0].includes('Vorname')));
    if (headerIdx < 0) {
      return NextResponse.json({ error: 'Kopfzeile (First Name/Vorname) in Connections.csv nicht gefunden.' }, { status: 400 });
    }

    interface ContactCandidate {
      name: string;
      unternehmen: string;
      rolle: string;
      linkedin_url: string;
      email: string;
      vernetzt_am?: string;
      status: string;
      isConnection?: boolean;
      tags: string[];
      nachrichtenverlauf: any;
      einladung_zurueckgezogen_am?: string;
    }

    const contactsToImport: ContactCandidate[] = [];

    for (let i = headerIdx + 1; i < connRows.length; i++) {
      const r = connRows[i];
      const firstName = r[0] || '';
      const lastName = r[1] || '';
      const url = r[2] || '';
      const email = r[3] || '';
      const company = r[4] || '';
      const position = r[5] || '';
      const connectedOn = r[6] || '';

      const name = `${firstName} ${lastName}`.trim();
      if (!name) continue;

      const normUrl = normalizeUrl(url);
      const history = messagesMap.get(normUrl) || messagesMap.get(name.toLowerCase()) || [];

      contactsToImport.push({
        name,
        unternehmen: company.trim(),
        rolle: position.trim(),
        linkedin_url: url.trim(),
        email: email.trim(),
        vernetzt_am: parseISODate(connectedOn),
        status: 'Vernetzt',
        isConnection: true,
        tags: ['LinkedIn Import'],
        nachrichtenverlauf: history.length > 0 ? history : null
      });
    }

    // -------------------------------------------------------------
    // STEP 3: PARSE INVITATIONS.CSV
    // -------------------------------------------------------------
    const invRows = parseCSV(invText);
    const existingUrls = new Set(contactsToImport.map(c => normalizeUrl(c.linkedin_url)));

    invRows.slice(1).forEach(r => {
      const fromName = r[0] || '';
      const toName = r[1] || '';
      const sentAt = r[2] || '';
      const inviterUrl = normalizeUrl(r[5]);
      const inviteeUrl = normalizeUrl(r[6]);

      const isUserSender = inviterUrl.includes('michael-keller') || fromName.toLowerCase().includes('michael keller');
      const targetUrl = isUserSender ? inviteeUrl : inviterUrl;
      const targetName = isUserSender ? toName : fromName;

      if (!targetUrl || existingUrls.has(targetUrl)) return;
      const normName = targetName.trim();
      if (!normName) return;

      existingUrls.add(targetUrl);
      const history = messagesMap.get(targetUrl) || messagesMap.get(normName.toLowerCase()) || [];

      contactsToImport.push({
        name: normName,
        unternehmen: '',
        rolle: '',
        linkedin_url: targetUrl,
        email: '',
        status: 'Gesperrt_1Jahr',
        einladung_zurueckgezogen_am: parseISODate(sentAt),
        tags: ['LinkedIn Import'],
        nachrichtenverlauf: history.length > 0 ? history : null
      });
    });

    // -------------------------------------------------------------
    // STEP 4: FETCH EXISTING POCKETBASE RECORDS
    // -------------------------------------------------------------
    const existingRecords: any[] = [];
    let page = 1;
    let totalPages = 1;
    while (page <= totalPages) {
      const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records?page=${page}&perPage=500`, {
        headers: { 'Cache-Control': 'no-cache' }
      });
      if (!res.ok) break;
      const data = await res.json();
      if (data.items && data.items.length > 0) {
        existingRecords.push(...data.items);
      }
      totalPages = data.totalPages || 1;
      page++;
    }

    const dbUrlMap = new Map<string, any>();
    const dbNameCompanyMap = new Map<string, any>();
    const dbNameMap = new Map<string, any>();

    existingRecords.forEach(r => {
      if (r.linkedin_url) dbUrlMap.set(normalizeUrl(r.linkedin_url), r);
      const key = `${(r.name || '').trim().toLowerCase()}_${(r.unternehmen || '').trim().toLowerCase()}`;
      dbNameCompanyMap.set(key, r);
      if (r.name && r.name.trim()) dbNameMap.set(r.name.trim().toLowerCase(), r);
    });

    let createdCount = 0;
    let updatedCount = 0;

    for (let i = 0; i < contactsToImport.length; i++) {
      const item = contactsToImport[i];
      if (!item.name || !item.name.trim() || item.name.trim() === 'Ohne Namen') continue;

      const normUrl = normalizeUrl(item.linkedin_url);
      const nameCompanyKey = `${item.name.toLowerCase().trim()}_${item.unternehmen.toLowerCase().trim()}`;
      const nameKey = item.name.toLowerCase().trim();

      const match = (normUrl ? dbUrlMap.get(normUrl) : null) || dbNameCompanyMap.get(nameCompanyKey) || dbNameMap.get(nameKey);

      if (match) {
        let newStatus = match.status || item.status;
        let newEinladungZurueckgezogenAm = match.einladung_zurueckgezogen_am;

        if (item.isConnection) {
          if (!match.status || match.status === 'Gesperrt_1Jahr' || match.status === 'Unvernetzt') {
            newStatus = 'Vernetzt';
            newEinladungZurueckgezogenAm = '';
          }
        } else {
          // If this is an invitation, never downgrade a connected or pipeline contact to Gesperrt_1Jahr
          if (match.status && match.status !== 'Gesperrt_1Jahr') {
            newStatus = match.status;
          }
        }

        const mergedTags = Array.from(new Set([...(match.tags || []), ...item.tags]));
        const updatePayload: Record<string, any> = {
          name: item.name || match.name,
          unternehmen: item.unternehmen || match.unternehmen,
          rolle: item.rolle || match.rolle,
          linkedin_url: item.linkedin_url || match.linkedin_url,
          email: item.email || match.email,
          vernetzt_am: item.vernetzt_am || match.vernetzt_am,
          einladung_zurueckgezogen_am: newEinladungZurueckgezogenAm,
          status: newStatus,
          tags: mergedTags
        };

        if (Array.isArray(match.nachrichtenverlauf) && match.nachrichtenverlauf.length > 0) {
          const combined = [...match.nachrichtenverlauf, ...(item.nachrichtenverlauf || [])];
          const deduped = dedupeMessages(combined);
          if (JSON.stringify(deduped) !== JSON.stringify(match.nachrichtenverlauf)) {
            updatePayload.nachrichtenverlauf = deduped;
          }
        } else if (item.nachrichtenverlauf && item.nachrichtenverlauf.length > 0) {
          updatePayload.nachrichtenverlauf = dedupeMessages(item.nachrichtenverlauf);
        }

        const patchRes = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records/${match.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updatePayload)
        });
        if (patchRes.ok) {
          updatedCount++;
          Object.assign(match, updatePayload);
        }
      } else {
        const { isConnection, ...insertPayload } = item;
        const postRes = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(insertPayload)
        });
        if (postRes.ok) {
          createdCount++;
          const newRecord = await postRes.json();
          if (normUrl) dbUrlMap.set(normUrl, newRecord);
          dbNameCompanyMap.set(nameCompanyKey, newRecord);
          dbNameMap.set(nameKey, newRecord);
        }
      }
    }

    return NextResponse.json({
      success: true,
      totalContactsMapped: contactsToImport.length,
      createdCount,
      updatedCount,
      totalExistingContacts: existingRecords.length
    });

  } catch (error: any) {
    console.error('LinkedIn-Import API Fehler:', error);
    return NextResponse.json({ error: error.message || 'Interner Serverfehler beim Importieren.' }, { status: 500 });
  }
}
