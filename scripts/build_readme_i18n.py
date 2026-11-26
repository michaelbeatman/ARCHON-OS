#!/usr/bin/env python3
"""Build the 9 translated READMEs from README.md + per-language catalogs.

Usage:
    python scripts/build_readme_i18n.py --dump-keys   # list EN lines (id -> source)
    python scripts/build_readme_i18n.py               # regenerate docs/readme/README.<lang>.md
    python scripts/build_readme_i18n.py --check       # validate only, write nothing (CI)

Source of truth:
    README.md                       EN master (never generated)
    README.de.md                    DE master (hand-maintained, near parity)
    config/version.json             SSOT for version / PDF version / release date
    docs/readme/i18n/<lang>.json    {k000: translated line, ...}

Outputs:
    docs/readme/README.<lang>.md    es, fr, it, ja, ko, nl, pt, ru, zh

Catalog keys are positional IDs (k000, k001, ...) derived from README.md at
build time. If the EN master changes, --check fails loudly: the catalog must be
updated. Shared across all languages: code blocks, Mermaid diagram, URLs, file
paths, product names, badge URLs, image files, project tree, PDF file names.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "README.md"
OUT_DIR = ROOT / "docs" / "readme"
I18N = OUT_DIR / "i18n"
VERSION_FILE = ROOT / "config" / "version.json"

LANGS = {
    "es": ("Español", "🇪🇸"),
    "fr": ("Français", "🇫🇷"),
    "it": ("Italiano", "🇮🇹"),
    "ja": ("日本語", "🇯🇵"),
    "ko": ("한국어", "🇰🇷"),
    "nl": ("Nederlands", "🇳🇱"),
    "pt": ("Português", "🇵🇹"),
    "ru": ("Русский", "🇷🇺"),
    "zh": ("中文", "🇨🇳"),
}
ALL_LANGS = [("en", "English", "🇬🇧"), ("de", "Deutsch", "🇩🇪")] + [
    (code, name, flag) for code, (name, flag) in LANGS.items()
]

# 3 PDF families exist in 11 languages under docs/system/ (DE uses unsuffixed names).
LOCAL_PDFS = {
    "System Manual": lambda lang: f"ARCHON_OS_SYSTEM_MANUAL_2026_{lang.upper()}.pdf",
    "Complete Feature List": lambda lang: f"ARCHON_OS_FEATURELISTE_2026_{lang.upper()}.pdf",
    "AI Boardroom: 55 Frameworks": lambda lang: f"ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_{lang.upper()}.pdf",
}

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
LINK_RE = re.compile(r"\]\(([^)]+)\)")
SRC_RE = re.compile(r'src="([^"]+)"')
NAV_PREFIX = "**🇬🇧 English**"


def ssot() -> dict[str, str]:
    data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    return {
        "VERSION": data["version"],
        "PDF_VERSION": "v0.5.2.1",  # PDFs were never regenerated; see CHANGELOG
        "RELEASE_DATE": data["released_at"][:10],
    }


def master_lines() -> list[str]:
    return MASTER.read_text(encoding="utf-8").splitlines()


def is_structural(line: str, in_fence: bool) -> bool:
    s = line.strip()
    if in_fence:
        return True
    if not s or s.startswith("```"):
        return True
    if s in {"---", '<div align="center">', "</div>"}:
        return True
    if re.fullmatch(r"\|[\s:|\-]+\|", s):
        return True
    return False


def normalize(line: str, v: dict[str, str]) -> str:
    """Version strings become placeholders so a version bump never breaks catalog keys."""
    out = line
    for key in ("VERSION", "PDF_VERSION"):
        out = out.replace(v[key], "{{" + key + "}}")
    return out


def collect_keys() -> list[str]:
    v = ssot()
    in_fence = False
    keys: list[str] = []
    for line in master_lines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if is_structural(line, in_fence) or line.startswith(NAV_PREFIX):
            continue
        keys.append(normalize(line, v))
    return list(dict.fromkeys(keys))


def key_id(i: int) -> str:
    return f"k{i:03d}"


def load_catalogs() -> dict[str, dict[str, str]]:
    out = {}
    for lang in LANGS:
        path = I18N / f"{lang}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Fehlender Katalog: {path}")
        out[lang] = json.loads(path.read_text(encoding="utf-8"))
    return out


def lang_nav(lang: str) -> str:
    parts = []
    for code, name, flag in ALL_LANGS:
        label = f"{flag} {name}"
        if code == lang:
            parts.append(f"**{label}**")
        elif code == "en":
            parts.append(f"[{label}](../../README.md)")
        elif code == "de":
            parts.append(f"[{label}](../../README.de.md)")
        else:
            parts.append(f"[{label}](README.{code}.md)")
    return " · ".join(parts)


def local_pdf_line(lang: str) -> str:
    links = [f"[{title}](../system/{fn(lang)})" for title, fn in LOCAL_PDFS.items()]
    return "*" + " · ".join(links) + "*"


def rewrite_links(text: str) -> str:
    """Rebase repo-relative links from repo root into docs/readme/."""
    def fix(target: str) -> str:
        if target.startswith(("http://", "https://", "#", "mailto:", "../")):
            return target
        if target.startswith("docs/"):
            return "../" + target[len("docs/"):]
        if target.startswith("./"):
            return "../../" + target[2:]
        return "../../" + target

    text = LINK_RE.sub(lambda m: "](" + fix(m.group(1)) + ")", text)
    return SRC_RE.sub(lambda m: 'src="' + fix(m.group(1)) + '"', text)


def validate(catalogs: dict[str, dict[str, str]]) -> list[str]:
    errors: list[str] = []
    keys = collect_keys()
    expected = {key_id(i): src for i, src in enumerate(keys)}
    for lang, cat in catalogs.items():
        missing = [k for k in expected if k not in cat]
        extra = [k for k in cat if k not in expected]
        if missing:
            errors.append(f"{lang}: {len(missing)} fehlende Keys (z. B. {missing[:3]})")
        if extra:
            errors.append(f"{lang}: {len(extra)} unbekannte Keys (z. B. {extra[:3]})")
        for kid, src in expected.items():
            value = cat.get(kid)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{lang}:{kid}: leerer Wert")
                continue
            if PLACEHOLDER_RE.findall(src) != PLACEHOLDER_RE.findall(value):
                errors.append(f"{lang}:{kid}: Platzhalter verändert")
            if value.count("](") != src.count("]("):
                errors.append(f"{lang}:{kid}: Link-Anzahl verändert")
    return errors


def render(lang: str, cat: dict[str, str]) -> str:
    v = ssot()
    keys = collect_keys()
    lookup = {src: cat[key_id(i)] for i, src in enumerate(keys)}
    in_fence = False
    out: list[str] = []
    for line in master_lines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if is_structural(line, in_fence):
            out.append(line)
            continue
        if line.startswith(NAV_PREFIX):
            out.append(lang_nav(lang))
            continue
        out.append(lookup[normalize(line, v)])
        if line.startswith("| **AI Boardroom: 55 Frameworks**"):
            out.append(local_pdf_line(lang))
    text = "\n".join(out) + "\n"
    for name, value in v.items():
        text = text.replace("{{" + name + "}}", value)
    return rewrite_links(text)


def main(argv: list[str]) -> int:
    if "--dump-keys" in argv:
        print(json.dumps({key_id(i): src for i, src in enumerate(collect_keys())},
                         ensure_ascii=False, indent=2))
        return 0
    if "--check" in argv and not (I18N / "es.json").is_file():
        print("OK: keine Kataloge vorhanden (Migration noch nicht erfolgt).")
        return 0
    catalogs = load_catalogs()
    errors = validate(catalogs)
    if errors:
        print("Validierung fehlgeschlagen:", file=sys.stderr)
        for e in errors[:40]:
            print("  -", e, file=sys.stderr)
        return 1
    rendered = {lang: render(lang, catalogs[lang]) for lang in LANGS}
    if "--check" in argv:
        bad = [
            lang for lang, text in rendered.items()
            if not (OUT_DIR / f"README.{lang}.md").is_file()
            or (OUT_DIR / f"README.{lang}.md").read_text(encoding="utf-8") != text
        ]
        if bad:
            print(f"Nicht aktuell: {bad} - Generator ausführen", file=sys.stderr)
            return 1
        print(f"OK: {len(LANGS)} Kataloge, {len(collect_keys())} Keys, Ausgaben aktuell.")
        return 0
    for lang, text in rendered.items():
        p = OUT_DIR / f"README.{lang}.md"
        p.write_text(text, encoding="utf-8")
        print(f"  {lang} -> {p.relative_to(ROOT)} ({len(text)} Bytes)")
    print(f"Fertig: {len(LANGS)} READMEs aus {len(collect_keys())} Keys erzeugt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
