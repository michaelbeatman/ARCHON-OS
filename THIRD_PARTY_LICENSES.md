# Third-Party Licenses, Synthetic Media Disclosure & Regulatory Notices

Archon OS is committed to open-source transparency, intellectual property compliance, and regulatory clarity. This document details the open-source components, prompt architectures, synthetic media assets, and regulatory disclaimers governing Archon OS.

---

## 1. Archon OS Core & Prompt Studio (Enterprise Prompt Templates)

- **Author / Copyright**: Michael Keller / Archon OS Project
- **License**: MIT License (see `LICENSE`)
- **Description**: The 832 parametric prompt templates in `prompt_studio_catalog.json` and the 71 agent `SOUL.md` directives are clean-room prompt architectures developed for Archon OS.

---

## 2. Hermes Agent Runtime & Orchestration Prompts (Nous Research)

- **Project**: Hermes Agent (`https://github.com/NousResearch/hermes-agent`)
- **Author**: Nous Research
- **License**: Apache License 2.0
- **Integration**: Archon OS integrates with the Hermes Agent runtime and CLI orchestration protocol.

---

## 3. Fabric Patterns (Daniel Miessler)

- **Project**: Fabric (`https://github.com/danielmiessler/fabric`)
- **Author**: Daniel Miessler
- **License**: MIT License
- **Integration**: Archon OS integrates curated Fabric pattern SOPs under the Fabric categories.

