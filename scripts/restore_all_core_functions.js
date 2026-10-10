const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');

const baseDir = __dirname ? path.dirname(__dirname) : process.cwd();
const indexHtmlPath = path.join(baseDir, 'static', 'index.html');

console.log('Restoring from HEAD for', indexHtmlPath);

const headContent = execSync('git show HEAD:static/index.html', { cwd: baseDir, maxBuffer: 15 * 1024 * 1024 }).toString('utf8');
const currentContent = fs.readFileSync(indexHtmlPath, 'utf8');

const startMarker = 'function handleSidebarPresetSelected';
const endMarker = 'function updateCardBackground';

const startIdx = headContent.indexOf(startMarker);
const endIdx = headContent.indexOf(endMarker);
const endOfLastFn = headContent.indexOf('    }', endIdx) + 5;

const headBlock = headContent.substring(startIdx, endOfLastFn);

const overlappingFns = [
  'resetRolesToDefault',
  'loadRolesFromServer',
  'loadModelsFromServer',
  'loadKanbanFromServer',
  'loadVaultFiles',
  'applyCustomizerSetting',
  'hexToRgba'
];

let cleanBlock = headBlock;
for (const fn of overlappingFns) {
  const regex = new RegExp('(?:async\\s+)?function\\s+' + fn + '\\s*\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n    \\}', 'g');
  cleanBlock = cleanBlock.replace(regex, `/* ${fn} preserved from current version */`);
}

const insertPos = currentContent.indexOf('function updateLogo');
let newHtml;
if (insertPos !== -1) {
  newHtml = currentContent.substring(0, insertPos) + cleanBlock + '\n\n    ' + currentContent.substring(insertPos);
} else {
  const lastScriptEnd = currentContent.lastIndexOf('</script>');
  newHtml = currentContent.substring(0, lastScriptEnd) + '\n\n' + cleanBlock + '\n\n' + currentContent.substring(lastScriptEnd);
}

fs.writeFileSync(indexHtmlPath, newHtml, 'utf8');
console.log('Successfully restored all missing core UI and navigation functions via Node.js!');
