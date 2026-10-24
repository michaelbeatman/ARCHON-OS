# Third-Party Licenses & Attributions

Archon OS is committed to open-source transparency and copyright compliance. This document details the open-source components, prompt architectures, and libraries utilized within Archon OS and the Archon Prompt Studio.

---

## 1. Archon Prompt Studio (Enterprise Prompt Templates)

- **Author / Copyright**: Archon OS Project
- **License**: MIT License / Open Source
- **Description**: The 824 parametric prompt templates in `prompt_studio_catalog.json` are native clean-room prompt architectures developed for Archon OS. They employ Archon's 4-tier structured framework:
  1. `AUFTRAG & ROLLE`: System context, persona, and objective.
  2. `EINGABE-PARAMETER`: Form-bound variable injection and context mapping.
  3. `METHODISCHE AUSARBEITUNG`: Systematic step-by-step reasoning and domain execution steps.
  4. `ARCHON OS GOVERNANCE & PHRASEN-VERBOT`: Anti-hallucination, strict factual grounding, and cliché elimination.

---

## 2. Fabric Patterns (Daniel Miessler)

- **Project**: Fabric (`https://github.com/danielmiessler/fabric`)
- **Author**: Daniel Miessler
- **License**: MIT License
- **Integration**: Archon OS integrates 255 curated Fabric pattern SOPs under the Fabric categories.

### Fabric MIT License Text:

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

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 3. Frontend & UI Libraries

### Lucide Icons
- **Project**: Lucide (`https://lucide.dev`)
- **License**: ISC License
- **Copyright**: (c) Lucide Contributors

### Tailwind CSS
- **Project**: Tailwind CSS (`https://tailwindcss.com`)
- **License**: MIT License
- **Copyright**: (c) Tailwind Labs, Inc.

### FastAPI & Uvicorn
- **License**: MIT License / BSD 3-Clause
- **Copyright**: (c) Sebastián Ramírez / Encode OSS
