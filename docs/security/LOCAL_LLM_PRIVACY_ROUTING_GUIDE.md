# Zero-Egress-Konfiguration, Privacy-Router Hard-Block & Docker-Worker-Isolation

Dieses Handbuch beschreibt das mehrschichtige Datenschutz- und Datensouveränitäts-System in Archon OS (`backend/privacy_router.py`, `backend/llm_egress_guard.py`, `backend/egress_firewall.py`, `backend/ephemeral_sandbox.py`).

---

## 1. Mehrschichtige Zero-Egress-Architektur (Defense-in-Depth)

Damit geschäftskritische Daten (Finanzen, Belege, Verträge, CRM-Kontakte, Personalakten) das eigene Haus niemals unbeabsichtigt verlassen — auch nicht indirekt über interne Router wie `omniroute` oder automatische Cloud-Fallback-Ketten — setzt Archon OS vier ineinandergreifende Schutzschichten durch:

| Schicht | Modul / Datei | Durchgesetzte Garantie |
|---|---|---|
| **1. Konsolidierte Zero-Egress-Konfiguration** | `backend/privacy_router.py` (`get_privacy_config`, `verify_zero_egress_config`) | Vereinheitlicht `data/privacy_routing.json`, `settings.json -> privacy.zero_egress` und `PRIVACY_ZERO_EGRESS`. Prüft, dass `local_llm_url` zwingend in Zone `LOCAL_ON_PREM` liegt. |
| **2. Privacy-Router Fail-Closed Hard-Block** | `backend/privacy_router.py` + `backend/llm_egress_guard.py` | Sensible Kategorien (`finance`/`finanzen`, `contracts`/`verträge`, `crm`, `hr`, `gdpr`) werden zwingend lokal geroutet. Ist das lokale Modell offline, greift vor dem ersten Netzwerk-Byte der **harte Block (`LOCAL_LLM_OFFLINE_HARD_BLOCK`)** — kein Ausweichen auf OpenRouter, Groq, OpenAI, OmniRoute-Cloud oder EU-Cloud. |
| **3. Cloud-Prefetch- & Egress-Firewall-Sperre** | `core_dispatcher.py` + `backend/egress_firewall.py` | Unterbindet spekulatives Vorladen von CRM-/ERP-Datensätzen in Cloud-Prompts (`block_crm_erp_prefetch_on_cloud = true`). Im Modus `zero_egress_strict = true` blockiert auch die Egress-Firewall jede Nicht-`LOCAL_ON_PREM`-Domain. |
| **4. Docker-Netzwerk-Isolation ohne Internet-Route** | `docker-compose.dev.yml`, `docker-compose.yml`, `backend/ephemeral_sandbox.py` | Worker laufen im isolierten Bridge-Netzwerk `archon-worker-zero-egress_net` bzw. `archon-sandbox_net` mit **`internal: true`** (kein Default-Gateway, kein IP-Masquerading/NAT, keine Internet-Route auf Kernel-Ebene) oder komplett mit `--network none`. |

Zusätzlich schreibt jeder erlaubte und jeder geblockte LLM-Aufruf einen signierten Block in die **SHA-256-Hashkette** (`docs/security/GOBD_ISO27001_AUDIT_LOG_GUIDE.md`).

---

## 2. Die zwei Betriebsmodi: Sensibler Hard-Block vs. Strict Zero-Egress

| Modus | Schalter | Verhalten bei Allgemein-Tasks (z. B. Coding) | Verhalten bei Sensiblen Kategorien (Finanzen, Verträge, CRM, HR, DSGVO) |
|---|---|---|---|
| **Standard-Schutz (Empfohlener Default)** | `sensitive_local_routing: true`<br>`hard_block_on_local_offline: true`<br>`zero_egress_strict: false` | Dürfen konfigurierte Provider nutzen (inkl. SHA-256-Dispatch-Protokollierung & CRM/ERP-Prefetch-Sperre). | Zwingend On-Premise (`LOCAL_ON_PREM`). Ist das lokale LLM offline → **sofortiger Hard-Block** (`LOCAL_LLM_OFFLINE_HARD_BLOCK`). |
| **Strict Zero-Egress (100 % Air-Gapped Inference)** | `zero_egress_strict: true` *(oder `PRIVACY_ZERO_EGRESS=true`)* | **Alle** Aufgaben gehen ausschließlich an `LOCAL_ON_PREM`. Direkte Cloud-APIs **und** Cloud-Modelle hinter `omniroute` sind gesperrt; bei Offline-Lokalmodell greift der Hard-Block. | Identisch: 100 % lokal oder Hard-Block; `fallback_to_eu` wird zwangsweise auf `false` gesetzt. |

---

## 3. Wo werden die Einstellungen verwaltet?

Alle steuerbaren Parameter sind an drei synchronisierten Stellen im Web-UI verfügbar (Single Source of Truth):

