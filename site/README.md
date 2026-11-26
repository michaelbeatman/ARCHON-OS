# Archon OS Landing Page & SEO/GEO Hub (`site/`)

Static GitHub Pages site generated from a single source of truth:

- `site/index.template.html` — Landing page template (11 languages)
- `site/i18n/<lang>.json` — Localized translation catalogs (`en`, `de`, `es`, `fr`, `it`, `ja`, `ko`, `nl`, `pt`, `ru`, `zh`)
- `site/assets/site.css` & `site/assets/site.js` — Horological Copperplate × Enterprise Telemetry design system, self-hosted `Geist` / `Geist Mono` fonts, interactive Cockpit switcher, dark/light theme toggle
- `scripts/site_svg_assets.py` — Mathematically meshing animated Copperplate Clockwork, Vault Lock & Zero-Egress circuit SVGs
- `scripts/build_site_i18n.py` — Main build & validation script
- `scripts/build_site_subpages.py` — Phase 3 indexable HTML deep-dive guides & filterable directories (`architecture/`, `gdpr-zero-egress/`, `compare/`, `boardroom-frameworks/`, `specialists/` in EN & DE)

## Regenerate Site

```bash
python scripts/build_site_i18n.py
python scripts/build_site_i18n.py --check
pytest tests/test_site_i18n_parity.py
```

## Phase 3 Custom Domain Migration (1-Command Switch)

When switching from `michaelbeatman.github.io/ARCHON-OS/` to a custom domain (e.g. `archon-os.dev`):

1. Add `site/CNAME` containing your domain (`archon-os.dev`) and configure GitHub Pages DNS records.
2. Regenerate all canonicals, `hreflang`, JSON-LD, `sitemap.xml`, `robots.txt`, and `llms.txt`:

```bash
python scripts/build_site_i18n.py --base-url https://archon-os.dev/
```

## Fallback Backup

The previous site snapshot before the Phase 1–3 upgrade is stored at `backups/site_fallback_20261126/`.
