const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const ROOT_DIR = path.join(__dirname, '..');
const STATIC_DIR = path.join(ROOT_DIR, 'static');
const DATA_DIR = path.join(ROOT_DIR, 'data');
const OUTPUT_DIR = path.join(ROOT_DIR, 'docs', 'system', 'screenshots');

if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2'
};

function readJsonSafe(filePath, fallback) {
  try {
    if (fs.existsSync(filePath)) {
      return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    }
  } catch (e) {}
  return fallback;
}

// Local hybrid server: serves latest static/ files from disk, proxies /api/* to 127.0.0.1:8501 if running,
// and provides local JSON fallback so all views render with full data even if backend is offline or older.
function startLocalHybridServer(port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const parsedUrl = new URL(req.url, `http://127.0.0.1:${port}`);
      const pathname = parsedUrl.pathname;

      // 1. Handle /api/corporate/* directly from data/corporate_entities.json if needed
      if (pathname.startsWith('/api/corporate/companies')) {
        const corpData = readJsonSafe(path.join(DATA_DIR, 'corporate_entities.json'), {
          active_company_id: 'archon-systems',
          companies: [
            {
              id: 'archon-systems',
              name: 'Archon Systems GmbH',
              legal_form: 'GmbH',
              managing_director: 'Michael Keller',
              street: 'Innovationsallee 42',
              zip_code: '48143',
              city: 'Münster',
              country: 'Deutschland',
              email: 'kontakt@archon-systems.de',
              phone: '+49 (0) 251 987654-0',
              website: 'https://www.archon-systems.de',
              register_court: 'Amtsgericht Münster',
              register_number: 'HRB 24680',
              tax_number: '337/5812/0912',
              vat_id: 'DE348192045',
              small_business_regulation: false,
              bank_name: 'Sparkasse Münsterland Ost',
              iban: 'DE89 4005 0150 0012 3456 78',
              bic: 'WELADED1MST',
              primary_color: '#4f46e5',
              secondary_color: '#0f172a',
              font_family: 'Outfit, sans-serif',
              logo_url: '/static/archon_os_logo.png',
              invoice_prefix: 'RE-2026-',
              payment_terms_days: 14,
              footer_note: 'Es gelten unsere Allgemeinen Geschäftsbedingungen.'
            }
          ]
        });
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ status: 'ok', ...corpData }));
        return;
      }

      // 1b. Handle /api/crm/* directly from data/crm_cache.json
      if (pathname.startsWith('/api/crm/')) {
        if (pathname.startsWith('/api/crm/avatars/')) {
          const parts = pathname.replace('/api/crm/avatars/', '').split('/');
          const avatarFile = path.join(ROOT_DIR, 'pocketbase', 'pb_data', 'storage', 'pbc_1512878646', parts[0], parts[1]);
          if (fs.existsSync(avatarFile)) {
            res.writeHead(200, { 'Content-Type': 'image/png' });
            fs.createReadStream(avatarFile).pipe(res);
            return;
          }
        }
        const crmCache = readJsonSafe(path.join(DATA_DIR, 'crm_cache.json'), {});
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        if (pathname.includes('/api/crm/report')) {
          res.end(JSON.stringify(crmCache.report || { status: 'success' }));
        } else if (pathname.includes('/api/crm/calendar')) {
          res.end(JSON.stringify(crmCache.calendar || { status: 'success', events: [] }));
        } else if (pathname.includes('/api/crm/messages')) {
          res.end(JSON.stringify(crmCache.messages || { status: 'success', items: [], total: 0 }));
        } else if (pathname.match(/\/api\/crm\/contacts\/[^?]+/)) {
          res.end(JSON.stringify(crmCache.detail_first || { status: 'success' }));
        } else if (pathname.includes('/api/crm/contacts')) {
          res.end(JSON.stringify(crmCache.contacts || { status: 'success', items: [], total: 0 }));
        } else {
          res.end(JSON.stringify({ status: 'success', items: [] }));
        }
        return;
      }

      // 2. Proxy other /api/* requests to 127.0.0.1:8501, with local fallback
      if (pathname.startsWith('/api/')) {
        const proxyReq = http.request({
          hostname: '127.0.0.1',
          port: 8501,
          path: req.url,
          method: req.method,
          headers: req.headers,
          timeout: 1500
        }, (proxyRes) => {
          if (proxyRes.statusCode && proxyRes.statusCode < 500 && proxyRes.statusCode !== 404) {
            res.writeHead(proxyRes.statusCode, proxyRes.headers);
            proxyRes.pipe(res);
          } else {
            serveApiFallback(pathname, res);
          }
        });
        proxyReq.on('error', () => serveApiFallback(pathname, res));
        proxyReq.on('timeout', () => { proxyReq.destroy(); serveApiFallback(pathname, res); });
        req.pipe(proxyReq);
        return;
      }

      // 3. Serve static files from workspace
      let relPath = pathname === '/' ? '/index.html' : pathname.replace(/^\/static\//, '/');
      let filePath = path.join(STATIC_DIR, relPath);
      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        filePath = path.join(ROOT_DIR, pathname);
      }
      if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath).toLowerCase();
        res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
        fs.createReadStream(filePath).pipe(res);
      } else {
        res.writeHead(404);
        res.end('Not found');
      }
    });

    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

