#!/usr/bin/env python3
"""Build all 11 GitHub Pages landing pages + Phase 3 SEO/GEO HTML subpages + sitemap/llms/robots.

Usage:
    python scripts/build_site_i18n.py                         # regenerate full site
    python scripts/build_site_i18n.py --check                 # validate only, write nothing (CI)
    python scripts/build_site_i18n.py --base-url https://archon-os.dev/

Source of truth:
    site/index.template.html    HTML with {{key}} placeholders
    site/i18n/<lang>.json       flat {key: value} translation catalogs
    scripts/site_svg_assets.py  animated Copperplate Clockwork, Vault Lock & Zero-Egress SVGs
    scripts/build_site_subpages.py  Phase 3 indexable HTML deep-dive pages (DE + EN)
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from site_svg_assets import (  # noqa: E402
    build_davinci_creation_overlay_svg,
    build_davinci_overlay_svg,
    build_davinci_underlayer_svg,
    build_davinci_vertical_overlay_svg,
    build_davinci_vertical_underlayer_svg,
    build_hero_clockwork_svg,
    build_zero_egress_diagram_svg,
)

SITE = ROOT / "site"
DOCS = ROOT / "docs"
TEMPLATE = SITE / "index.template.html"
I18N = SITE / "i18n"
VERSION_FILE = ROOT / "config" / "version.json"
DEFAULT_BASE_URL = "https://michaelbeatman.github.io/ARCHON-OS/"
BASE_URL = os.environ.get("ARCHON_SITE_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/"
REPO_URL = "https://github.com/michaelbeatman/ARCHON-OS"
REPO_BLOB = REPO_URL + "/blob/main/"
LINKEDIN_URL = "https://www.linkedin.com/in/michael-keller-a43b6611b/"
CONTACT_EMAIL = "archon.os.system@gmail.com"
LASTMOD = "2026-11-26"

# code -> (html lang, native label, og:locale)
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

SHOT_TABS: dict[str, tuple[str, str, str, str, str, str]] = {
    "de": ("Mission Control", "Agenten-Flotte", "AI Boardroom", "Workflows", "Token Guard", "Organigramm"),
    "en": ("Mission Control", "Agent Fleet", "AI Boardroom", "Workflows", "Token Guard", "Org Hierarchy"),
    "es": ("Mission Control", "Flota de Agentes", "AI Boardroom", "Workflows", "Token Guard", "Organigrama"),
    "fr": ("Mission Control", "Flotte d'Agents", "AI Boardroom", "Workflows", "Token Guard", "Organigramme"),
    "it": ("Mission Control", "Flotta Agenti", "AI Boardroom", "Workflows", "Token Guard", "Organigramma"),
    "ja": ("Mission Control", "エージェント艦隊", "AI Boardroom", "ワークフロー", "Token Guard", "組織階層"),
    "ko": ("Mission Control", "에이전트 플릿", "AI Boardroom", "워크플로우", "Token Guard", "조직 계층"),
    "nl": ("Mission Control", "Agentenvloot", "AI Boardroom", "Workflows", "Token Guard", "Organigram"),
    "pt": ("Mission Control", "Frota de Agentes", "AI Boardroom", "Workflows", "Token Guard", "Organograma"),
    "ru": ("Mission Control", "Флот агентов", "AI Boardroom", "Воркфлоу", "Token Guard", "Оргструктура"),
    "zh": ("Mission Control", "智能体舰队", "AI Boardroom", "工作流", "Token Guard", "组织架构"),
}

STRUCTURAL_VARS = {
    "LANG",
    "BASE",
    "CANONICAL",
    "HREFLANG",
    "LANG_OPTIONS",
    "DOC_HREF",
    "VERSION",
    "VERSION_BARE",
    "OG_LOCALE",
    "OG_IMAGE_URL",
    "JSON_LD",
    "DAVINCI_VERT_UNDERLAYER_SVG",
    "DAVINCI_VERT_OVERLAY_SVG",
    "DAVINCI_WHEEL_UNDERLAYER_SVG",
    "DAVINCI_WHEEL_OVERLAY_SVG",
    "DAVINCI_CREATION_OVERLAY_SVG",
    "HERO_CLOCKWORK_SVG",
    "NAV_SUBPAGES",
    "GEO_STRIP_HTML",
    "ARCH_SECTION_HTML",
    "COMPARE_SECTION_HTML",
    "HUB_SECTION_HTML",
    "GOV_PILLARS_HTML",
    "SHOT_TAB_1",
    "SHOT_TAB_2",
    "SHOT_TAB_3",
    "SHOT_TAB_4",
    "SHOT_TAB_5",
    "SHOT_TAB_6",
}

PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_.]+)\}\}")
BARE_AMP_RE = re.compile(
    r"&(?!(?:amp|lt|gt|quot|apos|middot|nbsp|copy|reg|hellip|ndash|mdash|"
    r"eacute|Eacute|uuml|ouml|auml|szlig|#\d+|#x[0-9a-fA-F]+);)"
)
ALLOWED_TAG_RE = re.compile(
    r"</?(?:a|strong|code|h2|h3|h4|p|tr|td|th)(?:\s[^<>]*?)?/?>"
)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
FAQ_PAIR_RE = re.compile(r"<h[34]>(.*?)</h[34]>\s*<p>(.*?)</p>", re.S)


def ssot_version() -> tuple[str, str]:
    """Single source of truth for the release badge + JSON-LD softwareVersion."""
    version = json.loads(VERSION_FILE.read_text(encoding="utf-8"))["version"]
    return version, version.lstrip("v")


def load_catalogs() -> dict[str, dict[str, str]]:
    catalogs: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        path = I18N / f"{lang}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Fehlender Katalog: {path}")
        catalogs[lang] = json.loads(path.read_text(encoding="utf-8"))
    return catalogs


def doc_href(lang: str) -> str:
    if lang == "en":
        return REPO_BLOB + "README.md"
    if lang == "de":
        return REPO_BLOB + "README.de.md"
    return REPO_BLOB + f"docs/readme/README.{lang}.md"


def canonical(lang: str, base_url: str | None = None) -> str:
    b = (base_url or BASE_URL).rstrip("/") + "/"
    return b if lang == "en" else b + lang + "/"


def lang_options(page_lang: str) -> str:
    base = "" if page_lang == "en" else "../"
    parts = []
    for code, (_, label) in LANGS.items():
        if code == "en":
            value = "./" if page_lang == "en" else "../"
        else:
            value = base + code + "/"
        selected = " selected" if code == page_lang else ""
        parts.append(f'<option value="{value}"{selected}>{label}</option>')
    return "".join(parts)


def hreflang_tags(base_url: str | None = None) -> str:
    b = (base_url or BASE_URL).rstrip("/") + "/"
    lines = [
        f'<link rel="alternate" hreflang="{code}" href="{canonical(code, b)}">'
        for code in LANGS
    ]
    lines.append(f'<link rel="alternate" hreflang="x-default" href="{b}">')
    return "\n".join(lines)


def _plain(val: str) -> str:
    return html_lib.unescape(TAG_STRIP_RE.sub("", val)).strip()


def build_json_ld(lang: str, cat: dict[str, str], version_bare: str, base_url: str | None = None) -> str:
    """Build localized @graph JSON-LD (WebSite, Organization, SoftwareApplication/SourceCode, FAQPage)."""
    b = (base_url or BASE_URL).rstrip("/") + "/"
    page_url = canonical(lang, b)
    og_img = b + "assets/img/og-card.png"
    html_lang = LANGS[lang][0]

    faq_entities = []
    for key in ("faq.what", "faq.leaks", "faq.costs", "faq.gdpr"):
        m = FAQ_PAIR_RE.search(cat[key])
        if m:
            faq_entities.append({
                "@type": "Question",
                "name": _plain(m.group(1)),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": _plain(m.group(2)),
                },
            })

    feature_list = [
        _plain(cat["features.boardroom"]),
        _plain(cat["features.zeroEgress"]),
        _plain(cat["features.budgetbank"]),
        _plain(cat["features.passkey"]),
        _plain(cat["features.ledger"]),
        _plain(cat["features.audit"]),
    ]

    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": b + "#organization",
                "name": "Archon OS",
                "url": b,
                "logo": {
                    "@type": "ImageObject",
                    "url": b + "archon_hand.png",
                },
                "founder": {
                    "@type": "Person",
                    "@id": b + "#founder",
                    "name": "Michael Keller",
                    "alternateName": "Michael Beatman",
                    "url": "https://github.com/michaelbeatman",
                    "email": "mailto:" + CONTACT_EMAIL,
                    "sameAs": [
                        "https://github.com/michaelbeatman",
                        LINKEDIN_URL,
                        REPO_URL,
                    ],
                },
                "contactPoint": {
                    "@type": "ContactPoint",
                    "email": CONTACT_EMAIL,
                    "contactType": "technical support",
                    "url": LINKEDIN_URL,
                },
                "sameAs": [
                    REPO_URL,
                    "https://github.com/michaelbeatman",
                    LINKEDIN_URL,
                ],
            },
            {
                "@type": "WebSite",
                "@id": b + "#website",
                "name": "Archon OS",
                "url": b,
                "inLanguage": html_lang,
                "publisher": {"@id": b + "#organization"},
            },
            {
                "@type": ["SoftwareApplication", "SoftwareSourceCode"],
                "@id": page_url + "#software",
                "name": "Archon OS",
                "alternateName": "ARCHON-OS",
                "inLanguage": html_lang,
                "applicationCategory": "DeveloperApplication, BusinessApplication",
                "operatingSystem": "Linux, Windows, macOS (Docker amd64 / arm64)",
                "softwareVersion": version_bare,
                "dateModified": LASTMOD,
                "license": "https://opensource.org/licenses/MIT",
                "url": page_url,
                "codeRepository": REPO_URL,
                "programmingLanguage": ["Python", "TypeScript", "JavaScript", "Shell"],
                "image": og_img,
                "description": _plain(cat["meta.description"]),
                "author": {"@id": b + "#founder"},
                "publisher": {"@id": b + "#organization"},
                "isBasedOn": {
                    "@type": "SoftwareSourceCode",
                    "name": "Hermes Agent",
                    "codeRepository": "https://github.com/NousResearch/hermes-agent",
                },
                "featureList": feature_list,
                "offers": {
                    "@type": "Offer",
                    "price": "0",
                    "priceCurrency": "EUR",
                },
            },
            {
                "@type": "FAQPage",
                "@id": page_url + "#faq",
                "inLanguage": html_lang,
                "mainEntity": faq_entities,
            },
        ],
    }
    raw = json.dumps(graph, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{raw}\n</script>'


_SECTIONS_CACHE: dict[str, dict[str, object]] | None = None


def load_sections_i18n() -> dict[str, dict[str, object]]:
    global _SECTIONS_CACHE
    if _SECTIONS_CACHE is None:
        raw = json.loads((I18N / "sections_i18n.json").read_text(encoding="utf-8"))
        _SECTIONS_CACHE = raw
    return _SECTIONS_CACHE


def _sec_for(lang: str) -> dict[str, object]:
    secs = load_sections_i18n()
    return secs.get(lang, secs["en"])


def _subpage_prefix(lang: str) -> tuple[str, str, str, str, str]:
    """Return (arch, gdpr, compare, frameworks, specialists) relative hrefs."""
    if lang == "de":
        return (
            "architektur/",
            "dsgvo-zero-egress/",
            "vergleich/",
            "boardroom-frameworks/",
            "spezialisten/",
        )
    if lang == "en":
        return (
            "architecture/",
            "gdpr-zero-egress/",
            "compare/",
            "boardroom-frameworks/",
            "specialists/",
        )
    # Non-EN/DE languages have their own native boardroom-frameworks/ subpage locally!
    return (
        "../architecture/",
        "../gdpr-zero-egress/",
        "../compare/",
        "boardroom-frameworks/",
        "../specialists/",
    )


def build_nav_subpages(lang: str) -> str:
    arch, gdpr, cmp_url, fw_url, _ = _subpage_prefix(lang)
    nav = _sec_for(lang)["nav"]
    assert isinstance(nav, dict)
    return (
        f'<a href="{arch}">{nav["arch"]}</a>'
        f'<a href="{gdpr}">{nav["gdpr"]}</a>'
        f'<a href="{cmp_url}">{nav["compare"]}</a>'
        f'<a href="{fw_url}">{nav["frameworks"]}</a>'
    )


def build_geo_strip(lang: str) -> str:
    items = _sec_for(lang)["geo"]
    assert isinstance(items, list)
    cards = "".join(f'<div class="geo-kpi"><strong>{k}</strong><span>{v}</span></div>' for k, v in items)
    return f'<div class="geo-strip">{cards}</div>'


def build_arch_section(lang: str) -> str:
    arch, gdpr, _, _, _ = _subpage_prefix(lang)
    arch_cfg = _sec_for(lang)["arch"]
    assert isinstance(arch_cfg, dict)
    svg_labels = arch_cfg["svg"]
    assert isinstance(svg_labels, dict)
    svg = build_zero_egress_diagram_svg(lang, svg_labels)
    sec_id = "architektur" if lang == "de" else "architecture"
    return (
        f'<h2 class="sec" id="{sec_id}">{arch_cfg["title"]}</h2>\n'
        '<div class="arch-box" data-reveal>\n'
        f"{svg}\n"
        '<p style="margin:0.9rem 0 0;font-size:0.86rem;color:var(--fg-muted)">'
        f'{arch_cfg["caption"]} '
        f'<a href="{arch}">{arch_cfg["linkArch"]} &rarr;</a> &middot; <a href="{gdpr}">{arch_cfg["linkGdpr"]} &rarr;</a>'
        "</p></div>"
    )


def build_compare_section(lang: str) -> str:
    arch, _, cmp_url, _, _ = _subpage_prefix(lang)
    cmp_cfg = _sec_for(lang)["compare"]
    assert isinstance(cmp_cfg, dict)
    rows = cmp_cfg["rows"]
    assert isinstance(rows, list)
    cls_map = [
        ("cmp-yes", "cmp-no", "cmp-part"),
        ("cmp-yes", "cmp-no", "cmp-no"),
        ("cmp-yes", "cmp-no", "cmp-no"),
        ("cmp-yes", "cmp-no", "cmp-no"),
        ("cmp-yes", "cmp-part", "cmp-part"),
    ]
    body_rows = []
    for idx, row in enumerate(rows):
        c1, c2, c3 = cls_map[idx]
        body_rows.append(
            f'      <tr><td><strong>{row[0]}</strong></td>'
            f'<td class="{c1}">{row[1]}</td>'
            f'<td class="{c2}">{row[2]}</td>'
            f'<td class="{c3}">{row[3]}</td></tr>'
        )
    sec_id = "vergleich" if lang == "de" else "compare"
    rows_html = "\n".join(body_rows)
    return f"""<h2 class="sec" id="{sec_id}">{cmp_cfg["title"]}</h2>
