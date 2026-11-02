"""
Rebuilds docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx from
the untouched backup in scratch (or docs/system/).

Guarantees:
1. Strict menu-driven sequential order (Vorwort -> Chapters 1..16 -> Appendices I..V).
2. Preserves all original screenshots and embeds all newly captured view/sub-view screenshots
   across all 16 chapters and their sub-tabs.
3. Removes obsolete Chapter 14 (Design System Lab) and eliminates standalone Chapters 16 & 17
   (integrating their autonomy/resilience/sandbox specs cleanly into 14.2 Autonomie & Module).
4. Includes all subheadings (1.1..1.5, 2.1..2.6, 3.1..3.8 with 57 agents, 4.1..4.4, 5.1..5.4,
   6.1..6.3, 7.1..7.3, 8.1..8.3, 9.1..9.4, 10.1..10.3, 11.1..11.2, 12.1..12.3, 13.1..13.3,
   14.1..14.10, 15, 16, Anhang I..V).
"""

import os
import re
import sys
import json
import docx
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH_BACKUP = r"C:\Users\micha\.gemini\antigravity\brain\efaf2cb2-3cad-4959-82eb-00332c4c9566\scratch\ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage_ORIGINAL_BACKUP.docx"
LOCAL_BACKUP = os.path.join(DOCS_DIR, "docs", "system", "backup -ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")
BACKUP_DOCX = SCRATCH_BACKUP if os.path.exists(SCRATCH_BACKUP) else (LOCAL_BACKUP if os.path.exists(LOCAL_BACKUP) else (os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage_NEU.docx") if os.path.exists(os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage_NEU.docx")) else os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")))
TARGET_DOCX = os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")
IMG_DIR = os.path.join(DOCS_DIR, "docs", "system", "screenshots")


def load_agents_data():
    inv_file = os.path.join(DOCS_DIR, "data", "eu_ai_act_inventory.json")
    prof_file = os.path.join(DOCS_DIR, "data", "agent_profiles.json")

    inventory = []
    if os.path.exists(inv_file):
        with open(inv_file, "r", encoding="utf-8") as f:
            inventory = json.load(f)

    profiles = []
    if os.path.exists(prof_file):
        with open(prof_file, "r", encoding="utf-8") as f:
            profiles = json.load(f)

    prof_map = {p.get("id"): p for p in profiles}
    by_cat = {}
    for a in inventory:
        cat = a.get("category", "7. Tech, Software & Data")
        by_cat.setdefault(cat, []).append(a)

    return by_cat, prof_map


