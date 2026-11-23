# Workflow-Station: Konfigurationsmodell (Design-Spec)

**Status:** Entwurf, freigegeben zur Umsetzung (Entscheidungen vom 22.11.2026).
**Ziel:** Eine Station vollumfänglich präzise konfigurieren können – inkl. Kontextfenster, SOUL, Anhängen, Agent, Budget, HITL – **ohne** die Matrix zu überladen und **ohne** einen zweiten, abweichenden Dialog neu zu bauen.

---

## 1. Entscheidungen

1. **Rechter Inspektor bleibt primär** (bereits verbreitert): alle *wichtigen* Parameter direkt dort.
2. **Zusätzlich ein Vollbild-Dialog** (Vorbild: Settings-Modal): Editor + alle Zusatzeingaben/Optionen. Aufteilung in drei Spalten:
   - **Mitte (breit):** Prompt/Editor, SOUL, Kontext, Modell/Reasoning, Budget, HITL, Zeitplan – im Wesentlichen die Felder aus „Neue autonome Aufgabe" (`static/index.html:10128-10335`).
   - **Rechtes Drittel:** **baustein-spezifische Parameter**, generiert aus `params_schema` des Node-Plugins. Hier liegen auch die ~40 Parameter eines Videoschnitt-Bausteins – gruppiert und durchsuchbar.
   - **Links (schmal):** Stations-Metadaten, Typ, Herkunft/Preset, Kopfzeile.
3. **Kontext wird referenziert, nicht kopiert.** Ein Upload wird einmalig in einem **Kontext-Paket** abgelegt; die Station speichert nur die `ctx_…-Referenz` inkl. Token-Budget-Anzeige.

## 2. Begriffsmodell

| Begriff | Bedeutung |
|---|---|
| **Baustein** | Typ in der Palette (`plugin_id`, `params_schema`, Defaults) |
| **Station** | Instanz auf der Matrix: `node_id`, `type`, `position`, `config_overlay`, `context_refs` |
| **Knoten** | Laufzeit-Repräsentation im DAG (`workflow_node_states`) |

## 3. Datenmodell

### Station (in `config/workflow_templates.json`)
```json
{
  "id": "n_cut_1",
  "type": "ffmpeg",
  "title": "Clip 9:16",
  "position": { "x": 240, "y": 120 },
  "config_overlay": {
    "mode": "clip_cut",
    "duration_sec": 30,
    "crf": 23
  },
  "task_config": {
    "soul_mode": "pro",
    "provider": "omniroute",
    "model": "",
    "reasoning": "medium",
    "token_budget": 120000,
    "cost_limit_usd": 0.5,
    "require_hitl": false,
    "tool_preset": "code"
  },
  "context_refs": ["ctx_8f3a...", "@upstream.n_research.synthesis"],
  "preset_id": "video-short-9x16"
}
```

**Nur Abweichungen** werden gespeichert (`config_overlay`). Ein `resolved_config` entsteht zur Laufzeit aus
`Plugin-Defaults + Profil-Defaults + config_overlay + aufgelöste {{upstream…}}-Referenzen`.

### Kontext-Paket
```
data/context_packages/
  manifest.json
  ctx_8f3a.../
    source.pdf              # sanitized filename, path-jail
    meta.json               # original_name, mime, size, sha256, tokens_est, scope, acl, created_at, ttl
```
- Upload via `POST /api/context-packages` (Multipart, `require_admin_or_503`, Größenlimit wie `/api/chat/upload` = 25 MB, `utils.path_jail`).
- `GET /api/context-packages` → Auswahl im Kontext-Tab des Stations-Dialogs.
- Referenz in der Station: `ctx_<id>`. Löschen eines Pakets != Löschen der Referenz (Auflösung meldet `missing`).
- Scope/ACL/TTL stammen aus dem bestehenden Memory-Scope-Modell (`private/shared/project/global`).
- Kontextpakete sind **wiederverwendbar** über mehrere Stationen und über mehrere Workflows.

