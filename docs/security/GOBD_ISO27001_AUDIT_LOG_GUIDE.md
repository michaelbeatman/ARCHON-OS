# Revisionssicheres Audit-Log & LLM-Dispatch SHA-256-Hashkette (GoBD & ISO/IEC 27001)

Dieses Handbuch beschreibt die Architektur, kryptografische Verifikation, LLM-Dispatch-Nachweisführung und Bedienung des unveränderlichen GoBD-Audit-Logs in Archon OS (`backend/audit_log.py` & `backend/llm_egress_guard.py`).

---

## 1. Übersicht & Regulatorische Schutzziele

Unternehmen unterliegen strengen Nachweispflichten für automatisierte System-, Vertrags-, CRM- und Finanzentscheidungen (**GoBD § 146 AO / Rz. 151 ff.**, **ISO/IEC 27001 Control A.12.4**, **EU AI Act Art. 12 & Art. 19**).

Das Audit-Log von Archon OS garantiert:
- **Lückenlose LLM-Dispatch-Protokollierung:** Für **jeden einzelnen LLM-Call** (sowohl durchgeführte Inferenz-Aufrufe als auch durch Zero-Egress / Privacy-Router hart geblockte Versuche) werden der **reale Ziel-Endpunkt**, der **verwendete Provider**, das **Modell**, der **Ziel-Host** sowie die **Egress-Zone** (`LOCAL_ON_PREM`, `INTERNAL_GATEWAY`, `EXTERNAL_CLOUD`) protokolliert.
- **Manipulationssichere SHA-256-Hashkette:** Jeder Block verankert den Hash seines Vorgängers (`prev_hash`) sowie den kanonisch sortierten JSON-Payload in einem kryptografischen SHA-256-Block-Hash (`current_hash`).
- **Doppelte Spalten- & Payload-Konsistenz:** `verify_integrity()` prüft neben der mathematischen Hash-Verkettung auch, ob die SQL-Indexspalten (`provider`, `model`, `target_host`, `target_endpoint`, `egress_zone`) exakt mit dem signierten JSON-Payload übereinstimmen — selbst direkte Datenbank-Manipulationen an Einzelspalten werden sofort erkannt.
- **Revisionspflicht (Unabschaltbare Invariante):** Die SHA-256-Verkettung besitzt bewusst keinen „Aus-Schalter" (`sha256_dispatch_audit_enforced = true`), während API-Keys/Tokens in URL-Query-Parametern vor dem Signieren deterministisch geschwärzt werden (`sanitize_llm_endpoint`).

---

## 2. Kryptografische SHA-256-Formel & Datenstruktur

Jeder Eintrag in `data/agentic_memory.db` (Tabelle `audit_log`, SQLite-WAL mit `BEGIN IMMEDIATE`) berechnet seinen Block-Hash deterministisch über:

$$\text{current\_hash} = \text{SHA-256}(\text{prev\_hash} \parallel \text{"|"} \parallel \text{timestamp} \parallel \text{"|"} \parallel \text{category} \parallel \text{"|"} \parallel \text{action} \parallel \text{"|"} \parallel \text{agent\_id} \parallel \text{"|"} \parallel \text{payload\_json})$$

### Beispiel eines signierten LLM-Dispatch-Blocks (`category = "llm_dispatch"`):
```json
{
  "id": 757,
  "timestamp": "2026-11-14T08:02:01.135688",
  "category": "llm_dispatch",
  "action": "llm_call_dispatched",
  "agent_id": "tax_holding_advisor",
  "provider": "local",
  "model": "llama3.2",
  "target_host": "127.0.0.1:11434",
  "target_endpoint": "http://127.0.0.1:11434/v1/chat/completions",
  "egress_zone": "LOCAL_ON_PREM",
  "payload_parsed": {
    "data_category": "finance",
    "egress_zone": "LOCAL_ON_PREM",
    "http_status": 200,
    "model": "llama3.2",
    "provider": "local",
    "target_endpoint": "http://127.0.0.1:11434/v1/chat/completions",
    "target_host": "127.0.0.1:11434",
    "zero_egress_active": true
  },
  "prev_hash": "e2fdcdbcd4dd33d0668334242c4576bdc67dc68f7e225a14852c8f71294330bc",
  "current_hash": "8a3adace94759e9d3f794781eb0315eb4acbc8bb09e43fba5e4cf9e02d57034c"
}
```

