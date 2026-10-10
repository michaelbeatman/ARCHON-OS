/**
 * Archon CRM - Automated LinkedIn Data Importer Script
 * 
 * Imports LinkedIn export CSVs (Connections.csv, Invitations.csv, messages.csv)
 * directly into PocketBase collection 'kontakte'.
 * 
 * Usage:
 *   node scripts/import_linkedin.js
 */

const fs = require('fs');
const path = require('path');

const POCKETBASE_URL = process.env.POCKETBASE_URL || 'http://localhost:8090';

// Locate LinkedIn Backup Folder
function findLinkedInFolder() {
  const customArg = process.argv[2];
  if (customArg && fs.existsSync(customArg) && fs.existsSync(path.join(customArg, 'Connections.csv'))) {
    return customArg;
  }

  const candidates = [
    'C:/.Antigravity-projekte/AgenticOS-2026/LinkedIn-backup',
    'C:/Users/micha/OneDrive/Desktop/LinkedIn-Backup',
    'C:/Users/micha/Desktop/LinkedIn-Backup',
    path.join(__dirname, '../LinkedIn-backup'),
    path.join(__dirname, '../LinkedIn-Backup'),
    path.join(__dirname, './LinkedIn-backup'),
    './LinkedIn-backup'
  ];

  for (const dir of candidates) {
    if (fs.existsSync(dir) && fs.existsSync(path.join(dir, 'Connections.csv'))) {
      return dir;
    }
  }
  throw new Error('LinkedIn-Backup folder with Connections.csv not found in candidate paths.');
}

// Robust CSV Parser supporting multiline double-quoted fields
function parseCSV(text) {
  // Strip BOM if present
  if (text.charCodeAt(0) === 0xFEFF) {
    text = text.slice(1);
  }
  const rows = [];
  let row = [];
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

// Convert various date formats to ISO Date (YYYY-MM-DD)
function parseISODate(dateStr) {
  if (!dateStr || !dateStr.trim()) return '';
  const str = dateStr.trim();

  // Try standard Date parse
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    return d.toISOString().split('T')[0];
  }

  // Handle formats like "29 Jul 2026" or "7/29/26, 3:12 AM"
  const monthMap = {
    jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06',
    jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12'
  };

  const parts = str.split(/\s+|,/);
  if (parts.length >= 3) {
    const day = parts[0].padStart(2, '0');
    const month = monthMap[parts[1].substring(0, 3).toLowerCase()];
    const year = parts[2];
    if (month && year) return `${year}-${month}-${day}`;
  }

  return '';
}

