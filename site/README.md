# Landingpage & Übersetzungen

Die GitHub-Pages-Seiten unter `site/` werden **generiert**. Bitte nie die
`index.html`-Dateien direkt editieren – Änderungen an `index.html` oder an
`site/<sprache>/index.html` werden beim nächsten Build überschrieben.

## Aufbau

| Datei | Zweck |
|---|---|
| `index.template.html` | Einzige HTML-Quelle mit `{{key}}`-Platzhaltern |
| `i18n/en.json` | EN-Quelltexte (Referenz) |
| `i18n/<lang>.json` | Übersetzungen: `de, es, fr, it, ja, ko, nl, pt, ru, zh` |
| `../scripts/build_site_i18n.py` | Generator + Validierung |
| `../tests/test_site_i18n_parity.py` | Parity-/Regressionstests |

Jeder Katalog muss **dieselben 89 Keys** enthalten. Werte dürfen Inline-HTML
enthalten (`<h3>`, `<h4>`, `<p>`, `<tr>`, `<td>`, `<th>`, `<strong>`, `<code>`,
`<a>`) – dann muss das Markup in jeder Sprache erhalten bleiben. Ein `&` in
HTML-Text muss als `&amp;` geschrieben werden; der Generator prüft das.

## Neu bauen

```bash
python scripts/build_site_i18n.py          # schreibt alle 11 Seiten
python scripts/build_site_i18n.py --check  # nur prüfen (für CI)
pytest tests/test_site_i18n_parity.py -q
```

`create_lang_pages.py` im Repo-Root ist nur noch ein Deprecation-Shim und
delegiert an den Generator.

## Was bewusst auf Englisch bleibt

* JSON-LD (`SoftwareApplication`, `FAQPage`) und `meta keywords` – maschinenlesbare,
  kanonische Metadaten.
* Marken- und Produktnamen: Archon OS, Hermes Agent, OmniRoute, BudgetBank,
  Zero-Egress, AI Boardroom, Mission Control, Obsidian, n8n, Passkey/WebAuthn,
  GoBD, EU AI Act, `/livez`, `ops.db`, `BEGIN IMMEDIATE` usw.
* Shell-Kommandos in `<pre>`-Blöcken, Versions- und Architektur-Badges sowie die
  Sprachnamen im Umschalter (`EN · English`, `DE · Deutsch`, …).

## Screenshots

Die Bilddateien selbst liegen unter `docs/system/screenshots/` und werden für
alle Sprachen als dieselben PNGs von `raw.githubusercontent.com` geladen. Sie
zeigen daher weiterhin die englische UI. **Bildunterschriften und `alt`-Texte
sind übersetzt** (Keys `shots.*`). Echte lokalisierte Screenshots bräuchten neue
Aufnahmen mit auf die jeweilige Locale gestellter UI (`static/locales/*.json`).

## Text ändern

1. `i18n/en.json` anpassen (neuer EN-Text).
2. Alle 10 anderen Kataloge nachziehen.
3. Falls die HTML-Struktur selbst geändert werden soll: `index.template.html`
   anpassen und die Platzhalter-Menge mit den Katalogen abgleichen
   (`--check` meldet fehlende/überzählige Keys).
4. Generator ausführen, Tests laufen lassen.
