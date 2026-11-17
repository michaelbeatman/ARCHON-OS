#!/usr/bin/env python3
"""Build KO docx from DE master + translation_cache_ko.json (offline, no API/COM/PDF)."""
import json, os, sys
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TOC_TITLE = "목차"
LOCALE = "ko-KR"
TAG = "KO"

def should_skip_text(txt):
    import re
    s = txt.strip()
    if len(s) <= 1 or not re.search(r"[A-Za-zÄÖÜäöüß]", s):
        return True
    if re.match(r"^(S\.|p\.)\s*[\d,\s]+$", s):
        return True
    return False

def merge_adjacent_similar_runs(p_el):
    for pe in list(p_el.findall("w:proofErr", NS)):
        p_el.remove(pe)
    def run_sig(r_el):
        if r_el.tag.split("}")[-1] != "r":
            return None
        for tag in ("w:drawing", "w:fldChar", "w:instrText", "w:tab", "w:br"):
            if r_el.find(tag, NS) is not None:
                return None
        rPr = r_el.find("w:rPr", NS)
        b = rPr is not None and rPr.find("w:b", NS) is not None
        it = rPr is not None and rPr.find("w:i", NS) is not None
        col = rPr.find("w:color", NS).attrib.get(qn("w:val"), "") if (rPr is not None and rPr.find("w:color", NS) is not None) else ""
        return (b, it, col)
    prev_r, prev_sig = None, None
    for ch in list(p_el):
        sig = run_sig(ch)
        if sig is not None and prev_r is not None and sig == prev_sig:
            t_cur = "".join(t.text or "" for t in ch.findall("w:t", NS))
            t_prev = prev_r.findall("w:t", NS)
            if t_prev:
                t_prev[0].set(qn("w:space"), "preserve")
                t_prev[0].text = (t_prev[0].text or "") + t_cur
                for extra in t_prev[1:]:
                    prev_r.remove(extra)
                p_el.remove(ch)
                continue
        prev_r = ch if sig is not None else None
        prev_sig = sig

# fix placeholder corrupted above
def build(inp, outp, cache):
    doc = docx.Document(inp)
    body = doc._body._body
    toc_ps = {p_el for sdt in body.findall("w:sdt", NS) for p_el in sdt.findall(".//w:p", NS)}
    targets, applied, missing = [], 0, 0
    for p_el in body.iter():
        if p_el.tag.endswith("}p") and p_el not in toc_ps:
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
        if txt not in cache:
            missing += 1
        else:
            applied += 1
        if txt.startswith(" ") and not tr.startswith(" "):
            tr = " " + tr
        if txt.endswith(" ") and not tr.endswith(" "):
            tr = tr + " "
        t_els[0].set(qn("w:space"), "preserve")
        t_els[0].text = tr
        for extra in t_els[1:]:
            r_el.remove(extra)
    for sdt in body.findall("w:sdt", NS):
        for t in sdt.findall(".//w:t", NS):
            if t.text and t.text.strip() in ("Inhalt", "Table of Contents"):
                t.text = TOC_TITLE
    for el in body.iter():
        if el.tag.endswith("}lang"):
            el.set(qn("w:val"), LOCALE)
        elif el.tag.endswith("}t") and el.text and "(DE)" in el.text:
            el.text = el.text.replace("(DE)", f"({TAG})")
    if doc.tables:
        last_tbl = doc.tables[-1]
        trs = last_tbl._tbl.findall("w:tr", NS)
        if len(trs) > 2:
            data_trs = trs[1:]
            sorted_trs = sorted(data_trs, key=lambda tr_el: "".join(t.text or "" for t in tr_el.findall("w:tc", NS)[0].findall(".//w:t", NS)).strip().lower())
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
    doc.save(outp)
    return len(targets), applied, missing

if __name__ == "__main__":
    cache = json.load(open("data/translation_cache_ko.json", encoding="utf-8"))
    jobs = [
        ("docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx", "docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_KO.docx"),
        ("docs/system/ARCHON_OS_FEATURELISTE_2026.docx", "docs/system/ARCHON_OS_FEATURELISTE_2026_KO.docx"),
        ("docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.docx", "docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_KO.docx"),
    ]
    for inp, outp in jobs:
        t, a, m = build(inp, outp, cache)
        print(f"{outp}: Segmente={t} angewendet={a} fehlend={m} MB={os.path.getsize(outp)/1024/1024:.2f}")
