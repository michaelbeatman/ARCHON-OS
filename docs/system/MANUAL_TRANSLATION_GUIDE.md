# Archon OS System Manual — Translation & Template Guide (DE → EN)

> **Source Master Template:** [ARCHON_OS_SYSTEM_HANDBUCH_2026.docx](ARCHON_OS_SYSTEM_HANDBUCH_2026.docx)  
> **Target Output File:** `docs/system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.docx`

---

## 1. Structural & Formatting Rules (Do Not Break)

1. **Preserve Word Styles:** Keep `Heading 1`, `Heading 2`, `Heading 3`, `Normal` (`10 pt`), `List Bullet`, and table cell fonts (`9.5 pt`) intact so Word's automatic Table of Contents (`TOC`) updates with zero errors.
2. **Page Breaks:** Do **not** inject forced page breaks on every heading; preserve existing chapter breaks only where already configured.
3. **Screenshots:** UI screenshots (`docs/system/screenshots/*.png`) are referenced inside the Word master template. Keep image widths unchanged; only translate captions (`Abb. X: ...` $\rightarrow$ `Fig. X: ...`).
4. **Update TOC After Translation:** Re-open the translated `.docx` in Microsoft Word (`Fields.Update()` on TOC) before exporting PDF/Word release artifacts.

---

## 2. Locked Identifiers & Terminology Mapping (DE → EN)

Translate descriptive prose into natural technical English, **but keep code paths, REST routes, API variables, and specialist IDs exact**:

| German Term (Master DE) | Official English Term (Target EN) | Notes |
|---|---|---|
| Die vier System-Säulen | The Four System Pillars | Fixed product architecture |
| Steuerung & Operation | Control & Operations | Pillar 1 |
| Kognition & Wissen | Cognition & Knowledge | Pillar 2 |
| Wirtschaft & ERP *(alpha)* | Business & ERP *(alpha)* | Pillar 3 — keep `alpha` marker |
| Infrastruktur & Governance | Infrastructure & Governance | Pillar 4 |
| Agenten-Kader (70 Spezialisten) | Specialist Fleet (70 Specialists) | Keep 8 + 5b domain numbering |
| 3-Stufen-SOUL-Mechanik | 3-Tier SOUL Architecture | Keep `SOUL_COMPACT.md`, `SOUL_PRO.md`, `SOUL_FULL.md` |
| AI-Boardroom (55 Frameworks) | AI Boardroom (55 Frameworks) | Keep 6-phase structure |
| Eingang / Triage | Inbox & Event Triage | View #2 |
| Zentralbibliothek / Wissensvault | Central Library & Obsidian Vault | Keep `Personalakten/` / file paths exact |
| Freigabe-Gate (HITL) | Human-in-the-Loop (HITL) Approval Gate | Keep `[T]` trusted badge naming |
| Datenschutz-Routing (Zero Egress) | Zero-Egress Privacy Routing | Keep `OLLAMA_BASE_URL`, `LM_STUDIO_URL` |
| Haftungs- & Berufsrechts-Warndialog | Regulatory & Liability Warning Modal | Adapt DE statutory notes (RDG/StBerG/BauGB) with international note (*"No legal/tax/medical advice"*) |

---

## 3. Master Template Chapter Inventory

| Section | Focus | Status |
|---|---|---|
| **Vorwort & `( ? )` Guide** | System philosophy, 4 pillars, context help | Cleaned (`v0.6.0-rc1`) |
| **0. Installationshinweise** | Hardware, DAU Installer (`setup.bat`/`install.sh`), `INSTALL_AGENT.md` | Updated |
| **1. – 19. Hauptkapitel** | All 19 UI views, 70 specialists in 8 domains, ERP *(Alpha)*, Guardian, Control Center | Clean master |
| **Anhang I – IV** | Practical use cases, full glossary, 55 frameworks, Security & Compliance guides | Clean master |
| **Anhang V (V.1 – V.22)** | DevOps, MCP drivers, Observability, Architecture Audit, **44-Milestone Roadmap (V.21)**, ERP Spec (V.22) | Updated |

---

## 4. Parallel Localization Coordination (Server vs. Docs)

When localizing Archon OS across multiple contributors/models:
- **Server / Code Localization:** Focuses on `agent_profiles.json`, `scripts/sync_soul_modes.py`, `SOUL.md` files under `.hermes/profiles/`, and 55 Boardroom framework prompts.
- **Documentation Localization:** Translates `ARCHON_OS_SYSTEM_HANDBUCH_2026.docx` $\rightarrow$ `ARCHON_OS_SYSTEM_MANUAL_2026_EN.docx` using this terminology mapping table so UI strings, agent IDs, and handbook chapters match 1:1.
