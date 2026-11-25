# HANDOVER — Archon OS SEO/GEO & i18n Setup (2026-11-25)

## Was erledigt ist (live auf https://michaelbeatman.github.io/ARCHON-OS/)

### ✅ SEO/GEO Landingpage (`site/index.html`)
- **JSON-LD Structured Data**: `SoftwareSourceCode` + `SoftwareApplication` + `FAQPage` (4 Fragen) — **Validator: 0 Errors, 0 Warnings**
- **Meta-Tags**: Title, Description, Keywords, Open Graph, Twitter Cards — alle mit v0.5.7.8 Keywords (Passkey HITL, Atomic BudgetBank, Effect-Ledger, Zero-Egress, GDPR/DSGVO, EU AI Act, GoBD)
- **Sichtbare Feature-Karten**: 3 neue v0.5.7 Karten (Passkey HITL, Atomic BudgetBank & Signed Warrants, Crash-Safe Effect-Ledger)
- **Why Archon OS? Block**: Vergleichsabsatz mit 3 konsolidierten WAL-DBs
- **FAQ-Sektion**: Sichtbare 3 Fragen passend zum FAQPage-Schema
- **Version Badge**: `v0.5.7.8` (einheitlich HTML + JSON-LD)
- **Roadmap Link**: `Roadmap & Milestones (M0–M112+)`

### ✅ GEO-Dateien (alle live)
| Datei | Status |
|-------|--------|
| `llms.txt` | ✅ Standard für KI-Crawler (Perplexity, ChatGPT Search, Claude, Gemini) |
| `robots.txt` | ✅ Explizite Erlaubnis: GPTBot, OAI-SearchBot, PerplexityBot, ClaudeBot, Google-Extended |
| `sitemap.xml` | ✅ Mit hreflang für 11 Sprachen + x-default |

### ✅ IndexNow Automation (`.github/workflows/pages.yml`)
- Key: `ecac6512cb55e5cf2c2cbc128fb011880d31a24bbf3e8fcbda3db80e2ecab3b6`
- Key-Datei: `site/ecac6512cb55e5cf2c2cbc128fb011880d31a24bbf3e8fcbda3db80e2ecab3b6.txt`
- Pinged URLs: 11 Sprach-Varianten (en, de, zh, ja, ko, ru, fr, es, it, nl, pt)
- Läuft bei jedem erfolgreichen Deploy automatisch

### ✅ i18n / 11 Sprachen
- **Deutsch (`site/de/index.html`)**: Vollständige Übersetzung + **hreflang-Tags** für alle 11 Sprachen
- **9 weitere Sprachen** (`zh, ja, ko, ru, fr, es, it, nl, pt`): Minimal-Seiten mit `hreflang` + Meta-Refresh zu EN
- **Sitemap.xml**: Vollständig mit `xhtml:link rel="alternate" hreflang` für alle 11 URLs + x-default

---

## Was DU jetzt machst (5 Min manuell)

### 1. Google Search Console
1. https://search.google.com/search-console → Property hinzufügen: `https://michaelbeatman.github.io/ARCHON-OS/` (URL-Präfix)
2. Verifizierung: **HTML-Tag** wählen → Meta-Tag kopieren (`<meta name="google-site-verification" content="...">`)
3. **Gib mir den Tag** → ich baue ihn in `site/index.html` + `site/de/index.html` ein + deploy
4. Danach: Sitemaps → `https://michaelbeatman.github.io/ARCHON-OS/sitemap.xml` einreichen

### 2. Bing Webmaster Tools
1. https://www.bing.com/webmasters → Site hinzufügen (gleiche URL)
2. Verifizierung: **Meta-Tag** (`<meta name="msvalidate.01" content="...">`)
3. **Gib mir den Tag** → ich baue ihn ein + deploy
4. Sitemaps → gleiche sitemap.xml einreichen
   > Wichtig: Bing speist **ChatGPT Search** direkt

### 3. LinkedIn Post (morgen 08:00)
- Dein Text „Ein Gedankenspiel.“ + Quadrat-Bild (109.000 vs 114.000)
- **Kein Link im Haupttext** → ersten Kommentar mit Repo + Quellen

---

## Nächste technische Schritte (nach Verifizierung)

| Task | Aufwand |
|------|---------|
| Google/Bing Meta-Tags einbauen + deploy | 1 Min (ich mach's) |
| Vollständige Übersetzungen für 9 Sprachen (nicht nur Redirect) | Bei Bedarf |
| Baidu (`ziyuan.baidu.com`) / Naver (`searchadvisor.naver.com`) | Erfordert lokale Accounts — später |
| Yandex (`webmaster.yandex.com`) | IndexNow deckt es teilweise ab, manuell besser |

---

## Wichtige URLs
- **Live**: https://michaelbeatman.github.io/ARCHON-OS/
- **Deutsch**: https://michaelbeatman.github.io/ARCHON-OS/de/
- **Sitemap**: https://michaelbeatman.github.io/ARCHON-OS/sitemap.xml
- **llms.txt**: https://michaelbeatman.github.io/ARCHON-OS/llms.txt
- **Validator**: https://validator.schema.org/ (0 Errors, 0 Warnings)

---

## Repo-Zustand
- Branch: `main` (Commit `c8c8d6da` + force-push)
- Deploy: GitHub Pages via `.github/workflows/pages.yml` (site/ Ordner)
- IndexNow Key: `ecac6512cb55e5cf2c2cbc128fb011880d31a24bbf3e8fcbda3db80e2ecab3b6`

---

**Wenn du die beiden Meta-Tags (Google + Bing) hast → kurz hier reinposten, ich deploye sofort.**