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
import logging
_archon_exc_logger = logging.getLogger("research_engine_v2")

import os
import re
import json
import time
import math
import threading
import socket
import ipaddress
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import research_engine as base
# Batch C: konservative Rechte-Metadaten fuer jede Research-Quelle.
from backend.research_sources import (
    apply_rights_defaults,
    rights_from_html,
    DEFAULT_LICENSE,
    DEFAULT_RIGHTS,
)

OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20128/v1")
# Kein hartcodierter Fallback-Key (Audit 23.11.2026); der Fehler wird am
# Nutzungspunkt geworfen, damit Importe/Tests ohne Gateway weiterhin laufen.
OMNIROUTE_KEY = os.environ.get("OMNIROUTE_API_KEY", "")

USER_AGENT = "Mozilla/5.0 (ArchonOS ResearchEngine v2)"
MAX_PAGE_BYTES = 1_500_000
BLOCKED_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16.")

# Batch C: gebundener Cache mit Rechte-Metadaten aus bereits geladenen Seiten.
# Greift nur auf HTML zu, das der lokale Scraper ohnehin heruntergeladen hat.
_RIGHTS_META_CACHE: Dict[str, Dict[str, Any]] = {}
_RIGHTS_CACHE_MAX = 256


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


def _is_global_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0])
    except ValueError:
        return False
    return bool(ip.is_global and not ip.is_multicast and not ip.is_unspecified)


def _is_safe_url(url: str) -> bool:
    """Schutz vor SSRF: nur http(s), prüft Hostnamen und aufgelöste IPs auf globale Erreichbarkeit."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return False
    host = p.hostname.lower().rstrip(".")
    if not host:
        return False
    if host in ("localhost", "host.docker.internal") or host.endswith((".local", ".internal", ".localhost")):
        return False
    if any(host == b or host.startswith(b) for b in BLOCKED_HOSTS):
        return False
    # Direktes IP-Literal (inkl. oktaler/hex/dezimaler Schreibweisen über socket.inet_aton)
    try:
        packed = socket.inet_aton(host)
        return _is_global_ip(socket.inet_ntoa(packed))
    except OSError as _exc:
        _archon_exc_logger.debug("[research_engine_v2] Ignorierte Ausnahme (Z.102): %s", _exc)
    try:
        ip_obj = ipaddress.ip_address(host)
        return _is_global_ip(str(ip_obj))
    except ValueError as _exc:
        _archon_exc_logger.debug("[research_engine_v2] Ignorierte Ausnahme (Z.107): %s", _exc)
    # DNS-Auflösung gegen interne Rebinding-Ziele prüfen (bei Offline-DNS nicht blind durchlassen für einlabelige Hostnamen)
    if "." not in host:
        return False
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not infos:
            return False
        return all(_is_global_ip(info[4][0]) for info in infos)
    except socket.gaierror:
        # Fail-Closed: Nicht aufloesbare oder manipulierbare DNS-Ziele blockieren
        return False
    except Exception:
        return False


_HTTP_CLIENT_LOCK = threading.Lock()
_HTTP_CLIENT = None


def _get_http_client():
    """Thread-sicherer persistenter httpx-Client mit Keep-Alive-Connection-Pool."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        with _HTTP_CLIENT_LOCK:
            if _HTTP_CLIENT is None:
                import httpx
                _HTTP_CLIENT = httpx.Client(
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
    return _HTTP_CLIENT


def _http_get(url: str, timeout: int = 15, headers: Optional[Dict[str, str]] = None) -> Tuple[bytes, str]:
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    client = _get_http_client()
    current_url = url
    for _ in range(6):
        with client.stream("GET", current_url, headers=h, timeout=float(timeout)) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location")
                if not loc:
                    raise ValueError("HTTP-Redirect ohne Location-Header")
                next_url = urllib.parse.urljoin(current_url, loc)
                if not _is_safe_url(next_url):
                    raise ValueError(f"SSRF-Schutz: unsicheres Redirect-Ziel blockiert ({next_url})")
                current_url = next_url
                continue
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            buf = bytearray()
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                remaining = MAX_PAGE_BYTES - len(buf)
                if remaining <= 0:
                    break
                buf.extend(chunk[:remaining])
                if len(buf) >= MAX_PAGE_BYTES:
                    break
            return bytes(buf), ctype
    raise ValueError("Zu viele HTTP-Redirects (>5)")


def scrape_local(url: str, timeout: int = 15) -> str:
    """Scraper 1: direkter Abruf. HTML per Stdlib, PDF per PyMuPDF falls installiert."""
    if not _is_safe_url(url):
        return ""
    raw, ctype = _http_get(url, timeout)
    if "pdf" in ctype.lower() or url.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw, filetype="pdf")
            return "\n".join(page.get_text() for page in doc[:15])
        except Exception:
            return ""
    html = raw.decode("utf-8", errors="ignore")
    # Batch C: Rechte-Metadaten aus dem bereits geladenen HTML ziehen.
    if len(_RIGHTS_META_CACHE) >= _RIGHTS_CACHE_MAX:
        _RIGHTS_META_CACHE.clear()
    _RIGHTS_META_CACHE[url] = rights_from_html(html)
    ex = _TextExtractor()
    ex.feed(html)
    text = "".join(ex.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def scrape_jina(url: str, timeout: int = 25) -> str:
    """Scraper 2: Jina Reader (r.jina.ai). Liefert Markdown, auch fuer JS-Seiten.
    Ohne Key stark ratenbegrenzt. Mit JINA_API_KEY stabiler.
    Achtung: Die URL wird an Jina uebermittelt (Datenschutz beachten)."""
    if (os.environ.get("ARCHON_DISABLE_JINA_SCRAPE") or "").strip().lower() in ("1", "true", "yes"):
        return ""
    if not _is_safe_url(url):
        return ""
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
    if not OMNIROUTE_KEY:
        raise RuntimeError(
            "OMNIROUTE_API_KEY fehlt in der Umgebung — kein Request mit leerem/Default-Key."
        )
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
            "sufficient": bool(data.get("sufficient", False)),
            "gaps": [str(g) for g in data.get("gaps", [])][:5],
            "queries": [str(q) for q in data.get("queries", [])
                        if str(q).strip() and str(q).strip() not in asked][:3],
        }
    except Exception as e:
        print(f"[ResearchV2] Reflexion nicht moeglich ({e}), beende Schleife.")
        # M3: frueher `sufficient=True` — eine kaputte/manipulierte LLM-Antwort
        # beendete die Recherche vorzeitig und wurde als "ausreichend" gewertet.
        return {"sufficient": False, "gaps": [], "queries": [], "error": str(e)}


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
        # Batch C: jede Quelle bekommt explizite, konservative Rechte-Schluessel.
        apply_rights_defaults(s)
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
        # Batch C: gefundene Metadaten auf die Quelle anwenden. Ohne explizite
        # Angabe bleibt es bei den konservativen Defaults aus _clean().
        rights_meta = _RIGHTS_META_CACHE.get(s["url"])
        if rights_meta:
            s["license"] = rights_meta.get("license", DEFAULT_LICENSE)
            s["rights"] = rights_meta.get("rights", DEFAULT_RIGHTS)
            s["rights_status"] = rights_meta.get("rights_status", "unknown")
            s["license_declared"] = bool(rights_meta.get("license_declared"))
        elif prov == "jina":
            # Jina liefert Markdown; nur explizit beschriftete Zeilen uebernehmen.
            m = re.search(r"(?im)^\s*(?:license|lizenz)\s*:\s*(.{2,120})$", text)
            if m:
                s["license"] = m.group(1).strip()
                s["rights_status"] = "declared"
                s["license_declared"] = True
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