### Klassifizierte Egress-Zonen (`sanitize_llm_endpoint`):

| Egress-Zone | Erfasste Ziel-Hosts | Bewertung unter Zero-Egress |
|---|---|---|
| `LOCAL_ON_PREM` | `127.0.0.1`, `localhost`, `::1`, `host.docker.internal`, `ollama`, `ollama-embed`, `vllm`, `lmstudio`, private RFC1918-IPs | **Zulässig** (Daten bleiben im Hausnetz) |
| `INTERNAL_GATEWAY` | `omniroute:20128`, `hermes`, `hermes-dashboard`, `odysseus`, `openclaw` | **Gesperrt für Cloud-Modelle** bei aktivem Zero-Egress / sensiblen Kategorien |
| `EXTERNAL_CLOUD` | `openrouter.ai`, `api.openai.com`, `api.groq.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `api.mistral.ai` u. a. | **Hart blockiert** bei sensiblen Kategorien & im Modus `zero_egress_strict` |

---

## 3. REST-API & Prüfer-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/operations/governance/audit-log` | Paginierte Audit-Einträge (Filter: `category`, `provider`, `target_host`, `search`, `limit`, `offset`). |
| `GET` | `/api/operations/governance/audit-log/llm-dispatches` | Dedizierter Nachweis aller LLM-Dispatches mit `provider`, `model`, `target_host`, `target_endpoint` & Hash-Verkettung. |
| `POST` | `/api/operations/governance/audit-log/verify` | Vollständige mathematische SHA-256-Ketten- & Spaltenkonsistenz-Prüfung vom Genesis-Block bis Head. |
| `GET` | `/api/operations/governance/audit-log/export?format=json\|csv` | GoBD-/ISO-27001-Prüferexport inkl. Spalten `Provider`, `Modell`, `Ziel_Host`, `Ziel_Endpunkt` und `Egress_Zone`. |
| `GET` | `/api/operations/governance/zero-egress-audit` | Kombinierter Live-Prüfbericht über Zero-Egress-Konfiguration, Privacy-Router Hard-Block, Docker-Worker-Netz (`Internal=true`) & SHA-256-Kette. |

---

## 4. Bedienung im Web-Interface & in den Einstellungen

1. **Forensische Ansicht:** Seitenleiste **Telemetrie & Logs** → Reiter **GoBD / Revisions-Log** → Kategorie-Pill **`LLM-Dispatches`** wählen. Jede Zeile zeigt unmittelbar `Provider / Modell → Ziel-Host (Ziel-Endpunkt)` sowie den verketteten SHA-256-Block-Hash.
2. **System Control Center (Einstellungen):**
   - Reiter **PROVIDER & GATEWAY** → Karte *„Zero-Egress, Privacy-Router Hard-Block & SHA-256 Dispatch-Audit"* → Button **„Posture prüfen"**.
   - Reiter **AUTONOMIE & MODULE** → **Bereich 7 / Modul 32** (Suche über `/` nach `SHA-256`, `LLM-Dispatch` oder `Zero-Egress`).
3. **1-Klick GoBD- & EU-AI-Act-Verfahrensdokumentation als PDF (M49):**
   - In **Operations** → Kachel **`AI Act / GoBD`** → **„GoBD + EU AI Act PDF herunterladen"** (`GET /api/v1/governance/compliance/verfahrensdokumentation.pdf`). Kapitel 3 dokumentiert live die Anzahl verifizierter Blöcke, die Zahl signierter LLM-Dispatches, den aktiven Hard-Block-Status sowie die Docker-Worker-Netzwerk-Isolation (`Internal=true`).
