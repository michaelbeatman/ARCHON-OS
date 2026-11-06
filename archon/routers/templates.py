"""Router /api/templates — ausgelagerte Routen (Modularisierung main.py -> archon/routers)."""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    logger, WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR, APP_ROOT,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json, atomic_write_json,
)

router = APIRouter()


PROMPT_TEMPLATES_PATHS = [
    "/opt/data/prompt_templates.json",
    os.path.join(MEMORY_DIR, "prompt_templates.json"),
    os.path.join(WORKSPACE_DIR, "data", "prompt_templates.json"),
    "./data/prompt_templates.json",
    "prompt_templates.json"
]

_FABRIC_CACHE: Optional[List[Dict[str, Any]]] = None

_PROMPT_STUDIO_CACHE: Optional[List[Dict[str, Any]]] = None

class PromptOptimizeRequest(BaseModel):
    prompt: str
    agent_id: Optional[str] = None


class TemplateSaveRequest(BaseModel):
    category: str
    title: str
    description: Optional[str] = ""
    fields: dict
    raw_text: Optional[str] = None


class TemplateRenderRequest(BaseModel):
    values: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None

def _load_prompt_templates() -> dict:
    for p in PROMPT_TEMPLATES_PATHS:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[Templates] Fehler beim Laden von {p}: {e}")
    return {
        "categories": [
            "Strategie & Business",
            "Marketing & Outreach",
            "Governance & Recht"
        ],
        "templates": []
    }


def _save_prompt_templates(data: dict):
    saved = False
    for p in ["/opt/data/prompt_templates.json", os.path.join(MEMORY_DIR, "prompt_templates.json"), os.path.join(WORKSPACE_DIR, "data", "prompt_templates.json"), "./data/prompt_templates.json"]:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            saved = True
        except Exception:
            pass
    return saved


@router.get("/api/templates")
async def get_prompt_templates():
    """Liefert alle Prompt-Vorlagen und Kategorien strukturiert zurück."""
    return _load_prompt_templates()


def _load_fabric_patterns_data() -> List[Dict[str, Any]]:
    global _FABRIC_CACHE
    if _FABRIC_CACHE is not None:
        return _FABRIC_CACHE

    paths = [
        "/app/fabric_patterns_de.csv",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fabric_patterns_de.csv"),
        "./fabric_patterns_de.csv",
        "/app/data/fabric_patterns_de.csv"
    ]
    records = []
    for p in paths:
        if os.path.exists(p):
            try:
                import csv
                with open(p, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f, delimiter=";")
                    for row in reader:
                        records.append({
                            "id": row.get("ID", ""),
                            "name_de": row.get("Name_DE", ""),
                            "category": row.get("Kategorie", "Allgemein & Produktivität"),
                            "variables": row.get("Empfohlene_Variablen", ""),
                            "purpose": row.get("Zweck_Original", ""),
                            "raw_path": row.get("Raw_Path", "")
                        })
                if records:
                    break
            except Exception as e:
                logger.warning(f"[Fabric API] Fehler beim Laden von {p}: {e}")

    _FABRIC_CACHE = records
    return _FABRIC_CACHE


@router.get("/api/fabric/patterns")
async def get_fabric_patterns(category: Optional[str] = None, q: Optional[str] = None):
    """Liefert alle Fabric-Patterns strukturiert mit Kategorien zurück."""
    patterns = _load_fabric_patterns_data()
    categories = sorted(list({p["category"] for p in patterns}))

    filtered = patterns
    if category and category != "all" and category != "Favoriten":
        filtered = [p for p in filtered if p["category"].lower() == category.lower()]
    if q:
        query = q.lower().strip()
        filtered = [
            p for p in filtered
            if query in p["name_de"].lower() or query in p["id"].lower() or query in p["purpose"].lower()
        ]

    return {
        "status": "ok",
        "total": len(patterns),
        "count": len(filtered),
        "categories": categories,
        "patterns": filtered
    }


