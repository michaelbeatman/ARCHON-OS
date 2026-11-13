"""
research_engine_v2.py - Prototyp: Reflexionsschleife + Seiten-Scraper + Kompression.

Ergaenzt research_engine.py, ohne es zu veraendern. Inspiriert vom
think-act-reflect-Muster und der Kontext-Kompression aus ii-researcher
(Apache-2.0, https://github.com/Intelligent-Internet/ii-researcher).
Der Code ist eine Eigenentwicklung, es wurde nichts kopiert.

Ablauf:
  Runde 1: Suche (research_engine.py) -> Sicherheits-Scan -> Seiten laden -> komprimieren
  Reflexion: Schnelles Modell prueft, ob die Evidenz reicht, und liefert Folgesuchen
  Runde 2..n: Folgesuchen -> gleiche Pipeline
  Ende: Synthese ueber query_omniroute_synthesis (unveraendert)

Kostenhebel:
  - Reflexion laeuft auf einem guenstigen Modell (fast_model), nicht auf dem Synthese-Modell
  - Seiten werden vor dem LLM auf relevante Absaetze gekuerzt (lexikalisch, ohne Embedding-Kosten)
  - Abbruch, sobald die Evidenz reicht
"""

import os
import re
import json
import time
import math
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import research_engine as base

OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20128/v1")
OMNIROUTE_KEY = os.environ.get("OMNIROUTE_API_KEY", "sk-archon")

USER_AGENT = "Mozilla/5.0 (ArchonOS ResearchEngine v2)"
MAX_PAGE_BYTES = 1_500_000
BLOCKED_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16.")


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Stdlib-Textextraktion. Ueberspringt Skripte, Styles, Navigation."""
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript", "form", "svg"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _is_safe_url(url: str) -> bool:
    """Schutz vor SSRF: nur http(s), keine lokalen Adressen."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    return not any(host == b or host.startswith(b) for b in BLOCKED_HOSTS)


def _http_get(url: str, timeout: int = 15, headers: Optional[Dict[str, str]] = None) -> Tuple[bytes, str]:
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        return resp.read(MAX_PAGE_BYTES), ctype


def scrape_local(url: str, timeout: int = 15) -> str:
    """Scraper 1: direkter Abruf. HTML per Stdlib, PDF per PyMuPDF falls installiert."""
    raw, ctype = _http_get(url, timeout)
    if "pdf" in ctype.lower() or url.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw, filetype="pdf")
            return "\n".join(page.get_text() for page in doc[:15])
        except Exception:
            return ""
    html = raw.decode("utf-8", errors="ignore")
    ex = _TextExtractor()
    ex.feed(html)
    text = "".join(ex.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def scrape_jina(url: str, timeout: int = 25) -> str:
    """Scraper 2: Jina Reader (r.jina.ai). Liefert Markdown, auch fuer JS-Seiten.
    Ohne Key stark ratenbegrenzt. Mit JINA_API_KEY stabiler.
    Achtung: Die URL wird an Jina uebermittelt (Datenschutz beachten)."""
    headers = {"Accept": "text/plain"}
    key = os.environ.get("JINA_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    raw, _ = _http_get("https://r.jina.ai/" + url, timeout, headers)
    return raw.decode("utf-8", errors="ignore").strip()


def scrape_page(url: str, providers: Tuple[str, ...] = ("local", "jina")) -> Tuple[str, str]:
    """Probiert Scraper der Reihe nach. Gibt (Text, Provider) zurueck."""
    if not _is_safe_url(url):
        return "", "blocked"
    fns = {"local": scrape_local, "jina": scrape_jina}
    for name in providers:
        try:
            text = fns[name](url)
            if len(text.split()) >= 80:
                return text, name
        except Exception:
            continue
    return "", "none"


# ---------------------------------------------------------------------------
# Kompression (lexikalisch, keine Embedding-Kosten)
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-zÄÖÜäöüß0-9]{3,}")


def _tokens(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text)]


