# Reverse Proxy & Single Sign-On (Caddy + Authelia 2FA)

## Überblick
Archon OS bündelt zahlreiche Dienste (FastAPI Kern `:8501`, Hermes Gateway `:8644`, OmniRoute `:20128`, n8n `:5678`, PocketBase `:8090`, Grafana `:3001`, Prometheus `:9090`, Uptime Kuma `:3002`).

Zur Erfüllung von **Säule 6 (Governance & Security by Design / Zero Trust)** kapselt ein zentraler **Caddy Reverse Proxy** (`config/caddy/Caddyfile`) alle internen Ports hinter einem einheitlichen Port (`:80` bzw. `:443` mit TLS) und delegiert Authentifizierungsentscheidungen an **Authelia** (`config/authelia/configuration.yml`).

---

## 1. Architektur & Routing-Tabelle

```
                          [Externer Benutzer / Browser]
                                        │
                                        ▼
                        ┌───────────────────────────────┐
                        │      Caddy Gateway (:80/:443)  │
                        └───────┬───────────────┬───────┘
                                │               │
          [Health/Metrics/Public]               │ [Admin & Dashboards]
                                │               ▼
                                │    ┌─────────────────────┐
                                │    │   Authelia (2FA)    │
                                │    │  TOTP / Passkey /   │
                                │    │  One-Factor Check   │
                                │    └──────────┬──────────┘
                                │               │ (OK: Remote-User Header)
                                ▼               ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Internes Docker Netzwerk (agentic_mesh)                                │
│                                                                        │
│  /           ──► archon-os:8501     /pb/*        ──► pocketbase:8090   │
│  /hermes/*   ──► hermes:8644        /grafana/*   ──► grafana:3000      │
│  /n8n/*      ──► n8n:5678           /prometheus/*──► prometheus:9090   │
│  /omniroute/*──► omniroute:20128    /uptime/*    ──► uptime-kuma:3001  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Richtlinien & Zero-Trust Regeln

1. **Bypass (Öffentlich):**
   - `/health`, `/metrics`, `/api/operations/metrics`
   - Diese Endpunkte sind ungeschützt erreichbar, damit externe Monitoringsysteme (Uptime Kuma, Prometheus) Healthchecks ohne Session durchführen können.
2. **One-Factor (Benutzername & Passwort):**
   - Basiszugriff auf das Operations Kanban Board.
3. **Two-Factor (2FA: TOTP oder Passkey / FIDO2):**
   - Hermes Orchestrator (`/hermes/*`)
   - n8n Workflows (`/n8n/*`)
   - Überwachungssysteme (`/grafana/*`, `/prometheus/*`, `/uptime/*`)

---

## 3. Starten des Gateway-Stacks

In `docker-compose.yml` sind `caddy` und `authelia` unter dem Profil `gateway` definiert:

```bash
# Gateway & SSO starten
docker compose --profile gateway up -d caddy authelia
```

Nach dem Start:
- **Zentrales Portal:** `http://localhost/`
- **SSO Login:** `http://localhost/authelia/`
- **Hermes Gateway:** `http://localhost/hermes/`
- **n8n:** `http://localhost/n8n/`
- **Grafana:** `http://localhost/grafana/`

---

## 4. Konfigurationsdateien
- [`config/caddy/Caddyfile`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/caddy/Caddyfile): Upstream-Proxy-Definitionen, Security-Header (HSTS, No-Sniff, Referrer-Policy).
- [`config/authelia/configuration.yml`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/authelia/configuration.yml): Rollen, Schwellenwerte, Brute-Force-Schutz (Ban nach 5 Fehlversuchen).
- [`config/authelia/users_database.yml`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/authelia/users_database.yml): Benutzerkonten mit Argon2id-Kennwort-Hashes.