<div class="table-wrap" data-reveal>
  <table>
    <thead>
      <tr>
        <th>{cmp_cfg["hCol"]}</th>
        <th>Archon OS</th>
        <th>CrewAI / LangGraph</th>
        <th>n8n / Dify</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
      <tr><td><strong>{cmp_cfg["hwLabel"]}</strong></td><td colspan="3">{cmp_cfg["hwVal"]}</td></tr>
    </tbody>
  </table>
</div>
<p style="margin:0.75rem 0 0;font-size:0.86rem;color:var(--fg-muted)"><a href="{cmp_url}">{cmp_cfg["linkCmp"]} &rarr;</a> &middot; <a href="{arch}#hardware">{cmp_cfg["linkHw"]} &rarr;</a></p>"""


def build_hub_section(lang: str) -> str:
    arch, gdpr, cmp_url, fw_url, sp_url = _subpage_prefix(lang)
    hrefs = [arch, gdpr, cmp_url, fw_url, sp_url]
    hub_cfg = _sec_for(lang)["hub"]
    assert isinstance(hub_cfg, dict)
    cards = hub_cfg["cards"]
    assert isinstance(cards, list)
    html_cards = "".join(
        f'<a class="hub-card" href="{hrefs[i]}"><span class="hub-kicker">{c[0]}</span><strong>{c[1]}</strong><span>{c[2]}</span></a>'
        for i, c in enumerate(cards)
    )
    return f'<h2 class="sec">{hub_cfg["title"]}</h2>\n<div class="hub-grid" data-reveal>{html_cards}</div>'


def build_gov_pillars(lang: str) -> str:
    pillars = _sec_for(lang)["pillars"]
    assert isinstance(pillars, list)
    return "\n          ".join(f"<li>{p}</li>" for p in pillars)


def validate_catalog_values(catalogs: dict[str, dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for lang, cat in catalogs.items():
        for key, value in cat.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{lang}:{key}: leerer oder kein String")
                continue
            if BARE_AMP_RE.search(value):
                errors.append(f"{lang}:{key}: bloßes '&' (muss &amp; sein)")
            stripped = ALLOWED_TAG_RE.sub("", value)
            if "<" in stripped or ">" in stripped:
                errors.append(f"{lang}:{key}: unerlaubtes HTML-Tag in {value[:60]!r}")
    return errors


def validate(template: str, catalogs: dict[str, dict[str, str]]) -> list[str]:
    errors = validate_catalog_values(catalogs)
    keys = set(catalogs["en"])
    placeholders = set(PLACEHOLDER_RE.findall(template))

    for lang, cat in catalogs.items():
        missing = keys - set(cat)
        extra = set(cat) - keys
        if missing:
            errors.append(f"{lang}: fehlende Keys: {sorted(missing)}")
        if extra:
            errors.append(f"{lang}: unbekannte Keys: {sorted(extra)}")

    unknown = placeholders - keys - STRUCTURAL_VARS
    unused = keys - placeholders
    if unknown:
        errors.append(f"Template-Platzhalter ohne Katalogeintrag: {sorted(unknown)}")
    if unused:
        errors.append(f"Katalog-Keys ohne Platzhalter im Template: {sorted(unused)}")
    return errors


def render(template: str, lang: str, cat: dict[str, str], base_url: str | None = None) -> str:
    b = (base_url or BASE_URL).rstrip("/") + "/"
    html = template
    for key, value in cat.items():
        html = html.replace("{{" + key + "}}", value)
    version, version_bare = ssot_version()
    tabs = SHOT_TABS.get(lang, SHOT_TABS["en"])
    replacements = {
        "VERSION": version,
        "VERSION_BARE": version_bare,
        "LANG": LANGS[lang][0],
        "BASE": "" if lang == "en" else "../",
        "CANONICAL": canonical(lang, b),
        "HREFLANG": hreflang_tags(b),
        "LANG_OPTIONS": lang_options(lang),
        "DOC_HREF": doc_href(lang),
        "OG_LOCALE": OG_LOCALES.get(lang, "en_US"),
        "OG_IMAGE_URL": b + "assets/img/og-card.png",
        "JSON_LD": build_json_ld(lang, cat, version_bare, b),
        "DAVINCI_VERT_UNDERLAYER_SVG": build_davinci_vertical_underlayer_svg(),
        "DAVINCI_VERT_OVERLAY_SVG": build_davinci_vertical_overlay_svg(),
        "DAVINCI_WHEEL_UNDERLAYER_SVG": build_davinci_underlayer_svg(),
        "DAVINCI_WHEEL_OVERLAY_SVG": build_davinci_overlay_svg(),
        "DAVINCI_CREATION_OVERLAY_SVG": build_davinci_creation_overlay_svg(),
        "HERO_CLOCKWORK_SVG": build_hero_clockwork_svg(),
        "NAV_SUBPAGES": build_nav_subpages(lang),
        "GEO_STRIP_HTML": build_geo_strip(lang),
        "ARCH_SECTION_HTML": build_arch_section(lang),
        "COMPARE_SECTION_HTML": build_compare_section(lang),
        "HUB_SECTION_HTML": build_hub_section(lang),
        "GOV_PILLARS_HTML": build_gov_pillars(lang),
        "SHOT_TAB_1": tabs[0],
        "SHOT_TAB_2": tabs[1],
        "SHOT_TAB_3": tabs[2],
        "SHOT_TAB_4": tabs[3],
        "SHOT_TAB_5": tabs[4],
        "SHOT_TAB_6": tabs[5],
    }
    for name, value in replacements.items():
        html = html.replace("{{" + name + "}}", value)
    leftover = PLACEHOLDER_RE.findall(html)
    if leftover:
        raise ValueError(f"{lang}: unaufgelöste Platzhalter: {sorted(set(leftover))}")
    return html


def output_path(lang: str) -> Path:
    return SITE / "index.html" if lang == "en" else SITE / lang / "index.html"


def build_robots_txt(base_url: str) -> str:
    b = base_url.rstrip("/") + "/"
    return f"""User-agent: *