@router.get("/api/fabric/pattern/{pattern_id}")
async def get_fabric_pattern_detail(pattern_id: str):
    """Liefert den detaillierten System-Prompt und Felder eines spezifischen Fabric-Patterns."""
    patterns = _load_fabric_patterns_data()
    pat = next((p for p in patterns if p["id"] == pattern_id), None)
    if not pat:
        raise HTTPException(status_code=404, detail="Fabric-Pattern nicht gefunden.")

    # System.md Inhalt laden (aus GitHub Cache oder Fallback)
    raw_path = pat.get("raw_path") or f"data/patterns/{pattern_id}/system.md"
    raw_url = f"https://raw.githubusercontent.com/danielmiessler/Fabric/main/{raw_path}"
    system_text = ""
    try:
        import urllib.request
        req = urllib.request.Request(raw_url, headers={"User-Agent": "Mozilla/5.0"})
        res = urllib.request.urlopen(req, timeout=4.0)
        system_text = res.read().decode("utf-8", errors="ignore")
    except Exception:
        system_text = f"# IDENTITÄT & ROLLE:\n{pat.get('purpose', '')}\n\n# ZIEL:\nFühre eine strukturierte Auswertung für '{pat.get('name_de', pattern_id)}' durch."

    # Erstelle deutschen Template-Bauplan
    german_template = (
        f"# ROLLE & EXPERTISE:\n"
        f"Du agierst als spezialisierter Experte für: {pat.get('name_de', pattern_id)}.\n"
        f"{pat.get('purpose', '')}\n\n"
        f"# AUFGABE & ZIEL:\n"
        f"Analysiere und bearbeite die übergebene Eingabe mit höchster analytischer Tiefe.\n\n"
        f"# ARBEITSSCHRITTE:\n"
        f"1. Gründliche Prüfung der bereitgestellten Daten und Extrahieren der Kernaussagen.\n"
        f"2. Strukturierte, präzise Aufbereitung ohne Füllwörter oder Phrasen.\n"
        f"3. Formulierung konkreter, umsetzbarer Erkenntnisse oder Handlungsempfehlungen.\n\n"
        f"# SPRACHE & AUSGABE:\n"
        f"Formuliere das vollständige Ergebnis auf Deutsch, klar gegliedert in Markdown."
    )

    return {
        "status": "ok",
        "pattern": pat,
        "system_raw": system_text,
        "template_de": german_template,
        "default_fields": [
            {
                "id": "context_input",
                "label": "Eingabetext / Kontext / Code",
                "type": "multiline",
                "required": True,
                "placeholder": "Füge hier deinen zu analysierenden Text, Code, URL oder Zusammenfassung ein..."
            },
            {
                "id": "specific_focus",
                "label": "Besonderer Schwerpunkt / Fragestellung (Optional)",
                "type": "text",
                "required": False,
                "placeholder": "z. B. Fokus auf Sicherheitsrisiken, Einsparpotenziale oder ROI..."
            },
            {
                "id": "output_style",
                "label": "Ausgabeformat (Optional)",
                "type": "select",
                "options": ["Ausführlicher Bericht", "Kompaktes Executive Summary", "Aufzählung / Bullet-Points", "Schritt-für-Schritt Anleitung"],
                "required": False
            }
        ]
    }


def _load_prompt_studio_catalog() -> List[Dict[str, Any]]:
    global _PROMPT_STUDIO_CACHE
    if _PROMPT_STUDIO_CACHE is not None:
        return _PROMPT_STUDIO_CACHE

    paths = [
        "/app/prompt_studio_catalog.json",
        "/app/data/prompt_studio_catalog.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_studio_catalog.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prompt_studio_catalog.json"),
        "./prompt_studio_catalog.json",
        "./data/prompt_studio_catalog.json",
        "/opt/data/prompt_templates.json"
    ]
    records = []
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    records = json.load(f)
                if records:
                    break
            except Exception as e:
                logger.warning(f"[Prompt Studio API] Fehler beim Laden von {p}: {e}")

    _PROMPT_STUDIO_CACHE = records or []
    return _PROMPT_STUDIO_CACHE


