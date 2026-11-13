const fs = require('fs');
const path = require('path');

const indexHtmlPath = path.join(__dirname, '..', 'static', 'index.html');
const html = fs.readFileSync(indexHtmlPath, 'utf8');

// Check duplicate variable or function declarations in the script
const scriptMatches = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
const mainScript = scriptMatches[scriptMatches.length - 1][1];

// Find all let / const / var / function top-level declarations
const lines = mainScript.split('\n');
const declared = new Map();

lines.forEach((line, idx) => {
  const letConstMatch = line.match(/^\s*(?:let|const|var)\s+([a-zA-Z0-9_]+)\s*=/);
  if (letConstMatch) {
    const name = letConstMatch[1];
    if (declared.has(name)) {
      console.log(`DUPLICATE VARIABLE DECLARATION: '${name}' on line ${idx + 1} (previous on line ${declared.get(name)})`);
    } else {
      declared.set(name, idx + 1);
    }
  }
});
