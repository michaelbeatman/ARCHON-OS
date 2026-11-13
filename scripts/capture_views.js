const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const OUTPUT_DIR = path.join(__dirname, '..', 'docs', 'system', 'screenshots');

if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

// DEFINITION ALLER HAUPT- UND SUB-ANSICHTEN INKL. SPEZIAL-STUDIOS
const VIEWS = [
  // 1. Mission Control
  { 
    id: "mission_control", 
    actionCode: `window.setTab("mission-control");` 
  },

  // 2. Operations (Kanban & Funk)
  { 
    id: "operations", 
    actionCode: `window.setTab("operations"); if (typeof window.setOperationsTab === 'function') window.setOperationsTab("kanban");` 
  },
  { 
    id: "ops_comm", 
    actionCode: `window.setTab("operations"); if (typeof window.setOperationsTab === 'function') window.setOperationsTab("comm");` 
  },

  // 3. Organisation & Ablaufdiagramm
  { 
    id: "org", 
    actionCode: `window.setTab("operations"); if (typeof window.setOperationsTab === 'function') window.setOperationsTab("org");` 
  },

  // 4. Eingang & Triage
  { 
    id: "inbox", 
    actionCode: `window.setTab("inbox");` 
  },

  // 5. Agenten-Kader & die 7 Fach-Reiter
  { 
    id: "kader", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("overview");` 
  },
  { 
    id: "kader_chat", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("chat");` 
  },
  { 
    id: "kader_skills", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("skills");` 
  },
  { 
    id: "kader_operations", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("operations");` 
  },
  { 
    id: "kader_soul", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("soul");` 
  },
  { 
    id: "kader_personalakte", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("personalakte");` 
  },
  { 
    id: "kader_marketplace", 
    actionCode: `window.setTab("agent-profiles"); if (typeof window.switchAgentCadreTab === 'function') window.switchAgentCadreTab("marketplace");` 
  },

  // 6. Showroom
  { 
    id: "showroom", 
    actionCode: `window.setTab("showroom");` 
  },

  // 7. Zentralbibliothek & Subtabs
  { 
    id: "library", 
    actionCode: `window.setTab("library"); if (typeof window.switchLibrarySubTab === 'function') window.switchLibrarySubTab("rag");` 
  },
  { 
    id: "library_erfasser", 
    actionCode: `window.setTab("library"); if (typeof window.switchLibrarySubTab === 'function') window.switchLibrarySubTab("erfasser");` 
  },
  { 
    id: "library_vault", 
    actionCode: `window.setTab("library"); if (typeof window.switchLibrarySubTab === 'function') window.switchLibrarySubTab("vault");` 
  },

  // 8. Second Brain
  { 
    id: "brain", 
    actionCode: `window.setTab("brain");` 
  },

  // 9. Automation n8n
  { 
    id: "automation", 
    actionCode: `window.setTab("automation");`,
    waitTime: 4000
  },

  // 10. OmniRoute
  { 
    id: "omniroute", 
    actionCode: `window.setTab("omniroute");`,
    waitTime: 4000
  },

  // 11. Guardian
  { 
    id: "guardian", 
    actionCode: `window.setTab("guardian");` 
  },

  // 12. Plugins
  { 
    id: "plugins", 
    actionCode: `window.setTab("plugins");` 
  },

  // 13. Research
  { 
    id: "research", 
    actionCode: `window.setTab("research");` 
  },

  // 14. Log Stream
  { 
    id: "log_stream", 
    actionCode: `window.setTab("log-stream");` 
  },

  // 15. SPEZIAL-STUDIO: Archon Prompt Studio (1.079 Vorlagen & Fabric SOP)
  {
    id: "prompt_studio",
    actionCode: `
      window.setTab("operations");
      if (typeof window.openSurePromptsModal === 'function') {
        window.openSurePromptsModal('ops-task');
      }
    `,
    cleanupCode: `
      if (typeof window.closeSurePromptsModal === 'function') {
        window.closeSurePromptsModal();
      }
    `,
    waitTime: 3000
  },

  // 16. SPEZIAL-STUDIO: Visual CSS Live Studio & In-Place Inspector
  {
    id: "css_studio",
    actionCode: `
      if (typeof window.closeSurePromptsModal === 'function') window.closeSurePromptsModal();
      window.setTab("mission-control");
      if (typeof window.toggleCssStudio === 'function') {
        window.toggleCssStudio();
      }
    `,
    cleanupCode: `
      if (typeof window.toggleCssStudio === 'function') {
        const studio = document.getElementById("archon-css-studio");
        if (studio && !studio.classList.contains("hidden")) {
          window.toggleCssStudio();
        }
      }
    `,
    waitTime: 2500
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
  await sleep(1500);

  // Entferne Loading-Overlay hart aus dem DOM
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
    console.log(`\nSchalte auf View/Subtab: ${v.id}...`);
    
    // Führe Aktions-Code aus
    await client.send('Runtime.evaluate', {
      expression: `(function() {
        const overlay = document.getElementById('global-loading-overlay');
        if (overlay) overlay.remove();
        if (typeof window.hideLoadingOverlay === 'function') window.hideLoadingOverlay();
        
        ${v.actionCode}
      })()`
    });

    const waitTime = v.waitTime || 2200;
    await sleep(waitTime);

    // Screenshot aufnehmen
    const screenshotRes = await client.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true
    });

    const imgPath = path.join(OUTPUT_DIR, `${v.id}.png`);
    const imgBuffer = Buffer.from(screenshotRes.data, 'base64');
    fs.writeFileSync(imgPath, imgBuffer);
    console.log(`  ✓ Gespeichert: ${imgPath} (${Math.round(imgBuffer.length / 1024)} KB)`);

    // Cleanup-Code ausführen (z. B. Modal schließen)
    if (v.cleanupCode) {
      await client.send('Runtime.evaluate', {
        expression: `(function() { ${v.cleanupCode} })()`
      });
      await sleep(500);
    }
  }

  client.close();
  chromeProc.kill();
  console.log("\nAlle Screenshots (inklusive Unteransichten und Spezial-Studios) erfolgreich generiert!");
}

main().catch(err => {
  console.error("Fehler im Screenshot-Skript:", err);
  process.exit(1);
});
