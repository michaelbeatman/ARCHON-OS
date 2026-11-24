// D06/HIGH: aktiviert alle 9 versionierten Archon-Workflows und registriert
// ihre Webhooks. Die Liste ist die SSOT aus
// scripts/n8n_routine_workflows.json + scripts/n8n_workflows_bundle.json.
// Fremde Webhook-Registrierungen werden nicht ueberschrieben (N2).
const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');

const workflows = [
  { workflowId: 'b1c3f1e9b2d84f11', webhookPath: 'archon-morning-briefing', method: 'POST', node: 'Webhook On-Demand' },
  { workflowId: 'b1c3f1e9b2d84f12', webhookPath: 'archon-weekly-audit',    method: 'POST', node: 'Webhook On-Demand' },
  { workflowId: 'b1c3f1e9b2d84f13', webhookPath: 'archon-rss-watchdog',    method: 'POST', node: 'Webhook On-Demand' },
  { workflowId: 'b1c3f1e9b2d84f01', webhookPath: 'archon-extract-article', method: 'POST', node: 'Webhook Ingest' },
  { workflowId: 'b1c3f1e9b2d84f02', webhookPath: 'archon-dispatch-message', method: 'POST', node: 'Webhook Ingest' },
  { workflowId: 'b1c3f1e9b2d84f03', webhookPath: 'archon-render-document', method: 'POST', node: 'Webhook Ingest' },
  { workflowId: 'b1c3f1e9b2d84f04', webhookPath: 'archon-search-feed',     method: 'POST', node: 'Webhook Ingest' },
  { workflowId: 'b1c3f1e9b2d84f05', webhookPath: 'archon-sync-crm',        method: 'POST', node: 'Webhook Ingest' },
  { workflowId: 'a7c3f1e9b2d84f6a', webhookPath: 'archon-execution',       method: 'POST', node: 'Webhook Ingest' },
];

db.serialize(() => {
  const ids = workflows.map(w => `'${w.workflowId}'`).join(', ');
  db.run(`
    UPDATE workflow_entity
    SET active = 1,
        activeVersionId = versionId,
        triggerCount = 2
    WHERE id IN (${ids})
  `, function (err) {
    if (err) console.error('Fehler beim Aktivieren der Workflows:', err);
    else console.log(`[OK] ${this.changes} Workflows aktiviert (active=1).`);
  });

  workflows.forEach(wh => {
    db.get(
      `SELECT workflowId FROM webhook_entity WHERE webhookPath = ? LIMIT 1`,
      [wh.webhookPath],
      (selErr, existing) => {
        if (selErr) {
          console.error(`Error checking webhook ${wh.webhookPath}:`, selErr);
          return;
        }
        if (existing && existing.workflowId !== wh.workflowId) {
          console.warn(`[SKIP] Webhook ${wh.webhookPath} gehoert zu ${existing.workflowId} — nicht ueberschrieben.`);
          return;
        }
        db.run(`
          INSERT OR REPLACE INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength)
          VALUES (?, ?, ?, ?, ?, ?)
        `, [wh.workflowId, wh.webhookPath, wh.method, wh.node, wh.webhookPath, wh.webhookPath.length], function (err) {
          if (err) console.error(`Error inserting webhook ${wh.webhookPath}:`, err);
          else console.log(`[OK] Registered webhook: ${wh.method} ${wh.webhookPath}`);
        });
      }
    );
  });

  db.all('SELECT * FROM webhook_entity', (err, rows) => {
    if (err) console.error(err);
    else {
      console.log('\n--- ALL REGISTERED WEBHOOKS IN N8N ---');
      rows.forEach(r => console.log(`${r.method} /webhook/${r.webhookPath} -> Workflow: ${r.workflowId} (${r.node})`));
    }
    db.close();
  });
});
