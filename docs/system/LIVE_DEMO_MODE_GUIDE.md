# Archon OS — "Zero-Install" Live-Demo Mode Guide (M47)
**English & Deutsch · Safe Public Hosting (`ARCHON_DEMO_MODE=true`)**

---

## Part 1 — English Documentation

### 1. Overview & Purpose
Milestone 47 introduces a hardened, single-container **Read-Only Live-Demo Mode** (`ARCHON_DEMO_MODE=true`) engineered for high-traffic public launches (**Show HN**, **Product Hunt**, conference kiosks, and B2B prospect evaluations) on a minimal **5 EUR VPS (1 vCPU, 1 GB RAM)**:

- **€0.00 LLM API Risk:** Zero API keys are mounted or required. Interactive previews (QuickChat, Master Chat, Direct Agent Chat, AI Boardroom, Prompt Studio) return instant, deterministic specialist-flavored simulations with `[DEMO SIMULATION — Zero Token Cost]`.
- **Zero RCE / 0-Day Attack Surface:** No `docker.sock`, no sibling proxy containers, immutable `read_only: true` root filesystem, `noexec` RAM-backed `tmpfs` scratch mounts, `cap_drop: [ALL]`, and `no-new-privileges:true`.
- **Rich Bilingual Showcase ("Mittelstand Muster Precision GmbH"):** Pre-populated with a 6-phase C-level AI Boardroom debate (EU AI Act & Benelux expansion), 8 Kanban tasks across all workflow columns, 6 B2B industrial accounts, 5 pipeline deals, and 5 GoBD SHA-256 sealed ERP quotes/invoices in both English (`en`) and German (`de`).

---

### 2. Defense-in-Depth Security Guarantees

| Layer | Mechanism | Threat Mitigated |
|---|---|---|
| **1. Pure ASGI Hard-Block** | `DemoModeMiddleware` blocks `/api/sandbox`, `/api/v1/container`, `/api/docker`, `/api/v1/system/update`, `/api/hermes/raw_config`, `/n8n-proxy`, `/omniroute-proxy`, `/api/proxy` with `403 demo_blocked` on **every** HTTP verb (incl. `GET`) and WebSockets. | Remote code execution, container escape, secret disclosure, SSRF. |
| **2. Read-Only Verb Guard** | All mutating requests (`POST`, `PUT`, `DELETE`, `PATCH`) outside the deterministic preview simulator return `403 demo_read_only` before reaching route handlers. | Defacement, stored XSS, SQLite tampering, vault deletion. |
| **3. Zero-Egress Simulator** | Safe preview POSTs (`/api/quickchat`, `/api/chat`, `/api/agent-chat`, `/api/boardroom/run`, `/api/templates/`) synthesize deterministic responses in memory with zero outbound sockets and zero disk writes. | Token-drain attacks, wallet exhaustion, outbound abuse. |
| **4. Kernel & Container Isolation** | `docker-compose.demo.yml` enforces `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`, `mem_limit: 1g`, `pids_limit: 128`, and `noexec,nosuid,nodev` `tmpfs` mounts. | Filesystem persistence, fork bombs, privilege escalation. |

> **Zero Production Overhead:** When `ARCHON_DEMO_MODE` is unset or `false`, `DemoModeMiddleware` executes a single boolean check and delegates directly (`await self.app(scope, receive, send)`), adding zero latency or request buffering to normal deployments.

---

### 3. Quickstart & Local Verification

```bash
# 1. Launch the standalone hardened demo container (bound to 127.0.0.1:8501)
docker compose -f docker-compose.demo.yml up --build -d

# 2. Check demo status & showcase bundle (EN & DE)
curl -s http://127.0.0.1:8501/api/demo/status | python3 -m json.tool
curl -s "http://127.0.0.1:8501/api/demo/showcase?lang=en" | python3 -m json.tool | head -n 40
curl -s "http://127.0.0.1:8501/api/demo/showcase?lang=de" | python3 -m json.tool | head -n 40

# 3. Verify hard 403 block on sandbox & mutations
curl -i http://127.0.0.1:8501/api/sandbox/run
curl -i -X DELETE http://127.0.0.1:8501/api/deals/deal-m47-01

# 4. Verify instant zero-token simulated specialist chat (200 OK)
curl -s -X POST http://127.0.0.1:8501/api/quickchat \
  -H "Content-Type: application/json" \
  -d '{"profile_id":"finance_lead","message":"Evaluate Benelux RFQ payback","lang":"en"}'
```

