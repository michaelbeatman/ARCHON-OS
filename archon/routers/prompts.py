"""Router fuer Prompt Studio Upload und Prompt-Optimierung."""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from archon.core.paths import OPT_DATA_DIR

logger = logging.getLogger("archon.routers.prompts")

router = APIRouter(tags=["prompts"])


@router.post("/api/prompt-studio/upload-context")
async def upload_prompt_studio_context(file: UploadFile = File(...)):
    """Nimmt eine Kontext-Datei (.pdf, .docx, .txt, .csv, .json, .md, .py, .js, etc.) entgegen,
    speichert sie unter /opt/data/temp_uploads/ ab und extrahiert den Text.
    """
    upload_dir = os.path.join(OPT_DATA_DIR, "temp_uploads")
    os.makedirs(upload_dir, exist_ok=True)

    filename = os.path.basename(file.filename or "upload.txt")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
    timestamp = int(time.time() * 1000)
    saved_filename = f"{timestamp}_{safe_name}"
    filepath = os.path.join(upload_dir, saved_filename)

    def _save_uploaded_file(path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)

    try:
        content = await file.read()
        await asyncio.to_thread(_save_uploaded_file, filepath, content)
    except Exception as e:
        logger.error(f"[Prompt Studio Upload] Fehler beim Speichern der Datei: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {e}")

    ext = os.path.splitext(filename)[1].lower()

    def _extract() -> str:
        if ext == ".pdf":
            try:
                import pypdf

                reader = pypdf.PdfReader(filepath)
                pages_text = []
                for p in reader.pages:
                    t = p.extract_text()
                    if t:
                        pages_text.append(t)
                return "\n\n".join(pages_text).strip()
            except Exception as pe:
                logger.warning(f"[Prompt Studio Upload] pypdf Fehler: {pe}")
                raise HTTPException(status_code=400, detail=f"PDF konnte nicht gelesen werden: {pe}")

        elif ext in [".docx", ".doc"]:
            try:
                import docx

                doc = docx.Document(filepath)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables_text = []
                for table in doc.tables:
                    for row in table.rows:
                        row_vals = [cell.text.strip() for cell in row.cells]
                        if any(row_vals):
                            tables_text.append(" | ".join(row_vals))
                return "\n".join(paragraphs + tables_text).strip()
            except Exception as de:
                logger.warning(f"[Prompt Studio Upload] docx Fehler: {de}")
                raise HTTPException(status_code=400, detail=f"Word-Dokument konnte nicht gelesen werden: {de}")

        elif ext == ".csv":
            try:
                with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
                    sample = f.read(2048)
                    f.seek(0)
                    delimiter = ";" if ";" in sample and sample.count(";") > sample.count(",") else ","
                    reader = csv.reader(f, delimiter=delimiter)
                    rows = list(reader)
                if rows:
                    header = rows[0]
                    md_lines = [
                        "| " + " | ".join(header) + " |",
                        "| " + " | ".join(["---"] * len(header)) + " |",
                    ]
                    for row in rows[1:101]:
                        row_padded = (row + [""] * len(header))[: len(header)]
                        md_lines.append("| " + " | ".join([c.replace("\n", " ") for c in row_padded]) + " |")
                    if len(rows) > 101:
                        md_lines.append(
                            f"\n*(Tabelle gekürzt: {len(rows)-1} Datensätze insgesamt, erste 100 dargestellt)*"
                        )
                    return "\n".join(md_lines).strip()
                return ""
            except Exception as ce:
                logger.warning(f"[Prompt Studio Upload] CSV Fehler: {ce}")
                raise HTTPException(status_code=400, detail=f"CSV konnte nicht gelesen werden: {ce}")

        elif ext in [".txt", ".md", ".py", ".js", ".json", ".html", ".yaml", ".yml", ".ts"]:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()

        else:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()

    try:
        extracted_text = await asyncio.to_thread(_extract)

    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"[Prompt Studio Upload] Text-Extraktionsfehler: {ex}")
        raise HTTPException(status_code=400, detail=f"Text-Extraktion fehlgeschlagen: {ex}")

    return {
        "filename": filename,
        "char_count": len(extracted_text),
        "extracted_text": extracted_text,
    }


class TemplateSaveRequest(BaseModel):
    category: str
    title: str
    description: Optional[str] = ""
    fields: dict
    raw_text: Optional[str] = None


class PromptOptimizeRequest(BaseModel):
    prompt: str
    agent_id: Optional[str] = None


