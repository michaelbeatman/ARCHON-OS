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
