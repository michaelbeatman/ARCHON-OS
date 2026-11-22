"""
seo_execution_agent.py - Autonome SEO- & Content-Execution Pipeline für Archon OS
Verbindet SERP-Analyse, Intent-Strukturierung, Anti-AI-Slop-Textung und
automatisierten Multi-Kanal-Export (Obsidian & n8n Outbound-Webhooks).
"""

import os
import sys
import re
import json
import time
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONTENT_DIR = BASE_DIR / "obsidian_vault" / "05_Content"
CONTENT_DIR.mkdir(parents=True, exist_ok=True)

class SEOExecutionAgent:
    def __init__(self):
        self.banned_words = [
            "delve", "tapestry", "realm", "nestled", "vibrant", "testament",
            "beacon", "pivotal", "cutting-edge", "comprehensive", "robust",
            "at its core", "boasts", "moreover", "furthermore", "additionally"
        ]

    def _generate_slug(self, text: str) -> str:
        s = text.lower().strip()
        s = re.sub(r'[^a-z0-9\-]+', '-', s)
        return s.strip('-')[:50]

    def plan_seo_blueprint(
        self,
        topic: str,
        keyword: str,
        audience: str = "B2B / Tech",
        serp_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Erstellt eine suchintentionierte Gliederung mit H2/H3-Struktur und Meta-Angaben.

        ``serp_analysis`` (optional) ist ein Dict mit einer oder mehreren dieser
        Quellen:

        * ``headings`` / ``h2``: H2-Eintraege (Strings oder Dicts mit ``title``
          bzw. ``text``).
        * ``people_also_ask`` / ``questions``: Fragen (Strings oder Dicts mit
          ``question``, ``title`` bzw. ``text``), als H3 eingeordnet.

        Ohne verwertbares ``serp_analysis`` bleibt die 5-H2-Standardvorlage als
        Fallback erhalten. Die Herkunft wird ueber ``outline_source`` (``"serp"``
        bzw. ``"template_fallback"``), ``serp_analyzed`` und ``serp_sources``
        ausgewiesen — es wird nie SERP-Analyse behauptet, die nicht stattfand.
        """
        slug = self._generate_slug(keyword or topic)
        meta_desc = f"Praxisleitfaden zu {topic}. Konkrete Architektur, Implementierungsschritte und Best Practices für {audience}."

        fallback_outline = [
            {"level": "h2", "title": f"1. Was ist {topic} und warum ist es relevant?"},
            {"level": "h2", "title": "2. Technische Kernarchitektur & Systemkomponenten"},
            {"level": "h2", "title": "3. Schritt-für-Schritt Implementierungs-Workflow"},
            {"level": "h2", "title": "4. Typische Hürden, Performance-Flaschenhälse & Lösungen"},
            {"level": "h2", "title": "5. Fazit & Handlungsleitfaden für die Praxis"}
        ]

        serp_sources: Dict[str, int] = {}
        outline: List[Dict[str, str]] = []
        if isinstance(serp_analysis, dict):
            for key in ("headings", "h2"):
                titles = self._serp_titles(serp_analysis.get(key))
                if titles:
                    serp_sources[key] = len(titles)
                    outline.extend({"level": "h2", "title": t} for t in titles)
            for key in ("people_also_ask", "questions"):
                titles = self._serp_titles(serp_analysis.get(key))
                if titles:
                    serp_sources[key] = len(titles)
                    outline.extend({"level": "h3", "title": t} for t in titles)

        if outline:
            outline_source = "serp"
            serp_analyzed = True
        else:
            outline = fallback_outline
            outline_source = "template_fallback"
            serp_analyzed = False
            serp_sources = {}

        return {
            "topic": topic,
            "target_keyword": keyword,
            "slug": slug,
            "meta_description": meta_desc[:160],
            "target_audience": audience,
            "outline": outline,
            "outline_source": outline_source,
            "serp_analyzed": serp_analyzed,
            "serp_sources": serp_sources,
        }

    @staticmethod
    def _serp_titles(value: Any) -> List[str]:
        """Normalisiert SERP-Rohdaten (String, Dict oder Liste) zu Titeln."""
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, (list, tuple)):
            return []
        titles: List[str] = []
        for entry in value:
            if isinstance(entry, str):
                title = entry.strip()
            elif isinstance(entry, dict):
                title = str(
                    entry.get("title")
                    or entry.get("text")
                    or entry.get("question")
                    or ""
                ).strip()
            else:
                title = ""
            if title:
                titles.append(title)
        return titles

    def generate_article_markdown(self, blueprint: Dict[str, Any], custom_body: Optional[str] = None) -> str:
        """Kompiliert das fertige Markdown unter strenger Anti-AI-Slop Disziplin."""
        topic = blueprint["topic"]
        kw = blueprint["target_keyword"]
        today_str = datetime.date.today().isoformat()

        outline_source = str(blueprint.get("outline_source") or "template_fallback")
        serp_analyzed = bool(blueprint.get("serp_analyzed", False))

        frontmatter = f"""---
title: "{topic}: Vollständiger Architektur- & Praxisleitfaden"
slug: "{blueprint['slug']}"
date: {today_str}
author: "Archon OS Content Engine"
keywords: ["{kw}", "Archon OS", "Agentic Systems", "Automation"]
meta_description: "{blueprint['meta_description']}"
status: "review"
approval_required: true
outline_source: "{outline_source}"
serp_analyzed: {str(serp_analyzed).lower()}
---
"""

        if custom_body:
            body = custom_body
        else:
            body = f"""# {topic}

{blueprint['meta_description']}

## 1. Was ist {topic} und warum ist es relevant?
Unternehmen stehen vor der Herausforderung, manuelle Prozesse zu reduzieren und Reaktionszeiten zu minimieren. {topic} bietet eine strukturierte Methode, um Aufgaben deterministisch und fehlerfrei auszuführen. Statt vager theoretischer Konzepte zählen messbare Durchlaufzeiten und Stabilität.

## 2. Technische Kernarchitektur & Systemkomponenten
Die funktionale Architektur gliedert sich in drei Hauptschichten:
1. **Erfassungsschicht (Ingestion):** Nimmt Trigger, Webhooks oder Datenströme entgegen.
2. **Kognitions- und Ausführungsschicht (Kernel):** Validiert Eingaben gegen Schemas und steuert Subprozesse.
3. **Persistenz- und Telemetrieschicht:** Speichert Statusberichte in einer relationalen Datenbank mit Write-Ahead Logging.

## 3. Schritt-für-Schritt Implementierungs-Workflow
* **Schritt 1:** Definiere die Ein- und Ausgabeschnittstellen via OpenAPI / Pydantic.
* **Schritt 2:** Implementiere automatisierte Unit- und Integrationstests (z. B. Playwright).
* **Schritt 3:** Schließe die Ausführung an das zentrale Monitoring an, um Latenzausreißer frühzeitig abzufangen.

## 4. Typische Hürden, Performance-Flaschenhälse & Lösungen
* **Hürde 1 (Gleichzeitige Zugriffe):** Parallele Dateizugriffe erzeugen Lock-Konflikte. **Lösung:** Isolation über separate Arbeitsverzeichnisse oder Git-Worktrees.
* **Hürde 2 (Ressourcenverbrauch):** Unkontrollierte Schleifen blockieren CPU-Kerne. **Lösung:** Watchdog-Daemon mit strengen Zeit- und Request-Limits.

## 5. Fazit & Handlungsleitfaden für die Praxis
Erfolgreiche Systeme zeichnen sich durch strikte Modulgrenzen und messbare SLAs aus. Starte mit einem minimalen funktionalen Prototyp und skaliere die Kapazität bedarfsgerecht.
"""

        # Slop-Filter-Check: Streiche verbotene Wörter
        for w in self.banned_words:
            pattern = re.compile(re.escape(w), re.IGNORECASE)
            body = pattern.sub("", body)

        return frontmatter + "\n" + body

    async def execute_content_pipeline(
        self,
        topic: str,
        keyword: str,
        audience: str = "B2B / Tech",
        trigger_n8n: bool = False,
        serp_analysis: Optional[Dict[str, Any]] = None,
        approved: bool = False,
    ) -> Dict[str, Any]:
        """Fuehrt Blueprint -> Entwurf -> Vault -> optionalen n8n-Draft aus.

        Es gibt bewusst keinen direkten Publish-Pfad: der n8n-Trigger erzeugt
        ausschliesslich einen CMS-Entwurf (``draft_cms``), auch wenn
        ``trigger_n8n`` gesetzt ist. ``approved`` dokumentiert lediglich die
        Absicht des Aufrufers; veroeffentlicht wird erst nach HITL-Freigabe via
        ``mark_asset_published``.
        """
        blueprint = self.plan_seo_blueprint(topic, keyword, audience, serp_analysis)
        content_md = self.generate_article_markdown(blueprint)

        # In Obsidian speichern (Entwurf, nicht veroeffentlicht)
        today_str = datetime.date.today().isoformat()
        filename = f"{today_str}_{blueprint['slug']}.md"
        file_path = CONTENT_DIR / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content_md)

        # n8n Outbound Trigger: nur Entwurf, niemals Direkt-Publish
        n8n_result = {"status": "skipped"}
        if trigger_n8n:
            try:
                import core_dispatcher
                n8n_result = await core_dispatcher.trigger_n8n_execution(
                    parent_project_id="seo_pipeline",
                    title=f"SEO: {topic}",
                    final_report_path=str(file_path),
                    content=content_md[:1500],
                    target_action="draft_cms"
                )
            except Exception as e:
                n8n_result = {"status": "error", "message": str(e)}

        return {
            "status": "review",
            "approval_required": True,
            "outline_source": blueprint["outline_source"],
            "serp_analyzed": blueprint["serp_analyzed"],
            "topic": topic,
            "keyword": keyword,
            "slug": blueprint["slug"],
            "vault_path": str(file_path),
            "words_count": len(content_md.split()),
            "n8n_dispatch": n8n_result,
            "approved": approved,
            "publish_hint": "Publishing requires HITL mark_asset_published; no direct publish.",
            "created_at": datetime.datetime.now().isoformat()
        }

if __name__ == "__main__":
    import asyncio
    agent = SEOExecutionAgent()
    res = asyncio.run(agent.execute_content_pipeline(
        topic="Agentic Operating Systems",
        keyword="Agentic OS",
        trigger_n8n=False
    ))
    print("SEO Pipeline Result:", json.dumps(res, indent=2))