Allow: /

# Explicitly allow AI search & answer engine citability crawlers
User-agent: Googlebot
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: Claude-SearchBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Applebot
Allow: /

# Optional training & grounding crawlers (allowed for open-source discoverability)
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Google-Extended
Allow: /

Sitemap: {b}sitemap.xml
"""


def build_sitemap_xml(base_url: str, subpage_pairs: list[tuple[str, str]]) -> str:
    b = base_url.rstrip("/") + "/"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    # 11 multilingual landing pages
    for code in LANGS:
        loc = canonical(code, b)
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{LASTMOD}</lastmod>")
        for alt_code in LANGS:
            lines.append(f'    <xhtml:link rel="alternate" hreflang="{alt_code}" href="{canonical(alt_code, b)}"/>')
        lines.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{b}"/>')
        lines.append("  </url>")

    # Phase 3 bilingual deep-dive HTML pages (EN <-> DE hreflang pairs)
    for en_rel, de_rel in subpage_pairs:
        if en_rel == "boardroom-frameworks/":
            continue  # handled as full 11-language hreflang cluster below
        en_url = b + en_rel
        de_url = b + de_rel
        for loc in (en_url, de_url):
            lines.append("  <url>")
            lines.append(f"    <loc>{loc}</loc>")
            lines.append(f"    <lastmod>{LASTMOD}</lastmod>")
            lines.append(f'    <xhtml:link rel="alternate" hreflang="en" href="{en_url}"/>')
            lines.append(f'    <xhtml:link rel="alternate" hreflang="de" href="{de_url}"/>')
            lines.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{en_url}"/>')
            lines.append("  </url>")

    # All 11 localized Boardroom-Frameworks HTML pages (full 11-way hreflang cluster)
    fw_urls = {
        code: (b + "boardroom-frameworks/" if code == "en" else b + f"{code}/boardroom-frameworks/")
        for code in LANGS
    }
    for code, loc in fw_urls.items():
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{LASTMOD}</lastmod>")
        for alt_code, alt_url in fw_urls.items():
            lines.append(f'    <xhtml:link rel="alternate" hreflang="{alt_code}" href="{alt_url}"/>')
        lines.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{fw_urls["en"]}"/>')
        lines.append("  </url>")

    lines.append("</urlset>\n")
    return "\n".join(lines)


def build_llms_txt(base_url: str, version: str) -> str:
    b = base_url.rstrip("/") + "/"
    return f"""# Archon OS