## 4. Schema-Erweiterung (bereits vorhanden: `params_schema`)

Neue, additive Felder pro Parameter:

```python
{
  "key": "crf",
  "label": "Qualität (CRF)",
  "type": "number",
  "default": 21,
  "min": 14, "max": 35, "step": 1,
  "group": "Encode",        # NEU: Gruppierung im rechten Drittel
  "advanced": True,         # NEU: hinter „+ Optionen"
  "help": "Niedriger = besser, langsamer",  # NEU: Tooltip
  "context_ref": False      # NEU: True = Feld akzeptiert ctx_-Referenzen
}
```

Helper in `backend/workflow_node_plugins.py`:
- `get_plugin_schema(plugin_id) -> dict`
- `split_schema_fields(fields) -> (primary: list, advanced: list, groups: dict)`
- `resolve_node_config(plugin_id, overlay: dict, upstream: dict) -> dict` (Defaults + Overlay + `resolve_upstream_templates`, Validierung gegen `min/max/options`)
- `validate_node_config(plugin_id, overlay) -> list[str]`

## 5. UI-Aufbau

### 5.1 Inspektor (rechte Seite, schmal)
- Stations-Titel, Typ-Badge, SOUL-Modus, Agent, 1–2 Top-Plugin-Parameter (`primary`).
- Button **„⚙ Vollständig konfigurieren"** → Dialog.
- Badges: `Geerbt`, `Full-SOUL`, `2 Kontext-Pakete`, `4 erweiterte Parameter`.

### 5.2 Vollbild-Dialog (Drei-Spalten)
- **Links:** Stations-Metadaten, Typ, Preset, Herkunft, Validierungsstatus.
- **Mitte:** Tabs `Ziel` / `Identität` / `Kontext` / `Werkzeuge` / `Grenzen` / `Zeitplan`. Enthält die vorhandenen Felder aus „Neue autonome Aufgabe" – **dieselben IDs/Callbacks wiederverwenden**, nicht duplizieren.
- **Rechts:** `params_schema` des Bausteins, gruppiert nach `group`, mit Suche und **„+ Optionen"** für `advanced: True`. 40 Parameter bleiben beherrschbar, weil nur 5–8 sichtbar sind.
- **Kontext-Tab:** Auswahl vorhandener Kontext-Pakete + Upload-Button; Token-Budget-Meter; `@`-Referenzen auf Upstream-Outputs.

### 5.3 Karte auf der Matrix
Nur Identität + 2–3 Kennzahlen, z. B. `🎬 FFmpeg · 9:16 · 30 s · 4 Kontext-Pakete`.

## 6. Umsetzungsphasen

| Phase | Inhalt | Aufwand |
|---|---|---|
| **P1** | Schema-Helper + `advanced`/`group`/`help` an Core-Plugins; `resolve_node_config` im DAG nutzen |Backend, klein |
| **P2** | Kontext-Pakete: Tabelle/Dateiablage, Upload/List/Delete-Endpunkte, `ctx_`-Auflösung beim Dispatch |Backend, mittel |
| **P3** | Vollbild-Dialog (Drei-Spalten), Wiederverwendung der Aufgaben-Felder, schema-generiertes Rechtes Drittel |Frontend, groß |
| **P4** | Inspektor-Badges, Presets („Als Vorlage speichern"), Validierung vor Speichern/Start |Frontend, mittel |

## 7. Offene Punkte

- Soll der Dialog **live speichern** (wie Settings) oder explizit „Übernehmen"? → Vorschlag: explizit, mit „Ungespeicherte Änderungen"-Marker.
- Wie werden `ctx_`-Referenzen beim **Klonen einer Vorlage** behandelt? → Vorschlag: Referenz bleibt, Paket wird nicht kopiert (mit Hinweis bei `missing`).
- Token-Schätzung: `len(text)/4` als Näherung oder echter Tokenizer? → Vorschlag: Näherung + `tiktoken` optional.
