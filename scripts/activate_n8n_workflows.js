const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');

const newWebhooks = [
  {
    workflowId: 'b1c3f1e9b2d84f11',
    webhookPath: 'archon-morning-briefing',
    method: 'POST',
    node: 'Webhook On-Demand'
  },
  {
    workflowId: 'b1c3f1e9b2d84f12',
    webhookPath: 'archon-weekly-audit',
    method: 'POST',
    node: 'Webhook On-Demand'
  },
  {
    workflowId: 'b1c3f1e9b2d84f13',
    webhookPath: 'archon-rss-watchdog',
    method: 'POST',
    node: 'Webhook On-Demand'
  }
];

db.serialize(() => {
  // Update workflow_entity
  db.run(`
    UPDATE workflow_entity
    SET active = 1,
        activeVersionId = versionId,
        triggerCount = 2
    WHERE id IN ('b1c3f1e9b2d84f11', 'b1c3f1e9b2d84f12', 'b1c3f1e9b2d84f13')
  `);

  // Insert into webhook_entity if not already present
  newWebhooks.forEach(wh => {
    db.run(`
      INSERT OR REPLACE INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength)
      VALUES (?, ?, ?, ?, ?, ?)
    `, [wh.workflowId, wh.webhookPath, wh.method, wh.node, wh.webhookPath, wh.webhookPath.length], function(err) {
      if (err) console.error(`Error inserting webhook ${wh.webhookPath}:`, err);
      else console.log(`[OK] Registered webhook: ${wh.method} ${wh.webhookPath}`);
    });
  });

  // Verify
  db.all('SELECT * FROM webhook_entity', (err, rows) => {
    if (err) console.error(err);
    else {
      console.log('\n--- ALL REGISTERED WEBHOOKS IN N8N ---');
      rows.forEach(r => console.log(`${r.method} /webhook/${r.webhookPath} -> Workflow: ${r.workflowId} (${r.node})`));
    }
    db.close();
  });
});
