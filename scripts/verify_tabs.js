const fs = require('fs');
const path = require('path');

const indexHtmlPath = path.join(__dirname, '..', 'static', 'index.html');
const content = fs.readFileSync(indexHtmlPath, 'utf8');

const navTabs = [
  'mission-control', 'paperclip', 'master-chat', 'agent-profiles',
  'ai-mastermind', 'kanban', 'workspace-gallery', 'brain',
  'hermes-dashboard', 'crm'
];

let allOk = true;
navTabs.forEach(t => {
  const btnExists = content.includes("onclick=\"setTab('" + t + "')\"");
  const viewExists = content.includes('id="view-' + t + '"');
  console.log(`Tab: ${t.padEnd(20)} -> Button: ${btnExists ? 'OK' : 'MISSING'} | View: ${viewExists ? 'OK' : 'MISSING'}`);
  if (!btnExists || !viewExists) allOk = false;
});

if (allOk) {
  console.log('\nALL 10 SIDEBAR TABS AND CORRESPONDING VIEWS ARE 100% PRESENT AND MATCHED!');
}
