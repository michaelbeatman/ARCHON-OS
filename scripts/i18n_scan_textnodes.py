#!/usr/bin/env python3
"""Findet Textknoten mit Buchstaben, die keinen ``data-i18n*``-Anker tragen.

Der Scanner ist die Messquelle der Lokalisierungs-Etappen: er liefert je
HTML-Datei die offenen Textknoten als TSV (``zeile | tag | text | key``) auf
stdout und eine Zusammenfassung auf stderr. Damit sind weitere Views ohne
Ad-hoc-Skripte prüfbar.

Anker-Semantik: ``static/js/archon_i18n.js`` ersetzt bei einem Element mit
``data-i18n`` den gesamten ``textContent``. Ein Textknoten gilt deshalb als
annotiert, sobald *irgendein* Vorfahrenelement einen ``data-i18n*``-Anker
trägt - exakt die Regel, die auch ``tests/test_locale_parity.py`` verwendet.

Aufruf:
    python scripts/i18n_scan_textnodes.py static/views/foo.html [...]
    python scripts/i18n_scan_textnodes.py --json static/views/foo.html
    python scripts/i18n_scan_textnodes.py --attrs static/views/foo.html
    python scripts/i18n_scan_textnodes.py --ignore-file exceptions.json ...

Exit-Code: 0 = kein offener Knoten, 1 = offene Knoten vorhanden, 2 = Fehler.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from html.parser import HTMLParser

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Elemente ohne Textinhalt und ohne Schliess-Tag.
VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

# Inhalte, die kein rendernaher UI-Text sind. ``template`` wird bewusst NICHT
# uebersprungen: geparkte Markup-Bloecke sind UI-Text, der bei Reaktivierung
# sonst unuebersetzt erscheint (die Baseline der Etappe 3 zaehlt sie mit).
SKIP_CONTENT_TAGS = frozenset({"script", "style", "svg", "path"})

# Attribute mit menschenlesbarem Text, die die Engine separat uebersetzt.
TRANSLATABLE_ATTRS = ("placeholder", "title", "aria-label")

ANCHOR_ATTRS = ("data-i18n", "data-i18n-title", "data-i18n-placeholder")

KEY_RE = re.compile(r"[^a-z0-9]+")
SECTION_RE = re.compile(r"(?:settings-tab|tab)-([a-z0-9_]+)")
ID_NOISE_RE = re.compile(
    r"^(?:settings|btn|step|new|modal|input|select|api-key|push|update|"
    r"auth|aut|autonomy|scope|field|label|val|row|card|box|badge)-+"
)


def slugify(text: str, limit: int = 42) -> str:
    """ASCII-snake_case-Slug fuer Katalogschluessel."""
    text = text.casefold()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(src, dst)
    slug = KEY_RE.sub("_", text).strip("_")
    if len(slug) > limit:
        slug = slug[:limit].rstrip("_")
    return slug or "text"


def recommended_key(section: str, element_id: str | None, text: str) -> str:
    """Empfohlener Key: ``settings.<bereich>.<element>`` (3 Segmente)."""
    section = slugify(section or "general", 24)
    if element_id:
        element = slugify(ID_NOISE_RE.sub("", element_id), 40)
    else:
        element = slugify(text, 40)
    return f"settings.{section}.{element}"


class TextNodeScanner(HTMLParser):
    """Sammelt Textknoten samt Anker-Status, Besitzer-Element und Tiefe."""

    def __init__(self, line_starts: list[int] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.line_starts = line_starts or [0]
        self.stack: list[dict] = []
        self.skip_depth = 0
        self.total = 0
        self.annotated = 0
        self.elements: dict[int, dict] = {}
        self.next_uid = 0
        self.open_nodes: list[dict] = []
        self.attr_candidates: list[dict] = []

    def _offset(self) -> int:
        """Absolute Zeichenposition des gerade geoeffneten Tags."""
        line, column = self.getpos()
        return self.line_starts[min(line - 1, len(self.line_starts) - 1)] + column

    # --- Elementverwaltung -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.stack:
            self.stack[-1]["has_children"] = True
        if tag in SKIP_CONTENT_TAGS:
            self.skip_depth += 1
            return
        if tag in VOID_TAGS:
            self._collect_attrs(tag, attrs)
            return

        element = {
            "tag": tag,
            "attrs": attrs,
            "id": attrs.get("id"),
            "anchored": any(name in attrs for name in ANCHOR_ATTRS),
            "has_children": False,
            "line": self.getpos()[0],
            "offset": self._offset(),
        }
        self.elements[self.next_uid] = element
        element["uid"] = self.next_uid
        self.next_uid += 1
        self.stack.append(element)
        self._collect_attrs(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        if tag in SKIP_CONTENT_TAGS:
            return
        self._collect_attrs(tag, dict(attrs))

    def handle_endtag(self, tag):
        if tag in SKIP_CONTENT_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if tag in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                return

    # --- Erhebung ----------------------------------------------------------
    def handle_data(self, data):
        if self.skip_depth or not any(char.isalpha() for char in data):
            return
        self.total += 1
        owner = self.stack[-1] if self.stack else None
        if any(entry["anchored"] for entry in self.stack):
            self.annotated += 1
            return

        text = " ".join(data.split())
        section = self._section()
        self.open_nodes.append(
            {
                "line": self.getpos()[0],
                "tag": owner["tag"] if owner else "?",
                "id": owner["id"] if owner else None,
                "mixed": False,
                "owner_uid": owner["uid"] if owner else -1,
                "owner_offset": owner["offset"] if owner else -1,
                "text": text,
                "key": recommended_key(section, owner["id"] if owner else None, text),
            }
        )

    def _collect_attrs(self, tag, attrs):
        for name in TRANSLATABLE_ATTRS:
            value = attrs.get(name)
            if not value or not any(char.isalpha() for char in value):
                continue
            if f"data-i18n-{name}" in attrs or "data-i18n" in attrs:
                continue
            self.attr_candidates.append(
                {
                    "line": self.getpos()[0],
                    "tag": tag,
                    "attr": name,
                    "text": " ".join(value.split()),
                    "key": recommended_key(self._section(), attrs.get("id"), value),
                }
            )

    def _section(self) -> str:
        """Bereich aus der naechsten ``settings-tab-*``- bzw. ``tab-*``-ID."""
        for entry in reversed(self.stack):
            ident = entry["id"] or ""
            match = SECTION_RE.match(ident)
            if match:
                return match.group(1)
        return "general"


def scan(path: pathlib.Path) -> TextNodeScanner:
    source = path.read_text(encoding="utf-8")
    line_starts = [0]
    for line in source.split("\n")[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)
    scanner = TextNodeScanner(line_starts)
    scanner.feed(source)
    scanner.close()
    # ``mixed`` erst nach dem Parsen bestimmen: ein Textknoten vor einem
    # Kind-Element weiss zum Lesezeitpunkt noch nichts von diesem Kind.
    for node in scanner.open_nodes:
        owner = scanner.elements.get(node["owner_uid"])
        node["mixed"] = bool(owner and owner["has_children"])
    return scanner


def load_ignores(path: pathlib.Path) -> set[tuple[str, str]]:
    """Ausnahmen als ``{(relativer_pfad, text)}`` aus einer JSON-Liste."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {(entry["file"], entry["text"]) for entry in entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0] or "i18n Textknoten-Scanner"
    )
    parser.add_argument("files", nargs="+", type=pathlib.Path)
    parser.add_argument("--json", action="store_true", help="JSON statt TSV")
    parser.add_argument("--attrs", action="store_true",
                        help="placeholder/title/aria-label mitpruefen")
    parser.add_argument("--ignore-file", type=pathlib.Path,
                        help="JSON-Liste begruendeter Ausnahmen")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)

    ignores = load_ignores(args.ignore_file) if args.ignore_file else set()
    reports = []
    for path in args.files:
        if not path.is_file():
            print(f"Datei nicht gefunden: {path}", file=sys.stderr)
            return 2
        scanner = scan(path)
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        nodes = [node for node in scanner.open_nodes
                 if (rel, node["text"]) not in ignores]
        attrs = [entry for entry in scanner.attr_candidates
                 if (rel, entry["text"]) not in ignores]
        reports.append(
            {
                "file": rel,
                "total": scanner.total,
                "annotated": scanner.annotated,
                "open": len(nodes),
                "ignored": len(scanner.open_nodes) - len(nodes),
                "nodes": nodes,
                "open_attrs": len(attrs),
                "attrs": attrs,
            }
        )

    if args.json:
        payload = reports if len(reports) > 1 else reports[0]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.summary_only:
        for report in reports:
            for node in report["nodes"]:
                print("\t".join(
                    (report["file"], str(node["line"]), node["tag"],
                     "mixed" if node["mixed"] else "leaf",
                     node["key"], node["text"])
                ))
            if args.attrs:
                for entry in report["attrs"]:
                    print("\t".join(
                        (report["file"], str(entry["line"]), entry["tag"],
                         f"@{entry['attr']}", entry["key"], entry["text"])
                    ))

    for report in reports:
        extra = f", {report['open_attrs']} offene Attribute" if args.attrs else ""
        print(
            f"{report['file']}: {report['total']} Textknoten, "
            f"{report['annotated']} annotiert, {report['open']} offen "
            f"({report['ignored']} Ausnahmen){extra}",
            file=sys.stderr,
        )

    return 0 if all(r["open"] == 0 and r["open_attrs"] == 0 for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
