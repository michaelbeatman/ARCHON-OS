# Third-Party Licenses, Synthetic Media Disclosure & Regulatory Notices

Archon OS is committed to open-source transparency, intellectual property compliance, and regulatory clarity. This document details the open-source components, prompt architectures, synthetic media assets, and regulatory disclaimers governing Archon OS.

---

## 1. Archon OS Core & Prompt Studio (Enterprise Prompt Templates)

- **Author / Copyright**: Michael Keller / Archon OS Project
- **License**: MIT License (see `LICENSE`)
- **Description**: The 824+ parametric prompt templates in `prompt_studio_catalog.json` and the 70 specialist `SOUL.md` directives are clean-room prompt architectures developed for Archon OS.

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

The 70 specialist agent profiles in Archon OS (including legal, tax, financial, real-estate, medical, pharmaceutical, and chemical personas) operate strictly as **AI-assisted analysis, structuring, and drafting tools (Decision Support)**.
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

### Frontend Vendor Assets (`static/`)
- **Lucide Icons (`static/vendor/lucide.min.js`)**: ISC License (`(c) Lucide Contributors`)
- **Tailwind CSS (`static/js/tailwind.cdn.js`)**: MIT License (`(c) Tailwind Labs, Inc.`)
- **Marked (`static/marked.min.js`)**: MIT License (`(c) Christopher Jeffrey`)
- **DOMPurify (`static/vendor/dompurify.min.js`)**: Apache-2.0 OR MPL-2.0 (`(c) Cure53`)
- **Chart.js (`static/vendor/chart.umd.min.js`)**: MIT License (`(c) Chart.js Contributors`)
- **3d-force-graph / Three.js (optional interactive graph views)**: MIT License (`(c) Vasco Asturiano / Three.js Authors`)