def save_dossier_for_result(
    result: Dict[str, Any],
    query: str,
    *,
    profile: str = "deep",
    model: str = "omniroute/free-forever",
    agent_role: str = "Lead Research Analyst",
    engines: Optional[List[str]] = None,
    vault_path: str = os.environ.get("ARCHON_OBSIDIAN_DIR", "./obsidian_vault"),
    workspace_dir: str = "/app/agent_workspace",
    export_obsidian: bool = False,
) -> str:
    """Batch D: schreibt zu einem run_research_mission_v2()-Ergebnis ein Dossier.

    Nutzt exakt denselben Pfad wie run_research_mission_reflect(), naemlich
    base.build_and_save_dossier(). Gibt den Dossier-Dateipfad zurueck oder ''
    bei leerer Evidenz/Fehlern (Graceful Degradation, kein Netzwerk, kein Crash).
    """
    if not isinstance(result, dict) or result.get("status") == "no_evidence":
        return ""
    sources = result.get("sources") or []
    if not sources:
        return ""
    try:
        synthesis = str(result.get("synthesis") or "")
        val_gate = base.validate_ai_output(f"Recherche: {query}", synthesis, min_score=6)
        domains = set(
            s.get("domain", "") for s in sources
            if isinstance(s, dict) and s.get("domain") and not s.get("ai_generated")
        )
        out = base.build_and_save_dossier(
            start_time=time.time(), query=query, profile=profile, model=model,
            model_actual=str(result.get("model") or model), agent_actual=agent_role,
            active_engines=engines or ["duckduckgo", "grokipedia", "wikipedia", "arxiv"],
            cleaned_sources=sources, unique_domains=domains,
            triangulation_verdict=str(
                result.get("triangulation_verdict") or result.get("verdict") or ""
            ),
            triangulation_score=int(result.get("triangulation_score") or 0),
            val_gate=val_gate, synthesis_markdown=synthesis,
            blocked_snippets=int(result.get("blocked_snippets") or 0),
            vault_path=vault_path, workspace_dir=workspace_dir,
            export_obsidian=export_obsidian,
            extra_meta="- **Modus:** Dossier aus dem DAG-Research-Knoten\n",
        )
        if not isinstance(out, dict):
            return ""
        return str(out.get("local_path") or out.get("obsidian_path") or "")
    except Exception as exc:
        _archon_exc_logger.debug(
            "[research_engine_v2] Dossier konnte nicht gespeichert werden: %s", exc
        )
        return ""


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