@router.post("/api/prompts/optimize")
async def optimize_prompt_endpoint(req: PromptOptimizeRequest):
    """Nimmt unstrukturierte Nutzereingabe entgegen,
    sendet via OmniRoute einen schnellen Call an ein kostenguenstiges Modell
    und transformiert den Text in die 5-Felder-Struktur inklusive Phrasenverbot.
    """
    import main as app_main

    raw_input = req.prompt.strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="Prompt darf nicht leer sein.")

    optimizer_system_prompt = (
        "Du bist der leitende Prompt-Architekt von Archon OS.\n"
        "Transformiere die unstrukturierte Benutzereingabe in einen professionellen 5-Felder-Prompt.\n"
        "Die Ausgabe MUSS EXAKT die folgenden 5 Abschnitte mit Markdown-Headings enthalten:\n\n"
        "# ROLLE:\n"
        "[Passende, spezialisierte Rollenbezeichnung]\n\n"
        "# ZIEL:\n"
        "[Klares, messbares Arbeitsergebnis]\n\n"
        "# SOP (ARBEITSSCHRITTE):\n"
        "1. [Schritt 1]\n"
        "2. [Schritt 2]\n"
        "3. [Schritt 3]\n\n"
        "# RESTRIKTIONEN (PHRASENVERBOT):\n"
        "- Phrasenverbot: Keine Begrüßungs- oder Höflichkeitsfloskeln ('Hallo', 'Gerne helfe ich', 'Möchten Sie', 'Wie kann ich').\n"
        "- Keine Gegenfragen an den Nutzer; triff plausible Annahmen.\n"
        "- Kein Konjunktiv; handlungsorientierte Sprache.\n"
        "- Striktes Markdown mit klaren Überschriften.\n\n"
        "# AUSGABE-ARTEFAKT:\n"
        "[Strukturierter Markdown-Bericht zur Ablage in Obsidian]\n\n"
        "WICHTIG: Gib AUSSCHLIESSLICH den 5-Felder-Prompt aus, ohne jegliches Vorgeplänkel oder Nachwort!"
    )

    try:
        res = await app_main.core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="prompt_optimizer",
            agent_name="Prompt Optimizer",
            prompt=f"Transformiere folgende Benutzereingabe:\n\n{raw_input}",
            role="Prompt Architect",
            system_prompt=optimizer_system_prompt,
            model="auto/best-fast",
        )
        opt_text = res.get("content", "").strip()
        if not opt_text or len(opt_text) < 30:
            opt_text = (
                f"# ROLLE:\nExecutive Decision Specialist\n\n"
                f"# ZIEL:\n{raw_input}\n\n"
                f"# SOP (ARBEITSSCHRITTE):\n"
                f"1. Analyse der Anforderung: {raw_input[:60]}\n"
                f"2. Methodische Erarbeitung der Lösungsarchitektur\n"
                f"3. Validierung und strukturierte Dokumentation\n\n"
                f"# RESTRIKTIONEN (PHRASENVERBOT):\n"
                f"- Keine Begrüßungsfloskeln ('Hallo', 'Gerne helfe ich').\n"
                f"- Keine Gegenfragen an den Nutzer.\n"
                f"- Striktes Markdown.\n\n"
                f"# AUSGABE-ARTEFAKT:\n"
                f"Markdown-Dokument für Obsidian (/opt/data/obsidian/01_PROJEKTE/)"
            )
        return {
            "status": "ok",
            "optimized_prompt": opt_text,
            "original_prompt": raw_input,
        }
    except Exception as e:
        logger.error(f"[Prompt Optimizer] Exception: {e}")
        fallback_text = (
            f"# ROLLE:\nExecutive Specialist\n\n"
            f"# ZIEL:\n{raw_input}\n\n"
            f"# SOP (ARBEITSSCHRITTE):\n"
            f"1. Analyse der Vorgaben\n"
            f"2. Fachliche Ausarbeitung der Arbeitspakete\n"
            f"3. Finale Bereitstellung\n\n"
            f"# RESTRIKTIONEN (PHRASENVERBOT):\n"
            f"- Keine Höflichkeitsfloskeln oder Rückfragen.\n"
            f"- Striktes Markdown.\n\n"
            f"# AUSGABE-ARTEFAKT:\n"
            f"Obsidian Markdown-Bericht"
        )
        return {
            "status": "ok",
            "optimized_prompt": fallback_text,
            "original_prompt": raw_input,
        }
