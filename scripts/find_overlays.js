const fs = require('fs');
const path = require('path');

const indexHtmlPath = path.join(__dirname, '..', 'static', 'index.html');
const html = fs.readFileSync(indexHtmlPath, 'utf8');

// Look for fixed/absolute elements without 'hidden' class by default
const tags = html.match(/<[a-z0-9]+[^>]*class="[^"]*(?:fixed|absolute)[^"]*"[^>]*>/gi) || [];

console.log(`Total fixed/absolute elements found: ${tags.length}`);
tags.forEach((tag, idx) => {
  const isHidden = tag.includes('hidden') || tag.includes('display: none') || tag.includes('display:none') || tag.includes('pointer-events-none');
  const isHighZ = /z-(?:[2-9][0-9]|100)/.test(tag) || tag.includes('z-50') || tag.includes('z-40') || tag.includes('z-30');
  const isFullCover = tag.includes('inset-0') || (tag.includes('top-0') && (tag.includes('left-0') || tag.includes('w-full') || tag.includes('h-full')));
  
  if (!isHidden && (isHighZ || isFullCover)) {
    console.log(`\n[POTENTIAL BLOCKING OVERLAY ${idx}]:`);
    console.log(tag);
  }
});