```text
MIT License
Copyright (c) 2024 Daniel Miessler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

---

## 4. Synthetic AI-Generated Profile Avatars (`static/avatars/`)

- **Origin**: All portrait images in `static/avatars/avatar_*.jpg` are 100% synthetic AI-generated portraits created via Google Gemini image generation (`Nano Banana 2`).
- **Personality Rights (§ 22 KUG / GDPR)**: The avatars depict fictional, non-existent personas color-coded by functional domain. No real living or deceased individuals are depicted.

---

## 5. Regulatory & Professional Liability Notice (RDG / StBerG / WpHG / EU-MDR)

The 71 agent profiles in Archon OS (including legal, tax, financial, real-estate, medical, pharmaceutical, and chemical personas) operate strictly as **AI-assisted analysis, structuring, and drafting tools (Decision Support)**.
- They do **not** provide binding legal services (§ 3 RDG), tax consultancy (§ 5 StBerG), financial/investment advice (§ 2 WpHG), or clinical medical diagnosis/treatment (Art. 2 EU MDR 2017/745).
- Regulated profiles automatically display an interactive compliance notice in the Archon OS UI upon selection.

---

## 6. Frontend & Backend Open-Source Libraries

### Backend Python Packages
- **FastAPI & Starlette**: MIT / BSD-3-Clause (`(c) Sebastián Ramírez / Encode OSS`)
- **Uvicorn**: BSD-3-Clause (`(c) Encode OSS`)
- **Pydantic**: MIT License (`(c) Samuel Colvin and contributors`)
- **HTTPX & httpcore / requests**: BSD-3-Clause / Apache-2.0 (`(c) Encode OSS / PSF`)
- **aiofiles / python-dotenv / python-multipart / watchfiles / watchdog**: Apache-2.0 / BSD-3-Clause / MIT
- **PyYAML / websockets / orjson**: MIT / BSD-3-Clause / Apache-2.0
- **Pillow / pypdf / pdfplumber / python-docx**: HPND / BSD-3-Clause / MIT
- **openai / edge-tts**: Apache-2.0 / GPL-3.0 (edge-tts CLI/library interface invoked for local voice synthesis)
- **pytest / pytest-xdist**: MIT License

### Development / CI tooling (nicht zur Laufzeit)

Folgende Pakete werden **ausschliesslich zur Entwicklung und in der CI** eingesetzt.
Sie sind **Dev-only, keine Produktiv-Abhängigkeit**: sie werden nicht zur Laufzeit
von Archon OS importiert und nicht in `requirements.lock.txt` (Produktiv-Lock) geführt.
Wo ein Eintrag in `requirements-ci.lock.txt` existiert, ist das Artefakt dort per
`--hash=sha256:…` fixiert; Installation nur via
`pip install --require-hashes --no-deps -r requirements-ci.lock.txt`.
Die Lizenzangaben folgen den Upstream-Projektmetadaten; die Pakete werden nicht
im Repo vendoriert, sondern zur Laufzeit der CI aus dem Hash-Lock installiert.

**Versionshinweis:** In dieser Dokumentations-Session war die Shell gesperrt
(`pwsh.exe: Zugriff verweigert, os error 5`). `.venv\Scripts\*.exe --version`
konnte daher **nicht** ausgeführt werden. Bei Tools ohne Hash-Lock-Eintrag steht
deshalb ehrlich „lokal installiert, Version im Scan-Log" — es wird keine Version
erfunden. Bei Tools mit Eintrag ist die Version die des tatsächlich im Lockfile
stehenden pins. Details: `docs/system/STATIC_ANALYSIS_TOOLCHAIN_GUIDE.md`.

**Alle Zeilen dieser Tabelle sind Dev-only = „ja"**: kein Runtime-Import, kein
Eintrag im Produktiv-Lock. Der Scanner-Lauf ist read-only und schreibt ausschliesslich
nach `audit_reports/tool_scans/*.txt` (siehe `scripts/run_static_toolchain.ps1`).

| Tool | Version | Lizenz / Copyright | Zweck | Dev-only | Hash-Pin in `requirements-ci.lock.txt` |
|---|---|---|---|---|---|
| **mypy** | 2.4.1 (Lock) | MIT License, (c) Jukka Lehtosalo / mypy contributors | Statisches Typ-Gate für Python (siehe `docs/system/MYPY_TYPE_GATE_GUIDE.md`); SSOT `mypy.ini` | ja | ja — `mypy==2.4.1`, 4 `--hash=sha256:…` (Zeile 165) |
| **pytest / pytest-xdist** | siehe `requirements-test.lock.txt` | MIT License | Unit-/Regressions-Suites, auch für die CI-Quality-Gates | ja | nein — eigenes Test-Lockfile |
| **ruff** | 0.17.6 (Lock) | MIT License, (c) Astral Software Inc. | Linting: kritische Fehlerklassen E9/F63/F7/F82 + Changed-Files-Ratchet (E,F,I ohne E501) | ja | ja — `ruff==0.17.6`, 3 `--hash=sha256:…` (Zeile 287) |
| **vulture** | lokal installiert, Version im Scan-Log | MIT License | Toter Code / unerreichbare Symbole → Hinweis auf „verdrahteten Schein" (§0) | ja | nein — kein Eintrag im Hash-Lock |
| **radon** | lokal installiert, Version im Scan-Log | MIT License | Komplexität (Cyclomatic Complexity) / God-Objects | ja | nein — kein Eintrag im Hash-Lock |
| **import-linter** (`lint-imports`) | lokal installiert, Version im Scan-Log | MIT License | Layergrenzen `archon` ↔ `backend`; SSOT `.importlinter` (Contract `backend-no-router-imports`) | ja | nein — kein Eintrag im Hash-Lock |
| **detect-secrets** | lokal installiert, Version im Scan-Log | Apache-2.0, (c) Yelp | versehentlich committete Secrets / Credentials (`scan --all-files`) | ja | nein — kein Eintrag im Hash-Lock |
| **bandit** | 1.9.4 (Lock) | Apache-2.0, (c) PyCQA / OpenStack | SAST, hartes CI-Gate auf HIGH-Severity-Funde | ja | ja — `bandit==1.9.4`, 2 `--hash=sha256:…` (Zeile 32) |
| **pip-audit** | 2.10.1 (Lock) | Apache-2.0, (c) PyPA / Trail of Bits | Bekannte CVEs in den hash-geprüften Lockdateien | ja | ja — `pip-audit==2.10.1`, 2 `--hash=sha256:…` (Zeile 202) |
| **semgrep** | lokal installiert, Version im Scan-Log | LGPL-3.0, (c) Semgrep Inc. | Taint-/Policy-Regeln (Egress, Body-Actor, HITL-Skip); lokaler Lauf mit `p/ci` | ja | nein — kein Eintrag im Hash-Lock |
| **coverage** | 7.17.5 (Lock) | Apache-2.0, (c) Ned Batchelder | nie ausgeführte Pfade; CI führt `coverage run -m pytest tests/ -q` + `coverage report` aus | ja | ja — `coverage==7.17.5`, 4 `--hash=sha256:…` (Zeile 68) |
| **pyright** | unbekannt (Shell gesperrt; kein Scan im Skript) | MIT License, (c) Microsoft | strengere Typen als mypy — Ideen-Pool, noch **nicht** im Scanner-Skript und ohne CI-Gate | ja | nein — kein Eintrag im Hash-Lock |
| **cyclonedx-bom** (`cyclonedx-py`) | 9.0.0 (Lock) | Apache-2.0, (c) OWASP CycloneDX contributors | Erzeugung der CycloneDX-1.5-SBOM aus den Hash-Locks | ja | ja — `cyclonedx-bom==9.0.0`, 2 `--hash=sha256:…` (Zeile 75) |

Beispiel-Hash-Pin (mypy 2.4.1, Auszug aus `requirements-ci.lock.txt`):

```text
mypy==2.4.1 \
    --hash=sha256:1784648d6ec8c2b5465e3f26241b845a0b3cb4e56c993c64abe16989e7698999 \
    --hash=sha256:1fb70621535c22fd4b1a0450d37ed1d6c5eb39656a1cebfb189084c12de54ba7 \
    --hash=sha256:63b590965691e540a335fa74dadf31a7069142f6b72e234689bbd244edf55623 \
    --hash=sha256:680ba5d9f0e3fe0c746b3d14df15f2a718e4bc308a1145616a1ea691ce7c354b
```

**Hinweis:** Dev-only, keine Produktiv-Abhängigkeit. Ein Upgrade der hash-gepinnten
Tools erfolgt ausschliesslich über eine bewusste Aktualisierung des Hash-Lockfiles,
nicht über Versionsbereiche in der Laufzeitumgebung. Fehlende Hash-Pins werden
nicht erfunden; sie sind als offene Aufgabe im
`docs/system/STATIC_ANALYSIS_TOOLCHAIN_GUIDE.md` vermerkt. Ein
„Clean-Code-Zertifikat" wird erst bei vollständig sauberem Stand ausgestellt —
der aktuelle Stand ist es nicht (siehe Ideen-Pool in `docs/system/ROADMAP_2026.md`).

### Frontend Vendor Assets (`static/`)
- **Lucide Icons (`static/vendor/lucide.min.js`)**: ISC License (`(c) Lucide Contributors`)
- **Tailwind CSS (`static/js/tailwind.cdn.js`)**: MIT License (`(c) Tailwind Labs, Inc.`)
- **Marked (`static/marked.min.js`)**: MIT License (`(c) Christopher Jeffrey`)
- **DOMPurify (`static/vendor/dompurify.min.js`)**: Apache-2.0 OR MPL-2.0 (`(c) Cure53`)
- **Chart.js (`static/vendor/chart.umd.min.js`)**: MIT License (`(c) Chart.js Contributors`)
- **3d-force-graph / Three.js (optional interactive graph views)**: MIT License (`(c) Vasco Asturiano / Three.js Authors`)
