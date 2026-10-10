const fs = require('fs');
const path = require('path');

const indexHtmlPath = path.join(__dirname, '..', 'static', 'index.html');
const html = fs.readFileSync(indexHtmlPath, 'utf8');
const scriptMatches = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
const mainScript = scriptMatches[scriptMatches.length - 1][1];

const lines = mainScript.split('\n');

let balance = 0;
let stack = [];

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  // Remove string literals and comments for brace counting
  const cleaned = line
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*/g, '')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/`(?:[^`\\]|\\.)*`/g, '``');

  for (let ch of cleaned) {
    if (ch === '{') {
      balance++;
      stack.push(i + 1);
    } else if (ch === '}') {
      balance--;
      if (stack.length > 0) stack.pop();
    }
  }
}

console.log(`Final brace balance: ${balance} (should be 0)`);
if (balance > 0) {
  console.log(`Unclosed braces opened at lines: ${stack.slice(-10).join(', ')}`);
} else if (balance < 0) {
  console.log(`Extra closing braces!`);
}
