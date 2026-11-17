#!/usr/bin/env python3
"""PT-Build: wendet data/translation_cache_pt.json auf die 3 DE-Master an (ohne API, ohne COM/PDF)."""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from translate_manual import should_skip_text, merge_adjacent_similar_runs, NS
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "translation_cache_pt.json")
JOBS = [
    ("docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx",
     "docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_PT.docx",
     "C:/tmp/pt_glosshand_handbuch.json"),
    ("docs/system/ARCHON_OS_FEATURELISTE_2026.docx",
     "docs/system/ARCHON_OS_FEATURELISTE_2026_PT.docx",
     "C:/tmp/pt_glosshand_feature.json"),
    ("docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.docx",
     "docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_PT.docx",
     "C:/tmp/pt_glosshand_board.json"),
]

def set_cell_text(cell, new_text):
    tc = cell._tc
    ts = tc.findall(".//w:t", NS)
    if not ts:
        p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
        r = p.add_run(); r.text = new_text
        return
    t0 = ts[0]
    t0.set(qn("w:space"), "preserve")
    t0.text = new_text
    for extra in ts[1:]:
        r = extra.getparent()
        if r is not None:
            r.remove(extra)
    # leere w:r entfernen
    for r in tc.findall(".//w:r", NS):
        if r.find("w:t", NS) is None and r.find("w:drawing", NS) is None \
           and r.find("w:fldChar", NS) is None and r.find("w:instrText", NS) is None:
            p = r.getparent()
            if p is not None:
                p.remove(r)

def main():
    cache = json.load(open(CACHE, encoding="utf-8"))
    for src_rel, out_rel, hand_path in JOBS:
        src = os.path.join(ROOT, src_rel)
        out = os.path.join(ROOT, out_rel)
        doc = docx.Document(src)
        body = doc._body._body
        toc_ps = {p_el for sdt in body.findall("w:sdt", NS) for p_el in sdt.findall(".//w:p", NS)}
        targets, applied = [], 0
        for p_el in body.iter():
            if p_el.tag.endswith("}p") and p_el not in toc_ps:
                merge_adjacent_similar_runs(p_el)
                for r_el in p_el.findall("w:r", NS):
                    if r_el.find("w:drawing", NS) is not None or r_el.find("w:fldChar", NS) is not None:
                        continue
                    t_els = r_el.findall("w:t", NS)
                    if not t_els:
                        continue
                    txt = "".join(t.text or "" for t in t_els)
                    if should_skip_text(txt):
                        continue
                    targets.append((r_el, t_els, txt))
        for r_el, t_els, txt in targets:
            tr = cache.get(txt, txt)
            if txt.startswith(" ") and not tr.startswith(" "):
                tr = " " + tr
            if txt.endswith(" ") and not tr.endswith(" "):
                tr = tr + " "
            t_els[0].set(qn("w:space"), "preserve")
            t_els[0].text = tr
            for extra in t_els[1:]:
                r_el.remove(extra)
            if tr != txt:
                applied += 1
        for sdt in body.findall("w:sdt", NS):
            for t in sdt.findall(".//w:t", NS):
                if t.text and t.text.strip() in ("Inhalt", "Table of Contents"):
                    t.text = "Sumário"
        for el in body.iter():
            if el.tag.endswith("}lang"):
                el.set(qn("w:val"), "pt-BR")
            elif el.tag.endswith("}t") and el.text and "(DE)" in el.text:
                el.text = el.text.replace("(DE)", "(PT)")
            elif el.tag.endswith("}t") and el.text and re.search(r"\bAbb\.", el.text):
                el.text = re.sub(r"\bAbb\.", "Fig.", el.text)
        # Glossar: Volltext aus Handliste
        gl = json.load(open(hand_path, encoding="utf-8"))
        if doc.tables:
            last_tbl = doc.tables[-1]
            trs = last_tbl._tbl.findall("w:tr", NS)
            data_trs = trs[1:]
            assert len(data_trs) == len(gl), (out_rel, len(data_trs), len(gl))
            for tr_el, (term_pt, def_pt) in zip(data_trs, gl):
                tcs = tr_el.findall("w:tc", NS)
                # term + def ueberschreiben (letzte Spalte = Seiten, bleibt)
                from docx.table import _Cell
                # wrap tc elements
                for tc_el, new in zip(tcs[:2], (term_pt, def_pt)):
                    ts = tc_el.findall(".//w:t", NS)
                    if ts:
                        ts[0].set(qn("w:space"), "preserve")
                        ts[0].text = new
                        for extra in ts[1:]:
                            r = extra.getparent()
                            if r is not None:
                                r.remove(extra)
            # sortieren + zebra (wie translate_manual)
            trs = last_tbl._tbl.findall("w:tr", NS)
            data_trs = trs[1:]
            sorted_trs = sorted(
                data_trs,
                key=lambda tr_el: "".join(t.text or "" for t in tr_el.findall("w:tc", NS)[0].findall(".//w:t", NS)).strip().lower(),
            )
            for r in data_trs:
                last_tbl._tbl.remove(r)
            for idx, r in enumerate(sorted_trs):
                for tc in r.findall("w:tc", NS):
                    tcPr = tc.find("w:tcPr", NS)
                    if tcPr is not None:
                        old = tcPr.find("w:shd", NS)
                        if old is not None:
                            tcPr.remove(old)
                        if idx % 2 == 1:
                            shd = OxmlElement("w:shd")
                            shd.set(qn("w:val"), "clear")
                            shd.set(qn("w:color"), "auto")
                            shd.set(qn("w:fill"), "F8FAFC")
                            tcPr.append(shd)
                last_tbl._tbl.append(r)
        doc.save(out)
        print(f"Gespeichert: {out_rel} | Segmente: {len(targets)} | uebersetzt: {applied} | MB: {os.path.getsize(out)/1024/1024:.2f}")

if __name__ == "__main__":
    main()