> Archon OS is a self-hosted, MIT-licensed Agentic Operating System (multi-agent enterprise suite) built on Hermes Agent. It enforces fail-closed Zero-Egress local LLM routing, atomic pre-dispatch token budget reservations, WebAuthn Passkey human-in-the-loop approvals, crash-safe Effect-Ledger execution, and a SHA-256 hash-chained audit log on your own Docker server.

- Website (EN): {b}
- Website (DE): {b}de/
- Source Code (MIT License): {REPO_URL}
- Author: Michael Keller (Michael Beatman) — https://github.com/michaelbeatman | {LINKEDIN_URL}
- Contact: {CONTACT_EMAIL}
- Current Release: {version} (pre-1.0, Docker amd64 / arm64)
- Updated: {LASTMOD}

## Indexable HTML Guides & Directories

- [Architecture & Stack (EN)]({b}architecture/): OmniRoute, PolicyEngine, HMAC Warrants, Atomic BudgetBank, Effect-Ledger, 3x SQLite WAL, hardware specs
- [Architektur & Stack (DE)]({b}de/architektur/): Technische Systemarchitektur, 6-Container-Docker-Stack & Hardware-Anforderungen
- [GDPR / DSGVO & Zero-Egress (EN)]({b}gdpr-zero-egress/): Fail-closed internal Docker network isolation, EU AI Act risk registry, GoBD export
- [DSGVO & Zero-Egress (DE)]({b}de/dsgvo-zero-egress/): Datenresidenz ohne Cloud-Abfluss, EU AI Act Art. 50/Annex III & GoBD-Dokumentation
- [Framework Comparison (EN)]({b}compare/): Archon OS vs. LangGraph, CrewAI, AutoGen, n8n & Dify
- [Systemvergleich (DE)]({b}de/vergleich/): Objektiver Enterprise-Vergleich (Archon OS vs. LangGraph, CrewAI, AutoGen, n8n, Dify)
- [AI Boardroom — 80 Frameworks (EN)]({b}boardroom-frameworks/): Structured multi-perspective debate frameworks catalog — all 80 methodologies sorted A–Z (also localized in DE, ES, FR, IT, JA, KO, NL, PT, RU, ZH at `/<lang>/boardroom-frameworks/`)
- [AI Boardroom — 80 Frameworks (DE)]({b}de/boardroom-frameworks/): Alle 80 strukturierten Decision-Engine-Methodiken alphabetisch durchsuchbar
- [71 Agent Profiles (EN)]({b}specialists/): Alphabetical, filterable directory of all 71 agent profiles across 8 domains
- [71 Agenten-Profile (DE)]({b}de/spezialisten/): Alle 71 Agenten-Profile aus 8 Domänen inkl. Guardrails