@router.get("/api/templates/catalog")
async def get_prompt_studio_catalog(category: Optional[str] = None, q: Optional[str] = None):
    """Liefert den gesamten Archon Prompt Studio Katalog (824 Vorlagen) gefiltert nach Kategorie/Suche."""
    catalog = _load_prompt_studio_catalog()
    categories = sorted(list({t["category"] for t in catalog if "category" in t}))

    filtered = catalog
    if category and category != "all" and category != "Favoriten":
        filtered = [t for t in filtered if t.get("category", "").lower() == category.lower() or t.get("category_slug", "").lower() == category.lower()]
    if q:
        query = q.lower().strip()
        filtered = [
            t for t in filtered
            if query in t.get("name", "").lower() or query in t.get("id", "").lower() or query in t.get("description", "").lower()
        ]

    # Kompakte Übersicht für das Frontend-Menü
    summaries = [
        {
            "id": t.get("id"),
            "name": t.get("name_de") or t.get("name"),
            "name_de": t.get("name_de") or t.get("name"),
            "category": t.get("category"),
            "category_slug": t.get("category_slug"),
            "tier": t.get("tier", "Community"),
            "description": t.get("description_de") or t.get("description", ""),
            "description_de": t.get("description_de") or t.get("description", ""),
            "field_count": len(t.get("form_fields", []))
        }
        for t in filtered
    ]

    return {
        "status": "ok",
        "total": len(catalog),
        "count": len(summaries),
        "categories": categories,
        "templates": summaries
    }


@router.get("/api/templates/{template_slug}/schema")
async def get_template_schema(template_slug: str):
    """Gibt das Formular-Schema und den Template-Text für ein einzelnes Template zurück."""
    catalog = _load_prompt_studio_catalog()
    tpl = next((t for t in catalog if t.get("id") == template_slug), None)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template nicht gefunden.")
    return {
        "status": "ok",
        "template": tpl
    }