def compress_text(text: str, query: str, max_words: int = 220) -> str:
    """Waehlt die zur Frage passendsten Absaetze (BM25-aehnlich) bis max_words."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 12]
    if not paras:
        return " ".join(text.split()[:max_words])
    q = set(_tokens(query))
    df: Dict[str, int] = {}
    toks = [_tokens(p) for p in paras]
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    n = len(paras)
    scored = []
    for i, t in enumerate(toks):
        if not t:
            continue
        s = sum(math.log(1 + n / df[w]) for w in t if w in q) / math.sqrt(len(t))
        scored.append((s, i))
    scored.sort(reverse=True)
    picked: List[int] = []
    words = 0
    for s, i in scored:
        if s <= 0 and picked:
            break
        picked.append(i)
        words += len(paras[i].split())
        if words >= max_words:
            break
    picked.sort()
    out = " ".join(paras[i] for i in picked)
    return " ".join(out.split()[: max_words + 40])


# ---------------------------------------------------------------------------
# LLM-Aufrufe (Reflexion)
# ---------------------------------------------------------------------------

def _chat(model: str, system: str, user: str, max_tokens: int, timeout: int = 40) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OMNIROUTE_URL.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OMNIROUTE_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]


def reflect(query: str, sources: List[Dict[str, Any]], asked: List[str], fast_model: str) -> Dict[str, Any]:
    """Fragt ein schnelles Modell: reicht die Evidenz? Welche Folgesuchen fehlen?"""
    digest = "\n".join(
        f"[{i+1}] {s.get('domain', '')}: {s.get('title', '')[:90]} | {s.get('snippet', '')[:260]}"
        for i, s in enumerate(sources[:12])
    )
    system = (
        "Du pruefst Recherche-Evidenz. Antworte AUSSCHLIESSLICH mit JSON: "
        '{"sufficient": bool, "gaps": [kurze Strings], "queries": [max 3 neue Suchanfragen]}. '
        "sufficient=true nur, wenn mindestens 2 Quellen die Frage DIREKT betreffen (nicht nur thematisch verwandt), "
        "mindestens eine davon amtlich oder fachlich belastbar ist und die Angaben aktuell sind. "
        "Off-Topic-Quellen (z.B. unverwandte Paper) zaehlen nicht. Neue Suchanfragen muessen sich von den bisherigen unterscheiden "
        "und gezielt die genannten Luecken schliessen."
    )
    user = f"Frage: {query}\nBisherige Suchen: {asked}\nQuellen:\n{digest}"
    try:
        raw = _chat(fast_model, system, user, max_tokens=300)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        return {
            "sufficient": bool(data.get("sufficient", True)),
            "gaps": [str(g) for g in data.get("gaps", [])][:5],
            "queries": [str(q) for q in data.get("queries", [])
                        if str(q).strip() and str(q).strip() not in asked][:3],
        }
    except Exception as e:
        print(f"[ResearchV2] Reflexion nicht moeglich ({e}), beende Schleife.")
        return {"sufficient": True, "gaps": [], "queries": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _search_round(query: str, engines: List[str], depth: int, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if "grokipedia" in engines:
        out += base.search_grokipedia(query, max_results=2)
    if "wikipedia" in engines:
        out += base.search_wikipedia(query, lang="de", max_results=depth) or base.search_wikipedia(query, lang="en", max_results=depth)
    if "arxiv" in engines:
        out += base.search_arxiv(query, max_results=depth)
    if "duckduckgo" in engines:
        out += base.search_duckduckgo(query, max_results=max(3, depth))
    if "searxng" in engines:
        out += base.search_searxng(query, searxng_url=cfg.get("research", {}).get("searxng_url") or "http://localhost:8888", max_results=depth)
    tk = cfg.get("research", {}).get("tavily_api_key") or os.environ.get("TAVILY_API_KEY", "")
    if "tavily" in engines and tk:
        out += base.search_tavily(query, api_key=tk, max_results=depth)
    return out


def _clean(raw: List[Dict[str, Any]], seen: set) -> Tuple[List[Dict[str, Any]], int]:
    """Dedupe + Prompt-Injection-Scan wie in research_engine.py."""
    kept, blocked = [], 0
    for s in raw:
        u = s.get("url", "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        chk = base.scan_prompt_injection(f"{s.get('title', '')} {s.get('snippet', '')}")
        if not chk.get("is_safe", True) and chk.get("verdict") == "blocked":
            blocked += 1
            continue
        s["is_safe"] = chk.get("is_safe", True)
        kept.append(s)
    return kept, blocked


def _enrich(sources: List[Dict[str, Any]], query: str, max_pages: int, providers: Tuple[str, ...]) -> int:
    """Laedt die Top-Seiten, scannt den Volltext auf Injection, ersetzt snippet durch relevanten Auszug."""
    enriched = 0
    for s in sources:
        if enriched >= max_pages:
            break
        if str(s.get("source", "")).lower() in ("wikipedia", "arxiv"):  # liefern bereits gute Extrakte
            continue
        text, prov = scrape_page(s["url"], providers)
        if not text:
            continue
        excerpt = compress_text(text, query)
        chk = base.scan_prompt_injection(excerpt)
        if not chk.get("is_safe", True) and chk.get("verdict") == "blocked":
            s["scrape_blocked"] = True
            continue
        s["snippet"] = excerpt
        s["scraped_with"] = prov
        enriched += 1
    return enriched


def run_research_mission_v2(
    query: str,
    engines: Optional[List[str]] = None,
    depth: int = 3,
    max_rounds: int = 2,
    max_pages: int = 4,
    scrapers: Tuple[str, ...] = ("local", "jina"),
    adversarial: bool = True,
    model: str = "omniroute/free-forever",
    fast_model: Optional[str] = None,
    profile: str = "deep",
    agent_role: str = "Lead Research Analyst",
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recherche mit Reflexionsschleife. Schreibt keine Dateien."""
    t0 = time.time()
    engines = engines or ["duckduckgo", "grokipedia", "wikipedia", "arxiv"]
    fast_model = fast_model or model
    cfg = settings or {}

    seen: set = set()
    all_sources: List[Dict[str, Any]] = []
    blocked_total = 0
    asked = [query]
    rounds_log: List[Dict[str, Any]] = []
    queries = [query]

    for rnd in range(1, max_rounds + 1):
        raw: List[Dict[str, Any]] = []
        # Folgerunden nur Websuche: Wikipedia/ArXiv liefern fuer Detailfragen wenig und drosseln (HTTP 429)
        round_engines = engines if rnd == 1 else [e for e in engines if e not in ("wikipedia", "arxiv")]
        for q in queries:
            raw += _search_round(q, round_engines, depth, cfg)
        fresh, blocked = _clean(raw, seen)
        blocked_total += blocked
        n_pages = _enrich(fresh, query, max_pages, scrapers)
        all_sources += fresh
        entry = {"round": rnd, "queries": list(queries), "new_sources": len(fresh), "pages_scraped": n_pages}

        if rnd == max_rounds:
            rounds_log.append(entry)
            break
        ref = reflect(query, all_sources, asked, fast_model)
        entry["reflection"] = ref
        rounds_log.append(entry)
        if ref["sufficient"] or not ref["queries"]:
            break
        queries = ref["queries"]
        asked += queries

    if not all_sources:
        # Keine Evidenz: nicht aus dem Modellgedaechtnis antworten
        return {"status": "no_evidence", "query": query, "rounds": rounds_log, "total_sources": 0,
                "duration_seconds": round(time.time() - t0, 2), "synthesis": "", "sources": []}

    domains = set(s.get("domain", "") for s in all_sources
                  if s.get("domain") and not s.get("ai_generated"))
    if len(domains) >= 3:
        verdict, score = "HOCH (>=3 unabhaengige Domains)", 9
    elif len(domains) == 2:
        verdict, score = "MODERAT (2 unabhaengige Domains)", 6
    else:
        verdict, score = "GERING (Einzelquelle oder unbestaetigt)", 3

    # Quellen mit Volltext-Auszug zuerst, damit sie in den 8 Synthese-Slots landen
    ordered = sorted(all_sources, key=lambda s: 0 if s.get("scraped_with") else 1)
    synth = base.query_omniroute_synthesis(
        query=query, sources=ordered, profile=profile, adversarial=adversarial,
        omniroute_url=OMNIROUTE_URL, model=model, agent_role=agent_role,
    )
    approx_ctx_words = sum(len(s.get("snippet", "").split()) for s in ordered[:8])

    return {
        "status": "success",
        "query": query,
        "model": synth.get("model_used", model),
        "fast_model": fast_model,
        "duration_seconds": round(time.time() - t0, 2),
        "rounds": rounds_log,
        "triangulation_verdict": verdict,
        "triangulation_score": score,
        "unique_domains": len(domains),
        "total_sources": len(all_sources),
        "scraped_sources": sum(1 for s in all_sources if s.get("scraped_with")),
        "blocked_snippets": blocked_total,
        "synthesis_context_words": approx_ctx_words,
        "synthesis": synth.get("synthesis", ""),
        "sources": ordered,
    }


