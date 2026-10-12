# -*- coding: utf-8 -*-
"""dossier_builder.py — erzeugt aus einem Berichtstext ein teilbares HTML-Dossier.

Zweck (User-Wunsch 12.10.2026, "2a"): Zwischenberichte sollen mit der
Telegram-Freigabe-Anfrage MITGESCHICKT werden, damit der Owner sieht, WAS er
freigibt — statt nur einem Hinweis "liegt unter <Pfad>".

Bewusst ABHAENGIGKEITSFREI (im ARCHON-Image gibt es kein reportlab/weasyprint/
pandoc/chromium): reines HTML, das Telegram als Dokument ausliefert und das im
Browser les- und druckbar ist. Kein externer Konverter, kein Image-Rebuild.

Regel "eine Datei = ein Zustaendigkeitsbereich": dieses Modul rendert NUR das
Dossier; wer es verschickt (Telegram) und wo es abgelegt wird, entscheidet der
Aufrufer.
"""

import os
import re
import html
import logging
import datetime

logger = logging.getLogger("archon_os")


def _inline(s: str) -> str:
    """Inline-Auszeichnung NACH dem Escapen: **bold**, `code`."""
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def md_to_html(text: str) -> str:
    """Minimaler, SICHERER Markdown->HTML-Umsetzer (escapet zuerst).

    Deckt ab: ATX-Ueberschriften, Code-Fences, **bold**, `code`, Listen,
    Blockquotes, Absaetze. Bewusst klein gehalten - genau das, was die
    Agenten-Berichte liefern.
    """
    text = (text or "").replace("\r\n", "\n")
    out, in_code, in_list = [], False, False
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            _item = re.sub(r"^\s*[-*]\s+", "", line)
            out.append(f"<li>{_inline(_item)}</li>")
            continue
        if line.strip().startswith(">"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote>{_inline(line.strip()[1:].strip())}</blockquote>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.strip():
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


_TEMPLATE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; line-height: 1.55;
        max-width: 52rem; margin: 0 auto; padding: 2rem 1.25rem 4rem;
        color: #242424; background: #fbfaf7; }}
 h1 {{ font-size: 1.5rem; margin: 0 0 .2rem; }}
 h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .4rem; border-bottom: 1px solid #e4e0d8;
       padding-bottom: .2rem; }}
 h3, h4, h5, h6 {{ font-size: 1rem; margin: 1.2rem 0 .3rem; }}
 .meta {{ color: #6f6a61; font-size: .85rem; margin-bottom: 1.4rem; }}
 .meta span {{ display: inline-block; margin: 0 1rem .2rem 0; }}
 pre {{ background: #f1eee8; border: 1px solid #e4e0d8; border-radius: 6px;
        padding: .6rem .8rem; overflow-x: auto; font-size: .85rem; }}
 code {{ background: #f1eee8; padding: .05rem .3rem; border-radius: 4px; font-size: .9em; }}
 pre code {{ background: none; padding: 0; }}
 blockquote {{ margin: .6rem 0; padding: .3rem .9rem; border-left: 3px solid #c9c3b8;
               color: #4a463f; }}
 ul {{ margin: .4rem 0 .8rem 1.2rem; }}
</style></head>
<body>
<h1>{title}</h1>
<div class="meta">{meta}</div>
{body}
</body></html>
"""


def _safe_name(name: str) -> str:
    n = re.sub(r"[^a-zA-Z0-9._-]+", "-", (name or "dossier")).strip("-")
    return (n or "dossier")[:80]


def build_dossier_html(title, body_text, target_dir, base_name, meta_pairs=None):
    """Schreibt ein HTML-Dossier und gibt den Pfad zurueck (oder None bei Fehler).

    title      : Ueberschrift des Dossiers
    body_text  : Berichtstext (Markdown-nah)
    target_dir : Zielordner (wird angelegt)
    base_name  : Dateiname ohne Endung (wird bereinigt)
    meta_pairs : optionale Liste (label, wert) fuer die Kopfzeile
    """
    try:
        os.makedirs(target_dir, exist_ok=True)
        meta_html = ""
        for label, wert in (meta_pairs or []):
            if wert in (None, ""):
                continue
            meta_html += f"<span><strong>{html.escape(str(label))}:</strong> {html.escape(str(wert))}</span>"
        doc = _TEMPLATE.format(
            title=html.escape(str(title or "Dossier")),
            meta=meta_html,
            body=md_to_html(body_text),
        )
        path = os.path.join(target_dir, _safe_name(base_name) + ".html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
        logger.info(f"[Dossier] erstellt: {path} ({len(doc)} B)")
        return path
    except Exception as e:
        logger.warning(f"[Dossier] Konnte Dossier nicht schreiben ({target_dir}/{base_name}): {e}")
        return None


def build_dossier_from_report(title, body_text, target_dir, base_name, ref_id="", quelle=""):
    """Bequemlichkeits-Wrapper mit Standard-Metazeile (Zeit/Referenz/Quelle)."""
    meta = [
        ("Erstellt", datetime.datetime.now().strftime("%d.%m.%Y %H:%M")),
        ("Referenz", ref_id),
        ("Quelle", quelle),
    ]
    return build_dossier_html(title, body_text, target_dir, base_name, meta_pairs=meta)
