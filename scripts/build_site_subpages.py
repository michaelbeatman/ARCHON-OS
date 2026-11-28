#!/usr/bin/env python3
"""Generate Phase 3 indexable SEO/GEO HTML subpages from real repo data.

Pages generated (21 HTML subpages total):
  - 5 EN <-> DE deep-dive guides (10 pages):
      architecture/       <-> de/architektur/
      gdpr-zero-egress/   <-> de/dsgvo-zero-egress/
      compare/            <-> de/vergleich/
      specialists/        <-> de/spezialisten/
      second-brain/       <-> de/second-brain-gedaechtnis/
  - 11 fully localized AI Boardroom Frameworks catalogs (11 pages, 80 methods each, A-Z sorted):
      boardroom-frameworks/          (EN)
      <lang>/boardroom-frameworks/   (de, es, fr, it, ja, ko, nl, pt, ru, zh)
"""
from __future__ import annotations

import ast
import html as html_lib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from site_svg_assets import (
    build_davinci_overlay_svg,
    build_davinci_underlayer_svg,
    build_davinci_vertical_overlay_svg,
    build_davinci_vertical_underlayer_svg,
    build_zero_egress_diagram_svg,
)


def _og_alt(lang: str) -> str:
    try:
        data = json.loads((Path(__file__).resolve().parent.parent / "site" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        return data.get("meta.twitterImageAlt", "Archon OS: Enterprise Multi-Agent OS, Zero-Egress optional")
    except Exception:
        return "Archon OS: Enterprise Multi-Agent OS, Zero-Egress optional"

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
I18N = SITE / "i18n"
FW_I18N_DIR = I18N / "frameworks"
REPO_URL = "https://github.com/michaelbeatman/ARCHON-OS"
LINKEDIN_URL = "https://www.linkedin.com/in/michael-keller-a43b6611b/"
CONTACT_EMAIL = "archon.os.system@gmail.com"
VERSION_FILE = ROOT / "config" / "version.json"

LANGS: dict[str, tuple[str, str]] = {
    "en": ("en", "EN · English"),
    "de": ("de", "DE · Deutsch"),
    "es": ("es", "ES · Español"),
    "fr": ("fr", "FR · Français"),
    "it": ("it", "IT · Italiano"),
    "ja": ("ja", "JA · 日本語"),
    "ko": ("ko", "KO · 한국어"),
    "nl": ("nl", "NL · Nederlands"),
    "pt": ("pt", "PT · Português"),
    "ru": ("ru", "RU · Русский"),
    "zh": ("zh-CN", "ZH · 中文"),
}

OG_LOCALES: dict[str, str] = {
    "en": "en_US",
    "de": "de_DE",
    "es": "es_ES",
    "fr": "fr_FR",
    "it": "it_IT",
    "ja": "ja_JP",
    "ko": "ko_KR",
    "nl": "nl_NL",
    "pt": "pt_PT",
    "ru": "ru_RU",
    "zh": "zh_CN",
}

COPY_LABELS: dict[str, tuple[str, str]] = {
    "en": ("Copy", "Copied"),
    "de": ("Kopieren", "Kopiert"),
    "es": ("Copiar", "Copiado"),
    "fr": ("Copier", "Copié"),
    "it": ("Copia", "Copiato"),
    "ja": ("コピー", "コピー済み"),
    "ko": ("복사", "복사됨"),
    "nl": ("Kopiëren", "Gekopieerd"),
    "pt": ("Copiar", "Copiado"),
    "ru": ("Копировать", "Скопировано"),
    "zh": ("复制", "已复制"),
}

SUBPAGE_PAIRS: list[tuple[str, str]] = [
    ("architecture/", "de/architektur/"),
    ("gdpr-zero-egress/", "de/dsgvo-zero-egress/"),
    ("compare/", "de/vergleich/"),
    ("boardroom-frameworks/", "de/boardroom-frameworks/"),
    ("specialists/", "de/spezialisten/"),
    ("second-brain/", "de/second-brain-gedaechtnis/"),
]

_SECTIONS_CACHE: dict[str, dict[str, Any]] | None = None
_CORE_FW_CACHE: dict[str, list[tuple[str, list[tuple[str, str]]]]] | None = None


def _esc(text: Any) -> str:
    return html_lib.escape(str(text or ""), quote=True)


def _load_version() -> tuple[str, str]:
    v = json.loads(VERSION_FILE.read_text(encoding="utf-8"))["version"]
    return v, v.lstrip("v")


def _load_sections_i18n() -> dict[str, dict[str, Any]]:
    global _SECTIONS_CACHE
    if _SECTIONS_CACHE is None:
        raw: dict[str, dict[str, Any]] = json.loads(
            (I18N / "sections_i18n.json").read_text(encoding="utf-8")
        )
        _SECTIONS_CACHE = raw
    return _SECTIONS_CACHE


def _sort_key(label: str) -> str:
    """Case- and diacritic-insensitive alphabetical sort key (A-Z)."""
    norm = unicodedata.normalize("NFKD", label)
    stripped = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return stripped.casefold().strip()


def _clean_latex_math(text: str) -> str:
    """Replace inline/display LaTeX formulas from prompt texts with plain readable Unicode math."""
    def _fmt(expr: str) -> str:
        e = expr
        e = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1) / (\2)", e)
        e = re.sub(r"\\text\{([^{}]*)\}", r"\1", e)
        e = e.replace(r"\times", "×").replace(r"\cdot", "·").replace(r"\le", "≤").replace(r"\ge", "≥")
        e = e.replace("{", "").replace("}", "").replace("\\", "")
        return re.sub(r"\s+", " ", e).strip()

    s = re.sub(r"\$\$(.+?)\$\$", lambda m: _fmt(m.group(1)), text)
    s = re.sub(r"\$(.+?)\$", lambda m: _fmt(m.group(1)), s)
    return s


def _clean_fw_desc(raw: str) -> str:
    """Clean raw framework prompt text into crisp, bracket-free catalog prose."""
    s = re.sub(r"\s+", " ", raw).strip()
    # Strip leading [METHODIK-FRAMEWORK: ...] / [METHODOLOGY FRAMEWORK: ...] prompt tags
    s = re.sub(r"^\s*\[[^\]]+\]\s*", "", s)
    # Strip trailing output-format boilerplate
    s = re.sub(
        r"\s*(?:AUSGABE-FORMAT|OUTPUT[\s-]*FORMAT|STRICT\s+OUTPUT\s+FORMAT)\s*[:：].*$",
        "",
        s,
        flags=re.I,
    ).strip()
    # Convert any raw LaTeX math into readable text
    s = _clean_latex_math(s)
    # Remove any remaining square brackets so zero raw prompt brackets appear in cards
    s = re.sub(r"\[([^\]]+)\]", r"\1", s)
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 225:
        cut = s[:222].rstrip(" ,;:-·")
        if " " in cut and len(cut) > 160:
            last_sp = cut.rfind(" ")
            if last_sp > 160:
                cut = cut[:last_sp].rstrip(" ,;:-·")
        s = cut + "..."
    return s


def _load_core_dispatcher_frameworks() -> dict[str, list[tuple[str, list[tuple[str, str]]]]]:
    """Load the authoritative 80 bilingual (DE + EN) frameworks from dispatcher_frameworks.py (or core_dispatcher.py)."""
    global _CORE_FW_CACHE
    if _CORE_FW_CACHE is not None:
        return _CORE_FW_CACHE

    df = ROOT / "archon" / "core" / "dispatcher_frameworks.py"
    cd = df if df.is_file() else (ROOT / "core_dispatcher.py")
    result: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {}
    if cd.is_file():
        src = cd.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                pairs = [(node.target, node.value)]
            elif isinstance(node, ast.Assign):
                pairs = [(t, node.value) for t in node.targets if isinstance(t, ast.Name)]
            else:
                continue
            for tgt, val in pairs:
                if tgt.id in (
                    "DEFAULT_CATEGORIZED_FRAMEWORKS",
                    "DEFAULT_CATEGORIZED_FRAMEWORKS_EN",
                    "CATEGORIZED_FRAMEWORKS",
                    "CATEGORIZED_FRAMEWORKS_EN",
                ):
                    lang_key = "de" if tgt.id in ("DEFAULT_CATEGORIZED_FRAMEWORKS", "CATEGORIZED_FRAMEWORKS") else "en"
                    raw = ast.literal_eval(val)
                    cats: list[tuple[str, list[tuple[str, str]]]] = []
                    for cat_name, fw_map in raw.items():
                        items: list[tuple[str, str]] = []
                        if isinstance(fw_map, dict):
                            for fw_name, fw_desc in fw_map.items():
                                clean_name = str(fw_name).replace("[", "").replace("]", "").strip()
                                clean_desc = _clean_fw_desc(str(fw_desc))
                                items.append((clean_name, clean_desc))
                        cats.append((str(cat_name), items))
                    result[lang_key] = cats
    _CORE_FW_CACHE = result
    return result


def _load_localized_frameworks(lang: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Load all 80 localized frameworks grouped into 9 categories for any of the 11 locales."""
    if lang in ("de", "en"):
        core = _load_core_dispatcher_frameworks()
        if lang in core and core[lang]:
            return core[lang]

    fp = FW_I18N_DIR / f"{lang}.json"
    if fp.is_file():
        data = json.loads(fp.read_text(encoding="utf-8"))
        cat_names: list[str] = data["categories"]
        grouped: list[list[tuple[str, str]]] = [[] for _ in cat_names]
        for entry in data["items"]:
            cat_idx = int(entry[0])
            name = str(entry[1]).replace("[", "").replace("]", "").strip()
            desc = _clean_fw_desc(str(entry[2]))
            grouped[cat_idx].append((name, desc))
        return [(cat_names[i], grouped[i]) for i in range(len(cat_names))]

    core = _load_core_dispatcher_frameworks()
    return core.get("en", [])


def _load_specialists() -> list[dict[str, Any]]:
    ap = ROOT / "agent_profiles.json"
    if not ap.is_file():
        return []
    raw = json.loads(ap.read_text(encoding="utf-8"))
    return [p for p in raw if isinstance(p, dict)]


def _render_shell(
    *,
    lang: str,
    rel_path: str,
    alt_en_rel: str,
    alt_de_rel: str,
    title: str,
    description: str,
    eyebrow: str,
    h1: str,
    lead: str,
    body_html: str,
    schema_type: str,
    base_url: str,
    lastmod: str,
    hreflang_map: dict[str, str] | None = None,
) -> str:
    b = base_url.rstrip("/") + "/"
    depth = len([p for p in rel_path.strip("/").split("/") if p])
    asset_base = "../" * depth
    home_href = asset_base if lang == "en" else (asset_base + lang + "/")
    can_url = b + rel_path
    og_img = b + "assets/img/og-card-" + lang + ".png"
    version, version_bare = _load_version()

    html_lang = LANGS.get(lang, (lang, lang))[0]
    og_locale = OG_LOCALES.get(lang, "en_US")
    copy_lbl, copied_lbl = COPY_LABELS.get(lang, ("Copy", "Copied"))

    secs = _load_sections_i18n()
    sec = secs.get(lang, secs["en"])
    nav = sec["nav"]
    fw_meta = sec["fwPage"]

    is_de = lang == "de"
    arch_href = asset_base + ("de/architektur/" if is_de else "architecture/")
    gdpr_href = asset_base + ("de/dsgvo-zero-egress/" if is_de else "gdpr-zero-egress/")
    cmp_href = asset_base + ("de/vergleich/" if is_de else "compare/")
    fw_href = asset_base + ("boardroom-frameworks/" if lang == "en" else f"{lang}/boardroom-frameworks/")
    spec_href = asset_base + ("de/spezialisten/" if is_de else "specialists/")

    if hreflang_map:
        hreflang_lines = [
            f'<link rel="alternate" hreflang="{LANGS.get(code, (code,))[0]}" href="{b + rel}">'
            for code, rel in hreflang_map.items()
        ]
        hreflang_lines.append(
            f'<link rel="alternate" hreflang="x-default" href="{b + hreflang_map["en"]}">'
        )
        hreflang_html = "\n".join(hreflang_lines)
        opts = []
        for code, (_, label) in LANGS.items():
            target = asset_base + hreflang_map[code]
            sel = " selected" if code == lang else ""
            opts.append(f'<option value="{target}"{sel}>{label}</option>')
        switcher_html = (
            '<select class="lang-switch" aria-label="Language" '
            'onchange="if(this.value)window.location.href=this.value">'
            + "".join(opts)
            + "</select>"
        )
    else:
        en_url = b + alt_en_rel
        de_url = b + alt_de_rel
        hreflang_html = (
            f'<link rel="alternate" hreflang="en" href="{en_url}">\n'
            f'<link rel="alternate" hreflang="de" href="{de_url}">\n'
            f'<link rel="alternate" hreflang="x-default" href="{en_url}">'
        )
        other_href = (asset_base + alt_en_rel) if is_de else (asset_base + alt_de_rel)
        other_label = "EN · English" if is_de else "DE · Deutsch"
        switcher_html = f'<a href="{other_href}" class="lang-switch">{other_label}</a>'

    nav_links = (
        f'<a href="{home_href}">{_esc(nav["home"])}</a>'
        f'<a href="{arch_href}">{_esc(nav["arch"])}</a>'
        f'<a href="{gdpr_href}">{_esc(nav["gdpr"])}</a>'
        f'<a href="{cmp_href}">{_esc(nav["compare"])}</a>'
        f'<a href="{fw_href}">{_esc(nav["frameworks"])}</a>'
        f'<a href="{spec_href}">{_esc(nav["specialists"])}</a>'
        f"{switcher_html}"
        '<button type="button" class="theme-btn" data-theme-toggle>Light</button>'
    )

    home_can = b if lang == "en" else (b + lang + "/")
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": 1,
                            "name": "Archon OS",
                            "item": home_can,
                        },
                        {
                            "@type": "ListItem",
                            "position": 2,
                            "name": h1,
                            "item": can_url,
                        },
                    ],
                },
                {
                    "@type": schema_type,
                    "@id": can_url + "#article",
                    "headline": h1,
                    "name": title,
                    "description": description,
                    "inLanguage": html_lang,
                    "url": can_url,
                    "dateModified": lastmod,
                    "image": og_img,
                    "author": {
                        "@type": "Person",
                        "name": "Michael Keller",
                        "alternateName": "Michael Beatman",
                        "url": "https://github.com/michaelbeatman",
                        "sameAs": [
                            "https://github.com/michaelbeatman",
                            LINKEDIN_URL,
                        ],
                    },
                    "publisher": {
                        "@type": "Organization",
                        "name": "Archon OS",
                        "url": b,
                    },
                    "about": {
                        "@type": "SoftwareApplication",
                        "@id": can_url + "#software",
                        "name": "Archon OS",
                        "softwareVersion": version_bare,
                    },
                },
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    skip_lbl = "Zum Inhalt springen" if og_locale.startswith("de") else "Skip to content"
    menu_lbl = "Menü" if og_locale.startswith("de") else "Menu"
    nav_lbl = "Hauptnavigation" if og_locale.startswith("de") else "Main navigation"
    scope_note = (
        '<aside class="feat" style="border-left:3px solid var(--emerald);padding:0.9rem 1rem;margin:1rem 0"><strong>Geltungsbereich:</strong> Diese Seite beschreibt technische Mechanismen, keine Rechtsberatung und keine Konformitätsgarantie. Ob eine Verarbeitung DSGVO-konform ist, hängt von deiner Konfiguration und deinem Betrieb ab. Die Datenschutzerklärung für diese statische Website findest du unter <a href="../../datenschutz/">Datenschutz</a>; sie gilt nicht für die selbst gehostete Software.</aside>' if og_locale.startswith("de") else '<aside class="feat" style="border-left:3px solid var(--emerald);padding:0.9rem 1rem;margin:1rem 0"><strong>Scope:</strong> This page describes technical mechanisms, not legal advice or a compliance guarantee. Whether processing is GDPR-compliant depends on your configuration and operation. The privacy notice for this static site is at <a href="../datenschutz/">Privacy</a>; it does not cover the self-hosted software.</aside>'
    )

    return f"""<!doctype html>
<html lang="{html_lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<meta name="author" content="Michael Keller (Michael Beatman)">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
<link rel="canonical" href="{can_url}">
{hreflang_html}
<link rel="icon" type="image/webp" href="{asset_base}archon_hand.webp">
<link rel="preload" href="{asset_base}assets/fonts/geist-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{asset_base}assets/fonts/geist-mono-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{asset_base}assets/site.css">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Archon OS">
<meta property="og:locale" content="{og_locale}">
<meta property="og:url" content="{can_url}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:image" content="{og_img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{_og_alt(lang)}">
<meta name="twitter:image:alt" content="{_og_alt(lang)}">
<meta property="article:published_time" content="2026-11-28T00:00:00+01:00">
<meta property="article:modified_time" content="2026-11-28T00:00:00+01:00">
<meta property="article:author" content="Michael Keller (Michael Beatman)">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(title)}">
<meta name="twitter:description" content="{_esc(description)}">
<meta name="twitter:image" content="{og_img}">
<script type="application/ld+json">
{json_ld}
</script>
</head>
<body data-copy="{_esc(copy_lbl)}" data-copied="{_esc(copied_lbl)}">
<a class="skip-link" href="#main">{skip_lbl}</a>
<div id="a11y-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
<div class="hero-davinci-stage" aria-hidden="true">
  <div class="davinci-layers">
    <div class="davinci-layer-under">{build_davinci_vertical_underlayer_svg()}</div>
    <div class="davinci-layer-plate">
      <div class="davinci-layer-plate" data-plate="vertical" aria-hidden="true"></div>
    </div>
    <div class="davinci-layer-over">{build_davinci_vertical_overlay_svg()}</div>
  </div>
</div>

<header>
  <div class="wrap">
    <a class="brand-link" href="{home_href}">
      <img class="hand-avatar" src="{asset_base}archon_hand.webp" width="40" height="40" alt="Archon OS" decoding="async">
      <span>
        <span class="brand-name">Archon OS</span>
        <span class="tag">{version} &middot; {_esc(fw_meta["tagline"])}</span>
      </span>
    </a>
    <button type="button" class="nav-toggle" data-nav-toggle aria-expanded="false" aria-controls="main-nav" aria-label="{menu_lbl}">{menu_lbl}</button>
    <nav id="main-nav" aria-label="{nav_lbl}">{nav_links}</nav>
  </div>
</header>

<main id="main" tabindex="-1">
  <section class="hero">
    <div class="wrap">
      <nav class="breadcrumb" aria-label="Breadcrumb">
        <a href="{home_href}">Archon OS</a><span>/</span><span>{_esc(eyebrow)}</span>
      </nav>
      <div class="hero-inner">
        <div class="hero-eyebrow"><span class="pulse-dot" aria-hidden="true"></span><span>{_esc(eyebrow)} &middot; {version}</span></div>
        <h1>{_esc(h1)}</h1>
        <p class="hero-lead">{_esc(lead)}</p>
  {scope_note}
        <div class="btnrow">
          <a class="btn primary" href="{home_href}#install">{_esc(fw_meta["ctaQuickstart"])}</a>
          <a class="btn" href="{REPO_URL}" target="_blank" rel="noopener noreferrer">{_esc(fw_meta["ctaGithub"])}</a>
        </div>
      </div>
    </div>
  </section>

  <div class="wrap">
    {body_html}
  </div>

  <div class="subpage-wheel-stage" aria-hidden="true">
    <div class="subpage-wheel-wrap">
      <div class="davinci-layer-under">{build_davinci_underlayer_svg()}</div>
      <div class="davinci-layer-plate">
        <div class="davinci-layer-plate" data-plate="wheel" aria-hidden="true"></div>
      </div>
      <div class="davinci-layer-over">{build_davinci_overlay_svg()}</div>
    </div>
  </div>
</main>

<footer>
  <div class="wrap">
    <a href="{home_href}">Archon OS {_esc(nav["home"])}</a>
    <a href="{REPO_URL}">GitHub</a>
    <a href="{REPO_URL}/blob/main/LICENSE">MIT</a>
    <a href="{LINKEDIN_URL}" rel="noopener me">LinkedIn</a>
    <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>
    <a href="{asset_base}impressum/">{"Impressum" if og_locale.startswith("de") else "Imprint"}</a>
    <a href="{asset_base}datenschutz/">{"Datenschutz" if og_locale.startswith("de") else "Privacy"}</a>
    <a href="{asset_base}llms.txt">llms.txt</a>
  </div>
</footer>
<script src="{asset_base}assets/site.js" defer></script>
</body>
</html>
"""


def _page_architecture(lang: str) -> tuple[str, str, str, str, str, str]:
    secs = _load_sections_i18n()
    svg_labels = secs.get(lang, secs["en"])["arch"]["svg"]
    svg = build_zero_egress_diagram_svg(lang, svg_labels)
    if lang == "de":
        title = "Archon OS Architektur: PolicyEngine, BudgetBank & Docker-Stack"
        desc = "Technische Architektur von Archon OS: OmniRoute Zero-Egress (optional), HMAC-Warrants, Atomic BudgetBank, Effect-Ledger, 3x SQLite WAL & 8-Container-Docker-Stack."
        eyebrow = "Architektur & Stack"
        h1 = "Systemarchitektur für verlässliche Multi-Agenten-Flotten."
        lead = "Archon OS trennt Agenten-Logik strikt von Governance, Kostenkontrolle und Seiteneffekten. Jeder Tool- und LLM-Aufruf durchläuft deterministische Sicherheits-Gates auf 3 konsolidierten SQLite-WAL-Datenbanken."
        body = f"""
<p class="version-note">Release: <a href="https://github.com/michaelbeatman/ARCHON-OS/blob/main/config/version.json">v0.6.0.2</a> · Basis-Image-Tag: <code>agent-os-container:v0.6.0.2</code>.</p>

<h2 class="sec">Zero-Egress- &amp; Governance-Datenfluss</h2>
<div class="arch-box">{svg}</div>

<h2 class="sec">Die 6 Kernkomponenten im Detail</h2>
<div class="feats">
  <div class="feat"><h3>1. Zentrale PolicyEngine &amp; HMAC-Warrants</h3><p>Standardmäßig gilt Default-Deny. Privilegierte Werkzeuge (Zahlungen, externe MCP-Server, Dateisystem-Schreibzugriffe) erfordern zeitlich begrenzte, mit HMAC-SHA256 signierte Warrants inkl. Parameter-Schranken (<code>max_amount</code>, <code>allowed_path_prefixes</code>). Delegierte Subagenten erben niemals privilegierte Rechte.</p></div>
  <div class="feat"><h3>2. Atomic BudgetBank (BEGIN IMMEDIATE)</h3><p>Bevor ein LLM-Call startet, reserviert die BudgetBank Token- und Euro-Kontingente transaktional in SQLite. Parallele Agenten können Tages- oder Task-Limits nicht per Race-Condition überschreiten; ungenutzte Reservierungen werden nach Abschluss atomar freigegeben.</p></div>
  <div class="feat"><h3>3. OmniRoute Fail-Closed Switchboard</h3><p>Die zentrale Routing-Weiche trennt sensible Datenklassen (Finanzen, Verträge, HR, CRM, DSGVO) hardwareseitig auf lokale Modelle (Ollama, LM Studio) in einem internen Docker-Netz ohne Internet-Gateway. Bei Ausfall greift Fail-Closed statt Cloud-Fallback.</p></div>
  <div class="feat"><h3>4. Crash-sicherer Effect-Ledger &amp; Outbox</h3><p>Externe Seiteneffekte (E-Mails, Webhooks, ERP-Buchungen) werden über Zustände (<code>PENDING &rarr; COMMITTED / FAILED / UNKNOWN</code>) und Idempotency-Keys protokolliert. Nach einem Absturz erzwingt die Reconciliation eine Prüfung statt doppelter Ausführung.</p></div>
  <div class="feat"><h3>5. 3 konsolidierte SQLite-WAL-Datenbanken</h3><p>Kein schweres Postgres/Redis-Cluster nötig: <code>ops.db</code> (Tasks, Budgets, Warrants, Audit-Chain), <code>business.db</code> (CRM, Verträge, ERP-Alpha) und <code>memory.db</code> (Wissen, Learnings) laufen im Write-Ahead-Logging-Modus und lassen sich per Litestream replizieren.</p></div>
  <div class="feat"><h3>6. 8 Standard-Container (bis 24 mit Profilen)</h3><p>Der Default-Docker-Stack (amd64 / arm64) umfasst Archon OS Core, Hermes Agent, OmniRoute, AnythingLLM, ChromaDB (lokales Vektor-RAG), Litestream (WAL-Replikation), Docker Socket Proxy und <code>archon-autoheal</code> — optional erweiterbar um 16 Profil-Services (Prometheus, Alertmanager, Grafana, Loki, OTel/Tempo, Uptime Kuma, Caddy, Authelia, n8n, Metabase, DocuSeal u. a.).</p></div>
</div>

<h2 class="sec" id="hardware">Hardware- &amp; Ressourcen-Empfehlungen</h2>
<div class="table-wrap">
  <table>
    <thead><tr><th>Profil</th><th>CPU / RAM</th><th>GPU / VRAM</th><th>Typischer Einsatz</th></tr></thead>
    <tbody>
      <tr><td><strong>Zero-Key Demo</strong></td><td>2 vCPU &middot; 4 GB RAM</td><td>Keine benötigt</td><td>Read-only UI-Evaluation ohne API-Keys (<code>ARCHON_DEMO_MODE=true</code>)</td></tr>
      <tr><td><strong>Team / KMU Lokal (7B–14B)</strong></td><td>4–8 vCPU &middot; 16–32 GB RAM</td><td>8–12 GB VRAM (z. B. RTX 4060 Ti / Apple M2–M4)</td><td>DSGVO Zero-Egress mit Qwen 2.5 / Llama 3.1 lokal + optionaler Cloud für unkritische Tasks</td></tr>
      <tr><td><strong>Enterprise On-Prem (32B–70B)</strong></td><td>12+ vCPU &middot; 64 GB RAM</td><td>24–48 GB VRAM (RTX 4090 / A100 / Mac Studio)</td><td>Vollständige Offline-Autonomie inkl. AI Boardroom, RAG &amp; parallelen Subagenten</td></tr>
    </tbody>
  </table>
</div>
"""
        return title, desc, eyebrow, h1, lead, body

    title = "Archon OS Architecture: PolicyEngine, BudgetBank & Docker Stack"
    desc = "Technical architecture of Archon OS: OmniRoute Zero-Egress, HMAC warrants, Atomic BudgetBank, Effect-Ledger, 3x SQLite WAL & 8-container Docker stack."
    eyebrow = "Architecture & Stack"
    h1 = "System architecture built for accountable multi-agent fleets."
    lead = "Archon OS decouples agent reasoning from governance, cost control, and external side effects. Every model and tool invocation clears deterministic safety gates backed by 3 consolidated SQLite WAL databases."
    body = f"""
<p class="version-note">Release: <a href="https://github.com/michaelbeatman/ARCHON-OS/blob/main/config/version.json">v0.6.0.2</a> · deployed base image tag: <code>agent-os-container:v0.6.0.2</code>.</p>

<h2 class="sec">Zero-Egress &amp; Governance Data Flow</h2>
<div class="arch-box">{svg}</div>

<h2 class="sec">Six Core Architectural Pillars</h2>
<div class="feats">
  <div class="feat"><h3>1. Central PolicyEngine &amp; HMAC Warrants</h3><p>Default-deny tool authorization. Privileged tools require time-bound HMAC-SHA256 signed warrants with strict parameter bounds (<code>max_amount</code>, <code>allowed_path_prefixes</code>). Delegated sub-agents never inherit elevated scopes.</p></div>
  <div class="feat"><h3>2. Atomic BudgetBank (BEGIN IMMEDIATE)</h3><p>Before any LLM dispatch runs, BudgetBank reserves token and currency budgets transactionally in SQLite. Parallel agents cannot race past daily or per-task caps; unused reservations settle back atomically.</p></div>
  <div class="feat"><h3>3. OmniRoute Fail-Closed Switchboard</h3><p>Routes sensitive domains (finance, contracts, HR, CRM, GDPR) exclusively to local models (Ollama, LM Studio) inside an internal Docker network without an internet route. Fails closed rather than falling back to cloud APIs.</p></div>
  <div class="feat"><h3>4. Crash-Safe Effect-Ledger &amp; Outbox</h3><p>External side effects track explicit state transitions (<code>PENDING &rarr; COMMITTED / FAILED / UNKNOWN</code>) with idempotency keys and mandatory reconciliation after crashes, eliminating duplicate webhooks or payouts.</p></div>
  <div class="feat"><h3>5. Three Consolidated SQLite WAL Databases</h3><p>No bloated database cluster required: <code>ops.db</code> (tasks, budgets, warrants, audit hash-chain), <code>business.db</code> (CRM, contracts, ERP alpha), and <code>memory.db</code> (learnings) run in WAL mode with optional Litestream replication.</p></div>
  <div class="feat"><h3>6. 8 Default Containers (up to 24 with Profiles)</h3><p>The default Docker Compose stack (amd64 / arm64) runs Archon OS Core, Hermes Agent, OmniRoute, AnythingLLM, ChromaDB (local vector RAG), Litestream (WAL replication), Docker Socket Proxy, and <code>archon-autoheal</code> — expandable with 16 optional profile services (Prometheus, Alertmanager, Grafana, Loki, OTel/Tempo, Uptime Kuma, Caddy, Authelia, n8n, Metabase, DocuSeal, and more).</p></div>
</div>

<h2 class="sec" id="source-map">One Request, End to End</h2>
<p>No black box: each gate has a deterministic implementation you can inspect in the repository.</p>
<div class="table-wrap">
  <table>
    <thead><tr><th>Stage</th><th>Enforcement</th><th>Source</th></tr></thead>
    <tbody>
      <tr><td>Admission &amp; tool policy</td><td>Default-deny, scoped warrants</td><td><code>backend/approval_policy_engine.py</code></td></tr>
      <tr><td>Budget reservation</td><td><code>BEGIN IMMEDIATE</code>, atomic settle/release</td><td><code>backend/role_budget_engine.py</code></td></tr>
      <tr><td>External side effects</td><td>Effect-Ledger with idempotency keys</td><td><code>core_dispatcher.py</code></td></tr>
      <tr><td>Audit integrity</td><td>HMAC-SHA256 chained records</td><td><code>local_security_guard.py</code></td></tr>
      <tr><td>Liveness &amp; restart</td><td><code>/livez</code> heartbeat, autoheal</td><td><code>watchdog_daemon.py</code></td></tr>
    </tbody>
  </table>
</div>
<pre data-lang="bash">curl -sS http://localhost:8501/livez -w "\nHTTP %{{http_code}}\n"
# 200 = healthy · 503 = heartbeat stalled, autoheal restarts the container</pre>

<h2 class="sec" id="hardware">Hardware &amp; Sizing Baseline</h2>
<div class="table-wrap">
  <table>
    <thead><tr><th>Profile</th><th>CPU / RAM</th><th>GPU / VRAM</th><th>Target Workload</th></tr></thead>
    <tbody>
      <tr><td><strong>Zero-Key Demo</strong></td><td>2 vCPU &middot; 4 GB RAM</td><td>None required</td><td>Read-only UI evaluation with zero API keys (<code>ARCHON_DEMO_MODE=true</code>)</td></tr>
      <tr><td><strong>SMB / Team Local (7B–14B)</strong></td><td>4–8 vCPU &middot; 16–32 GB RAM</td><td>8–12 GB VRAM (RTX 4060 Ti / Apple M2–M4)</td><td>Strict Zero-Egress local inference for sensitive data + capped cloud for public research</td></tr>
      <tr><td><strong>Enterprise On-Prem (32B–70B)</strong></td><td>12+ vCPU &middot; 64 GB RAM</td><td>24–48 GB VRAM (RTX 4090 / A100 / Mac Studio)</td><td>Full air-gapped autonomy with AI Boardroom debates, local RAG &amp; parallel workers</td></tr>
    </tbody>
  </table>
</div>
"""
    return title, desc, eyebrow, h1, lead, body


def _page_gdpr(lang: str) -> tuple[str, str, str, str, str, str]:
    if lang == "de":
        title = "DSGVO, Zero-Egress & EU AI Act mit Archon OS"
        desc = "Wie Archon OS DSGVO-Datenresidenz, Fail-Closed Zero-Egress im Docker-Netz, EU-AI-Act-Risikoregister, Passkey-HITL & GoBD-Exporte umsetzt."
        eyebrow = "DSGVO & Compliance"
        h1 = "Fail-Closed Zero-Egress für DSGVO, EU AI Act und GoBD – nach Aktivierung (Default: aus)."
        lead = "Datenschutz entsteht nicht durch Prompt-Hinweise, sondern durch Netzwerkgrenzen und kryptografische Nachweise. Die folgenden Mechanismen stehen bereit und wirken nach Aktivierung – im Auslieferungszustand ist Zero-Egress deaktiviert."
        body = """
<h2 class="sec">Technische Schutzmaßnahmen (TOMs nach Art. 32 DSGVO)</h2>
<div class="table-wrap">
  <table>
    <thead><tr><th>Regulatorische Anforderung</th><th>Archon OS Mechanismus</th><th>Prüfbarer Nachweis</th></tr></thead>
    <tbody>
      <tr><td><strong>Datenresidenz &amp; Drittlandtransfer (DSGVO)</strong></td><td>OmniRoute Fail-Closed Zero-Egress im <code>internal: true</code> Docker-Netz ohne Default-Gateway</td><td>Nach Aktivierung: kein ausgehender Traffic aus Worker-Containern; lokales Ollama / LM Studio (Default: aus)</td></tr>
      <tr><td><strong>Recht auf Löschung (Art. 17 DSGVO)</strong></td><td>Integrierter Art.-17-Erasure-Workflow über <code>business.db</code>, <code>ops.db</code> und RAG-Index</td><td>Protokollierter Löschbeleg in der Audit-Chain</td></tr>
      <tr><td><strong>Menschliche Aufsicht (EU AI Act Art. 14 / Annex III)</strong></td><td>WebAuthn / Passkey HITL-Gates (Windows Hello, Touch ID, YubiKey) vor kritischen Aktionen</td><td>Kryptografisch verifizierte Signatur, vom LLM nicht fälschbar</td></tr>
      <tr><td><strong>Transparenz &amp; Risiko-Klassifikation (EU AI Act)</strong></td><td>Eingebautes EU-AI-Act-Risikoregister + Pflicht-Warndialoge für regulierte Domänen (Recht, Steuer, Medizin)</td><td>Exportierbare Risiko- &amp; Rollenmatrix</td></tr>
      <tr><td><strong>Unveränderbarkeit (GoBD)</strong></td><td>SHA-256 hash-verkettetes Audit-Log mit HMAC-Anker + 1-Klick-Export der GoBD-Verfahrensdokumentation</td><td>Jede Manipulation bricht die Hash-Kette nachweisbar</td></tr>
      <tr><td><strong>Vertraulichkeit des Wortes (§ 201 StGB)</strong></td><td>Explizites Consent-Gate vor Transkription oder Audio-Verarbeitung</td><td>Zeitstempel-Einwilligung im Transaktionslog</td></tr>
    </tbody>
  </table>
</div>

<h2 class="sec">Warum Fail-Closed statt Best-Effort entscheidend ist</h2>
<div class="feat why-callout">
  <p>Viele KI-Wrapper schalten bei einem Timeout des lokalen Modells stillschweigend auf einen Cloud-Provider um („Fail-Open"). Genau dann fließen Gehaltslisten, Verträge oder Patientendaten unbemerkt ab. <strong>Nach Aktivierung von Zero-Egress</strong> bricht Archon OS in sensiblen Kategorien bei nicht erreichbarem lokalem Modell hart ab (<strong>Fail-Closed</strong>) und protokolliert den Vorfall im Audit-Log.</p>
</div>
"""
        return title, desc, eyebrow, h1, lead, body

    title = "GDPR, Zero-Egress & EU AI Act Compliance in Archon OS"
    desc = "How Archon OS enforces GDPR data residency via fail-closed Docker Zero-Egress, WebAuthn Passkey HITL, EU AI Act risk registry & SHA-256 audit trails."
    eyebrow = "GDPR & Compliance"
    h1 = "Fail-closed Zero-Egress for GDPR, EU AI Act, and GoBD – once enabled (default: off)."
    lead = "Data sovereignty cannot rely on prompt instructions. Archon OS provides hard Docker network boundaries, cryptographic sign-offs and SHA-256 audit chains – effective once enabled; Zero-Egress ships disabled."
    body = """
<h2 class="sec">Technical &amp; Organizational Safeguards</h2>
<div class="table-wrap">
  <table>
    <thead><tr><th>Regulatory Requirement</th><th>Archon OS Enforcement</th><th>Verifiable Artifact</th></tr></thead>
    <tbody>
      <tr><td><strong>GDPR Data Residency</strong></td><td>OmniRoute fail-closed Zero-Egress inside an <code>internal: true</code> Docker network with no internet route</td><td>With Zero-Egress enabled: no outbound cloud packets for finance, HR, contracts &amp; CRM (shipped default: off)</td></tr>
      <tr><td><strong>Right to Erasure (GDPR Art. 17)</strong></td><td>Built-in erasure pipeline across <code>business.db</code>, <code>ops.db</code>, and local vector storage</td><td>Recorded erasure receipt in the audit chain</td></tr>
      <tr><td><strong>Human Oversight (EU AI Act Art. 14)</strong></td><td>WebAuthn / Passkey HITL gates (Windows Hello, Touch ID, hardware keys) for high-risk actions</td><td>Cryptographic signature unforgeable by any LLM</td></tr>
      <tr><td><strong>EU AI Act Risk Classification</strong></td><td>Integrated EU AI Act risk registry + mandatory regulated-domain guardrails (legal, tax, medical)</td><td>Exportable risk &amp; specialist scope register</td></tr>
      <tr><td><strong>Tamper-Evident Records (GoBD / Audit)</strong></td><td>SHA-256 hash-chained audit log with HMAC anchors and 1-click GoBD procedural export</td><td>Any record tampering immediately breaks hash verification</td></tr>
    </tbody>
  </table>
</div>

<h2 class="sec">Why Fail-Closed Beats Best-Effort Routing</h2>
<div class="feat why-callout">
  <p>Typical LLM routers silently fall back to cloud APIs when a local model stalls (fail-open), leaking contracts or payroll records during transient hiccups. <strong>With Zero-Egress enabled</strong>, Archon OS aborts sensitive requests hard when local inference is unavailable (<strong>fail-closed</strong>) and logs the blocked dispatch.</p>
</div>
"""
    return title, desc, eyebrow, h1, lead, body


def _page_compare(lang: str) -> tuple[str, str, str, str, str, str]:
    if lang == "de":
        title = "Archon OS vs. LangGraph, CrewAI, AutoGen, n8n & Dify – Vergleich"
        desc = "Objektiver Systemvergleich: Archon OS vs. LangGraph, CrewAI, AutoGen, n8n und Dify bei Zero-Egress, Budgetkontrolle, Passkey-HITL & Audit-Logs."
        eyebrow = "Systemvergleich"
        h1 = "Archon OS im Vergleich: LangGraph, CrewAI, AutoGen, n8n & Dify."
        lead = "Orchestrierungs-Bibliotheken sind stark für eigene Agenten-Prototypen. Archon OS liefert das komplette selbstgehostete Betriebssystem mit Governance, Budgets, Zero-Egress und Audit-Chain out of the box."
        body = """
<h2 class="sec">Enterprise-Governance-Matrix</h2>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Kriterium</th>
        <th>Archon OS</th>
        <th>LangGraph</th>
        <th>CrewAI</th>
        <th>AutoGen</th>
        <th>n8n / Dify</th>
      </tr>
    </thead>
    <tbody>
      <tr><td><strong>Kategorie</strong></td><td>Komplettes Agentic OS</td><td>Python/JS Graph-SDK</td><td>Multi-Agent SDK</td><td>Agent-Framework</td><td>Workflow / App-Builder</td></tr>
      <tr><td><strong>Lizenz</strong></td><td class="cmp-yes">MIT</td><td class="cmp-yes">MIT (Core)</td><td class="cmp-yes">MIT (Core)</td><td class="cmp-yes">CC-BY / MIT</td><td class="cmp-part">Fair-Code / Custom</td></tr>
      <tr><td><strong>Fail-Closed Zero-Egress</strong></td><td class="cmp-yes">Nativ (Docker-Netz)</td><td class="cmp-no">Eigenbau</td><td class="cmp-no">Eigenbau</td><td class="cmp-no">Eigenbau</td><td class="cmp-part">Manuell konfigurierbar</td></tr>
      <tr><td><strong>Atomic Pre-Dispatch BudgetBank</strong></td><td class="cmp-yes">BEGIN IMMEDIATE</td><td class="cmp-no">Nicht enthalten</td><td class="cmp-no">Nicht enthalten</td><td class="cmp-no">Nicht enthalten</td><td class="cmp-no">Nur Post-hoc Tracking</td></tr>
      <tr><td><strong>Signierte Tool-Warrants (HMAC)</strong></td><td class="cmp-yes">Default-Deny</td><td class="cmp-no">Eigenbau</td><td class="cmp-no">Eigenbau</td><td class="cmp-no">Eigenbau</td><td class="cmp-no">Statische Credentials</td></tr>
      <tr><td><strong>Passkey / WebAuthn HITL</strong></td><td class="cmp-yes">Kryptografisch</td><td class="cmp-part">Interrupt-Hooks</td><td class="cmp-part">Human-Input-Flag</td><td class="cmp-part">CLI/Callback</td><td class="cmp-part">Webhook-Formular</td></tr>
      <tr><td><strong>SHA-256 Audit-Chain &amp; GoBD</strong></td><td class="cmp-yes">Integriert</td><td class="cmp-no">LangSmith (Cloud/SaaS)</td><td class="cmp-no">Enterprise-Addon</td><td class="cmp-no">Standard-Logs</td><td class="cmp-no">Execution-History</td></tr>
      <tr><td><strong>Crash-sicherer Effect-Ledger</strong></td><td class="cmp-yes">Outbox + Reconciliation</td><td class="cmp-part">State Checkpoints</td><td class="cmp-no">Kein Ledger</td><td class="cmp-no">Kein Ledger</td><td class="cmp-part">Node Retries</td></tr>
      <tr><td><strong>Fertige Rollen &amp; Boardroom</strong></td><td class="cmp-yes">71 Profile · 80 Frameworks</td><td class="cmp-no">Leerstart</td><td class="cmp-part">YAML-Templates</td><td class="cmp-no">Leerstart</td><td class="cmp-part">Community-Flows</td></tr>
    </tbody>
  </table>
</div>

<h2 class="sec">Ehrliche Entscheidungshilfe: Wann passt was?</h2>
<div class="feats">
  <div class="feat"><h3>Wähle Archon OS, wenn ...</h3><p>du eine selbstgehostete Enterprise-Suite mit strenger DSGVO-Datenresidenz, harten Pre-Execution-Budgetgrenzen, kryptografischer Passkey-Freigabe, 71 sofort einsetzbaren Agenten-Profilen und prüfbaren SHA-256-Audit-Logs suchst — ohne Monate in Governance-Klebecode zu investieren.</p></div>
  <div class="feat"><h3>Wähle LangGraph oder CrewAI, wenn ...</h3><p>du ein dediziertes KI-Engineering-Team hast, das eine tief in ein eigenes Produkt eingebettete Custom-Agent-Engine von Grund auf in Python/TypeScript programmiert.</p></div>
  <div class="feat"><h3>Wähle n8n, wenn ...</h3><p>du primär klassische SaaS-zu-SaaS-Webhook-Automationen brauchst — übrigens ist n8n in Archon OS direkt eingebettet nutzbar, kombiniert mit Archons Governance-Schicht.</p></div>
</div>
"""
        return title, desc, eyebrow, h1, lead, body

    title = "Archon OS vs. LangGraph, CrewAI, AutoGen, n8n & Dify"
    desc = "Objective enterprise comparison: Archon OS vs. LangGraph, CrewAI, AutoGen, n8n and Dify across Zero-Egress, atomic budgets, Passkey HITL & audits."
    eyebrow = "Framework Comparison"
    h1 = "Archon OS vs. LangGraph, CrewAI, AutoGen, n8n & Dify."
    lead = "Agent SDKs excel when building bespoke pipelines from scratch. Archon OS ships as a complete self-hosted operating system with fail-closed Zero-Egress, pre-dispatch budget caps, Passkey HITL, and SHA-256 audit trails included."
    body = """
<h2 class="sec">Enterprise Governance Comparison Matrix</h2>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Capability</th>
        <th>Archon OS</th>
        <th>LangGraph</th>
        <th>CrewAI</th>
        <th>AutoGen</th>
        <th>n8n / Dify</th>
      </tr>
    </thead>
    <tbody>
      <tr><td><strong>Category</strong></td><td>Complete Agentic OS</td><td>Graph Agent SDK</td><td>Multi-Agent SDK</td><td>Agent Framework</td><td>Workflow / App Builder</td></tr>
      <tr><td><strong>License</strong></td><td class="cmp-yes">MIT</td><td class="cmp-yes">MIT (Core)</td><td class="cmp-yes">MIT (Core)</td><td class="cmp-yes">CC-BY / MIT</td><td class="cmp-part">Fair-Code / Custom</td></tr>
      <tr><td><strong>Fail-Closed Zero-Egress</strong></td><td class="cmp-yes">Built-in Docker net</td><td class="cmp-no">DIY infra</td><td class="cmp-no">DIY infra</td><td class="cmp-no">DIY infra</td><td class="cmp-part">Manual setup</td></tr>
      <tr><td><strong>Atomic Pre-Dispatch BudgetBank</strong></td><td class="cmp-yes">BEGIN IMMEDIATE</td><td class="cmp-no">Not included</td><td class="cmp-no">Not included</td><td class="cmp-no">Not included</td><td class="cmp-no">Post-hoc only</td></tr>
      <tr><td><strong>Signed Tool Warrants (HMAC)</strong></td><td class="cmp-yes">Default-deny</td><td class="cmp-no">DIY</td><td class="cmp-no">DIY</td><td class="cmp-no">DIY</td><td class="cmp-no">Static creds</td></tr>
      <tr><td><strong>Passkey / WebAuthn HITL</strong></td><td class="cmp-yes">Cryptographic</td><td class="cmp-part">Interrupt hooks</td><td class="cmp-part">Human flag</td><td class="cmp-part">Callback</td><td class="cmp-part">Form button</td></tr>
      <tr><td><strong>SHA-256 Audit Chain &amp; EU AI Act</strong></td><td class="cmp-yes">Built-in export</td><td class="cmp-no">External SaaS</td><td class="cmp-no">Paid add-on</td><td class="cmp-no">Plain logs</td><td class="cmp-no">Run history</td></tr>
      <tr><td><strong>Crash-Safe Effect-Ledger</strong></td><td class="cmp-yes">Outbox + Reconcile</td><td class="cmp-part">State checkpoints</td><td class="cmp-no">None</td><td class="cmp-no">None</td><td class="cmp-part">Node retries</td></tr>
      <tr><td><strong>Pre-Built Fleet &amp; Boardroom</strong></td><td class="cmp-yes">71 Profiles · 80 Methods</td><td class="cmp-no">Blank slate</td><td class="cmp-part">Templates</td><td class="cmp-no">Blank slate</td><td class="cmp-part">Community flows</td></tr>
    </tbody>
  </table>
</div>

<h2 class="sec">Honest Fit Guide: When to Choose What</h2>
<div class="feats">
  <div class="feat"><h3>Choose Archon OS if...</h3><p>you need a self-hosted enterprise suite with strict GDPR data residency, hard pre-dispatch budget enforcement, cryptographic Passkey sign-offs, 71 ready-to-run agent profiles, and verifiable SHA-256 audit logs out of the box.</p></div>
  <div class="feat"><h3>Choose LangGraph or CrewAI if...</h3><p>you have an engineering team building a custom single-purpose agent engine tightly embedded inside your own SaaS application codebase.</p></div>
  <div class="feat"><h3>Choose n8n if...</h3><p>you primarily automate deterministic SaaS-to-SaaS webhook pipelines — and you can run n8n embedded right inside Archon OS when you want both.</p></div>
</div>
"""
    return title, desc, eyebrow, h1, lead, body


def _page_frameworks(lang: str) -> tuple[str, str, str, str, str, str]:
    cats = _load_localized_frameworks(lang)
    total_loaded = sum(len(items) for _, items in cats)
    secs = _load_sections_i18n()
    fw_meta = secs.get(lang, secs["en"])["fwPage"]

    all_label = fw_meta["allLabel"]
    pills = [
        f'<button type="button" class="filter-pill is-active" data-dir-cat="all">{_esc(all_label)} ({total_loaded})</button>'
    ]
    flat_cards: list[tuple[str, str, str, str]] = []
    for idx, (cat_name, items) in enumerate(cats):
        cid = f"cat-{idx}"
        short = cat_name.split(".", 1)[-1].strip() if re.match(r"^\d+\.", cat_name) else cat_name
        pills.append(
            f'<button type="button" class="filter-pill" data-dir-cat="{cid}">{_esc(short)} ({len(items)})</button>'
        )
        for fw_name, fw_desc in items:
            flat_cards.append((fw_name, fw_desc, cid, short))

    # Sort all 80 cards alphabetically (A-Z) so both the full view and every category filter stay A-Z sorted
    flat_cards.sort(key=lambda row: _sort_key(row[0]))

    cards = [
        f'<div class="feat" data-dir-item data-cat="{cid}">'
        f'<span class="hub-kicker" style="display:block;font-family:var(--font-mono);font-size:0.68rem;color:var(--fg-subtle);margin-bottom:0.3rem">{_esc(short)}</span>'
        f"<h3>{_esc(fw_name)}</h3>"
        f"<p>{_esc(fw_desc)}</p>"
        f"</div>"
        for fw_name, fw_desc, cid, short in flat_cards
    ]

    ph = fw_meta["placeholder"]
    cnt_lbl = fw_meta["countLabel"]
    body = f"""
<h2 class="sec" id="framework-catalog">Framework-Katalog (A–Z)</h2>
<h2 class="sec" id="specialist-directory">Specialist directory (A–Z)</h2>
<div class="filter-bar">
  <input type="search" class="filter-input" placeholder="{_esc(ph)}" data-dir-search aria-label="{_esc(ph)}">
  <span style="font-family:var(--font-mono);font-size:0.8rem;color:var(--fg-muted)">{_esc(cnt_lbl)} <strong data-dir-count>{total_loaded}</strong> &middot; A–Z</span>
</div>
<div class="filter-pills" style="margin-bottom:1.5rem">{''.join(pills)}</div>
<div class="feats">{''.join(cards)}</div>
"""
    return (
        fw_meta["title"],
        fw_meta["desc"],
        fw_meta["eyebrow"],
        fw_meta["h1"],
        fw_meta["lead"],
        body,
    )


def _page_specialists(lang: str) -> tuple[str, str, str, str, str, str]:
    profiles = _load_specialists()
    is_de = lang == "de"

    by_cat: dict[str, list[dict[str, Any]]] = {}
    for p in profiles:
        if is_de:
            c = str(p.get("category") or "Sonstige")
        else:
            c = str(p.get("category_en") or p.get("category") or "Other")
        by_cat.setdefault(c, []).append(p)

    pills = [
        f'<button type="button" class="filter-pill is-active" data-dir-cat="all">{"Alle Domänen" if is_de else "All Domains"} ({len(profiles)})</button>'
    ]
    flat_cards: list[tuple[str, str]] = []
    for idx, (cat_name, items) in enumerate(sorted(by_cat.items())):
        cid = f"dom-{idx}"
        pills.append(
            f'<button type="button" class="filter-pill" data-dir-cat="{cid}">{_esc(cat_name)} ({len(items)})</button>'
        )
        for p in items:
            pid = str(p.get("id", ""))
            name = str((p.get("name") if is_de else (p.get("name_en") or p.get("name"))) or pid)
            desc = str((p.get("description") if is_de else (p.get("description_en") or p.get("description"))) or "")
            neg = str((p.get("negative_scope") if is_de else (p.get("negative_scope_en") or p.get("negative_scope"))) or "")
            cap = p.get("daily_cost_limit_eur")
            cap_str = f" · Limit {cap:.2f} EUR/d" if isinstance(cap, (int, float)) else ""
            neg_html = (
                f'<p style="margin-top:0.45rem;font-size:0.78rem;color:var(--silver)">Guardrail: {_esc(neg[:160])}</p>'
                if neg
                else ""
            )
            card_html = (
                f'<div class="feat" data-dir-item data-cat="{cid}">'
                f'<span style="display:block;font-family:var(--font-mono);font-size:0.68rem;color:var(--fg-subtle);margin-bottom:0.25rem">@{_esc(pid)}{_esc(cap_str)}</span>'
                f"<h3>{_esc(name)}</h3>"
                f"<p>{_esc(desc)}</p>"
                f"{neg_html}"
                f"</div>"
            )
            flat_cards.append((name, card_html))

    # Sort all 71 specialist profiles alphabetically (A-Z)
    flat_cards.sort(key=lambda row: _sort_key(row[0]))
    cards = [card_html for _, card_html in flat_cards]

    if is_de:
        title = "71 Agenten-Profile in 8 Domänen — Archon OS Agenten-Flotte"
        desc = "Alphabetisch sortiertes, durchsuchbares Verzeichnis aller 71 Agenten-Profile in Archon OS über 8 Unternehmens-Domänen inkl. Kostenlimits und Negative-Scope-Guardrails."
        eyebrow = "Spezialisten-Flotte"
        h1 = "Die 71-Profile-Flotte über 8 Unternehmens-Domänen."
        lead = "Jede Rolle besitzt ein klares Mandat, eigene Token-/Tageslimits in der Atomic BudgetBank sowie explizite Negative-Scope-Verbote für regulierte Bereiche."
        ph = "Spezialist, Rolle oder Domäne suchen (z. B. DSGVO, Tax, DevOps, DCF, MDR)..."
        cnt_lbl = "Angezeigte Profile:"
    else:
        title = "71 Agent Profiles across 8 Domains — Archon OS Fleet"
        desc = "Alphabetical, filterable directory of all 71 agent profiles in Archon OS across 8 enterprise domains with daily budget caps and negative-scope guardrails."
        eyebrow = "Specialist Fleet"
        h1 = "The 71-profile agent fleet across 8 enterprise domains."
        lead = "Every role ships with a defined operational mandate, explicit daily Atomic BudgetBank caps, and negative-scope guardrails for regulated decisions."
        ph = "Search specialist, role, or domain (e.g. GDPR, Tax, DevOps, DCF, MDR)..."
        cnt_lbl = "Visible profiles:"

    body = f"""
<div class="filter-bar">
  <input type="search" class="filter-input" placeholder="{_esc(ph)}" data-dir-search aria-label="{_esc(ph)}">
  <span style="font-family:var(--font-mono);font-size:0.8rem;color:var(--fg-muted)">{cnt_lbl} <strong data-dir-count>{len(profiles)}</strong> &middot; A–Z</span>
</div>
<div class="filter-pills" style="margin-bottom:1.5rem">{''.join(pills)}</div>
<div class="feats">{''.join(cards)}</div>
"""
    return title, desc, eyebrow, h1, lead, body


def _page_second_brain(lang: str) -> tuple[str, str, str, str, str, str]:
    if lang == "de":
        title = "2nd Brain, Obsidian-RAG, Personalakte & Self-Improving Agents — Archon OS"
        desc = "Wie Archon OS mit Obsidian Vault, ChromaDB/AnythingLLM Vektor-RAG, Corrective RAG, Agenten-Personalakten und Skill-Synthese auf eigenen Daten arbeitet."
        eyebrow = "2nd Brain, RAG & Self-Evolution"
        h1 = "Agenten, die auf deinen eigenen Daten arbeiten — und mit jedem Auftrag dazugelernt haben."
        lead = "Statt flüchtiger Chat-Verläufe verbindet Archon OS einen lokalen Obsidian Markdown Vault mit vektorisiertem AnythingLLM/ChromaDB-RAG, Personalakten pro Agent (Wins, Scorecards, Learnings) und kontrollierter Skill-Synthese."
        body = """
<h2 class="sec">Die 5 Säulen des Wissens- &amp; Lernsystems</h2>
<div class="feats">
  <div class="feat"><h3>1. Obsidian Vault als 2nd Brain</h3><p>Alle Projektergebnisse, Dossiers, Radar-Berichte und Entscheidungen landen als saubere Markdown-Dateien in <code>obsidian_vault/</code> (<code>00_HR_Agenten</code>, <code>01_PROJEKTE</code>, <code>02_Wissensbibliothek</code>, <code>04_Radar</code>, <code>05_Content</code>) — lesbar für Mensch und Agent, ohne Vendor-Lock-in.</p></div>
  <div class="feat"><h3>2. Lokale Wissensdatenbank (AnythingLLM + ChromaDB)</h3><p>Über <code>backend/rag_bridge.py</code> greifen Agenten direkt auf tausende lokal vektorisierte Dokumente (Verträge, PDFs, interne Handbücher, Research-Dossiers) in <code>ChromaDB</code> &amp; <code>AnythingLLM</code> zu. Dein Wissen verlässt niemals deinen Server.</p></div>
  <div class="feat"><h3>3. Corrective RAG (CRAG) &amp; Hybrid Search</h3><p><code>backend/corrective_rag.py</code> prüft abgerufene Dokumente vor der Antwort gegen einen Relevanz-Schwellenwert (Standard <code>0.45</code>), verwirft Rauschen und formuliert Suchanfragen automatisch um — kombiniert mit Wissensgraph und hybrider Suche.</p></div>
  <div class="feat"><h3>4. Personalakte, Wins &amp; Agent-Scorecards</h3><p><code>backend/agent_scorecard_engine.py</code> erfasst pro Rolle 8 operative Kennzahlen, 4-Augen-Reviews, Durchlaufzeiten, Wins und Erkenntnisse in <code>memory.db</code> und synchronisiert qualitative Beurteilungen direkt in die Markdown-Personalakte unter <code>00_HR_Agenten/Personalakten/</code>.</p></div>
  <div class="feat"><h3>5. Self-Improving Agents &amp; Skill-Synthese</h3><p><code>backend/skill_synthesizer.py</code> und Hermes Agent erkennen wiederkehrende erfolgreiche Abläufe, erzeugen daraus neue wiederverwendbare <code>SKILL.md</code>-Entwürfe unter <code>.agents/skills/drafts/</code>, dokumentieren sie in der Personalakte und legen sie zur Freigabe vor.</p></div>
  <div class="feat"><h3>6. Epistemic Hygiene &amp; Offline AEAD Vault</h3><p><code>backend/epistemic_hygiene.py</code> (M53) erkennt widersprüchliche Preise/Fristen, abgelaufene Vertragsstände und verwaiste Notizen im Vault. Sensibles Langzeitwissen liegt zudem AEAD-verschlüsselt im <code>compartment_vault.db</code> (<code>backend/offline_memory_vault.py</code>) mit ACL-Scopes.</p></div>
</div>

<h2 class="sec">Gedächtnis-Ebenen im Vergleich</h2>
<div class="table-wrap">
  <table>
    <thead><tr><th>Ebene</th><th>Speicherort &amp; Modul</th><th>Zweck</th><th>Datenschutz</th></tr></thead>
    <tbody>
      <tr><td><strong>Working Memory (Pinned)</strong></td><td><code>backend/core_memory_manager.py</code></td><td>Aktive Projektfakten &amp; Persona-Blöcke mit Scope (<code>private/shared/project/global</code>) &amp; TTL</td><td>Mandanten- &amp; ACL-isoliert</td></tr>
      <tr><td><strong>Vektor-RAG (Wissensdatenbank)</strong></td><td><code>ChromaDB</code> + <code>AnythingLLM</code> + <code>rag_bridge.py</code></td><td>Semantische Suche über tausende eigene Dokumente, Verträge &amp; PDFs</td><td>100 % lokal im Docker-Netz</td></tr>
      <tr><td><strong>Personalakte &amp; Learnings</strong></td><td><code>memory.db</code> + <code>Personalakten/</code></td><td>Wins, Fehler-Prävention, Scorecards &amp; Wissenszuwachs je Agent</td><td>Revisionssicher &amp; menschenlesbar</td></tr>
      <tr><td><strong>Self-Improving Skills</strong></td><td><code>.agents/skills/</code> + <code>skill_synthesizer.py</code></td><td>Automatisch abgeleitete <code>SKILL.md</code>-Workflows nach erfolgreichen Läufen</td><td>Freigabe-Gate vor Aktivierung</td></tr>
      <tr><td><strong>Offline AEAD Vault</strong></td><td><code>compartment_vault.db</code> + <code>lossless_session_dag.py</code></td><td>Verschlüsseltes Langzeitgedächtnis &amp; verlustfreie Session-Historie</td><td>Lokal verschlüsselt, Zero-Egress</td></tr>
    </tbody>
  </table>
</div>
"""
        return title, desc, eyebrow, h1, lead, body

    title = "2nd Brain, Obsidian Vector RAG, Agent HR Files & Self-Improving Skills — Archon OS"
    desc = "How Archon OS grounds agents on your own vectorized documents using Obsidian Vault, ChromaDB/AnythingLLM RAG, Corrective RAG, Agent Scorecards & Skill Synthesis."
    eyebrow = "2nd Brain, RAG & Self-Evolution"
    h1 = "Agents grounded on your own data — with persistent memory and self-improving skills."
    lead = "Instead of ephemeral chat logs, Archon OS combines a local Obsidian Markdown vault with vectorized ChromaDB/AnythingLLM RAG, per-agent HR files (wins, scorecards, learnings), and human-gated skill synthesis."
    body = """
<h2 class="sec">Six Pillars of the Knowledge &amp; Self-Evolution Layer</h2>
<div class="feats">
  <div class="feat"><h3>1. Obsidian Vault as 2nd Brain</h3><p>Project deliverables, research dossiers, radar digests, and boardroom decisions are stored as clean Markdown inside <code>obsidian_vault/</code> (<code>00_HR_Agenten</code>, <code>01_PROJEKTE</code>, <code>02_Wissensbibliothek</code>, <code>04_Radar</code>, <code>05_Content</code>) — readable by both humans and agents with zero lock-in.</p></div>
  <div class="feat"><h3>2. Local Knowledge Base (AnythingLLM + ChromaDB)</h3><p>Via <code>backend/rag_bridge.py</code>, agents query thousands of locally vectorized company documents (contracts, PDFs, internal manuals, dossiers) stored in <code>ChromaDB</code> &amp; <code>AnythingLLM</code> without sending your knowledge base to cloud vector APIs.</p></div>
  <div class="feat"><h3>3. Corrective RAG (CRAG) &amp; Hybrid Search</h3><p><code>backend/corrective_rag.py</code> scores retrieved chunks against <code>relevance_threshold</code> (default <code>0.45</code>) before generation, discards noise, and automatically rewrites queries across hybrid search and the local knowledge graph.</p></div>
  <div class="feat"><h3>4. Agent HR Files, Wins &amp; Scorecards</h3><p><code>backend/agent_scorecard_engine.py</code> tracks 8 operational KPIs, 4-eyes review scores, cycle times, wins, and operator notes per role in <code>memory.db</code>, syncing qualitative assessments into each agent's Markdown HR file.</p></div>
  <div class="feat"><h3>5. Self-Improving Agents &amp; Skill Synthesis</h3><p><code>backend/skill_synthesizer.py</code> and Hermes Agent detect recurring successful workflows, draft reusable <code>SKILL.md</code> packages under <code>.agents/skills/drafts/</code>, log them in the agent's HR file, and submit them for human approval.</p></div>
  <div class="feat"><h3>6. Epistemic Hygiene &amp; Offline AEAD Vault</h3><p><code>backend/epistemic_hygiene.py</code> (M53) flags conflicting prices/terms, expired contract dates, and orphaned notes across the vault, while <code>backend/offline_memory_vault.py</code> encrypts sensitive archival memory in <code>compartment_vault.db</code>.</p></div>
</div>

<h2 class="sec">Memory &amp; Knowledge Layers</h2>
<div class="table-wrap">
  <table>
    <thead><tr><th>Layer</th><th>Storage &amp; Module</th><th>Purpose</th><th>Privacy &amp; Control</th></tr></thead>
    <tbody>
      <tr><td><strong>Working Memory (Pinned)</strong></td><td><code>backend/core_memory_manager.py</code></td><td>Active project facts &amp; persona blocks with ACL scopes (<code>private/shared/project/global</code>) &amp; TTL</td><td>Tenant- &amp; ACL-isolated</td></tr>
      <tr><td><strong>Vector RAG (Knowledge Base)</strong></td><td><code>ChromaDB</code> + <code>AnythingLLM</code> + <code>rag_bridge.py</code></td><td>Semantic retrieval across thousands of private contracts, PDFs &amp; notes</td><td>100% local inside Docker network</td></tr>
      <tr><td><strong>Agent HR File &amp; Learnings</strong></td><td><code>memory.db</code> + <code>Personalakten/</code></td><td>Wins, failure prevention, scorecards &amp; domain insights per specialist</td><td>Auditable &amp; human-readable Markdown</td></tr>
      <tr><td><strong>Self-Improving Skills</strong></td><td><code>.agents/skills/</code> + <code>skill_synthesizer.py</code></td><td>Synthesized reusable <code>SKILL.md</code> workflows from proven runs</td><td>Human approval gate before activation</td></tr>
      <tr><td><strong>Offline AEAD Vault</strong></td><td><code>compartment_vault.db</code> + <code>lossless_session_dag.py</code></td><td>AEAD-encrypted archival memory &amp; lossless session summary DAG</td><td>Offline encrypted, Zero-Egress</td></tr>
    </tbody>
  </table>
</div>
"""
    return title, desc, eyebrow, h1, lead, body


def build_all(base_url: str, lastmod: str) -> list[tuple[str, str]]:
    """Build 5 DE/EN Phase 3 HTML guides + 11 localized Boardroom-Frameworks catalogs."""
    bilingual_builders = [
        ("architecture/", "de/architektur/", _page_architecture, "TechArticle"),
        ("gdpr-zero-egress/", "de/dsgvo-zero-egress/", _page_gdpr, "TechArticle"),
        ("compare/", "de/vergleich/", _page_compare, "TechArticle"),
        ("specialists/", "de/spezialisten/", _page_specialists, "CollectionPage"),
        ("second-brain/", "de/second-brain-gedaechtnis/", _page_second_brain, "TechArticle"),
    ]
    for en_rel, de_rel, fn, schema_type in bilingual_builders:
        for lang, rel in (("en", en_rel), ("de", de_rel)):
            title, desc, eyebrow, h1, lead, body_html = fn(lang)
            html_out = _render_shell(
                lang=lang,
                rel_path=rel,
                alt_en_rel=en_rel,
                alt_de_rel=de_rel,
                title=title,
                description=desc,
                eyebrow=eyebrow,
                h1=h1,
                lead=lead,
                body_html=body_html,
                schema_type=schema_type,
                base_url=base_url,
                lastmod=lastmod,
            )
            out_file = SITE / rel / "index.html"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(html_out, encoding="utf-8")
            print(f"  sub {lang:>2} -> {out_file.relative_to(ROOT)} ({len(html_out)} Bytes)")

    # Build all 11 localized AI Boardroom Frameworks catalogs (80 frameworks each, A-Z sorted)
    fw_hreflang_map = {
        code: ("boardroom-frameworks/" if code == "en" else f"{code}/boardroom-frameworks/")
        for code in LANGS
    }
    for lang, rel in fw_hreflang_map.items():
        title, desc, eyebrow, h1, lead, body_html = _page_frameworks(lang)
        html_out = _render_shell(
            lang=lang,
            rel_path=rel,
            alt_en_rel="boardroom-frameworks/",
            alt_de_rel="de/boardroom-frameworks/",
            title=title,
            description=desc,
            eyebrow=eyebrow,
            h1=h1,
            lead=lead,
            body_html=body_html,
            schema_type="CollectionPage",
            base_url=base_url,
            lastmod=lastmod,
            hreflang_map=fw_hreflang_map,
        )
        out_file = SITE / rel / "index.html"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html_out, encoding="utf-8")
        print(f"  fw  {lang:>2} -> {out_file.relative_to(ROOT)} ({len(html_out)} Bytes)")

    return SUBPAGE_PAIRS