// Format message timestamp to YYYY-MM-DD HH:mm
function parseMessageDate(dateStr) {
  if (!dateStr || !dateStr.trim()) return '';
  const d = new Date(dateStr.trim());
  if (!isNaN(d.getTime())) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${mins}`;
  }
  return dateStr.trim();
}

// Helper: Normalize URL for matching
function normalizeUrl(url) {
  if (!url) return '';
  let u = url.trim().toLowerCase();
  if (u.endsWith('/')) u = u.slice(0, -1);
  return u;
}

async function main() {
  console.log('🚀 Starting LinkedIn Data Export Import into PocketBase CRM...');

  const dataDir = findLinkedInFolder();
  console.log(`📁 Found LinkedIn Backup directory: ${dataDir}`);

  // -------------------------------------------------------------
  // STEP 1: PARSE MESSAGES.CSV (Build chat history map by profile URL / name)
  // -------------------------------------------------------------
  console.log('\n💬 Step 1: Reading & parsing messages.csv...');
  const messagesMap = new Map(); // key: normalized URL or lower name -> array of message items

  if (fs.existsSync(path.join(dataDir, 'messages.csv'))) {
    const msgContent = fs.readFileSync(path.join(dataDir, 'messages.csv'), 'utf-8');
    const msgRows = parseCSV(msgContent);
    const msgHeader = msgRows[0] || [];

    // Columns: "CONVERSATION ID","CONVERSATION TITLE","FROM","SENDER PROFILE URL","TO","RECIPIENT PROFILE URLS","DATE","SUBJECT","CONTENT","FOLDER","ATTACHMENTS"
    const fromIdx = msgHeader.findIndex(h => h.includes('FROM'));
    const fromUrlIdx = msgHeader.findIndex(h => h.includes('SENDER PROFILE URL'));
    const toIdx = msgHeader.findIndex(h => h.includes('TO'));
    const toUrlIdx = msgHeader.findIndex(h => h.includes('RECIPIENT PROFILE URLS'));
    const dateIdx = msgHeader.findIndex(h => h.includes('DATE'));
    const contentIdx = msgHeader.findIndex(h => h.includes('CONTENT'));

    msgRows.slice(1).forEach(r => {
      const fromName = r[fromIdx] || '';
      const fromUrl = normalizeUrl(r[fromUrlIdx]);
      const toName = r[toIdx] || '';
      const toUrl = normalizeUrl(r[toUrlIdx]);
      const dateRaw = r[dateIdx] || '';
      const text = r[contentIdx] || '';

      if (!text.trim()) return;

      const isUserSender = fromUrl.includes('michael-keller') || fromName.includes('Michael Keller');
      const targetUrl = isUserSender ? toUrl : fromUrl;
      const targetName = isUserSender ? toName : fromName;
      const senderLabel = isUserSender ? 'Ich' : (fromName || 'Kontakt');

      const msgObj = {
        date: parseMessageDate(dateRaw),
        sender: senderLabel,
        text: text.trim()
      };

      if (targetUrl) {
        if (!messagesMap.has(targetUrl)) messagesMap.set(targetUrl, []);
        messagesMap.get(targetUrl).push(msgObj);
      }
      if (targetName) {
        const keyName = targetName.trim().toLowerCase();
        if (!messagesMap.has(keyName)) messagesMap.set(keyName, []);
        messagesMap.get(keyName).push(msgObj);
      }
    });

    // Sort messages in each conversation chronologically
    messagesMap.forEach((msgList) => {
      msgList.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    });

    console.log(`✅ Parsed ${msgRows.length - 1} messages mapped across ${messagesMap.size} conversation targets.`);
  }

  // -------------------------------------------------------------
  // STEP 2: PARSE CONNECTIONS.CSV
  // -------------------------------------------------------------
  console.log('\n🤝 Step 2: Reading & parsing Connections.csv...');
  const connContent = fs.readFileSync(path.join(dataDir, 'Connections.csv'), 'utf-8');
  const connRows = parseCSV(connContent);

  // Find start of header
  const headerIdx = connRows.findIndex(r => r[0] && r[0].includes('First Name'));
  if (headerIdx < 0) throw new Error('First Name header row not found in Connections.csv');

  const contactsToImport = [];

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

    // Retrieve chat history if available
    let history = messagesMap.get(normUrl) || messagesMap.get(name.toLowerCase()) || [];

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

  console.log(`✅ Mapped ${contactsToImport.length} contacts from Connections.csv.`);

  // -------------------------------------------------------------
  // STEP 3: PARSE INVITATIONS.CSV (Add withdrawn/pending invites not in Connections)
  // -------------------------------------------------------------
  console.log('\n📩 Step 3: Checking Invitations.csv for withdrawn/unconnected invitations...');
  if (fs.existsSync(path.join(dataDir, 'Invitations.csv'))) {
    const invContent = fs.readFileSync(path.join(dataDir, 'Invitations.csv'), 'utf-8');
    const invRows = parseCSV(invContent);

    const existingUrls = new Set(contactsToImport.map(c => normalizeUrl(c.linkedin_url)));

    let invAdded = 0;
    invRows.slice(1).forEach(r => {
      const fromName = r[0] || '';
      const toName = r[1] || '';
      const sentAt = r[2] || '';
      const inviterUrl = normalizeUrl(r[5]);
      const inviteeUrl = normalizeUrl(r[6]);

      const isUserSender = inviterUrl.includes('michael-keller') || fromName.includes('Michael Keller');
      const targetUrl = isUserSender ? inviteeUrl : inviterUrl;
      const targetName = isUserSender ? toName : fromName;

      if (!targetUrl || existingUrls.has(targetUrl)) return;

      const normName = targetName.trim();
      if (!normName) return;

      existingUrls.add(targetUrl);

      let history = messagesMap.get(targetUrl) || messagesMap.get(normName.toLowerCase()) || [];

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

      invAdded++;
    });

    console.log(`✅ Added ${invAdded} withdrawn/unconnected invitation contacts with status 'Gesperrt_1Jahr'.`);
  }

  // -------------------------------------------------------------
  // STEP 4: DEDUPLICATION & POCKETBASE UPSERT
  // -------------------------------------------------------------
  console.log(`\n💾 Step 4: Upserting ${contactsToImport.length} contacts into PocketBase...`);

  // Fetch all existing records from PocketBase for deduplication across all pages
  const existingRecords = [];
  let page = 1;
  let totalPages = 1;
  while (page <= totalPages) {
    const existingRes = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records?page=${page}&perPage=500`);
    const existingData = await existingRes.json();
    if (existingData.items && existingData.items.length > 0) {
      existingRecords.push(...existingData.items);
    }
    totalPages = existingData.totalPages || 1;
    page++;
  }

  const dbUrlMap = new Map();
  const dbNameCompanyMap = new Map();

  existingRecords.forEach(r => {
    if (r.linkedin_url) dbUrlMap.set(normalizeUrl(r.linkedin_url), r);
    const key = `${(r.name || '').trim().toLowerCase()}_${(r.unternehmen || '').trim().toLowerCase()}`;
    dbNameCompanyMap.set(key, r);
  });

  console.log(`🔍 Database currently contains ${existingRecords.length} existing contacts.`);

  let createdCount = 0;
  let updatedCount = 0;
  const processedRecords = []; // Keep track for image scraper step

  for (let i = 0; i < contactsToImport.length; i++) {
    const item = contactsToImport[i];
    const normUrl = normalizeUrl(item.linkedin_url);
    const nameCompanyKey = `${item.name.toLowerCase()}_${item.unternehmen.toLowerCase()}`;

    let match = dbUrlMap.get(normUrl) || dbNameCompanyMap.get(nameCompanyKey);

    if (match) {
      // Update existing record
      let newStatus = match.status || item.status;
      let newEinladungZurueckgezogenAm = match.einladung_zurueckgezogen_am;

      // If contact is an active connection from Connections.csv, ensure they are not wrongly in Gesperrt or Unvernetzt
      // Note: Do NOT touch 'Irrelevant' - manual user classification is strictly preserved.
      if (item.isConnection) {
        if (!match.status || match.status === 'Gesperrt_1Jahr' || match.status === 'Unvernetzt') {
          newStatus = 'Vernetzt';
          newEinladungZurueckgezogenAm = ''; // Clear withdrawn/blocked date if connected
        }
      }

      const mergedTags = Array.from(new Set([...(match.tags || []), ...item.tags]));
      const updatePayload = {
        name: item.name || match.name,
        unternehmen: item.unternehmen || match.unternehmen,
        rolle: item.rolle || match.rolle,
        linkedin_url: item.linkedin_url || match.linkedin_url,
        email: item.email || match.email,
        vernetzt_am: item.vernetzt_am || match.vernetzt_am,
        einladung_zurueckgezogen_am: newEinladungZurueckgezogenAm,
        status: newStatus,
        tags: mergedTags,
        nachrichtenverlauf: item.nachrichtenverlauf || match.nachrichtenverlauf
      };

      const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records/${match.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatePayload)
      });
      const resData = await res.json();
      processedRecords.push(resData);
      updatedCount++;
    } else {
      // Insert new record (clean temporary flags like isConnection)
      const { isConnection, ...insertPayload } = item;
      const res = await fetch(`${POCKETBASE_URL}/api/collections/kontakte/records`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(insertPayload)
      });
      const resData = await res.json();
      processedRecords.push(resData);
      createdCount++;
    }

    if ((i + 1) % 50 === 0 || i === contactsToImport.length - 1) {
      console.log(`   Processed ${i + 1}/${contactsToImport.length} contacts... (${createdCount} created, ${updatedCount} updated)`);
    }
  }

  console.log(`\n🎉 Step 4 Complete: ${createdCount} created, ${updatedCount} updated in PocketBase.`);

  // -------------------------------------------------------------
  // STEP 5: PROFILBILD SCRAPING SKIPPED (USER DIRECTIVE)
  // -------------------------------------------------------------
  console.log('\n⏭️ Step 5: Profilbild-Scraping übersprungen (auf Wunsch des Nutzers zur Vermeidung von LinkedIn-Sperren).');

  console.log(`\n✨ LinkedIn Data Import Complete!`);
  console.log(`📊 Summary:`);
  console.log(`   - Total Processed Contacts: ${processedRecords.length}`);
  console.log(`   - New Records Created:      ${createdCount}`);
  console.log(`   - Existing Records Updated: ${updatedCount}`);
}

main().catch(err => {
  console.error('❌ LinkedIn Import Script Error:', err);
  process.exit(1);
});