def run_research_mission_reflect(
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
    agent_role: str = "Lead Research Analyst",
    fast_model: Optional[str] = None,
    max_rounds: int = 3,
    max_pages: int = 4,
) -> Dict[str, Any]:
    """Reflexions-Modus mit derselben Signatur und Ausgabe wie research_engine.run_research_mission.

    Fuehrt run_research_mission_v2 aus und speichert das Dossier im gleichen Format
    (Workspace, optional Obsidian), damit API und UI unveraendert bleiben.
    """
    t0 = time.time()
    res = run_research_mission_v2(
        query=query, engines=engines, depth=depth, max_rounds=max_rounds, max_pages=max_pages,
        adversarial=adversarial, model=model, fast_model=fast_model, profile=profile,
        agent_role=agent_role, settings=settings,
    )
    if res.get("status") == "no_evidence":
        res["dossier_markdown"] = (
            f"# Research Dossier: {query}\n\n"
            "**Keine Quellen gefunden.** Es wurde bewusst keine Synthese aus dem Modellwissen erzeugt.\n"
        )
        return res

    synthesis = res.get("synthesis", "")
    val_gate = base.validate_ai_output(f"Recherche: {query}", synthesis, min_score=6)
    sources = res.get("sources", [])
    domains = set(s.get("domain", "") for s in sources if s.get("domain") and not s.get("ai_generated"))
    extra = (
        f"- **Modus:** Reflexion ({len(res.get('rounds', []))} Runden, "
        f"{res.get('scraped_sources', 0)} Seiten gescrapt, Reflexionsmodell: {res.get('fast_model')})\n"
    )
    out = base.build_and_save_dossier(
        start_time=t0, query=query, profile=profile, model=model,
        model_actual=res.get("model", model), agent_actual=agent_role,
        active_engines=engines or ["duckduckgo", "grokipedia", "wikipedia", "arxiv"],
        cleaned_sources=sources, unique_domains=domains,
        triangulation_verdict=res["triangulation_verdict"], triangulation_score=res["triangulation_score"],
        val_gate=val_gate, synthesis_markdown=synthesis, blocked_snippets=res.get("blocked_snippets", 0),
        vault_path=vault_path, workspace_dir=workspace_dir, export_obsidian=export_obsidian,
        extra_meta=extra,
    )
    out["mode"] = "reflect"
    out["rounds"] = res.get("rounds", [])
    out["scraped_sources"] = res.get("scraped_sources", 0)
    return out
