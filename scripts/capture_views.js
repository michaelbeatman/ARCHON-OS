const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const OUTPUT_DIR = path.join(__dirname, '..', 'docs', 'system', 'screenshots');

if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

const VIEWS = [
  { id: "mission_control", tab: "mission-control" },
  { id: "operations", tab: "operations", subtab: "kanban" },
  { id: "org", tab: "operations", subtab: "org" },
  { id: "inbox", tab: "inbox" },
  { id: "kader", tab: "agent-profiles" },
  { id: "showroom", tab: "showroom" },
  { id: "library", tab: "library" },
  { id: "brain", tab: "brain" },
  { id: "automation", tab: "automation" },
  { id: "omniroute", tab: "omniroute" },
  { id: "guardian", tab: "guardian" },
  { id: "plugins", tab: "plugins" },
  { id: "research", tab: "research" },
  { id: "log_stream", tab: "log-stream" }
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
  const tempUserDataDir = path.join(require('os').tmpdir(), 'chrome_cdp_profile_' + Date.now());
  console.log("Starte Chrome mit CDP...");

  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    '--remote-debugging-port=9222',
    '--window-size=1600,1000',
    '--disable-gpu',
    '--no-sandbox',
    '--disable-web-security',
    '--allow-running-insecure-content',
    '--disable-extensions',
    `--user-data-dir=${tempUserDataDir}`,
    'http://localhost:8501'
  ], { detached: false });

  // Warte bis Port erreichbar ist und Page Target existiert
  let pageTarget = null;
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    try {
      const targets = await fetchJson('http://127.0.0.1:9222/json/list');
      if (Array.isArray(targets) && targets.length > 0) {
        pageTarget = targets.find(t => t.type === 'page') || targets[0];
        if (pageTarget && pageTarget.webSocketDebuggerUrl) break;
      }
    } catch (e) {}
  }

  if (!pageTarget || !pageTarget.webSocketDebuggerUrl) {
    chromeProc.kill();
    throw new Error("Kein Page-Target in Chrome gefunden.");
  }

  console.log("Page-Target gefunden:", pageTarget.title, pageTarget.webSocketDebuggerUrl);

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

  console.log("Warte auf vollständiges Laden und Montieren aller Archon OS Views...");
  
  // Warte bis alle Subviews (operations, agent-profiles, inbox etc.) fertig gefetcht und gemountet sind
  let ready = false;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    const evalRes = await client.send('Runtime.evaluate', {
      expression: `(function() {
        const ops = document.getElementById('view-operations');
        const kader = document.getElementById('view-agent-profiles');
        const inbox = document.getElementById('view-inbox');
        const setTabOk = typeof window.setTab === 'function';
        return {
          opsReady: !!ops,
          kaderReady: !!kader,
          inboxReady: !!inbox,
          setTabOk
        };
      })()`,
      returnByValue: true
    });

    if (evalRes && evalRes.result && evalRes.result.value) {
      const v = evalRes.result.value;
      if (v.opsReady && v.kaderReady && v.inboxReady && v.setTabOk) {
        ready = true;
        break;
      }
    }
  }

  console.log("Archon OS Initialisierung & Mounts abgeschlossen (ready =", ready, ")");
  
  // Warte noch 1.5s für asynchrone Datenabfragen
  await sleep(1500);

  // Entferne Loading-Overlay hart aus dem DOM und schalte initial auf mission-control
  await client.send('Runtime.evaluate', {
    expression: `(function() {
      const overlay = document.getElementById('global-loading-overlay');
      if (overlay) overlay.remove();
      if (typeof window.hideLoadingOverlay === 'function') window.hideLoadingOverlay();
      if (typeof window.setTab === 'function') window.setTab('mission-control');
    })()`
  });

  await sleep(2000);

  for (const v of VIEWS) {
    console.log(`\nSchalte auf View: ${v.id} (tab: ${v.tab})...`);
    
    // Wechsle Tab per JS und bereinige Overlay falls neu erzeugt
    await client.send('Runtime.evaluate', {
      expression: `(function() {
        const overlay = document.getElementById('global-loading-overlay');
        if (overlay) overlay.remove();
        if (typeof window.hideLoadingOverlay === 'function') window.hideLoadingOverlay();
        
        window.setTab("${v.tab}");
        if ("${v.subtab || ''}" && typeof window.setOperationsTab === 'function') {
          window.setOperationsTab("${v.subtab}");
        }
      })()`
    });

    // Gib dem DOM, Charts, iframes und Tabellen ausreichend Zeit zum Rendern
    const waitTime = (v.tab === "automation" || v.tab === "omniroute") ? 4500 : 2500;
    await sleep(waitTime);

    // Optional: Überprüfe, ob view sichtbar ist
    const checkView = await client.send('Runtime.evaluate', {
      expression: `(function() {
        const activeView = document.getElementById("view-${v.tab}");
        return {
          exists: !!activeView,
          display: activeView ? window.getComputedStyle(activeView).display : null,
          textLen: activeView ? (activeView.innerText || "").length : 0
        };
      })()`,
      returnByValue: true
    });
    console.log(`  DOM-Status für view-${v.tab}:`, checkView.result.value);

    // Screenshot aufnehmen
    const screenshotRes = await client.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true
    });

    const imgPath = path.join(OUTPUT_DIR, `${v.id}.png`);
    const imgBuffer = Buffer.from(screenshotRes.data, 'base64');
    fs.writeFileSync(imgPath, imgBuffer);
    console.log(`  ✓ Gespeichert: ${imgPath} (${Math.round(imgBuffer.length / 1024)} KB)`);
  }

  client.close();
  chromeProc.kill();
  console.log("\nAlle 14 Screenshots erfolgreich generiert!");
}

main().catch(err => {
  console.error("Fehler im Screenshot-Skript:", err);
  process.exit(1);
});
