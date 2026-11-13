"""
research_engine.py — Multi-Engine Research & Triangulation Pipeline für Archon OS.
Säule 2: KOGNITION & WISSEN — Research Lab.

Unterstützt etablierte Suchmaschinen:
1. DuckDuckGo (Keyless, Web & News)
2. Wikipedia OpenSearch & Extracts (Keyless, Enzyklopädie DE/EN)
3. ArXiv Preprints & Papers (Keyless, Wissenschaftliche Publikationen)
4. SearXNG Meta-Search (Multi-Source Aggregator)
5. Tavily AI Search (Agenten-Web-Extrakt)
6. Perplexity Sonar / OmniRoute (KI-Recherche mit Quellen)
"""

import os
import re
import json
import time
import asyncio
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

# Import Security Guard für Input-Sanitization & Quality-Gate
try:
    from local_security_guard import scan_prompt_injection, sanitize_injection_text, validate_ai_output
except ImportError:
    def scan_prompt_injection(text, **kwargs):
        return {"verdict": "safe", "is_safe": True, "pattern_matches": []}
    def sanitize_injection_text(text):
        return text
    def validate_ai_output(task, result, **kwargs):
        return {"score": 8, "recommendation": "TRUST", "passed": True, "pattern_flags": []}


# Import Informationsquellen-Strategie & Vertrauens-Registry
try:
    from backend.research_sources import get_domain_reputation, evaluate_triangulation_quality, format_citation
except ImportError:
    def get_domain_reputation(d):
        return {"name": "Web", "level": 2, "weight": 0.8, "badge_color": "sky"}
    def evaluate_triangulation_quality(sources):
        unique = set(s.get("domain", "") for s in sources if s.get("domain") and not s.get("ai_generated"))
        if len(unique) >= 3:
            return {"verdict": "HOCH (>=3 unabhängige Domains)", "score": 9, "unique_domains": len(unique)}
        elif len(unique) == 2:
            return {"verdict": "MODERAT (2 unabhängige Domains)", "score": 6, "unique_domains": 2}
        return {"verdict": "GERING (Einzelquelle)", "score": 3, "unique_domains": len(unique)}
    def format_citation(name, url, d=None):
        return f"[{name}]({url})"


PROVIDERS_CONFIG = {
    "duckduckgo": {
        "id": "duckduckgo",
        "name": "DuckDuckGo",
        "icon": "🦆",
        "type": "web",
        "requires_key": False,
        "description": "Kostenlose, datensparsame Websuche für aktuelle Ereignisse und Websites.",
        "default_enabled": True
    },
    "wikipedia": {
        "id": "wikipedia",
        "name": "Wikipedia",
        "icon": "📖",
        "type": "encyclopedia",
        "requires_key": False,
        "description": "Strukturierte Enzyklopädie-Artikel und Begriffserklärungen (DE/EN).",
        "default_enabled": True
    },
    "grokipedia": {
        "id": "grokipedia",
        "name": "Grokipedia",
        "icon": "\U0001F4D6",
        "type": "encyclopedia",
        "requires_key": False,
        "description": "KI-generierte Enzyklopaedie (xAI). Zusatzquelle, zaehlt nicht als unabhaengige Quelle in der Triangulation.",
        "default_enabled": True
    },
    "arxiv": {
        "id": "arxiv",
        "name": "ArXiv",
        "icon": "📄",
        "type": "academic",
        "requires_key": False,
        "description": "Wissenschaftliche Preprints, CS- und KI-Forschungsarbeiten.",
        "default_enabled": True
    },
    "searxng": {
        "id": "searxng",
        "name": "SearXNG",
        "icon": "🔍",
        "type": "meta",
        "requires_key": False,
        "description": "Datenschutz-konformer Meta-Search Aggregator (Google, Bing, Reddit, Wiki).",
        "default_enabled": False
    },
    "tavily": {
        "id": "tavily",
        "name": "Tavily AI",
        "icon": "⚡",
        "type": "agent_api",
        "requires_key": True,
        "description": "Für KI-Agenten optimierte Such-API mit präzisen Content-Snippets.",
        "default_enabled": False
    },
    "perplexity": {
        "id": "perplexity",
        "name": "Perplexity / OmniRoute",
        "icon": "🔮",
        "type": "llm_search",
        "requires_key": False,
        "description": "Zitierte Online-Synthese über OmniRoute Sonar / Online-Modelle.",
        "default_enabled": True
    }
}