1. **System Control Center → Reiter `AUTONOMIE & MODULE` → Bereich 7 / Modul 32** *(Schnellsuche mit Taste `/` nach `Zero-Egress` oder `Hard-Block`)*:
   - `Sensibles Lokal-Routing` (`sensitive_local_routing`)
   - `Hard-Block (Lokal offline)` (`hard_block_on_local_offline`)
   - `Strict Zero-Egress (Alle)` (`zero_egress_strict`)
   - `Cloud-Prefetch-Sperre` (`block_crm_erp_prefetch_on_cloud`)
   - `Lokaler On-Premise Endpunkt` (`local_llm_url`), `Lokales Modell` (`local_llm_model`), `Isoliertes Worker-Docker-Netz` (`worker_isolation_network`) und `Geschützte Kategorien` (`sensitive_categories`)
   - **Modul 5 (Ephemeral Docker Sandbox):** Schalter `Worker Zero-Egress` (`zero_egress_worker_net`) bindet flüchtige Ausführungscontainer an `archon-worker-zero-egress_net` (`Internal=true`).
2. **System Control Center → Reiter `PROVIDER & GATEWAY`**:
   - Direkt-Karte mit **„Posture prüfen"** (Live-Verifikation von Konfiguration, Docker-Netz `Internal=true` und SHA-256-Hashkette) sowie **„Konfigurieren"**.
3. **Sidebar-Footer Statusleuchten (`[●] LOKAL` / `[●] DSGVO`)**:
   - Klick öffnet das Datenschutz-Modal zum schnellen Umschalten inkl. Live-Verbindungstest zum lokalen Ollama / LM Studio / vLLM Server.

> **Wichtiger Governance-Hinweis:** Die **SHA-256-Hashkette & LLM-Dispatch-Protokollierung** ist als gesetzliche Revisionsanforderung (GoBD / ISO 27001) **zwangsweise immer aktiv** (`sha256_dispatch_audit_enforced = true`) und kann in den Einstellungen bewusst nicht deaktiviert werden.

---

## 4. Docker-Worker-Netzwerk-Isolation verifizieren

Beide Compose-Definitionen (`docker-compose.dev.yml` und `docker-compose.yml`) deklarieren:
```yaml
networks:
  archon-worker-zero-egress_net:
    driver: bridge
    internal: true
  archon-sandbox_net:
    driver: bridge
    internal: true
```

Vor jedem Container-Start prüft `backend/ephemeral_sandbox.py` (`_ensure_sandbox_network`) per `docker network inspect`, dass `Internal == true` gesetzt ist. Ein fehlkonfiguriertes Netzwerk mit Internet-Route (`Internal == false` oder `bridge`/`host`) wirft sofort `ZeroEgressNetworkIsolationError` (Fail-Closed).

### Manuelle Verifikation per CLI:
```bash
# 1. Docker-Flag prüfen (muss internal=true ausgeben)
docker network inspect archon-worker-zero-egress_net --format '{{.Name}}: internal={{.Internal}}'

# 2. Live-Beweis aus einem Worker-Container: Außenwelt = Errno 101 (Network unreachable)
docker run --rm --network archon-worker-zero-egress_net --cap-drop=ALL --read-only \
  python:3.11-alpine python -c "import socket; socket.create_connection(('1.1.1.1', 443), 2)"
```

---

## 5. Persistenz & REST-API

Konfigurationsdatei `data/privacy_routing.json` (synchronisiert mit `settings.json -> zero_egress_governance` & `privacy.zero_egress`):
```json
{
  "zero_egress_strict": false,
  "sensitive_local_routing": true,
  "hard_block_on_local_offline": true,
  "block_crm_erp_prefetch_on_cloud": true,
  "local_llm_url": "http://127.0.0.1:11434/v1",
  "local_llm_model": "llama3.2",
  "fallback_to_eu": false,
  "worker_isolation_network": "archon-worker-zero-egress_net",
  "sensitive_categories": [
    "finance", "finanzen", "receipts", "buchhaltung", "erp", "invoices",
    "contracts", "verträge", "vertraege", "legal",
    "crm", "kunden", "contacts", "gdpr", "dsgvo", "personalakte", "hr"
  ]
}
```

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/llm-providers/privacy-status` | Live-Status von Lokal-LLM, Hard-Block, Zero-Egress-Verifikation & DSGVO-Ampel. |
| `POST` | `/api/llm-providers/privacy-routing` | Speichert die Privacy- & Zero-Egress-Regeln revisionssicher (Admin-RBAC). |
| `POST` | `/api/llm-providers/test-connection` | Live-Latenz- & Modellprüfung des lokalen Endpunkts (Admin-RBAC). |
| `GET` | `/api/operations/governance/zero-egress-audit` | Vollständiger Prüfbericht (Config + Local LLM + Docker `Internal=true` + SHA-256-Kette). |