---

### 4. Public VPS Deployment with Caddy (Automatic HTTPS)

Keep `ARCHON_DEMO_BIND_IP=127.0.0.1` (the default in `docker-compose.demo.yml`) so Docker never bypasses host firewall rules, and place **Caddy** in front for TLS 1.3 + HTTP/3 + request body caps:

```caddyfile
demo.archon-os.example {
    encode zstd gzip

    # Cap request body size on public demo node (64 KB)
    request_body {
        max_size 64KB
    }

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }

    reverse_proxy 127.0.0.1:8501 {
        header_up X-Forwarded-Proto {scheme}
    }
}
```

---

## Teil 2 — Deutsche Dokumentation

### 1. Architektur & Einsatzzweck
Meilenstein 47 stellt einen gehärteten **Read-Only Live-Demo-Modus** (`ARCHON_DEMO_MODE=true`) bereit, mit dem Archon OS gefahrlos öffentlich im Internet präsentiert werden kann (**Show HN**, **Product Hunt**, Kunden-Demos auf einem **5-EUR-VPS mit 1 GB RAM**):

- **0,00 € Token- & API-Risiko:** Es werden keinerlei LLM-API-Keys hinterlegt. Interaktive Vorschauen (QuickChat, Master-Chat, Direkt-Chat, KI-Boardroom, Prompt Studio) liefern deterministische Fachantworten der jeweiligen Spezialisten inklusive `[DEMO SIMULATION — Zero Token Cost]`-Hinweis.
- **Keine Angriffsfläche für Code-Ausführung:** Kein gemounteter `docker.sock`, keine Proxy-Container, schreibgeschütztes Container-Dateisystem (`read_only: true`), reine RAM-`tmpfs`-Verzeichnisse (`noexec,nosuid,nodev`), `cap_drop: [ALL]` und `no-new-privileges:true`.
- **Zweisprachiger Referenzmandant („Mittelstand Muster GmbH“):** Vollständige 6-Phasen-Vorstandsdebatte (Benelux-Expansion & EU-AI-Act-Audit mit `@executive_decision_architect`, `@finance_lead`, `@commercial_jurist_contracts`, `@red_team_challenger`, `@senior_fullstack_engineer`), 8 Kanban-Aufgaben, 6 B2B-Kundenkonten, 5 Vertriebs-Deals sowie 5 GoBD-versiegelte Angebote/Rechnungen (`de` & `en`).

---

### 2. Vierstufige Sicherheitsgarantien

1. **Harte Pfadsperre (`403 demo_blocked`):** Alle Ausführungs-, Container-, Update-, Rohkonfigurations- und Proxy-Routen (`/api/sandbox`, `/api/v1/container`, `/api/docker`, `/api/v1/system/update`, `/api/hermes/raw_config`, `/n8n-proxy`, `/omniroute-proxy`, `/api/proxy`) werden unabhängig von der HTTP-Methode sofort in der ASGI-Schicht abgewiesen.
2. **Schreibschutz-Sperre (`403 demo_read_only`):** Sämtliche übrigen `POST`-, `PUT`-, `DELETE`- und `PATCH`-Aufrufe werden vor den FastAPI-Routen abgefangen. Im Browser blendet `static/js/demo_banner.js` automatisch einen freundlichen Hinweis-Toast mit GitHub-Link ein.
3. **Deterministische Vorschau ohne Egress (`200 OK`):** Testeingaben im Chat, Boardroom oder Prompt-Template-Renderer werden rein im Arbeitsspeicher beantwortet — ohne ausgehende Netzwerkverbindungen und ohne Festplattenzugriffe.
4. **Ephemerer `tmpfs`-Kaltstart:** Beim Containerstart befüllt `seed_demo_workspace()` einmalig `boardroom_history.json` und `kanban_cards.json` im flüchtigen RAM-Dateisystem. Ein `docker compose -f docker-compose.demo.yml restart` setzt den Zustand binnen Sekunden rückstandslos zurück.

---

### 3. Automatisierte Verifikation (Testsuite)

```bash
/mnt/raid/AgenticOS-2026/.venv/bin/python -m pytest tests/test_m47_demo_mode.py -q
node --check static/js/demo_banner.js
docker compose -f docker-compose.demo.yml config -q
```
