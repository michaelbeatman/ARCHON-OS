# Contributing to Archon OS

Thank you for contributing to **Archon OS** — the open-source, self-hosted Agentic Operating System built on top of [Hermes Agent (Nous Research)](https://github.com/NousResearch/hermes-agent).

## Ways to Contribute

1. **Specialist Personas (`SOUL.md`) & Domain Skills:** Propose or refine domain specialists across the 8 business & engineering domains (both English and German).
2. **AI Boardroom Frameworks:** Add structured decision-making, risk-audit, or systems-thinking methodologies (`core_dispatcher.py`).
3. **Prompt Studio Templates:** Contribute clean-room parametric prompt workflows (`prompt_studio_catalog.json`).
4. **Core Platform, Connectors & Localization:** Improve FastAPI routers, MCP integrations, ERP/CRM modules, or the 9 UI locales (`static/locales/*.json`).

## Local Development Quickstart

```bash
git clone https://github.com/michaelbeatman/ARCHON-OS.git
cd ARCHON-OS

# Option A: Full Docker Stack (Linux, macOS Intel & Apple Silicon, Windows)
./install.sh          # or setup.bat on Windows

# Option B: Instant Read-Only Showcase Demo (zero API keys required)
ARCHON_DEMO_MODE=true docker compose -f docker-compose.demo.yml up --build -d
```

## Quality & Security Gates Before Opening a PR

1. **Run the test suite:**
   ```bash
   python -m pytest tests/ -q
   ```
2. **Check JavaScript syntax** if frontend scripts were edited:
   ```bash
   node --check static/js/<file>.js
   ```
3. **Verify i18n & Locale Parity** if HTML views or `static/locales/*.json` were modified:
   ```bash
   python -m pytest tests/test_locale_parity.py -q
   ```
4. **Never commit secrets or machine-specific paths:** `.env` files, real tokens, private IPs, or personal user directories must never enter version control.

## License

By contributing to Archon OS, you agree that your contributions will be licensed under the [MIT License](LICENSE).
