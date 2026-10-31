# Datenschutz-Routing (Zero Egress) & Lokale LLMs

Dieses Handbuch beschreibt die Konfiguration, automatische Erkennung und Funktionsweise des DSGVO-konformen Routings sensibler Daten in Archon OS (`backend/privacy_router.py`).

---

## 1. Motivation & Schutzziele (DSGVO Art. 28 & 32)

Geschäftskritische Daten (z. B. Rechnungen, Verträge, HR-Akten, Kundendaten im CRM) dürfen nicht unkontrolliert an externe US-Cloud-APIs übermittelt werden. 

Archon OS implementiert eine zweistufige Schutzschicht:
1. **Zero-Egress-Klassifizierung:** Anfragen mit vertraulichen Daten werden standardmäßig für externe Endpunkte gesperrt.
2. **On-Premise Inferenz:** Aufgaben werden primär an lokale Sprachmodelle (LM Studio, Ollama) auf dem Host übergeben.
3. **DSGVO-zertifizierter EU-Fallback:** Steht kein lokales LLM bereit, routet das System kontrolliert an europäische Server (z. B. Mistral AI mit Hosting in Frankreich/EU), statt an US-Dienste.

---

## 2. Automatische Erkennung lokaler Inferenz-Engines

Das System tastet beim Start und zyklisch (alle 10 Sekunden zwischengespeichert) die Standard-Ports des Hosts ab:

| Engine | Default-Endpunkt | Port | API-Spezifikation |
|---|---|---|---|
| **LM Studio** | `http://127.0.0.1:1234/v1` | 1234 | OpenAI-kompatibel (`/v1/chat/completions`) |
| **Ollama** | `http://127.0.0.1:11434` | 11434 | Native & OpenAI-Bridge (`/api/chat`, `/v1`) |
| **LocalAI / vLLM** | `http://127.0.0.1:8080/v1` | 8080 | OpenAI-kompatibel |

*Hinweis zur Netzwerk-Optimierung:* Um Windows-DNS-Laufzeiten (`localhost`-Auflösung) zu vermeiden, greift der Prüfmechanismus synchron und direkt auf `127.0.0.1` mit einem 0,3-Sekunden-Socket-Timeout zu.

---

## 3. Die DSGVO-Statusleuchten in der Benutzeroberfläche

Am unteren Rand der linken Navigationsleiste (Sidebar Footer) befinden sich zwei permanente Indikatoren:

```
[●] LOKAL     [●] DSGVO
```

### Farb- und Statusmatrix:

| Indikator | Farbe | Bedeutung |
|---|---|---|
| **LOKAL** | **Grün** | Lokale LLM-Engine (LM Studio oder Ollama) ist erreichbar **und** das Routing für sensible Daten ist aktiv geschaltet. |
| **LOKAL** | **Gelb** | Lokale LLM-Engine antwortet, Routing sensibler Daten ist jedoch in den Einstellungen deaktiviert. |
| **LOKAL** | **Grau** | Keine lokale Engine gefunden (Weder LM Studio noch Ollama aktiv). |
| **DSGVO** | **Grün** | Zero-Egress oder EU-Fallback (Mistral AI EU) ist aktiv. Daten verlassen nicht den DSGVO-Geltungsbereich. |
| **DSGVO** | **Rot** | Datenschutz-Routing ist deaktiviert; sensible Daten würden über globale US-Endpunkte geleitet. |

Ein Klick auf die Fußzeilenleuchten öffnet direkt das Einstellungsmodal für Datenschutz & LLM-Provider.

---

## 4. REST-API Schnittstellen

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/llm-providers/privacy-status` | Liefert den aggregierten Datenschutzstatus, erkannte lokale Engines und EU-Fallback-Zustand. |
| `POST` | `/api/llm-providers/privacy-routing` | Schaltet das Datenschutz-Routing um (`{"enabled": true\|false}`). |
| `POST` | `/api/llm-providers/test-connection` | Testet gezielt einen lokalen oder Remote-Provider auf Latenz und Verfügbarkeit. |

---

## 5. Konfiguration & Schwellenwerte

Die Konfiguration wird in `config/privacy_settings.json` persistent gespeichert:

```json
{
  "sensitive_routing_enabled": true,
  "preferred_local_provider": "lm_studio",
  "local_port": 1234,
  "eu_fallback_provider": "mistral_ai",
  "data_categories_zero_egress": [
    "FINANCE_INVOICE",
    "LEGAL_CONTRACT",
    "CRM_CUSTOMER_DATA",
    "HR_EMPLOYEE_FILE"
  ]
}
```