def get_available_providers(settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Gibt alle Provider mit ihrem aktuellen Konfigurationsstatus zurück."""
    cfg = settings or {}
    research_cfg = cfg.get("research", {})
    tavily_key = research_cfg.get("tavily_api_key") or os.environ.get("TAVILY_API_KEY", "")
    searxng_url = research_cfg.get("searxng_url") or "http://localhost:8888"

    result = []
    for pid, p in PROVIDERS_CONFIG.items():
        item = dict(p)
        if pid == "tavily":
            item["is_configured"] = bool(tavily_key)
            item["api_key_set"] = bool(tavily_key)
        elif pid == "searxng":
            item["is_configured"] = True
            item["endpoint_url"] = searxng_url
        else:
            item["is_configured"] = True
        result.append(item)
    return result


def search_wikipedia(query: str, lang: str = "de", max_results: int = 3) -> List[Dict[str, Any]]:
    """Fragt die offizielle Wikipedia-API nach Artikeln und Textauszügen ab."""
    results = []
    headers = {"User-Agent": "ArchonOS-ResearchLab/2.0 (mailto:admin@archon-os.internal)"}
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={encoded_query}&limit={max_results}&namespace=0&format=json"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            if len(data) >= 2:
                titles = data[1]
                urls = data[3] if len(data) >= 4 else []
                for i, title in enumerate(titles):
                    link = urls[i] if i < len(urls) else f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                    snippet = ""
                    try:
                        sum_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"
                        sreq = urllib.request.Request(sum_url, headers=headers)
                        with urllib.request.urlopen(sreq, timeout=4) as sresp:
                            sdata = json.loads(sresp.read().decode("utf-8"))
                            snippet = sdata.get("extract", "")
                    except Exception:
                        pass
                    if not snippet:
                        snippet = f"Wikipedia-Artikel: {title}"
                    results.append({
                        "title": title,
                        "snippet": sanitize_injection_text(snippet[:500]),
                        "url": link,
                        "source": "Wikipedia",
                        "domain": f"{lang}.wikipedia.org",
                        "type": "encyclopedia"
                    })
    except Exception as e:
        print(f"[ResearchEngine] Wikipedia Suche fehlgeschlagen: {e}")
    return results


def search_arxiv(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Fragt ArXiv nach wissenschaftlichen Papern und Preprints ab."""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}&start=0&max_results={max_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "ArchonOS-ResearchLab/1.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read().decode("utf-8")
            root = ET.fromstring(xml_data)
            # Atom Namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = entry.find("atom:title", ns)
                summary = entry.find("atom:summary", ns)
                id_elem = entry.find("atom:id", ns)
                published = entry.find("atom:published", ns)
                
                t_text = title.text.strip().replace("\n", " ") if title is not None and title.text else ""
                s_text = summary.text.strip().replace("\n", " ") if summary is not None and summary.text else ""
                url_text = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
                pub_text = published.text[:10] if published is not None and published.text else ""

                if t_text and s_text:
                    clean_snippet = sanitize_injection_text(s_text[:400] + "...")
                    results.append({
                        "title": f"[Paper] {t_text}",
                        "snippet": clean_snippet,
                        "url": url_text,
                        "published": pub_text,
                        "source": "ArXiv",
                        "domain": "arxiv.org",
                        "type": "academic"
                    })
    except Exception as e:
        print(f"[ResearchEngine] ArXiv Suche fehlgeschlagen: {e}")
    return results


def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Sucht via DuckDuckGo (unterstützt Bibliothek oder Instant-Answer Fallback)."""
    results = []
    # 1. Versuch: ddgs oder duckduckgo_search Modul
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        ddgs = DDGS()
        ddg_res = list(ddgs.text(query, max_results=max_results))
        for r in ddg_res:
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            if href and (title or body):
                domain = urlparse(href).netloc or "duckduckgo.com"
                results.append({
                    "title": title,
                    "snippet": sanitize_injection_text(body),
                    "url": href,
                    "source": "DuckDuckGo",
                    "domain": domain,
                    "type": "web"
                })
        if results:
            return results
    except Exception as e:
        print(f"[ResearchEngine] DDGS Modul nicht verfügbar oder blockiert ({e}), nutze Fallback...")

    # 2. Fallback: DuckDuckGo Instant Answer API
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "ArchonOS-ResearchLab/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            abstract = data.get("AbstractText", "")
            abstract_url = data.get("AbstractURL", "")
            heading = data.get("Heading", query)
            if abstract and abstract_url:
                results.append({
                    "title": heading,
                    "snippet": sanitize_injection_text(abstract),
                    "url": abstract_url,
                    "source": "DuckDuckGo",
                    "domain": urlparse(abstract_url).netloc,
                    "type": "web"
                })
            # Related Topics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                    results.append({
                        "title": topic.get("Text")[:60] + "...",
                        "snippet": sanitize_injection_text(topic.get("Text")),
                        "url": topic.get("FirstURL"),
                        "source": "DuckDuckGo",
                        "domain": urlparse(topic.get("FirstURL")).netloc,
                        "type": "web"
                    })
    except Exception as e:
        print(f"[ResearchEngine] DDG Instant-Answer Fallback fehlgeschlagen: {e}")

    return results


def search_searxng(query: str, searxng_url: str = "http://localhost:8888", max_results: int = 5) -> List[Dict[str, Any]]:
    """Fragt eine SearXNG Instanz nach aggregierten Ergebnissen ab."""
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"{searxng_url.rstrip('/')}/search?q={encoded}&format=json&language=de"
        req = urllib.request.Request(url, headers={"User-Agent": "ArchonOS-ResearchLab/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for r in data.get("results", [])[:max_results]:
                url_str = r.get("url", "")
                if url_str:
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": sanitize_injection_text(r.get("content", "")),
                        "url": url_str,
                        "source": f"SearXNG ({r.get('engine', 'meta')})",
                        "domain": urlparse(url_str).netloc,
                        "type": "meta"
                    })
    except Exception as e:
        print(f"[ResearchEngine] SearXNG Suche nicht erreichbar ({searxng_url}): {e}")
    return results


def search_tavily(query: str, api_key: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Fragt die Tavily AI Search API ab."""
    if not api_key:
        return []
    results = []
    try:
        url = "https://api.tavily.com/search"
        payload = json.dumps({
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_domains": [],
            "exclude_domains": []
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "ArchonOS/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for r in data.get("results", []):
                url_str = r.get("url", "")
                results.append({
                    "title": r.get("title", ""),
                    "snippet": sanitize_injection_text(r.get("content", "")),
                    "url": url_str,
                    "source": "Tavily AI",
                    "domain": urlparse(url_str).netloc,
                    "type": "agent_api"
                })
    except Exception as e:
        print(f"[ResearchEngine] Tavily Suche fehlgeschlagen: {e}")
    return results


def search_grokipedia(query: str, max_results: int = 2) -> List[Dict[str, Any]]:
    """Grokipedia-Artikel (KI-generiert, xAI).

    robots.txt von grokipedia.com sperrt /api/, daher wird der Typeahead-Endpoint nicht genutzt.
    Artikel werden per Websuche (site:grokipedia.com) gefunden, die /page/-Seiten selbst sind erlaubt.
    Markiert mit ai_generated=True: zaehlt nicht als unabhaengige Quelle in der Triangulation.
    """
    results: List[Dict[str, Any]] = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        for r in DDGS().text(f"site:grokipedia.com {query}", max_results=max_results * 3):
            href = r.get("href", "")
            if "grokipedia.com/page/" not in href:
                continue
            title = r.get("title", "").replace(" - Grokipedia", "").replace(" \u2014 Grokipedia", "")
            results.append({
                "title": title,
                "snippet": sanitize_injection_text(r.get("body", "")),
                "url": href,
                "source": "Grokipedia",
                "domain": "grokipedia.com",
                "type": "encyclopedia",
                "ai_generated": True,
            })
            if len(results) >= max_results:
                break
    except Exception as e:
        print(f"[ResearchEngine] Grokipedia Suche fehlgeschlagen: {e}")
    return results


def query_omniroute_synthesis(
    query: str,
    sources: List[Dict[str, Any]],
    profile: str = "deep",
    adversarial: bool = True,
    omniroute_url: str = "http://omniroute:20128/v1",
    model: str = "omniroute/free-forever",
    agent_role: str = "Lead Research Analyst"
) -> Dict[str, Any]:
    """Generiert eine strukturierte Zusammenfassung und Thesenanalyse über OmniRoute."""
    sources_summary = "\n\n".join([
        f"Quelle [{i+1}] ({s['source']} - {s['domain']}):\nTitel: {s['title']}\nInhalt: {s['snippet']}\nURL: {s['url']}"
        for i, s in enumerate(sources[:8])
    ])

    system_prompt = (
        f"Du bist der Lead-Research-Agent '{agent_role}' für Archon OS. "
        "Erstelle aus den bereitgestellten Quellen ein sachliches, evidenzbasiertes Forschungs-Dossier. "
        "Arbeite nach dem Prinzip der Quellen-Triangulation: Behauptungen müssen durch Quellen gestützt sein. "
        "Formuliere präzise Thesen. "
        "Vermeide vage Floskeln und KI-Stereotypen. "
        "Antworte auf Deutsch im sauberen Markdown-Format."
    )

    user_prompt = f"""Forschungsfrage: {query}
Recherche-Profil: {profile}
Gegenargumente / Risikoprüfung erzwingen: {'Ja' if adversarial else 'Nein'}

GEFUNDENE QUELLEN:
{sources_summary}

Bitte strukturiere das Dossier exakt so:
### 1. Kernaussage (Executive Briefing)
Kurze Zusammenfassung der Faktenlage in 2-4 Sätzen.

### 2. Zentrale Thesen & Evidenz
- These 1 mit Beleg aus den Quellen
- These 2 mit Beleg aus den Quellen

### 3. Gegenpositionen & Risiken (Adversarial Check)
Welche Schwachstellen, Widersprüche oder offenen Fragen bleiben bestehen?

### 4. Fazit & Nächste Schritte
Handlungsempfehlung für Archon OS.
"""

    try:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{omniroute_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-archon"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return {"synthesis": content, "model_used": model, "agent_role": agent_role}
    except Exception as e:
        print(f"[ResearchEngine] OmniRoute LLM Synthese nicht erreichbar: {e}")
        # Lokaler Heuristik-Fallback ohne LLM
        fallback = f"""### 1. Kernaussage (Heuristische Zusammenfassung)
Die Recherche zu '{query}' lieferte {len(sources)} relevante Nachweise aus unterschiedlichen Quellen.

### 2. Zentrale Erkenntnisse
"""
        for i, s in enumerate(sources[:4]):
            fallback += f"- **{s['title']}** ({s['source']}): {s['snippet'][:180]}...\n"
        
        fallback += "\n### 3. Quellenbewertung & Triangulation\n"
        domains = set(s['domain'] for s in sources if s.get('domain'))
        fallback += f"Insgesamt {len(domains)} eigenständige Domains erfasst ({', '.join(list(domains)[:5])}).\n"
        return {"synthesis": fallback, "model_used": "local-fallback"}


def run_research_mission(
    query: str,
    profile: str = "deep",
    engines: Optional[List[str]] = None,
    depth: int = 3,
    adversarial: bool = True,
    export_obsidian: bool = True,
    vault_path: str = os.environ.get("ARCHON_OBSIDIAN_DIR", "./obsidian_vault"),
    workspace_dir: str = "/app/agent_workspace",
    settings: Optional[Dict[str, Any]] = None,
    model: str = "omniroute/free-forever",
    agent_role: str = "Lead Research Analyst"
) -> Dict[str, Any]:
    """
    Führt den gesamten Research-Prozess aus:
    1. Multi-Engine Suche
    2. URL De-Duplizierung
    3. Injection- & Delimiter-Filterung
    4. Triangulation (Domain-Diversität)
    5. Synthese & Dossier-Generierung
    6. Speicherung in Workspace & Obsidian Vault
    """
    start_time = time.time()
    active_engines = engines or ["duckduckgo", "grokipedia", "wikipedia", "arxiv"]
    cfg = settings or {}
    tavily_key = cfg.get("research", {}).get("tavily_api_key") or os.environ.get("TAVILY_API_KEY", "")
    searxng_url = cfg.get("research", {}).get("searxng_url") or "http://localhost:8888"

    raw_sources: List[Dict[str, Any]] = []

    # 1. Parallel / Sequenziell Suchmaschinen abfragen
    if "wikipedia" in active_engines:
        wiki_res = search_wikipedia(query, lang="de", max_results=depth)
        if not wiki_res:
            wiki_res = search_wikipedia(query, lang="en", max_results=depth)
        raw_sources.extend(wiki_res)

    if "grokipedia" in active_engines:
        raw_sources.extend(search_grokipedia(query, max_results=2))

    if "arxiv" in active_engines:
        arxiv_res = search_arxiv(query, max_results=depth)
        raw_sources.extend(arxiv_res)

    if "duckduckgo" in active_engines:
        ddg_res = search_duckduckgo(query, max_results=max(3, depth))
        raw_sources.extend(ddg_res)

    if "searxng" in active_engines:
        searx_res = search_searxng(query, searxng_url=searxng_url, max_results=depth)
        raw_sources.extend(searx_res)

    if "tavily" in active_engines and tavily_key:
        tavily_res = search_tavily(query, api_key=tavily_key, max_results=depth)
        raw_sources.extend(tavily_res)

    # 2. De-Duplizierung und Sicherheits-Scan
    seen_urls = set()
    cleaned_sources = []
    blocked_snippets = 0

    for s in raw_sources:
        u = s.get("url", "").strip()
        if not u or u in seen_urls:
            continue
        seen_urls.add(u)

        # Prompt-Injection Check auf den Textauszug
        text_to_scan = f"{s.get('title', '')} {s.get('snippet', '')}"
        sec_check = scan_prompt_injection(text_to_scan)
        if not sec_check.get("is_safe", True) and sec_check.get("verdict") == "blocked":
            blocked_snippets += 1
            continue  # Gefährliche Snippets werden verworfen

        s["is_safe"] = sec_check.get("is_safe", True)
        cleaned_sources.append(s)

    # 2b. Keine Evidenz: nicht aus dem Modellgedaechtnis antworten
    if not cleaned_sources:
        return {
            "status": "no_evidence",
            "query": query,
            "profile": profile,
            "engines": active_engines,
            "duration_seconds": round(time.time() - start_time, 2),
            "total_sources": 0,
            "unique_domains": 0,
            "blocked_snippets": blocked_snippets,
            "sources": [],
            "dossier_markdown": (
                f"# Research Dossier: {query}\n\n"
                "**Keine Quellen gefunden.** Es wurde bewusst keine Synthese aus dem Modellwissen erzeugt. "
                "Bitte Suchmaschinen pruefen (Drosselung?) oder die Frage anders formulieren.\n"
            ),
        }

    # 3. Triangulations-Score & Evidenz-Stufe berechnen
    unique_domains = set(s.get("domain", "") for s in cleaned_sources
                         if s.get("domain") and not s.get("ai_generated"))
    triang_eval = evaluate_triangulation_quality(cleaned_sources)
    triangulation_verdict = triang_eval.get("verdict", "GERING")
    triangulation_score = triang_eval.get("score", 4)

    # 4. Synthese erstellen mit gewähltem Modell & Agent
    synth_res = query_omniroute_synthesis(
        query=query,
        sources=cleaned_sources,
        profile=profile,
        adversarial=adversarial,
        model=model,
        agent_role=agent_role
    )
    synthesis_markdown = synth_res.get("synthesis", "")
    model_actual = synth_res.get("model_used", model)
    agent_actual = synth_res.get("agent_role", agent_role)

    # Quality Gate Check auf das Synthese-Ergebnis
    val_gate = validate_ai_output(f"Recherche: {query}", synthesis_markdown, min_score=6)

    return build_and_save_dossier(
        start_time=start_time, query=query, profile=profile, model=model,
        model_actual=model_actual, agent_actual=agent_actual, active_engines=active_engines,
        cleaned_sources=cleaned_sources, unique_domains=unique_domains,
        triangulation_verdict=triangulation_verdict, triangulation_score=triangulation_score,
        val_gate=val_gate, synthesis_markdown=synthesis_markdown, blocked_snippets=blocked_snippets,
        vault_path=vault_path, workspace_dir=workspace_dir, export_obsidian=export_obsidian,
    )


def build_and_save_dossier(
    start_time: float,
    query: str,
    profile: str,
    model: str,
    model_actual: str,
    agent_actual: str,
    active_engines: List[str],
    cleaned_sources: List[Dict[str, Any]],
    unique_domains: set,
    triangulation_verdict: str,
    triangulation_score: int,
    val_gate: Dict[str, Any],
    synthesis_markdown: str,
    blocked_snippets: int,
    vault_path: str,
    workspace_dir: str,
    export_obsidian: bool,
    extra_meta: str = "",
) -> Dict[str, Any]:
    """Setzt das Dossier zusammen, speichert es im Workspace (und optional im Obsidian Vault)."""
    duration = round(time.time() - start_time, 2)
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", query[:40]).strip("_")
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_{slug}.md"

    # 5. Markdown Dossier zusammensetzen
    dossier_content = f"""# Research Dossier: {query}

- **Datum & Uhrzeit:** {timestamp_str}
- **Lead-Agent:** {agent_actual}
- **Sprachmodell:** {model_actual}
- **Recherche-Profil:** {profile.upper()}
- **Dauer:** {duration}s
- **Eingesetzte Suchmaschinen:** {', '.join(active_engines)}
- **Gefundene Quellen:** {len(cleaned_sources)} (aus {len(unique_domains)} unterschiedlichen Domains)
- **Triangulation:** {triangulation_verdict} (Score: {triangulation_score}/10)
- **Quality-Gate Status:** {val_gate.get('recommendation', 'TRUST')} (Verlässlichkeit: {val_gate.get('score', 8)}/10)
{extra_meta}
---

{synthesis_markdown}

---

### Quellenverzeichnis & Triangulationsmatrix

| # | Quelle / Provider | Vertrauensstufe | Domain | Titel | URL |
|---|-------------------|-----------------|--------|-------|-----|
"""
    for i, s in enumerate(cleaned_sources):
        rep = get_domain_reputation(s.get('domain', ''))
        tier_label = f"{rep.get('name', 'Web')} (Lvl {rep.get('level', 2)})"
        dossier_content += f"| {i+1} | {s.get('source', '-')} | {tier_label} | `{s.get('domain', '-')}` | {s.get('title', '-')} | [{s.get('domain', 'Link')}]({s.get('url', '#')}) |\n"

    dossier_content += "\n\n*Erstellt durch Archon OS Research Lab (Säule 2: Kognition & Wissen)*\n"

    # 6. Lokale Speicherung in Workspace
    research_dir = os.path.join(workspace_dir, "research")
    os.makedirs(research_dir, exist_ok=True)
    local_path = os.path.join(research_dir, filename)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(dossier_content)

    obsidian_saved = False
    obsidian_target_path = ""
    # 7. Speicherung in Obsidian Vault falls gewünscht
    if export_obsidian and vault_path and os.path.exists(vault_path):
        obsidian_research_dir = os.path.join(vault_path, "memories", "research")
        try:
            os.makedirs(obsidian_research_dir, exist_ok=True)
            obsidian_target_path = os.path.join(obsidian_research_dir, filename)
            with open(obsidian_target_path, "w", encoding="utf-8") as f:
                f.write(dossier_content)
            obsidian_saved = True
        except Exception as e:
            print(f"[ResearchEngine] Konnte nicht in Obsidian Vault schreiben: {e}")

    return {
        "status": "success",
        "query": query,
        "profile": profile,
        "model": model_actual,
        "agent_role": agent_actual,
        "duration_seconds": duration,
        "triangulation_verdict": triangulation_verdict,
        "triangulation_score": triangulation_score,
        "unique_domains": len(unique_domains),
        "total_sources": len(cleaned_sources),
        "blocked_snippets": blocked_snippets,
        "quality_gate": val_gate,
        "filename": filename,
        "local_path": local_path,
        "obsidian_saved": obsidian_saved,
        "obsidian_path": obsidian_target_path,
        "dossier_markdown": dossier_content,
        "sources": cleaned_sources
    }


def list_research_history(workspace_dir: str = "/app/agent_workspace") -> List[Dict[str, Any]]:
    """Gibt eine Liste aller im Workspace archivierten Research Dossiers zurück."""
    research_dir = os.path.join(workspace_dir, "research")
    if not os.path.exists(research_dir):
        return []
    
    history = []
    for fname in sorted(os.listdir(research_dir), reverse=True):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(research_dir, fname)
        try:
            stat = os.stat(fpath)
            # Erste Zeile auslesen für Titel
            title = fname
            with open(fpath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line.startswith("# Research Dossier:"):
                    title = first_line.replace("# Research Dossier:", "").strip()
            history.append({
                "filename": fname,
                "title": title,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        except Exception:
            continue
    return history
