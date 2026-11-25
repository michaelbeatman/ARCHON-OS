# -*- coding: utf-8 -*-
"""
backend/deep_research_lab.py
============================
Meilenstein 45: Research Lab zum Deep-Research-Labor ausbauen.

Mehrstufige Quellen-Triangulation (Trust-Tiers), Citation-Check
(ArXiv / PatSnap / amtliche Quellen) und Dossier-Export inkl. Vault-Ablage.

D12/MED: Trust-Tier und Konfidenz duerfen nicht aus URL-Strings erfunden
werden. Der Host wird exakt via ``urlparse().hostname`` geprueft (kein
Substring-Score ueber Query/Path), und das Dossier wird nur mit echter
Quellenverifikation als verifiziert ausgegeben. Ohne Abruf:
``unverified=True``, ``confidence=None``, ``status="needs_human_review"``.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

_TIER1_DOMAINS = (
    "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "wipo.int", "epo.org", "uspto.gov",
    "connect.patsnap.com", "gesetze-im-internet.de", "eur-lex.europa.eu", ".gov",
)
_TIER2_DOMAINS = ("github.com", "nature.com", "science.org", "ieee.org", "de.wikipedia.org", "en.wikipedia.org")

Fetcher = Callable[[str], Dict[str, Any]]


def _host_of(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except Exception:
        return ""


def _host_matches(host: str, domain: str) -> bool:
    """Exakter Host oder Subdomain — niemals ein Substring in Query/Pfad."""
    if not host:
        return False
    domain = domain.lower().lstrip(".")
    if domain == "gov":
        return host == "gov" or host.endswith(".gov")
    if domain.startswith("."):
        return host.endswith(domain)
    return host == domain or host.endswith("." + domain)


def classify_source_tier(url: str) -> str:
    """D12/MED: nur der Host zaehlt, nicht ``?ref=arxiv.org``."""
    host = _host_of(url)
    if any(_host_matches(host, d) for d in _TIER1_DOMAINS):
        return "tier1_primary"
    if any(_host_matches(host, d) for d in _TIER2_DOMAINS):
        return "tier2_specialist"
    return "tier3_web"


def _default_fetcher(url: str, timeout: float = 2.0) -> Dict[str, Any]:
    """Echter, SSRF-gepruefter Abruf einer Quelle (fail-closed)."""
    try:
        import urllib.request
        from utils.egress_guard import check_public_url

        target = check_public_url(str(url or ""))
        req = urllib.request.Request(
            target, headers={"User-Agent": "Archon-DeepResearch/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if int(getattr(resp, "status", 200)) != 200:
                return {
                    "ok": False,
                    "error": f"HTTP {getattr(resp, 'status', '?')}",
                }
            text = resp.read(200_000).decode("utf-8", errors="replace")
        return {"ok": True, "text": text}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _content_matches(text: str, source: Dict[str, Any], summary: str) -> bool:
    """Prueft, ob die Quelle tatsaechlich zum behaupteten Inhalt passt."""
    text_l = (text or "").lower()
    for key in ("title", "snippet", "excerpt"):
        value = str(source.get(key) or "").strip().lower()
        if len(value) >= 8 and value in text_l:
            return True
    # Ohne Titel/Snippet: wenigstens ein substantiver Teil der Behauptung.
    summary_l = (summary or "").strip().lower()
    if len(summary_l) >= 20:
        probe = summary_l[:60].strip()
        return bool(probe) and probe in text_l
    return False


def triangulate_sources(
    sources: List[Dict[str, Any]],
    *,
    verify: bool = False,
    fetcher: Optional[Fetcher] = None,
    fetch_summary: str = "",
    timeout: float = 2.0,
) -> Dict[str, Any]:
    """Bewertet Quellen nach Trust-Tiers und echter Mehrfach-Absicherung.

    ``verify=True`` (Produktivpfad über ``compile_research_dossier``) ruft
    jede Quelle ab und akzeptiert sie nur bei uebereinstimmendem Inhalt.
    ``verify=False`` bewahrt die historische, rein strukturelle Helper-
    Semantik — markiert das Ergebnis aber ausdruecklich als ``unverified``
    mit ``confidence=None``, damit keine erfundenen Fakten entstehen.
    """
    enriched: List[Dict[str, Any]] = []
    domains: set[str] = set()
    verified_domains: set[str] = set()
    tier1_count = 0
    verified_tier1_count = 0

    for s in sources or []:
        if not isinstance(s, dict):
            continue
        url = str(s.get("url") or "").strip()
        host = _host_of(url)
        tier = classify_source_tier(url)
        if tier == "tier1_primary":
            tier1_count += 1
        if host:
            domains.add(host)

        verified = False
        fetch_error = None
        if verify:
            try:
                fetched = (fetcher or (lambda u: _default_fetcher(u, timeout)))(url)
                if fetched and fetched.get("ok"):
                    verified = _content_matches(
                        str(fetched.get("text") or ""), s, fetch_summary
                    )
                    if not verified:
                        fetch_error = "INHALT_STIMMT_NICHT_UEBEREIN"
                else:
                    fetch_error = str((fetched or {}).get("error") or "FETCH_FEHLGESCHLAGEN")
            except Exception as exc:
                fetch_error = f"{type(exc).__name__}: {exc}"
        item = {**s, "tier": tier, "host": host, "verified": verified}
        if fetch_error:
            item["fetch_error"] = fetch_error
        enriched.append(item)
        if verified:
            if host:
                verified_domains.add(host)
            if tier == "tier1_primary":
                verified_tier1_count += 1

    verified_count = sum(1 for s in enriched if s.get("verified"))
    unverified = len(enriched) == 0 or verified_count < len(enriched)

    if verify:
        corroborated = len(verified_domains) >= 2
        independent_domains = len(verified_domains)
        effective_tier1 = verified_tier1_count
    else:
        # Rueckwaerts kompatible Strukturinformation — aber nie verifiziert.
        corroborated = len(domains) >= 2
        independent_domains = len(domains)
        effective_tier1 = tier1_count

    confidence = (
        None if unverified
        else min(1.0, round(0.25 * independent_domains + 0.25 * effective_tier1, 2))
    )
    status = "verified" if (not unverified and corroborated) else "needs_human_review"
    return {
        "status": status,
        "unverified": unverified,
        "corroborated": corroborated,
        "independent_domains": independent_domains,
        "tier1_count": tier1_count,
        "verified_sources": verified_count,
        "confidence": confidence,
        "sources": enriched,
    }


def compile_research_dossier(
    topic: str,
    summary: str,
    sources: List[Dict[str, Any]],
    vault_dir: Optional[str] = None,
    *,
    verify: bool = True,
    fetcher: Optional[Fetcher] = None,
    timeout: float = 2.0,
) -> Dict[str, Any]:
    """Erzeugt ein Dossier — ohne verifizierte Quellen klar markiert."""
    tri = triangulate_sources(
        sources, verify=verify, fetcher=fetcher,
        fetch_summary=summary, timeout=timeout,
    )
    conf = "unverifiziert" if tri["confidence"] is None else str(tri["confidence"])
    lines = [
        f"# Deep Research Dossier: {topic}",
        "",
        f"- **Erstellt:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **Status:** {tri['status']}",
        f"- **Trianguliert:** {'Ja' if tri['corroborated'] else 'Nein'} "
        f"({tri['independent_domains']} verifizierte Domains, {tri['verified_sources']} verifizierte Quellen)",
        f"- **Konfidenz:** {conf}",
    ]
    if tri["unverified"]:
        lines.append(
            "> **UNVERIFIZIERT / NEEDS HUMAN REVIEW** — Quellen konnten nicht "
            "abgerufen oder inhaltlich bestaetigt werden. Keine hieraus "
            "abgeleitete Behauptung ohne menschliche Pruefung verwenden."
        )
    lines += ["", "## Kernaussagen", summary.strip(), "", "## Quellenverzeichnis"]
    for idx, s in enumerate(tri["sources"], start=1):
        mark = "verifiziert" if s.get("verified") else "UNVERIFIZIERT"
        lines.append(
            f"{idx}. [{s.get('title') or s.get('url')}]({s.get('url')}) "
            f"— `{s['tier']}` — {mark}"
        )
    md = "\n".join(lines) + "\n"

    saved_path = None
    if vault_dir:
        out_dir = os.path.join(vault_dir, "02_Research")
        os.makedirs(out_dir, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", topic.lower()).strip("-")[:50] or "dossier"
        saved_path = os.path.join(out_dir, f"{slug}.md")
        with open(saved_path, "w", encoding="utf-8") as f:
            f.write(md)

    return {"markdown": md, "saved_path": saved_path, "triangulation": tri}