## Core Architecture & Differentiators

- **71 Agent Profiles across 8 Domains:** Strategy & Leadership (13), Law/Tax/Finance (11), Sales/CRM/Marketing (11), Creation/Media (8), Tech/Software/QA (8), Commerce/Procurement (7), Real Estate/Construction (7), and Medicine/Chemistry/Engineering (6).
- **PolicyEngine & Signed Tool Warrants:** Default-deny tool access. Privileged tools require HMAC-SHA256 signed, time-limited warrants with parameter bounds. Delegated sub-agents never inherit privileged tools.
- **Atomic BudgetBank:** Pre-execution transactional budget reservations (`BEGIN IMMEDIATE`) prevent parallel agents from exceeding daily or per-task cost caps.
- **Passkey / WebAuthn HITL:** High-risk approvals (payments, budget overruns, destructive actions) require cryptographic verification via Windows Hello, Touch ID, Face ID, or hardware keys.
- **Fail-Closed Zero-Egress Routing:** OmniRoute sends finance, HR, contract, CRM, and GDPR workloads exclusively to local models (Ollama, LM Studio) inside an internal Docker network without an internet route.
- **Crash-Safe Execution (Effect-Ledger):** Transactional Effect-Ledger (`PENDING -> COMMITTED / FAILED / UNKNOWN`) with Outbox idempotency keys and mandatory reconciliation prevents duplicate external side effects.
- **Auditability & Compliance:** SHA-256 hash-chained audit log, 3 consolidated SQLite WAL databases (`ops.db`, `business.db`, `memory.db`), EU AI Act risk registry, and 1-click GoBD procedural documentation export.
- **AI Boardroom & Knowledge Base:** 80 structured multi-perspective decision frameworks across 9 categories, 832 Prompt Studio templates, local Obsidian Markdown vault + AnythingLLM/Chroma RAG, and embedded n8n webhook automation.