@router.post("/api/templates/{template_slug}/render")
async def render_template_prompt(template_slug: str, req: TemplateRenderRequest):
    """
    Rendert das Archon_Prompt_Template mit den übergebenen Formularwerten.
    Verhalten A: Leere optionale Variablen und deren Zeilen werden rückstandslos entfernt.
    Inklusive Unterstützung für Advanced Options (Denk-Methodik, Ausgabe-Vorgaben, etc.).
    """
    catalog = _load_prompt_studio_catalog()
    tpl = next((t for t in catalog if t.get("id") == template_slug), None)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template nicht gefunden.")

    raw_template = tpl.get("archon_prompt_template", "")
    values = req.values or {}
    options = req.options or {}

    # Variablen-Ersetzung & Verhalten A
    rendered_lines = []
    for line in raw_template.split("\n"):
        line_has_empty_var = False
        vars_in_line = re.findall(r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}', line)
        for var_name in vars_in_line:
            val = str(values.get(var_name, "")).strip()
            if not val:
                form_fields = tpl.get("form_fields", [])
                field_def = next((f for f in form_fields if f.get("id") == var_name), None)
                if field_def and not field_def.get("required", False):
                    line_has_empty_var = True
                    break
                else:
                    placeholder = field_def.get("label_de") or field_def.get("label") or var_name if field_def else var_name
                    line = line.replace(f"{{{{{var_name}}}}}", f"[{placeholder.upper()}]")
                    line = line.replace(f"{{{{ {var_name} }}}}", f"[{placeholder.upper()}]")
            else:
                line = line.replace(f"{{{{{var_name}}}}}", val)
                line = line.replace(f"{{{{ {var_name} }}}}", val)

        if not line_has_empty_var:
            rendered_lines.append(line)

    assembled = "\n".join(rendered_lines).strip()

    # Advanced Options einspeisen
    adv_sections = []
    thinking = []
    if options.get("stepbystep"):
        thinking.append("- Schritt für Schritt: Durchdenken Sie das Problem systematisch in logischen Einzelschritten, bevor Sie das Endergebnis formulieren.")
    if options.get("reasoning"):
        thinking.append("- Begründung & Herleitung: Erläutern Sie Ihre strategische Entscheidungslogik und Gedankengänge transparent.")
    if options.get("perspectives"):
        thinking.append("- Multiperspektivität: Beleuchten Sie die Fragestellung aus mehreren relevanten Blickwinkeln und wägen Sie Gegenargumente ab.")
    if options.get("systematic"):
        thinking.append("- Systematischer Ansatz: Wenden Sie ein klares, strukturiertes Analyse- und Handlungs-Framework an.")
    if options.get("cot"):
        thinking.append("- Chain-of-Thought: Verknüpfen Sie alle Zwischenschritte nachvollziehbar miteinander.")
    if options.get("roleplay"):
        thinking.append("- Vertieftes Rollenspiel: Agieren Sie strikt aus der spezifizierten Expertenperspektive mit profunder Fachsprache.")
    if thinking:
        adv_sections.append("### DENK-METHODIK & STRATEGIE:\n" + "\n".join(thinking))

    output = []
    if options.get("confidence"):
        output.append("- Konfidenz-Rating: Weisen Sie zentralen Empfehlungen eine Zuverlässigkeitsbewertung (Hoch/Mittel/Niedrig) zu.")
    if options.get("citations"):
        output.append("- Quellen & Belege: Untermauern Sie Fakten, Daten und Kernaussagen mit konkreten Quellenverweisen.")
    ex_count = int(options.get("examples_count") or 0)
    if ex_count > 0:
        output.append(f"- Praxisbeispiele: Integrieren Sie mindestens {ex_count} konkrete, illustrative Anwendungsbeispiele.")
    if output:
        adv_sections.append("### ERWEITERTE AUSGABE-VORGABEN:\n" + "\n".join(output))

    if options.get("context"):
        adv_sections.append(f"### ZUSÄTZLICHER KONTEXT & HINTERGRUND:\n{options['context']}")
    if options.get("examples"):
        adv_sections.append(f"### REFERENZ-BEISPIELE (GEWÜNSCHTER AUSGABESTIL):\n{options['examples']}")
    if options.get("success"):
        adv_sections.append(f"### ERFOLGSKRITERIEN (DEFINITION OF DONE):\n{options['success']}")

    if adv_sections:
        adv_block = "\n\n".join(adv_sections)
        if "4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT" in assembled:
            assembled = assembled.replace(
                "4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT",
                f"{adv_block}\n\n4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT"
            )
        else:
            assembled += f"\n\n{adv_block}"

    final_rendered = re.sub(r'\n{3,}', '\n\n', assembled).strip()
    return {
        "status": "ok",
        "rendered_prompt": final_rendered
    }


@router.post("/api/templates")
async def save_prompt_template(req: TemplateSaveRequest):
    """Speichert eine neue oder angepasste Vorlage in der persistenten Template-Bibliothek."""
    data = _load_prompt_templates()
    if req.category not in data.get("categories", []):
        data.setdefault("categories", []).append(req.category)
    
    raw_text = req.raw_text
    if not raw_text and req.fields:
        raw_text = (
            f"# ROLLE:\n{req.fields.get('rolle', 'Experte')}\n\n"
            f"# ZIEL:\n{req.fields.get('ziel', '')}\n\n"
            f"# SOP (ARBEITSSCHRITTE):\n{req.fields.get('sop', '')}\n\n"
            f"# RESTRIKTIONEN (PHRASENVERBOT):\n{req.fields.get('restriktionen', '')}\n\n"
            f"# AUSGABE-ARTEFAKT:\n{req.fields.get('ausgabe_artefakt', '')}"
        )
    
    new_tpl = {
        "id": f"tpl-custom-{int(time.time()*1000)%100000}",
        "category": req.category,
        "title": req.title,
        "description": req.description or "",
        "fields": req.fields,
        "raw_text": raw_text
    }
    data.setdefault("templates", []).insert(0, new_tpl)
    _save_prompt_templates(data)
    return {"status": "ok", "template": new_tpl}