function serveApiFallback(pathname, res) {
  if (res.headersSent || res.writableEnded) return;
  res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
  if (pathname.includes('/profiles')) {
    const profs = readJsonSafe(path.join(DATA_DIR, 'agent_profiles.json'), []);
    res.end(JSON.stringify({ status: 'ok', profiles: profs }));
  } else if (pathname.includes('/boardroom/history')) {
    const hist = readJsonSafe(path.join(DATA_DIR, 'boardroom_history.json'), []);
    res.end(JSON.stringify({ status: 'ok', history: hist }));
  } else {
    res.end(JSON.stringify({ status: 'ok', items: [], data: [] }));
  }
}

const VIEWS_TO_CAPTURE = [
  // 9. Adressen & CRM (9.1 - 9.7)
  {
    id: "addresses_all",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("kontakte"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_network",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("kontakte"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_customers",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("kunden"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_suppliers",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("lieferanten"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_messages",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("nachrichten"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_calendar",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("kalender"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_report",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try { if (window.crmStudio) window.crmStudio.switchSubTab("bericht"); } catch(e) {}
    `,
    waitTime: 1600
  },
  {
    id: "addresses_drawer",
    actionCode: `
      try { window.setTab("addresses"); } catch(e) {}
      try {
        if (window.crmStudio) {
          window.crmStudio.openContactDrawer("i16nr1nm9dkkbcq");
        }
      } catch(e) {}
    `,
    waitTime: 2500,
    cleanupCode: `
      try {
        if (window.crmStudio) window.crmStudio.closeContactDrawer();
      } catch(e) {}
    `
  },
  // 10. Artikel & Leistungen (10.1 - 10.4)
  {
    id: "items_all",
    actionCode: `
      try { window.setTab("items"); } catch(e) {}
      try { if (typeof window.setItemsTypeFilter === 'function') window.setItemsTypeFilter("all"); } catch(e) {}
    `,
    waitTime: 1200
  },
  {
    id: "items_service",
    actionCode: `
      try { window.setTab("items"); } catch(e) {}
      try { if (typeof window.setItemsTypeFilter === 'function') window.setItemsTypeFilter("service"); } catch(e) {}
    `,
    waitTime: 1200
  },
  {
    id: "items_saas",
    actionCode: `
      try { window.setTab("items"); } catch(e) {}
      try { if (typeof window.setItemsTypeFilter === 'function') window.setItemsTypeFilter("saas"); } catch(e) {}
    `,
    waitTime: 1200
  },
  {
    id: "items_product",
    actionCode: `
      try { window.setTab("items"); } catch(e) {}
      try { if (typeof window.setItemsTypeFilter === 'function') window.setItemsTypeFilter("product"); } catch(e) {}
    `,
    waitTime: 1200
  },
  {
    id: "items_drawer",
    actionCode: `
      try { window.setTab("items"); } catch(e) {}
      try {
        if (typeof window.openErpItemDrawer === 'function') {
          window.openErpItemDrawer(null);
        }
      } catch(e) {}
    `,
    waitTime: 2000,
    cleanupCode: `
      try {
        if (typeof window.closeErpItemDrawer === 'function') window.closeErpItemDrawer();
      } catch(e) {}
    `
  },
  // 11. Vorgänge & Verträge (11.1 - 11.3)
  {
    id: "ops_erp_offers",
    actionCode: `
      try { window.setTab("operations-erp"); } catch(e) {}
      try { if (typeof window.switchErpOpsSubTab === 'function') window.switchErpOpsSubTab("offers"); } catch(e) {}
    `,
    waitTime: 1200
  },
  {
    id: "ops_erp_pipeline",
    actionCode: `
      try { window.setTab("operations-erp"); } catch(e) {}
      try { if (typeof window.switchErpOpsSubTab === 'function') window.switchErpOpsSubTab("pipeline"); } catch(e) {}
    `,
    waitTime: 1200
  },
  {
    id: "ops_erp_contracts",
    actionCode: `
      try { window.setTab("operations-erp"); } catch(e) {}
      try { if (typeof window.switchErpOpsSubTab === 'function') window.switchErpOpsSubTab("contracts"); } catch(e) {}
    `,
    waitTime: 1200
  }
];

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.id = 0;
    this.callbacks = new Map();
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (err) => reject(err);
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id && this.callbacks.has(msg.id)) {
          const { res, rej } = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) rej(msg.error);
          else res(msg.result);
        }
      };
    });
  }

  send(method, params = {}) {
    return new Promise((res, rej) => {
      const id = ++this.id;
      this.callbacks.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

async function main() {
  const SERVER_PORT = 18502;
  const CDP_PORT = 9230;
  const server = await startLocalHybridServer(SERVER_PORT);
  console.log(`Hybrid Static/API Server gestartet auf http://127.0.0.1:${SERVER_PORT}`);

  const tempUserDataDir = path.join(require('os').tmpdir(), 'chrome_cdp_missing_' + Date.now());
  console.log("Starte Chrome Headless mit CDP...");

  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    '--window-size=1600,1000',
    '--disable-gpu',
    '--no-sandbox',
    '--disable-web-security',
    '--allow-running-insecure-content',
    '--disable-extensions',
    `--user-data-dir=${tempUserDataDir}`,
    `http://127.0.0.1:${SERVER_PORT}`
  ], { detached: false });

  let pageTarget = null;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      const targets = await fetchJson(`http://127.0.0.1:${CDP_PORT}/json/list`);
      if (Array.isArray(targets) && targets.length > 0) {
        pageTarget = targets.find(t => t.type === 'page') || targets[0];
        if (pageTarget && pageTarget.webSocketDebuggerUrl) break;
      }
    } catch (e) {}
  }

  if (!pageTarget || !pageTarget.webSocketDebuggerUrl) {
    chromeProc.kill();
    server.close();
    throw new Error("Kein Page-Target in Chrome gefunden.");
  }

  const client = new CDPClient(pageTarget.webSocketDebuggerUrl);
  await client.connect();

  await client.send('Page.enable');
  await client.send('Runtime.enable');
  await client.send('Emulation.setDeviceMetricsOverride', {
    width: 1600,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false
  });

  console.log("Warte auf vollständiges Laden und Montieren aller Views...");
  for (let i = 0; i < 40; i++) {
    await sleep(400);
    const evalRes = await client.send('Runtime.evaluate', {
      expression: `(function() {
        return {
          corpReady: !!document.getElementById('view-corporate'),
          finReady: !!document.getElementById('view-finance'),
          setTabOk: typeof window.setTab === 'function'
        };
      })()`,
      returnByValue: true
    });
    if (evalRes && evalRes.result && evalRes.result.value) {
      const v = evalRes.result.value;
      if (v.corpReady && v.finReady && v.setTabOk) break;
    }
  }

  await sleep(1200);

  // Remove loading overlays, inject corporate_controller.js & crm_studio.js & render icons
  const corpJsCode = fs.readFileSync(path.join(STATIC_DIR, 'js', 'corporate_controller.js'), 'utf-8');
  await client.send('Runtime.evaluate', {
    expression: corpJsCode
  });

  const crmJsCode = fs.readFileSync(path.join(STATIC_DIR, 'js', 'crm_studio.js'), 'utf-8');
  await client.send('Runtime.evaluate', {
    expression: crmJsCode
  });

  await client.send('Runtime.evaluate', {
    expression: `(function() {
      const overlay = document.getElementById('global-loading-overlay');
      if (overlay) overlay.remove();
      if (typeof window.hideLoadingOverlay === 'function') window.hideLoadingOverlay();
      if (window.lucide && typeof window.lucide.createIcons === 'function') window.lucide.createIcons();
    })()`
  });

  await sleep(1000);

  const targetFilter = process.argv[2];
  const viewsToRun = targetFilter ? VIEWS_TO_CAPTURE.filter(v => v.id.includes(targetFilter)) : VIEWS_TO_CAPTURE;

  for (const v of viewsToRun) {
    process.stdout.write(`Capture ${v.id}... `);
    await client.send('Runtime.evaluate', {
      expression: `(function() {
        const overlay = document.getElementById('global-loading-overlay');
        if (overlay) overlay.remove();
        if (typeof window.hideLoadingOverlay === 'function') window.hideLoadingOverlay();
        ${v.actionCode}
        if (window.lucide && typeof window.lucide.createIcons === 'function') window.lucide.createIcons();
      })()`
    });

    await sleep(v.waitTime || 1400);

    const screenshotRes = await client.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true
    });

    const imgPath = path.join(OUTPUT_DIR, `${v.id}.png`);
    const imgBuffer = Buffer.from(screenshotRes.data, 'base64');
    fs.writeFileSync(imgPath, imgBuffer);
    console.log(`OK (${Math.round(imgBuffer.length / 1024)} KB)`);

    if (v.cleanupCode) {
      await client.send('Runtime.evaluate', {
        expression: `(function() { ${v.cleanupCode} })()`
      });
      await sleep(300);
    }
  }

  client.close();
  chromeProc.kill();
  server.close();
  console.log(`\nAlle ${VIEWS_TO_CAPTURE.length} fehlenden Screenshots erfolgreich erstellt!`);
}

main().catch(err => {
  console.error("Fehler:", err);
  process.exit(1);
});