## Quick Start

- Full stack (7 default containers, expandable to 24 with optional profiles): `git clone {REPO_URL}.git && cd ARCHON-OS && docker compose up -d`
- Zero-key demo mode: `ARCHON_DEMO_MODE=true docker compose -f docker-compose.demo.yml up --build -d`

## PDF Documentation & Changelog

- System Manual (EN, 97 pp.): https://raw.githubusercontent.com/michaelbeatman/ARCHON-OS/main/docs/system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf
- Systemhandbuch (DE, 97 S.): https://raw.githubusercontent.com/michaelbeatman/ARCHON-OS/main/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf
- Complete Feature List (EN): https://raw.githubusercontent.com/michaelbeatman/ARCHON-OS/main/docs/system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf
- Changelog: {REPO_BLOB}CHANGELOG.md
"""


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    base_url = BASE_URL
    for i, arg in enumerate(argv):
        if arg == "--base-url" and i + 1 < len(argv):
            base_url = argv[i + 1].rstrip("/") + "/"

    template = TEMPLATE.read_text(encoding="utf-8")
    catalogs = load_catalogs()
    errors = validate(template, catalogs)
    if errors:
        print("Validierung fehlgeschlagen:", file=sys.stderr)
        for error in errors:
            print("  -", error, file=sys.stderr)
        return 1

    rendered = {lang: render(template, lang, catalogs[lang], base_url) for lang in LANGS}

    if check_only:
        for lang, html in rendered.items():
            path = output_path(lang)
            if not path.is_file() or path.read_text(encoding="utf-8") != html:
                errors.append(f"{lang}: {path} ist nicht aktuell (Generator ausführen)")
        if errors:
            print("Ausgaben nicht aktuell:", file=sys.stderr)
            for error in errors:
                print("  -", error, file=sys.stderr)
            return 1
        print(f"OK: {len(LANGS)} Kataloge, {len(catalogs['en'])} Keys, Ausgaben aktuell.")
        return 0

    for lang, html in rendered.items():
        path = output_path(lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        print(f"  {lang:>2} -> {path.relative_to(ROOT)} ({len(html)} Bytes)")

    # Build Phase 3 SEO/GEO subpages if module is available
    subpage_pairs: list[tuple[str, str]] = []
    try:
        import build_site_subpages

        subpage_pairs = build_site_subpages.build_all(base_url=base_url, lastmod=LASTMOD)
    except ImportError:
        pass

    version, _ = ssot_version()
    robots = build_robots_txt(base_url)
    llms = build_llms_txt(base_url, version)
    sitemap = build_sitemap_xml(base_url, subpage_pairs)

    (SITE / "robots.txt").write_text(robots, encoding="utf-8")
    (SITE / "llms.txt").write_text(llms, encoding="utf-8")
    (SITE / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    # Keep docs/ robots.txt & llms.txt synced so no stale v0.5.7.8 / 55-framework drift remains
    if DOCS.is_dir():
        (DOCS / "robots.txt").write_text(robots, encoding="utf-8")
        (DOCS / "llms.txt").write_text(llms, encoding="utf-8")
        (DOCS / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    print(
        f"Fertig: {len(LANGS)} Landingpages + {len(subpage_pairs) * 2} SEO/GEO-Unterseiten, "
        f"sitemap.xml, robots.txt und llms.txt ({version}) erzeugt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
