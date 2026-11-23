// M6 (Audit-Lauf 5): Dieses Skript senkt CSP und Frame-Protection (DENY ->
// ALLOWALL, frame-ancestors -> *). Es ist NICHT in docker-compose.yml gemountet
// und darf nicht ausgefuehrt werden. Bewusst als described-risk dokumentiert
// statt geloescht (moeglicher Restore-/.Debug-Zweck). Nur mit explizitem Flag.
if (process.env.ARCHON_ALLOW_INSECURE_HEADER_DOWNGRADE !== 'true') {
  console.error('BLOCKED: CSP/Frame-Header-Downgrade ist nicht erlaubt.');
  console.error('Setze ARCHON_ALLOW_INSECURE_HEADER_DOWNGRADE=true nur fuer isolierte Diagnose.');
  process.exit(2);
}

const fs = require('fs');

const p = '/app/.build/next/routes-manifest.json';
if (fs.existsSync(p)) {
  let content = fs.readFileSync(p, 'utf8');
  console.log('Original routes-manifest.json length:', content.length);
  
  content = content.replaceAll('"value": "DENY"', '"value": "ALLOWALL"');
  content = content.replaceAll("frame-ancestors 'none'", "frame-ancestors *");
  content = content.replaceAll("frame-ancestors 'self'", "frame-ancestors *");
  
  fs.writeFileSync(p, content, 'utf8');
  console.log('Successfully patched routes-manifest.json!');
} else {
  console.error('File not found:', p);
}