def read_guide(rel_path):
    full_path = os.path.join(DOCS_DIR, rel_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def rebuild_clean_docx():
    print(f"Loading untouched backup: {BACKUP_DOCX}")
    doc = docx.Document(BACKUP_DOCX)
    body = doc.element.body
    orig = list(body)
    print(f"Original body element count: {len(orig)}")

    para_map = {p._element: p for p in doc.paragraphs}

    def set_el_text(el, new_text, new_style=None):
        p = para_map.get(el)
        if p is not None:
            p.text = new_text
            if new_style:
                p.style = new_style

    def make_p(text, style="Normal"):
        p = doc.add_paragraph(text, style=style)
        el = p._element
        body.remove(el)
        return el

    def make_img(img_id, width_inches=6.4):
        img_path = os.path.join(IMG_DIR, f"{img_id}.png")
        if not os.path.exists(img_path):
            print(f"  [WARN] Screenshot not found: {img_path}")
            return None
        p_img = doc.add_paragraph()
        p_img.paragraph_format.space_before = Pt(4)
        p_img.paragraph_format.space_after = Pt(8)
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p_img.add_run()
        run.add_picture(img_path, width=Inches(width_inches))
        el = p_img._element
        body.remove(el)
        return el

    def append_img(target_list, img_id, width_inches=6.4):
        el = make_img(img_id, width_inches=width_inches)
        if el is not None:
            target_list.append(el)

    def make_bullets(items):
        els = []
        for item in items:
            els.append(make_p(item, style="List Bullet"))
        return els

    def make_callout(text):
        return make_p(f"📖 Vertiefender Leitfaden: {text}", style="Normal")

    def clean_md_inline(text):
        if not text:
            return ""
        # Remove internal task IDs like (t-6fad7a) or (`t-7ca8cd`)
        text = re.sub(r"\s*\(`?t-[0-9a-f]{6}`?\)", "", text)
        # Convert markdown links [label](url) -> label
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        return text.strip()

    def add_formatted_runs(p, text):
        text = clean_md_inline(text)
        if not text:
            return
        tokens = re.split(r"(\*\*.*?\*\*|`[^`]+`)", text)
        for tok in tokens:
            if not tok:
                continue
            if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
                r = p.add_run(tok[2:-2])
                r.bold = True
            elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
                r = p.add_run(tok[1:-1])
                r.font.name = "Consolas"
                r.font.size = Pt(9.5)
            else:
                p.add_run(tok)

    def make_md_table(table_lines):
        parsed_rows = []
        for tl in table_lines:
            inner = tl.strip().strip("|")
            cells = [c.strip() for c in inner.split("|")]
            # Skip separator row like |---|---|
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                continue
            parsed_rows.append(cells)
        if not parsed_rows:
            return None
        num_cols = max(len(r) for r in parsed_rows)
        if num_cols == 0:
            return None
        tbl = doc.add_table(rows=len(parsed_rows), cols=num_cols)
        tbl.style = "Table Grid"
        for r_idx, row_cells in enumerate(parsed_rows):
            row_obj = tbl.rows[r_idx].cells
            for c_idx in range(num_cols):
                val = row_cells[c_idx] if c_idx < len(row_cells) else ""
                p_cell = row_obj[c_idx].paragraphs[0]
                p_cell.text = ""
                if r_idx == 0:
                    clean_hdr = clean_md_inline(val).replace("**", "").replace("`", "")
                    run = p_cell.add_run(clean_hdr)
                    run.bold = True
                else:
                    add_formatted_runs(p_cell, val)
        el = tbl._element
        body.remove(el)
        return el

    def make_guide_elements(title, rel_path):
        els = [make_p(title, style="Heading 2")]
        text = read_guide(rel_path)
        if not text:
            return els

        lines = text.splitlines()
        in_code_block = False
        code_lines = []
        table_lines = []

        def flush_code():
            nonlocal code_lines
            if not code_lines:
                return
            code_text = "\n".join(code_lines).strip()
            if code_text:
                p = doc.add_paragraph(style="Normal")
                p.paragraph_format.left_indent = Pt(14)
                p.paragraph_format.space_before = Pt(3)
                p.paragraph_format.space_after = Pt(6)
                r = p.add_run(code_text)
                r.font.name = "Consolas"
                r.font.size = Pt(9)
                el = p._element
                body.remove(el)
                els.append(el)
            code_lines = []

        def flush_table():
            nonlocal table_lines
            if not table_lines:
                return
            tbl_el = make_md_table(table_lines)
            if tbl_el is not None:
                els.append(tbl_el)
            table_lines = []

        for raw_line in lines:
            stripped = raw_line.strip()

            # Handle fenced code blocks
            if stripped.startswith("```"):
                if table_lines:
                    flush_table()
                if in_code_block:
                    flush_code()
                    in_code_block = False
                else:
                    in_code_block = True
                    code_lines = []
                continue

            if in_code_block:
                code_lines.append(raw_line.rstrip("\r\n"))
                continue

            # Handle Markdown pipe tables
            if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
                table_lines.append(stripped)
                continue
            elif table_lines:
                flush_table()

            if not stripped or stripped in ("---", "***", "___"):
                continue

            # Skip redundant top-level # H1 title (already represented by Heading 2 `title`)
            if stripped.startswith("# "):
                continue

            # Render ## and ### inside guides as clean bold sub-section headers (Normal style, not Heading!)
            if stripped.startswith("## "):
                sub_title = clean_md_inline(stripped.lstrip("#").strip()).replace("**", "").replace("`", "")
                p = doc.add_paragraph(style="Normal")
                p.paragraph_format.space_before = Pt(10)
                p.paragraph_format.space_after = Pt(3)
                p.paragraph_format.keep_with_next = True
                r = p.add_run(sub_title)
                r.bold = True
                r.font.size = Pt(11)
                el = p._element
                body.remove(el)
                els.append(el)
                continue

            if stripped.startswith("### ") or stripped.startswith("#### "):
                sub_title = clean_md_inline(stripped.lstrip("#").strip()).replace("**", "").strip("`")
                p = doc.add_paragraph(style="Normal")
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.keep_with_next = True
                r = p.add_run(sub_title)
                r.bold = True
                r.font.size = Pt(10)
                el = p._element
                body.remove(el)
                els.append(el)
                continue

            # Bullet list items
            if stripped.startswith("- ") or stripped.startswith("* "):
                p = doc.add_paragraph(style="List Bullet")
                add_formatted_runs(p, stripped[2:].strip())
                el = p._element
                body.remove(el)
                els.append(el)
                continue

            # Numbered list items
            if re.match(r"^\d+\.\s+", stripped):
                p = doc.add_paragraph(style="Normal")
                p.paragraph_format.left_indent = Pt(12)
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(2)
                add_formatted_runs(p, stripped)
                el = p._element
                body.remove(el)
                els.append(el)
                continue

            # Blockquotes
            if stripped.startswith(">"):
                q_text = stripped.lstrip(">").strip()
                if q_text:
                    p = doc.add_paragraph(style="Normal")
                    p.paragraph_format.left_indent = Pt(12)
                    add_formatted_runs(p, q_text)
                    el = p._element
                    body.remove(el)
                    els.append(el)
                continue

            # Standard paragraph line
            p = doc.add_paragraph(style="Normal")
            add_formatted_runs(p, stripped)
            el = p._element
            body.remove(el)
            els.append(el)

        if in_code_block:
            flush_code()
        if table_lines:
            flush_table()

        return els

    # Update metadata line in frontmatter (Child 6)
    set_el_text(
        orig[6],
        "Stand: 1. November 2026  |  Release: 0.3.7 Enterprise (4-Säulen-ERP)  |  57 Autonome Spezialisten-Rollen  |  19 Fachmodule"
    )

    # Clean internal headings in original slices before re-slicing
    set_el_text(orig[121], "1.2.1 4-Augen Qualitäts-Gate & Revisor-Freigabe (Auto-Validation)", "Heading 3")
    set_el_text(orig[224], "3.1.1 Modell-Wechsel & Provider-Wahl (KI-Routenwahl)", "Heading 3")
    set_el_text(orig[239], "3.1.2 360°-Dossier & Messenger-Rufname", "Heading 3")
    set_el_text(orig[372], "4.4.1 Interaktive Code-Sandbox & Live-Artefakt-Vorschau", "Heading 3")
    set_el_text(orig[530], "6.1.1 Mehrstufige Reflexions-Schleife (Deep Research v2)", "Heading 3")

    # Clean former 16.x and 17.x headings so they integrate cleanly under 17.2 Autonomie & Module
    set_el_text(orig[672], "17.2.1 Replay & Time-Travel Debugging (Execution Trace Player & State-Forker)", "Heading 3")
    set_el_text(orig[680], "17.2.2 Multi-Modell Head-to-Head Benchmark & Eval-Matrix (OmniRoute Arena)", "Heading 3")
    set_el_text(orig[687], "17.2.3 Dual- & Tri-Agent Konsens-Gate & Schiedsgericht (Debate / Voting Protocol)", "Heading 3")
    set_el_text(orig[694], "17.2.4 Autonome Task-Selbstheilung mit Git- & Snapshot-Rollback", "Heading 3")
    set_el_text(orig[701], "17.2.5 Event-Mesh & Webhook-Trigger-Brücke (Inbound Automation & Directory Watcher)", "Heading 3")
    set_el_text(orig[712], "17.2.6 Flüchtige Code-Sandboxen (Ephemeral Micro-Containers & Runner)", "Heading 3")
    set_el_text(orig[719], "17.2.7 Nächtliche Gedächtnis-Konsolidierung & Sleep-Cycle Wartung", "Heading 3")
    set_el_text(orig[726], "17.2.8 Headless-Browser & Visueller Web-Agent (Playwright Screenshot-Audit)", "Heading 3")
    set_el_text(orig[733], "17.2.9 Virtueller Pre-Mortem Stresstest (War-Room-Simulation)", "Heading 3")
    set_el_text(orig[740], "17.2.10 SLA- & Übergabe-Verträge zwischen Agenten (Contract Enforcement)", "Heading 3")

    new_body = []

    # =========================================================================
    # VORWORT & FRONTMATTER (0..65)
    # =========================================================================
    new_body.extend(orig[0:65])

    # =========================================================================
    # 1. OPERATIONS – OPERATIVE PROJEKTSTEUERUNG & FUNK
    # =========================================================================
    new_body.append(make_p("1. Operations – Operative Projektsteuerung & Funk", "Heading 1"))
    new_body.extend(orig[102:105])  # Intro to Operations

    # 1.1 Mission Control
    new_body.append(make_p("1.1 Mission Control", "Heading 2"))
    new_body.extend(orig[66:101])   # Mission Control content + screenshot (67) + KPI table (99)

    # 1.2 Kanban
    new_body.append(make_p("1.2 Kanban", "Heading 2"))
    new_body.extend(orig[106:127])  # Kanban screenshot (106), content, 4-Augen Gate (121..126)
    new_body.append(make_p(
        "Deal-Pipeline & Vertriebs-Integration (t-5b159d): Neben klassischen Projektaufgaben unterstützt das Kanban-Board "
        "eine B2B-Vertriebspipeline mit den Phasen Lead, Qualified, Proposal, Negotiation, Closed Won und Closed Lost "
        "inklusive gewichteter Umsatzprognose (Forecast).",
        "Normal"
    ))
    new_body.append(make_callout("Siehe die Spezifikation zu Massenoperationen im Board in Anhang V.7: Kanban Bulk Actions & Massenoperationen."))

    # 1.3 Organisation
    new_body.append(make_p("1.3 Organisation", "Heading 2"))
    new_body.extend(orig[128:140])  # Organigramm screenshot (128) + content + table (139)

    # 1.4 n8n Automatisierung
    new_body.append(make_p("1.4 n8n Automatisierung", "Heading 2"))
    new_body.extend(orig[141:162])  # n8n screenshot (142) + content + tables (150, 159)

    # 1.5 Kommunikation
    new_body.append(make_p("1.5 Kommunikation", "Heading 2"))
    new_body.extend(orig[163:181])  # Funk screenshot (163) + content + table (179)

    # =========================================================================
    # 2. POSTEINGANG & EREIGNIS-STREAM
    # =========================================================================
    new_body.append(make_p("2. Posteingang & Ereignis-Stream", "Heading 1"))

    # 2.1 Übersicht
    new_body.append(make_p("2.1 Übersicht", "Heading 2"))
    new_body.extend(orig[182:200])  # Inbox screenshot (183) + overview content + table (198)
    new_body.append(make_callout("Zur Absicherung aller Eingänge gegen schädliche Manipulationen siehe Anhang IV.3: Dual-LLM Prompt-Injection Guard."))

    # 2.2 Webhooks
    new_body.append(make_p("2.2 Webhooks", "Heading 2"))
    append_img(new_body, "inbox_webhooks")
    new_body.append(make_p(
        "Die Webhook-Ansicht empfängt und protokolliert Echtzeit-Events externer Systeme (GitHub, Stripe, Typeform, "
        "Monitoring-Alarme oder eigene Web-Crawler).",
        "Normal"
    ))
    new_body.extend(make_bullets([
        "HMAC-SHA256 Signaturprüfung (t-803095): Eingehende Payloads werden kryptografisch auf Authentizität und Replay-Schutz geprüft.",
        "Automatische Triage: Validierte Ereignisse werden regelbasiert in strukturierte Aufgaben für den zuständigen Fachagenten umgewandelt."
    ]))

    # 2.3 Intern
    new_body.append(make_p("2.3 Intern", "Heading 2"))
    append_img(new_body, "inbox_intern")
    new_body.append(make_p(
        "Bündelt systeminterne Ereignisse, Eskalationen aus Hintergrundprozessen und Statusmeldungen des Daemon-Kernels.",
        "Normal"
    ))
    new_body.extend(make_bullets([
        "Watchdog-Meldungen bei ungewöhnlichen Laufzeiten, Deadlocks oder Speicherschwellen.",
        "Rückmeldungen autonomer Nachtläufe (Memory Consolidation, Backup-Verifikation, Fristen-Scanner)."
    ]))

    # 2.4 E-Mail
    new_body.append(make_p("2.4 E-Mail", "Heading 2"))
    append_img(new_body, "inbox_email")
    new_body.append(make_p(
        "Zwei-Wege-E-Mail-Synchronisation mit automatischer Kontakt- und Vorgangszuordnung (Auto-Enrichment).",
        "Normal"
    ))
    new_body.extend(make_bullets([
        "Direkter MAPI-Abgleich mit lokal geöffnetem Microsoft Outlook sowie Unterstützung für IMAP/SMTP-Konten.",
        "Automatische Extraktion von Absenderdaten, Signaturen und Anhängen zur Ablage im Kontakt-Dossier.",
        "Vorbereitung von Antwort-Entwürfen durch Kommunikations-Agenten mit anschließender Vorlage zur Freigabe."
    ]))

    # 2.5 Messenger
    new_body.append(make_p("2.5 Messenger", "Heading 2"))
    append_img(new_body, "inbox_messenger")
    new_body.append(make_p(
        "Mobile Echtzeit-Anbindung über das Telegram-Gateway für Text- und Sprachnachrichten von unterwegs.",
        "Normal"
    ))
    new_body.extend(make_bullets([
        "Persönliches Rufnamen-Routing (z. B. /robert, /anwalt, /steuer) zur direkten Ansprache jedes Spezialisten.",
        "Synchroner Verlauf zwischen Smartphone und Desktop-Oberfläche.",
        "Konfigurierbare Ruhezeiten (Quiet Hours) für unterbrechungsfreie Zeiten (siehe Anhang IV.11: Notification Policy & Quiet Hours)."
    ]))

    # 2.6 Freigaben
    new_body.append(make_p("2.6 Freigaben", "Heading 2"))
    append_img(new_body, "inbox_approvals")
    new_body.append(make_p(
        "Dedizierte Human-in-the-Loop (HITL) Schaltzentrale für alle genehmigungspflichtigen Agenten-Aktionen.",
        "Normal"
    ))
    new_body.extend(make_bullets([
        "Übersichtliche Freigabekarten mit Diff-Ansicht für ausgehende E-Mails, Dateiänderungen oder Finanzbuchungen.",
        "Ein-Klick-Genehmigung, Ablehnung mit Korrekturhinweis oder direkte Nachbearbeitung im Dialogfeld."
    ]))
    new_body.append(make_callout("Siehe den vollständigen Leitfaden in Anhang IV.9: E-Mail Approval Queue & Human-in-the-Loop Policies."))

    # =========================================================================
    # 3. AGENTEN-KADER
    # =========================================================================
    new_body.append(make_p("3. Agenten-Kader", "Heading 1"))
    new_body.extend(orig[201:211])  # Agenten-Kader Intro + main screenshot (202)

    # 3.1 Übersicht
    new_body.append(make_p("3.1 Übersicht", "Heading 2"))
    new_body.extend(orig[212:258])  # Katalog-Verwaltung (212), Modell-Wechsel (224..238), 360°-Dossier (239..257)

    # 3.2 Chat
    new_body.append(make_p("3.2 Chat", "Heading 2"))
    new_body.extend(orig[259:272])  # Direkt-Chat screenshot (259) + content + table (265)

    # 3.3 Fähigkeiten
    new_body.append(make_p("3.3 Fähigkeiten", "Heading 2"))
    new_body.extend(orig[273:288])  # Skills screenshot (273) + content

    # 3.4 Operation
    new_body.append(make_p("3.4 Operation", "Heading 2"))
    new_body.extend(orig[289:305])  # Operations screenshot (289) + content
    new_body.append(make_callout("Zur Qualitätsbewertung von Agenten-Ergebnissen siehe Anhang V.6: Human Feedback Loop & Kontinuierliche Optimierung."))

    # 3.5 Soul
    new_body.append(make_p("3.5 Soul", "Heading 2"))
    new_body.extend(orig[306:321])  # SOUL screenshot (306) + content

    # 3.6 Personalakte
    new_body.append(make_p("3.6 Personalakte", "Heading 2"))
    new_body.extend(orig[322:338])  # Personalakte screenshot (322) + content
    new_body.append(make_callout("Siehe den ungekürzten Leitfaden in Anhang V.5: Agenten-Scorecards & HR-Personalakten."))

    # 3.7 Marktplatz
    new_body.append(make_p("3.7 Marktplatz", "Heading 2"))
    new_body.extend(orig[339:355])  # Marktplatz screenshot (339) + content + table (353)

    # 3.8 Vollständiger 57-Agenten-Kader
    new_body.append(make_p("3.8 Der vollständige Flotten-Kader: Alle 57 Spezialisten nach Fachdomänen", "Heading 2"))
    new_body.append(make_p(
        "Das Gesamtsystem umfasst 57 spezialisierte Rollenprofile, die nach den 7 strategischen Unternehmensdomänen "
        "gegliedert und nach dem EU AI Act (Art. 50 / Art. 113) klassifiziert sind:",
        "Normal"
    ))

    by_cat, prof_map = load_agents_data()
    for cat_name in sorted(by_cat.keys()):
        new_body.append(make_p(f"Domäne: {cat_name} ({len(by_cat[cat_name])} Spezialisten)", "Heading 3"))
        tbl = doc.add_table(rows=1, cols=5)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        hdr[0].text = "Agenten-Name"
        hdr[1].text = "Handle / ID"
        hdr[2].text = "Modell / Provider"
        hdr[3].text = "EU AI Act"
        hdr[4].text = "Kernfunktion & Zweck"
        for a in by_cat[cat_name]:
            row = tbl.add_row().cells
            aid = a.get("agent_id", "")
            p_info = prof_map.get(aid, {})
            name = a.get("agent_name", aid)
            model = a.get("underlying_model", "omniroute / auto/best-free")
            risk = a.get("risk_tier", "MINIMAL_RISK")
            purpose = (a.get("primary_purpose") or p_info.get("description") or "").replace("\n", " ").strip()
            if len(purpose) > 130:
                purpose = purpose[:127] + "..."
            row[0].text = str(name)
            row[1].text = str(aid)
            row[2].text = str(model)
            row[3].text = str(risk)
            row[4].text = str(purpose)
        tbl_el = tbl._element
        body.remove(tbl_el)
        new_body.append(tbl_el)

    # =========================================================================
    # 4. SHOWROOM
    # =========================================================================
    new_body.append(make_p("4. Showroom", "Heading 1"))
    new_body.extend(orig[356:372])  # Showroom intro + screenshot (357) + table (371)

    new_body.append(make_p("4.1 Explorer", "Heading 2"))
    append_img(new_body, "showroom_explorer")
    new_body.extend(make_bullets([
        "Strukturierter Datei- und Projekt-Explorer für alle von Agenten erzeugten Arbeitsergebnisse.",
        "Filterung nach Projekt, verantwortlichem Agenten, Dateityp und Erstellungsdatum."
    ]))

    new_body.append(make_p("4.2 Berichte", "Heading 2"))
    append_img(new_body, "showroom_berichte")
    new_body.extend(make_bullets([
        "Sammlung ausgearbeiteter Analysedossiers, Entscheidungsvorlagen, Konzepte und Audit-Berichte.",
        "Direktes Lesen im integrierten Markdown- und HTML-Viewer."
    ]))

    new_body.append(make_p("4.3 Medien", "Heading 2"))
    append_img(new_body, "showroom_medien")
    new_body.extend(make_bullets([
        "Galerie für generierte Architekturdiagramme (Mermaid), Grafiken, Mockups und Präsentationsfolien.",
        "Sofortvorschau ohne Wechsel in Drittprogramme."
    ]))

    new_body.append(make_p("4.4 Endprodukte", "Heading 2"))
    append_img(new_body, "showroom_endprodukte")
    new_body.extend(make_bullets([
        "Abnahmebereite Lieferpakete, exportierbare PDF-Berichte und ausführbare Software-Prototypen."
    ]))
    new_body.extend(orig[372:378])  # 4.4.1 Interaktive Code-Sandbox

    # =========================================================================
    # 5. INTERNET
    # =========================================================================
    new_body.append(make_p("5. Internet", "Heading 1"))
    new_body.append(make_p(
        "Das Modul Internet (Internet-Watchdog & Web-Radar) überwacht kontinuierlich relevante Webquellen, "
        "Fachmedien, Wettbewerber und regulatorische Veröffentlichungen.",
        "Normal"
    ))

    new_body.append(make_p("5.1 Radar", "Heading 2"))
    append_img(new_body, "watchdog_radar")
    new_body.extend(make_bullets([
        "Chronologischer Echtzeit-Stream neu erkannter Artikel, Marktbewegungen und Gesetzesänderungen.",
        "Semantische Relevanzbewertung anhand hinterlegter Suchprofile und Interessenfilter."
    ]))

    new_body.append(make_p("5.2 Korb", "Heading 2"))
    append_img(new_body, "watchdog_basket")
    new_body.extend(make_bullets([
        "Zwischenablage für markierte Web-Fundstücke und Artikel zur Sichtung.",
        "Ein-Klick-Übergabe an das Research Lab zur Tiefenanalyse oder direkt in die Zentralbibliothek."
    ]))

    new_body.append(make_p("5.3 Quellen", "Heading 2"))
    append_img(new_body, "watchdog_sources")
    new_body.extend(make_bullets([
        "Verwaltung überwachter Domains, RSS-Feeds, APIs und Branchenportale.",
        "Individuelle Festlegung von Abfrageintervallen und Prioritätsstufen."
    ]))

    new_body.append(make_p("5.4 Optionen", "Heading 2"))
    append_img(new_body, "watchdog_settings")
    new_body.extend(make_bullets([
        "Konfiguration der Crawler-Parameter, Headless-Browser-Optionen (Playwright) und Rate-Limits.",
        "Schwellenwerte für automatische Benachrichtigungen bei kritischen Treffern."
    ]))

    # =========================================================================
    # 6. RESEARCH LAB
    # =========================================================================
    new_body.append(make_p("6. Research Lab", "Heading 1"))
    new_body.extend(orig[514:530])  # Research Lab intro + screenshot (515) + table (529)

    new_body.append(make_p("6.1 Labor", "Heading 2"))
    append_img(new_body, "research_labor")
    new_body.extend(make_bullets([
        "Startpunkt für mehrstufige Tiefenrecherchen mit einstellbarer Suchtiefe und Domänenfokus.",
        "Echtzeit-Verfolgung der Agenten-Suchschritte, Hypothesenbildung und Faktenextraktion."
    ]))
    new_body.extend(orig[530:537])  # 6.1.1 Mehrstufige Reflexions-Schleife

    new_body.append(make_p("6.2 Dossiers", "Heading 2"))
    append_img(new_body, "research_dossiers")
    new_body.extend(make_bullets([
        "Strukturierte Ergebnisberichte mit Executive Summary, Pro-/Contra-Abwägung und vollständigem Fußnotenapparat.",
        "Direkter Export in den Obsidian Vault oder als Entscheidungsvorlage für die Decision Engine."
    ]))

    new_body.append(make_p("6.3 Quellen", "Heading 2"))
    append_img(new_body, "research_quellen")
    new_body.extend(make_bullets([
        "Verzeichnis aller herangezogenen Primär- und Sekundärquellen inklusive Vertrauenswürdigkeits-Bewertung.",
        "Automatische Kennzeichnung widersprüchlicher Aussagen zwischen verschiedenen Quellen."
    ]))

    # =========================================================================
    # 7. ZENTRALBIBLIOTHEK
    # =========================================================================
    new_body.append(make_p("7. Zentralbibliothek", "Heading 1"))
    new_body.extend(orig[379:388])  # Zentralbibliothek intro + screenshot (380)

    new_body.append(make_p("7.1 RAG Index", "Heading 2"))
    new_body.extend(orig[389:404])  # RAG screenshot (389) + content

    new_body.append(make_p("7.2 Erfasser", "Heading 2"))
    new_body.extend(orig[405:423])  # Erfasser screenshot (405) + content
    new_body.append(make_p(
        "Docling & Unstructured Tabellen-Extraktion (t-539b65): Komplexe PDF-Tabellen, Bilanzen und mehrspaltige "
        "Verträge werden verlustfrei in saubere GitHub-Flavored Markdown-Tabellen überführt.",
        "Normal"
    ))

    new_body.append(make_p("7.3 Obsidian", "Heading 2"))
    new_body.extend(orig[424:439])  # Obsidian screenshot (424) + content + table (438)

    # =========================================================================
    # 8. DECISION ENGINE
    # =========================================================================
    new_body.append(make_p("8. Decision Engine", "Heading 1"))
    new_body.extend(orig[440:468])  # Decision Engine intro + screenshot (441) + tables (452, 462)

    new_body.append(make_p("8.1 Übersicht", "Heading 2"))
    append_img(new_body, "boardroom_overview")
    new_body.extend(make_bullets([
        "Revisionssicheres Archiv aller durchgeführten Boardroom-Debatten, Risikoanalysen und Vorstandsbeschlüsse.",
        "Schnellzugriff auf historische Entscheidungsgründe und verworfene Handlungsalternativen."
    ]))

    new_body.append(make_p("8.2 Debatte", "Heading 2"))
    append_img(new_body, "boardroom_debate")
    new_body.extend(make_bullets([
        "Konfiguration neuer Gremiensitzungen: Auswahl aus 55 Denk-Frameworks (siehe Anhang III), Besetzung der C-Level-Rollen und Budgetvorgabe.",
        "Möglichkeit zur Einbindung interner Dokumente und Dossiers als Faktenbasis."
    ]))

    new_body.append(make_p("8.3 Live", "Heading 2"))
    append_img(new_body, "boardroom_live")
    new_body.extend(make_bullets([
        "Echtzeit-Verfolgung der mehrstufigen Kontroverse (Thesen, Kreuzverhör, Red-Team-Kritik und Synthese durch den Chairman).",
        "Direkte Überführung der beschlossenen Maßnahmen in ausführbare Kanban-Aufgaben."
    ]))
    new_body.append(make_callout("Zur technischen Echtzeit-Übertragung siehe Anhang V.8: Live Streaming mit SSE & WebSockets."))

    # =========================================================================
    # 9. ADRESSEN & CRM (SÄULE 3: WIRTSCHAFT & ERP)
    # =========================================================================
    new_body.append(make_p("9. Adressen & CRM (Säule 3: Wirtschaft & ERP)", "Heading 1"))
    new_body.append(make_p(
        "Das Modul Adressen & CRM bildet den Einstiegspunkt der dritten System-Säule (Wirtschaft & ERP). "
        "Es vereint ein vollwertiges B2B-CRM (LinkedIn-Netzwerk, E-Mail-Chronik, 360°-KI-Dossiers) mit der "
        "buchhalterischen Stammdatenpflege für Kunden (Debitoren 10000+) und Lieferanten (Kreditoren 70000+). "
        "Gemäß DSGVO und GoBD speichert Archon OS sämtliche ERP-Daten physisch getrennt je Mandant in einer "
        "eigenen SQLite-WAL-Datenbank unter data/tenants/{company_id}/erp.db.",
        "Normal"
    ))
    new_body.append(make_callout("Zur vollständigen Datenbank- und Belegketten-Architektur siehe Anhang V.22: Archon ERP & CRM Architektur-Spezifikation (Säule 3)."))

    new_body.append(make_p("9.1 Kontakte (Haupttabelle & CRM-Adressstamm)", "Heading 2"))
    append_img(new_body, "addresses_all")
    new_body.extend(make_bullets([
        "Vollständige CRM-Tabelle über alle 2.331 Kontakte mit Name, Firma, Position, Rating-Sternen, Status-Pills und Interaktions-Badges.",
        "Zweizeiliger Schnellfilter (Volltextsuche nach Name, Firma, Ort oder Nummer sowie Direkt-Sync mit PocketBase Port 8090).",
        "Performante Paginierung (50 Kontakte pro Seite) mit Checkbox-Stapelverarbeitung und Ein-Klick-Öffnen der Datensatzansicht."
    ]))

    new_body.append(make_p("9.2 Kundenstamm (Debitoren 10000+)", "Heading 2"))
    append_img(new_body, "addresses_customers")
    new_body.extend(make_bullets([
        "Kunden- und Mandantenverzeichnis mit automatischer Vergabe fortlaufender Debitorennummern im Nummernkreis 10000–69999.",
        "Pflege von Zahlungszielen (Netto-Tage), Skonto-Konditionen, Umsatzsteuer-ID, Kreditlimit und verknüpften Ausgangsrechnungen."
    ]))

    new_body.append(make_p("9.3 Lieferantenstamm (Kreditoren 70000+)", "Heading 2"))
    append_img(new_body, "addresses_suppliers")
    new_body.extend(make_bullets([
        "Lieferanten-, Dienstleister- und Cloud-Provider-Stamm im DATEV-konformen Kreditoren-Nummernkreis ab 70000.",
        "Hinterlegung von IBAN/BIC, Eingangsrechnungs-Workflows, Standard-Aufwandskonten und verknüpften Einkaufsartikeln."
    ]))

    new_body.append(make_p("9.4 Alle Nachrichten (Multi-Channel Timeline)", "Heading 2"))
    append_img(new_body, "addresses_messages")
    new_body.extend(make_bullets([
        "Aggregierter chronologischer Feed über alle 2.229 Nachrichten und Interaktionsverläufe über alle Kontakte hinweg.",
        "Kanalfilter für LinkedIn (2.220), E-Mail (3), Persönliche Treffen (3), Audio-Diktate und Notizen (3) sowie Richtungsfilter (Erhalten / Gesendet).",
        "Volltext-Expansion auf Knopfdruck zur vollständigen Nachverfolgung jedes Dialogverlaufs mit Zeitstempel."
    ]))

    new_body.append(make_p("9.5 Kalender & Wiedervorlagen", "Heading 2"))
    append_img(new_body, "addresses_calendar")
    new_body.extend(make_bullets([
        "Kalendarische Übersicht aller geplanten Termine, Kontakt-Wiedervorlagen und anstehenden Check-ins.",
        "Automatische Kennzeichnung dringlicher oder überfälliger Follow-ups zur Vermeidung von Kontaktstagnation."
    ]))

    new_body.append(make_p("9.6 Bericht (CRM-Missionskontrolle & KPI-Analyse)", "Heading 2"))
    append_img(new_body, "addresses_report")
    new_body.extend(make_bullets([
        "Echtzeit-KPI-Karten: Aktive Kontakte (1.145), Antwortrate (32 %), Meeting-Rate (0 %), Personalberater (67) und stagnierte Kontakte.",
        "Rollenverteilungs-Diagramme: Automatische Klassifizierung in Geschäftsführer / Inhaber, Entscheider, Investoren, Beratung und Finanzen.",
        "Statusverteilung der Pipeline-Phasen sowie täglicher Handlungsradar ('Was heute tun?') für proaktives Kontaktmanagement."
    ]))

    new_body.append(make_p("9.7 Datensatzansicht & Kontakt-Drawer (VARIO 8 Standard & 360°-Akte)", "Heading 2"))
    append_img(new_body, "addresses_drawer")
    new_body.extend(make_bullets([
        "80-Pixel-Kopfleiste mit 6 VARIO-Teilansichten: Übersicht, Nachrichten, Kaufmännisch, Belege & Vorgänge, Ansprechpartner & Filialen sowie DSGVO & Compliance.",
        "Ergonomische Fenstersteuerung: Schließen über den abgedunkelten Hintergrund (Backdrop-Klick), die Escape-Taste oder das markante Schließen-Kreuz (✕) oben rechts.",
        "Kaufmännische VARIO-Stammdaten: Debitor- (10000+) und Kreditor-Nummern (70000+), Zahlungsziele, Skonto-Sätze, Kreditlimite, Preisgruppen, Bankdaten (IBAN, BIC) und USt-IdNr.",
        "Integrierter DIN-5008 Belegfluss: Direktes Einsehen und Drucken von Angeboten (ANG) und Aufträgen (AB) mit Firmenbriefkopf und USt-Ausweis über 1-Klick-Aktionen.",
        "DSGVO & Compliance: 1-Klick-Datenexport als strukturiertes JSON (Art. 15/20 DSGVO) sowie rechtssichere unwiderrufliche Anonymisierung (Art. 17 DSGVO) bei voller Wahrung der GoBD-Buchhaltungsintegrität."
    ]))

    # =========================================================================
    # 10. ARTIKEL & LEISTUNGEN (SÄULE 3: WIRTSCHAFT & ERP)
    # =========================================================================
    new_body.append(make_p("10. Artikel & Leistungen (Säule 3: Wirtschaft & ERP)", "Heading 1"))
    new_body.append(make_p(
        "Das Modul Artikel & Leistungen verwaltet den gesamten Leistungs-, Produkt- und Lizenzkatalog des aktiven "
        "Mandanten. Jede Position kalkuliert in Echtzeit den Deckungsbeitrag in Euro sowie die prozentuale "
        "Handelsspanne aus Netto-Verkaufspreis (VK) und Einkaufspreis (EK) und lässt sich direkt in Angebote, "
        "Auftragsbestätigungen und Rechnungen übernehmen.",
        "Normal"
    ))

    new_body.append(make_p("10.1 Gesamtkatalog (Alle Artikel & Leistungen)", "Heading 2"))
    append_img(new_body, "items_all")
    new_body.extend(make_bullets([
        "Übersicht aller aktiven Leistungspositionen, Beratungs-Tagessätze, SaaS-Lizenzen und physischen Produkte.",
        "Live-Kalkulationskachel im rechten Inspektor: Automatische Berechnung von Rohgewinn (VK − EK) und Marge in Prozent bei jeder Preisänderung.",
        "Direkte Zuordnung eines bevorzugten Lieferanten (Kreditor 70000+) inklusive Lieferanten-Artikelnummer."
    ]))

    new_body.append(make_p("10.2 Zeit / Service & Pauschalen", "Heading 2"))
    append_img(new_body, "items_service")
    new_body.extend(make_bullets([
        "Verwaltung von Beratungsleistungen, Architektur-Workshops, Entwicklungs-Stundensätzen und Festpreis-Pauschalen.",
        "Flexible Einheiten (Stunde, Tagessatz, Pauschal) mit hinterlegten Leistungsbeschreibungen für Angebote."
    ]))

    new_body.append(make_p("10.3 SaaS & Abonnements", "Heading 2"))
    append_img(new_body, "items_saas")
    new_body.extend(make_bullets([
        "Wiederkehrende Lizenz-, Hosting-, Wartungs- und Agenten-Infrastruktur-Abonnements (MRR / ARR).",
        "Nahtlose Verknüpfung mit Laufzeitverträgen und automatischer Fälligkeitsüberwachung."
    ]))

    new_body.append(make_p("10.4 Produkte & Hardware (inkl. Lagerbestand)", "Heading 2"))
    append_img(new_body, "items_product")
    new_body.extend(make_bullets([
        "Physische Produkte, Edge-AI-Workstations, Hardware-Bundles und Handelswaren.",
        "Integrierte Bestandsführung mit aktuellem Lagerbestand, Mindestbestand (Meldebestand) und Lagerort."
    ]))

    new_body.append(make_p("10.5 Artikel-Drawer & VARIO 8 Stammdaten-Inspektor", "Heading 2"))
    append_img(new_body, "items_drawer")
    new_body.extend(make_bullets([
        "80-Pixel-Kopfleiste mit 4 modularen Teilansichten nach VARIO 8 Standard: Stammdaten, Preise & Staffeln, Bestand & Konditionen sowie Verkaufshistorie.",
        "Kaufmännische Staffelpreise und Fibu-Erlöskonten (SKR03 / SKR04) mit automatischer Live-Margenkalkulation in Euro und Prozent.",
        "Integrierte Bestandsführung (Mindestbestand, Lagerort, Lieferanten-Kreditorzuordnung) und SaaS-Abo-Konditionen (Seats, Kündigungsfristen, Senioritätsstufen).",
        "Belegverwendung & Absatzhistorie: Vollständige Rückverfolgbarkeit aller Angebote (ANG) und Aufträge (AB), in denen der Artikel eingesetzt wurde."
    ]))

    # =========================================================================
    # 11. VORGÄNGE & VERTRÄGE (SÄULE 3: WIRTSCHAFT & ERP)
    # =========================================================================
    new_body.append(make_p("11. Vorgänge & Verträge (Säule 3: Wirtschaft & ERP)", "Heading 1"))
    new_body.append(make_p(
        "Das Modul Vorgänge & Verträge bildet die operative Klammer zwischen Vertrieb, Projektabwicklung und "
        "Rechnungswesen. Nach dem Vorbild moderner ERP-Belegketten (z. B. Nuclos) lassen sich Angebote (ANG) "
        "und Auftragsbestätigungen (AB) mit einem Klick verlustfrei in GoBD-konforme Ausgangsrechnungen (RE) "
        "oder Gutschriften (GS) überführen.",
        "Normal"
    ))

    new_body.append(make_p("11.1 Angebote (ANG) & Aufträge (AB)", "Heading 2"))
    append_img(new_body, "ops_erp_offers")
    new_body.extend(make_bullets([
        "Beleg-Editor mit direkter Kundenauswahl aus dem Adressstamm und Positionsübernahme aus dem Artikelkatalog.",
        "1-Klick Belegfluss: Umwandlung eines Angebots (ANG) in eine Auftragsbestätigung (AB) oder direkt in eine Ausgangsrechnung (RE) im Modul Rechnungswesen.",
        "Automatische Summierung von Netto-Volumen, Umsatzsteuer und Brutto-Gesamtbetrag.",
        "DIN-5008 Beleg-Druck & PDF-Export: Generierung formaler Angebote und Auftragsbestätigungen mit Mandanten-Briefkopf, Steuernummern, Bankverbindung und Annahme-Unterschriftenfeld."
    ]))

    new_body.append(make_p("11.2 Deal-Pipeline & Gewichteter Umsatz-Forecast", "Heading 2"))
    append_img(new_body, "ops_erp_pipeline")
    new_body.extend(make_bullets([
        "Mehrstufiges Vertriebs-Board über die Phasen Lead, Qualified, Proposal, Negotiation und Closed Won.",
        "Echtzeit-Berechnung des ungewichteten Pipeline-Volumens sowie des nach Abschlusswahrscheinlichkeit gewichteten Umsatz-Forecasts."
    ]))

    new_body.append(make_p("11.3 Vertrags- & Fristenradar", "Heading 2"))
    append_img(new_body, "ops_erp_contracts")
    new_body.extend(make_bullets([
        "Überwachung sämtlicher Kunden- und Lieferantenverträge inklusive Mindestlaufzeiten, Verlängerungsintervallen und Kündigungsfristen.",
        "Automatische Fristen-Ampel (Aktiv, Bald fällig <= 30 Tage, Kritisch <= 14 Tage) mit Eskalation an Telegram und Operations."
    ]))

    # =========================================================================
    # 12. RECHNUNGSWESEN (SÄULE 3: WIRTSCHAFT & ERP)
    # =========================================================================
    new_body.append(make_p("12. Rechnungswesen (Säule 3: Wirtschaft & ERP)", "Heading 1"))
    new_body.append(make_p(
        "Das Modul Rechnungswesen bündelt die kaufmännische Belegverarbeitung, Finanzkennzahlen, "
        "Vertragsüberwachung und das Forderungsmanagement.",
        "Normal"
    ))

    new_body.append(make_p("12.1 Belege", "Heading 2"))
    append_img(new_body, "finance_receipts")
    new_body.extend(make_bullets([
        "GoBD-konforme Erfassung und Archivierung von Eingangs- und Ausgangsrechnungen sowie Quittungen.",
        "Automatische OCR-Auslesung von Rechnungssteller, Datum, Steuersatz, Netto- und Bruttobetrag."
    ]))
    new_body.append(make_callout("Siehe Anhang V.4: Telegram Receipt OCR & Belegdigitalisierung sowie Anhang IV.2: GoBD & ISO 27001 Audit-Logging."))

    new_body.append(make_p("12.2 Analytics", "Heading 2"))
    append_img(new_body, "finance_analytics")
    new_body.extend(make_bullets([
        "Finanz-Cockpit für Einnahmen, laufende Betriebskosten (OpEx), KI-Token-Ausgaben und Projekt-Deckungsbeiträge.",
        "Abweichungsanalysen und Liquiditätsvorschau."
    ]))
    new_body.append(make_callout("Zur Anbindung erweiterter Business-Intelligence-Auswertungen siehe Anhang V.14: Metabase BI-Dashboard."))

    new_body.append(make_p("12.3 Verträge", "Heading 2"))
    append_img(new_body, "finance_contracts")
    new_body.extend(make_bullets([
        "Zentrales Vertragsregister mit automatischem Fristen- und Kündigungsmanagement (t-0a2171).",
        "Heuristische Erkennung von Mindestlaufzeiten, automatischen Verlängerungsklauseln und Kündigungsfenstern.",
        "Frühwarnung per Telegram und Kanban-Ticket bei Fristen <= 14 Tagen."
    ]))
    new_body.append(make_callout("Zur digitalen Vertragsunterzeichnung siehe Anhang V.3: DocuSeal E-Signatur & Vertragsunterzeichnung."))

    new_body.append(make_p("12.4 Mahnwesen", "Heading 2"))
    append_img(new_body, "finance_dunning")
    new_body.extend(make_bullets([
        "Überwachung offener Ausgangsrechnungen und Fälligkeitstermine.",
        "Mehrstufige Dunning-Engine zur Erstellung rechtssicherer Zahlungserinnerungen und Mahnungen inklusive Verzugszinsberechnung nach BGB."
    ]))
    new_body.append(make_callout("Siehe die vollständige Spezifikation in Anhang V.2: Dunning Engine & Automatisches Mahnwesen."))

    # =========================================================================
    # 13. CORPORATE & MANDANT (SÄULE 3: WIRTSCHAFT & ERP)
    # =========================================================================
    new_body.append(make_p("13. Corporate & Mandant (Säule 3: Wirtschaft & ERP)", "Heading 1"))
    new_body.append(make_p(
        "Das Modul Corporate & Mandant verwaltet sämtliche Unternehmensstammdaten (mandantenfähig mit physisch "
        "getrennter SQLite-Datenbank je Gesellschaft), Corporate-Design-Vorgaben sowie offizielle Geschäftsvorlagen "
        "für Korrespondenz und Abrechnung.",
        "Normal"
    ))

    new_body.append(make_p("13.1 Stammdaten", "Heading 2"))
    append_img(new_body, "corporate_master")
    new_body.extend(make_bullets([
        "Mandantenfähigkeit (Multi-Company): Verwaltung mehrerer Firmen oder Standorte mit schnellem Wechsel über das Kopfzeilen-Dropdown und den globalen Mandanten-Umschalter in der linken Seitenleiste.",
        "Physische DB-Isolation: Jeder Mandant besitzt eine eigene, strikt getrennte Datenbank (data/tenants/{company_id}/erp.db).",
        "Rechtliche Angaben & Anschrift: Firmenname, Rechtsform, Geschäftsführung, Straße, PLZ, Ort und Kontaktdaten.",
        "Handelsregister & Steuern: Registergericht, HRB-/HRA-Nummer, Steuernummer, Umsatzsteuer-Identifikationsnummer (USt-IdNr.) und Kleinunternehmer-Status (§ 19 UStG).",
        "Bankverbindung & Corporate Design: IBAN, BIC, Kreditinstitut sowie Primär-/Sekundärfarben, Typografie und Firmenlogo."
    ]))

    new_body.append(make_p("13.2 Formulare & Vorlagen", "Heading 2"))
    append_img(new_body, "corporate_templates")
    new_body.extend(make_bullets([
        "Interaktives Vorlagen-Studio mit Echtzeit-Vorschau, automatischer Einbindung der hinterlegten Firmenstammdaten und Direkt-Auswahl von Empfängern aus dem Adressstamm.",
        "DIN 5008 Geschäftsbrief: Normgerechtes Briefblatt mit Faltmarken, Anschriftzone, Informationsblock und Pflichtangaben-Fußzeile.",
        "Ausgangsrechnung (§ 14 UStG): Vollständige Rechnungsvorlage mit Positionsberechnung, Netto-/Umsatzsteuer-Ausweis und Zahlungsziel.",
        "Geheimhaltungsvereinbarung (NDA): Direkt einsatzbereite Vorlage für beidseitige Vertraulichkeitsvereinbarungen.",
        "Direktdruck & PDF-Export auf DIN-A4 über die integrierte Druckfunktion."
    ]))

    # =========================================================================
    # 14. APPROVAL-POLICIES (SÄULE 4: INFRASTRUKTUR & GOVERNANCE)
    # =========================================================================
    new_body.append(make_p("14. Approval-Policies", "Heading 1"))
    new_body.append(make_p(
        "In den Approval-Policies legst du verbindlich fest, welche Aktionen Agenten dunkel (autonom) ausführen "
        "dürfen und wo zwingend eine menschliche Freigabe (Human-in-the-Loop) eingeholt werden muss.",
        "Normal"
    ))

    new_body.append(make_p("14.1 Finanzen", "Heading 2"))
    append_img(new_body, "approvals_finance")
    new_body.extend(make_bullets([
        "Freigabegrenzen für Ausgaben, Abonnements, Rechnungsfreigaben und Budgetverschiebungen.",
        "Vier-Augen-Prinzip ab frei definierbaren Euro-Schwellenwerten."
    ]))

    new_body.append(make_p("14.2 E-Mail", "Heading 2"))
    append_img(new_body, "approvals_email")
    new_body.extend(make_bullets([
        "Regelwerk für ausgehende Korrespondenz: Pflichtfreigabe bei externen Empfängern, Behörden oder Vertragsangeboten.",
        "Schutz vor ungeprüften rechtlichen Zusagen im Außenverhältnis."
    ]))

    new_body.append(make_p("14.3 System & IT", "Heading 2"))
    append_img(new_body, "approvals_system")
    new_body.extend(make_bullets([
        "Absicherung kritischer Infrastruktur-Eingriffe (Datenbank-Migrationen, Container-Neustarts, Konfigurationsänderungen).",
        "Automatische Datenklassifizierung nach ISO 27001 / BSI (t-53315b) in PUBLIC, INTERNAL, CONFIDENTIAL und STRICTLY_CONFIDENTIAL mit Blockade externer Cloud-Übertragungen bei sensiblen Daten."
    ]))
    new_body.append(make_callout("Siehe Anhang IV.10: Approval Policies & Schwellenwert-Governance sowie Anhang IV.1: DSGVO Compliance."))

    # =========================================================================
    # 15. TOKEN GUARD
    # =========================================================================
    new_body.append(make_p("15. Token Guard", "Heading 1"))
    new_body.extend(orig[491:513])  # Token Guard content + tables (492, 504, 511)

    new_body.append(make_p("15.1 Übersicht", "Heading 2"))
    append_img(new_body, "guardian_overview")
    new_body.extend(make_bullets([
        "Echtzeit-Überwachung des Token- und Kostenverbrauchs über alle Provider, Modelle und Fachagenten hinweg.",
        "Budget-Ampel für Tages- und Monatslimits."
    ]))

    new_body.append(make_p("15.2 Sessions", "Heading 2"))
    append_img(new_body, "guardian_sessions")
    new_body.extend(make_bullets([
        "Aufschlüsselung des Token-Bedarfs einzelner Sitzungen und Tasks (Input- vs. Output-Tokens).",
        "Erkennung ungewöhnlich großer Kontextfenster oder Endlosschleifen."
    ]))

    new_body.append(make_p("15.3 Drosselung", "Heading 2"))
    append_img(new_body, "guardian_concurrency")
    new_body.extend(make_bullets([
        "Konfiguration von Soft-Limits (Warnmeldung bei 80 %) und Hard-Limits (Automatischer Stopp oder Fallback auf kostenfreie Modelle bei 100 %)."
    ]))
    new_body.append(make_callout("Siehe Anhang IV.4: API-Keys, Berechtigungs-Scopes & Rate-Limits sowie Anhang IV.6: Lokales Privacy-Routing."))

    # =========================================================================
    # 16. TELEMETRIE & LOGS
    # =========================================================================
    new_body.append(make_p("16. Telemetrie & Logs", "Heading 1"))
    new_body.extend(orig[538:554])  # Telemetrie intro + screenshot (539) + table (553)

    new_body.append(make_p("16.1 Container", "Heading 2"))
    append_img(new_body, "logstream_containers")
    new_body.extend(make_bullets([
        "Live-Metriken aller Docker-Container (Latenzen, CPU-/RAM-Auslastung und Health-Checks).",
        "Direkte Einsicht in die Standardausgabe- und Fehler-Logs einzelner Dienste."
    ]))
    new_body.append(make_callout("Siehe Anhang V.12: Prometheus & Grafana Systemüberwachung sowie Anhang V.13: Zentrales Logging mit Grafana Loki."))

    new_body.append(make_p("16.2 Agenten", "Heading 2"))
    append_img(new_body, "logstream_agents")
    new_body.extend(make_bullets([
        "Chronologischer Trace-Stream sämtlicher Agenten-Überlegungen, Tool-Aufrufe und Modellantworten.",
        "Filterung nach Agenten-ID, Schweregrad (INFO, WARN, ERROR) und Zeitraum."
    ]))
    new_body.append(make_callout("Zur tiefgehenden Observability siehe Anhang V.9: LLM Tracing mit Langfuse."))

    new_body.append(make_p("16.3 Audit", "Heading 2"))
    append_img(new_body, "logstream_audit")
    new_body.extend(make_bullets([
        "Revisionssicheres, kryptografisch verkettetes Audit-Log aller sicherheitsrelevanten Systemaktionen.",
        "Geordneter Server-Shutdown über den GracefulShutdownCoordinator (t-12113b) mit Task-Draining und vollständigem SQLite-WAL-Flush."
    ]))

    # =========================================================================
    # 17. SYSTEM CONTROL CENTER
    # =========================================================================
    new_body.append(make_p("17. System Control Center", "Heading 1"))
    new_body.extend(orig[624:626])  # Intro to System Control Center
    new_body.extend(orig[640:650])  # Praxis-Workflow + Overview Table (647) + Prompt Box (649)

    # 17.1 Hermes Core
    new_body.append(make_p("17.1 Hermes Core", "Heading 2"))
    append_img(new_body, "settings_kernel")
    new_body.append(orig[626])      # Hermes Core description
    new_body.append(orig[633])      # Health-Score
    new_body.append(orig[634])      # Master-Dossier-Generator
    new_body.append(make_callout("Zum Notfallzugriff und Resilienz-Tests siehe Anhang IV.8: Break-Glass Recovery und Anhang V.17: Chaos Resilience."))

    # 17.2 Autonomie & Module (includes former Chapters 16 & 17 technical pillars!)
    new_body.append(make_p("17.2 Autonomie & Module", "Heading 2"))
    append_img(new_body, "settings_autonomy")
    new_body.append(orig[636])      # Settings-Paket 1
    new_body.append(orig[637])      # Settings-Paket 2
    new_body.append(orig[638])      # Table 15.2 title
    new_body.append(orig[639])      # Table 15.2 (10 steuerable Autonomie-Gruppen)
    new_body.extend(orig[670:707])  # 17.2.1 to 17.2.5
    new_body.extend(orig[710:747])  # 17.2.6 to 17.2.10

    # 17.3 Container & Dienste
    new_body.append(make_p("17.3 Container & Dienste", "Heading 2"))
    append_img(new_body, "settings_services")
    new_body.append(orig[627])
    new_body.append(make_callout("Siehe Anhang V.15: Litestream SQLite Replikation sowie Anhang IV.7: Reverse Proxy, SSL/TLS & SSO."))

    # 17.4 Provider & Gateway (includes Settings Routing screenshot + OmniRoute LLM Gateway screenshot 470!)
    new_body.append(make_p("17.4 Provider & Gateway", "Heading 2"))
    append_img(new_body, "settings_routing")
    new_body.append(orig[628])
    new_body.append(make_p(
        "Hinweis zur Navigation: Das LLM Gateway (OmniRoute) ist direkt über das CPU-Symbol unten links in der "
        "Statusleiste (Port 20128) sowie über diesen Reiter im System Control Center erreichbar.",
        "Normal"
    ))
    new_body.extend(orig[469:490])  # OmniRoute screenshot (470) + content + tables (480, 487)
    new_body.append(make_callout("Zum Training eigener lokaler Sprachmodelle siehe Anhang V.11: Modell-Finetuning & Lokale Gewichtung."))

    # 17.5 API-Keys & Access
    new_body.append(make_p("17.5 API-Keys & Access", "Heading 2"))
    append_img(new_body, "settings_keys")
    new_body.extend(make_bullets([
        "Zentraler, verschlüsselter Tresor für alle API-Schlüssel externer Provider (OpenRouter, Anthropic, OpenAI, Google, Groq).",
        "Verwaltung interner System-Keys, Berechtigungs-Scopes und Rotations-Intervalle."
    ]))
    new_body.append(make_callout("Siehe Anhang IV.5: Secrets-Management & Key-Rotation sowie Anhang IV.12: Config Validation & Linting."))

    # 17.6 Methodik
    new_body.append(make_p("17.6 Methodik", "Heading 2"))
    append_img(new_body, "settings_frameworks")
    new_body.append(orig[629])

    # 17.7 Plugins
    new_body.append(make_p("17.7 Plugins", "Heading 2"))
    append_img(new_body, "settings_plugins")
    new_body.append(orig[630])
    new_body.extend(orig[657:661])  # Standardisiertes Pluginsystem & Runtime-Hooks
    new_body.append(make_callout("Siehe Anhang V.1: Archon MCP Server & Tool-Treiber Entwicklung."))

    # 17.8 Kommunikation
    new_body.append(make_p("17.8 Kommunikation", "Heading 2"))
    append_img(new_body, "settings_comm")
    new_body.append(orig[631])
    new_body.extend(orig[663:667])  # Telegram Voice-Pipeline & Sprachausgabe

    # 17.9 Design
    new_body.append(make_p("17.9 Design", "Heading 2"))
    append_img(new_body, "settings_design")
    new_body.append(orig[632])

    # 17.10 Systemupdate
    new_body.append(make_p("17.10 Systemupdate", "Heading 2"))
    append_img(new_body, "settings_update")
    new_body.extend(orig[652:655])  # Release-Lifecycle, Updatesystem & GitHub-Sync
    new_body.append(make_callout("Siehe Anhang V.18: Ansible Infrastruktur, Anhang V.19: CI/CD Pipeline & E2E-Testing sowie Anhang V.16: Restore-Tests."))

    # =========================================================================
    # 18. SPEZIAL-FEATURE: ARCHON PROMPT STUDIO (824 VORLAGEN & FABRIC SOP)
    # =========================================================================
    new_body.append(make_p("18. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)", "Heading 1"))
    new_body.extend(orig[555:580])  # Prompt Studio screenshot (556) + content + table (577)
    new_body.append(make_callout("Zur Versionierung und schrittweisen Freigabe von Prompts siehe Anhang V.10: Prompt Registry & Canary Releases."))

    # =========================================================================
    # 19. SPEZIAL-FEATURE: VISUAL CSS LIVE STUDIO & IN-PLACE INSPECTOR
    # =========================================================================
    new_body.append(make_p("19. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector", "Heading 1"))
    new_body.extend(orig[581:601])  # CSS Live Studio screenshot (583) + content + table (598)

    # =========================================================================
    # ANHANG I, II, III (Original Word Appendices with cleaned headings & tables)
    # =========================================================================
    # Clean Anhang I headings (I.1 .. I.5)
    set_el_text(orig[747], "Anhang I: 5 Praxis-Use-Cases", "Heading 1")
    set_el_text(orig[750], "I.1 Use Case 1: Telegram-Direktansprache über persönliche Rufnamen (/anwalt, /robert)", "Heading 2")
    set_el_text(orig[763], "I.2 Use Case 2: Eingehende Partner-E-Mail: Triage, Antwortentwurf & Human-in-the-Loop Freigabe", "Heading 2")
    set_el_text(orig[777], "I.3 Use Case 3: Wissensaufbau: 80-seitiges PDF-Gutachten per Auto-OCR in Zentralbibliothek & RAG", "Heading 2")
    set_el_text(orig[791], "I.4 Use Case 4: Strategische Projektentwicklung: Delegation durch Robert (CEO), Research Lab & Kanban", "Heading 2")
    set_el_text(orig[805], "I.5 Use Case 5: Vollautonome Hintergrundüberwachung, OmniRoute-Failover & Notfall-Eskalation", "Heading 2")

    # Clean Anhang II headings (II.1 .. II.16 consistently as Heading 2)
    set_el_text(orig[820], "Anhang II: Archon OS — Komplett-Glossar", "Heading 1")
    set_el_text(orig[823], "II.1 System-Ansichten & Spezial-Studios (UI Views & Kernmechaniken)", "Heading 2")
    set_el_text(orig[864], "II.2 Token-Spar- & FinOps-Ökosystem (Kostenminimierung)", "Heading 2")
    set_el_text(orig[893], "II.3 Kernel, Scheduling & Daemon-Architektur (Pillar 1)", "Heading 2")
    set_el_text(orig[910], "II.4 Multi-Agenten-Prozessmodell, Hierarchie & Synthese (Pillar 2)", "Heading 2")
    set_el_text(orig[925], "II.5 MCP-Treiber, Externe Dienste & Multimodale Werkzeuge (Pillar 3)", "Heading 2")
    set_el_text(orig[942], "II.6 Gedächtnis, Datenbank-Hygiene & Obsidian 2nd Brain (Pillar 4)", "Heading 2")
    set_el_text(orig[963], "II.7 Sicherheit, Zero-Trust Governance & System-Diagnose (Pillar 6)", "Heading 2")
    set_el_text(orig[976], "II.8 Selbst-Evolution, Marktplätze & Auto-Dokumentation (Pillar 7)", "Heading 2")
    set_el_text(orig[985], "II.9 Referenz-Matrix: Steuerbare Evey/Hermes-Plugins", "Heading 2")
    set_el_text(orig[988], "II.10 Enterprise- & Resilienz-Architektur", "Heading 2")
    set_el_text(orig[999], "II.11 Autonomie-, Sandbox- & Governance-Architektur", "Heading 2")
    set_el_text(orig[1012], "II.12 Performance-Core, Durchsatz-Skalierung & Token-Effizienz", "Heading 2")
    set_el_text(orig[1023], "II.13 Moderne Gedächtnis- & RAG-Architektur", "Heading 2")
    set_el_text(orig[1034], "II.14 Zuverlässige Ausführung & Determinismus (Durable Execution)", "Heading 2")
    set_el_text(orig[1045], "II.15 Sicherheit, Datenschutz & Enterprise-Guardrails", "Heading 2")
    set_el_text(orig[1056], "II.16 Selbst-Optimierung, Evaluation & Schwarm-Intelligenz", "Heading 2")

    # Clean Anhang III headings (III.1 .. III.9) and framework items (#01..#55)
    set_el_text(orig[1068], "Anhang III: Decision Engine & Boardroom (55 Lösungs-Frameworks)", "Heading 1")
    set_el_text(orig[1072], "III.1 Agile, Lean & Innovation (7 Frameworks)", "Heading 2")
    set_el_text(orig[1105], "III.2 Ursachenanalyse & Formale Logik (6 Frameworks)", "Heading 2")
    set_el_text(orig[1132], "III.3 Kognitive Entzerrung & Debatte (6 Frameworks)", "Heading 2")
    set_el_text(orig[1160], "III.4 Strategie, Moat & Positionierung (6 Frameworks)", "Heading 2")
    set_el_text(orig[1188], "III.5 Marktanalyse, Nachfrage & Spieltheorie (6 Frameworks)", "Heading 2")
    set_el_text(orig[1216], "III.6 Product-Launch & Growth Engineering (5 Frameworks)", "Heading 2")
    set_el_text(orig[1239], "III.7 Business Model & Venture Building (5 Frameworks)", "Heading 2")
    set_el_text(orig[1263], "III.8 Operations, Durchsatz & Qualität (6 Frameworks)", "Heading 2")
    set_el_text(orig[1291], "III.9 Systemdenken, Risiko & Resilienz (8 Frameworks)", "Heading 2")

    for idx in range(1069, 1328):
        p = para_map.get(orig[idx])
        if p is not None and p.text:
            txt = p.text.strip()
            m_fw = re.match(r"^#(\d+)\s+(.*)$", txt)
            if m_fw:
                p.text = ""
                p.paragraph_format.space_before = Pt(8)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.keep_with_next = True
                r = p.add_run(f"Framework {m_fw.group(1)}: {m_fw.group(2)}")
                r.bold = True
                r.font.size = Pt(10.5)
            elif "###" in txt or "\n" in txt:
                clean_txt = txt.replace("### ", "").replace("\n", " ")
                p.text = clean_txt

    new_body.extend(orig[747:820])    # ANHANG I: 5 PRAXIS-USE-CASES
    new_body.extend(orig[820:1068])   # ANHANG II: ARCHON OS — KOMPLETT-GLOSSAR
    new_body.extend(orig[1068:1328])  # ANHANG III: DECISION ENGINE & BOARDROOM (55 LÖSUNGS-FRAMEWORKS)

    # =========================================================================
    # ANHANG IV: SPEZIAL-LEITFÄDEN: IT-SICHERHEIT & COMPLIANCE (12 Guides)
    # =========================================================================
    new_body.append(make_p("Anhang IV: Spezial-Leitfäden: IT-Sicherheit & Compliance", "Heading 1"))
    new_body.append(make_p(
        "In diesem Anhang sind alle 12 spezialisierten Sicherheits-, Datenschutz- und Compliance-Leitfäden "
        "des Archon OS Ökosystems vollständig und übersichtlich gegliedert enthalten.",
        "Normal"
    ))

    sec_guides = [
        ("IV.1 DSGVO / GDPR Compliance für Agenten-Systeme", "docs/system/GDPR_COMPLIANCE_GUIDE.md"),
        ("IV.2 GoBD & ISO 27001 Revisionssicheres Audit-Logging", "docs/security/GOBD_ISO27001_AUDIT_LOG_GUIDE.md"),
        ("IV.3 Dual-LLM Prompt-Injection Guard", "docs/security/DUAL_LLM_PROMPT_INJECTION_GUARD_GUIDE.md"),
        ("IV.4 API-Keys, Berechtigungs-Scopes & Rate-Limits", "docs/security/API_KEYS_SCOPES_RATELIMITS_GUIDE.md"),
        ("IV.5 Secrets-Management & Key-Rotation", "docs/security/SECRETS_MANAGEMENT_UND_ROTATION.md"),
        ("IV.6 Lokales Privacy-Routing & Zero-Data-Leakage", "docs/security/LOCAL_LLM_PRIVACY_ROUTING_GUIDE.md"),
        ("IV.7 Reverse Proxy, SSL/TLS & SSO-Authentifizierung", "docs/security/REVERSE_PROXY_SSO_GUIDE.md"),
        ("IV.8 Break-Glass Recovery & Notfallzugriff", "docs/security/BREAK_GLASS_RECOVERY_GUIDE.md"),
        ("IV.9 E-Mail Approval Queue & Human-in-the-Loop Policies", "docs/system/EMAIL_APPROVAL_QUEUE_GUIDE.md"),
        ("IV.10 Approval Policies & Schwellenwert-Governance", "docs/system/APPROVAL_POLICIES_GUIDE.md"),
        ("IV.11 Notification Policy & Quiet Hours", "docs/system/NOTIFICATION_POLICY_QUIET_HOURS_GUIDE.md"),
        ("IV.12 Config Validation & Linting", "docs/system/CONFIG_VALIDATION_GUIDE.md"),
    ]
    for title, rel_path in sec_guides:
        new_body.extend(make_guide_elements(title, rel_path))

    # =========================================================================
    # ANHANG V: TECHNISCHE BETRIEBS- & INTEGRATIONS-HANDBÜCHER (22 Guides)
    # =========================================================================
    new_body.append(make_p("Anhang V: Technische Betriebs- & Integrations-Handbücher", "Heading 1"))
    new_body.append(make_p(
        "In diesem Anhang sind alle 22 technischen Betriebs-, Infrastruktur-, ERP- und Integrationshandbücher "
        "vollständig und übersichtlich gegliedert enthalten.",
        "Normal"
    ))

    sys_guides = [
        ("V.1 Archon MCP Server & Tool-Treiber Entwicklung", "docs/system/ARCHON_MCP_SERVER_GUIDE.md"),
        ("V.2 Dunning Engine & Automatisches Mahnwesen", "docs/system/DUNNING_ENGINE_GUIDE.md"),
        ("V.3 DocuSeal E-Signatur & Vertragsunterzeichnung", "docs/system/ESIGN_DOCUSEAL_GUIDE.md"),
        ("V.4 Telegram Receipt OCR & Belegdigitalisierung", "docs/system/TELEGRAM_RECEIPT_OCR_GUIDE.md"),
        ("V.5 Agenten-Scorecards & HR-Personalakten", "docs/system/AGENT_SCORECARDS_PERSONALAKTE_GUIDE.md"),
        ("V.6 Human Feedback Loop & Kontinuierliche Optimierung", "docs/system/HUMAN_FEEDBACK_LOOP_GUIDE.md"),
        ("V.7 Kanban Bulk Actions & Massenoperationen", "docs/system/KANBAN_BULK_ACTIONS_GUIDE.md"),
        ("V.8 Live Streaming mit SSE & WebSockets", "docs/system/LIVE_STREAMING_SSE_WEBSOCKET_GUIDE.md"),
        ("V.9 LLM Tracing mit Langfuse", "docs/system/LLM_TRACING_LANGFUSE_GUIDE.md"),
        ("V.10 Prompt Registry & Canary Releases", "docs/system/PROMPT_REGISTRY_CANARY_GUIDE.md"),
        ("V.11 Modell-Finetuning & Lokale Gewichtung", "docs/system/MODEL_FINETUNING_GUIDE.md"),
        ("V.12 Prometheus & Grafana Systemüberwachung", "docs/system/PROMETHEUS_GRAFANA_MONITORING_GUIDE.md"),
        ("V.13 Zentrales Logging mit Grafana Loki", "docs/system/CENTRAL_LOGGING_LOKI_GUIDE.md"),
        ("V.14 Metabase BI-Dashboard & Geschäftsanalytik", "docs/system/BI_DASHBOARD_METABASE_GUIDE.md"),
        ("V.15 Litestream SQLite Replikation & Disaster Recovery", "docs/system/LITESTREAM_REPLICATION_GUIDE.md"),
        ("V.16 Automatisierte Restore-Tests & Integritätsprüfung", "docs/system/AUTOMATED_RESTORE_TEST_GUIDE.md"),
        ("V.17 Chaos Resilience & Störungs-Simulation", "docs/system/CHAOS_RESILIENCE_GUIDE.md"),
        ("V.18 Ansible Infrastruktur-Automatisierung", "docs/system/ANSIBLE_INFRASTRUCTURE_GUIDE.md"),
        ("V.19 CI/CD Pipeline & E2E-Testing", "docs/system/CI_PIPELINE_E2E_TESTING_GUIDE.md"),
        ("V.20 Systemarchitektur & Technisches Audit 2026", "docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md"),
        ("V.21 Archon OS Strategische Roadmap 2026", "docs/system/ROADMAP_2026.md"),
        ("V.22 Archon ERP & CRM Architektur-Spezifikation (Säule 3)", "docs/system/ARCHON_ERP_ARCHITECTURE_SPEC.md"),
    ]
    for title, rel_path in sys_guides:
        new_body.extend(make_guide_elements(title, rel_path))

    # Finally append sectPr
    sect_pr = orig[1328]
    new_body.append(sect_pr)

    # Clear body and insert all elements in strict order
    for child in list(body):
        body.remove(child)
    for el in new_body:
        body.append(el)

    target_main = os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026.docx")
    for out_path in (TARGET_DOCX, target_main):
        try:
            print(f"Saving rebuilt Word document to {out_path} (Total elements: {len(new_body)})...")
            doc.save(out_path)
            print(f"SUCCESS: Saved {out_path}")
        except PermissionError:
            alt_path = out_path.replace(".docx", "_NEU.docx")
            print(f"[WARN] File locked in Word ({out_path}), saving to {alt_path} instead...")
            doc.save(alt_path)
            print(f"SUCCESS: Saved {alt_path}")


if __name__ == "__main__":
    rebuild_clean_docx()
