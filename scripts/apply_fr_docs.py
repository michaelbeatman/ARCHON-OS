#!/usr/bin/env python3
"""FR-Apply: wendet data/translation_cache_fr.json auf die 3 DE-Master an.
Port von scripts/translate_ja_offline.py (process_one) mit FR-Regeln:
TOC 'Inhalt'->'Table des matières', Locale fr-FR, '(DE)'->'(FR)',
'Langue : Allemand'->'Langue : Français', Abb.->Fig., Glossar sortiert + Zebra F8FAFC.
"""
import json, os, re
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
CACHE = os.path.join("data", "translation_cache_fr.json")
EMOJI_RX = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def should_skip_text(txt):
    s = txt.strip()
    if len(s) <= 1 or not re.search(r"[A-Za-zÄÖÜäöüß]", s):
        return True
    if re.match(r"^(S\.|p\.)\s*[\d,\s]+$", s):
        return True
    return False


def merge_runs(p_el):
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


def collect_targets(doc):
    body = doc._body._body
    toc_ps = {p_el for sdt in body.findall("w:sdt", NS) for p_el in sdt.findall(".//w:p", NS)}
    targets, uniq, seen = [], [], set()
    for p_el in body.iter():
        if p_el.tag.endswith("}p") and p_el not in toc_ps:
            merge_runs(p_el)
            for r_el in p_el.findall("w:r", NS):
                if r_el.find("w:drawing", NS) is not None or r_el.find("w:fldChar", NS) is not None:
                    continue
                t_els = r_el.findall("w:t", NS)
                if not t_els:
                    continue
                t = "".join(x.text or "" for x in t_els)
                if should_skip_text(t):
                    continue
                targets.append((r_el, t_els, t))
                if t not in seen:
                    seen.add(t)
                    uniq.append(t)
    return body, targets, uniq


def process_one(src, dst):
    doc = docx.Document(src)
    body, targets, uniq = collect_targets(doc)
    with open(CACHE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    pending = [u for u in uniq if u not in cache]
    print(f"{src}: Segmente gesamt {len(targets)} | Unique {len(uniq)} | Pending {len(pending)}", flush=True)
    for p in pending[:10]:
        print(f"  MISSING: {p[:100]!r}", flush=True)
    for r_el, t_els, t in targets:
        tr = EMOJI_RX.sub("", cache.get(t, t))
        if t.startswith(" ") and not tr.startswith(" "):
            tr = " " + tr
        if t.endswith(" ") and not tr.endswith(" "):
            tr = tr + " "
        t_els[0].set(qn("w:space"), "preserve")
        t_els[0].text = tr
        for extra in t_els[1:]:
            r_el.remove(extra)
    for sdt in body.findall("w:sdt", NS):
        for t in sdt.findall(".//w:t", NS):
            if t.text and t.text.strip() in ("Inhalt", "Table of Contents"):
                t.text = "Table des matières"
    for el in body.iter():
        if el.tag.endswith("}lang"):
            el.set(qn("w:val"), "fr-FR")
        elif el.tag.endswith("}t") and el.text:
            if "(DE)" in el.text:
                el.text = el.text.replace("(DE)", "(FR)")
            if "Langue : Allemand" in el.text:
                el.text = el.text.replace("Langue : Allemand", "Langue : Français")
            el.text = re.sub(r"\bAbb\.(\s*\d+)", r"Fig.\1", el.text)
            el.text = re.sub(r"\bAbb\.", "Fig.", el.text)
    if doc.tables:
        last_tbl = doc.tables[-1]
        trs = last_tbl._tbl.findall("w:tr", NS)
        if len(trs) > 2:
            data_trs = trs[1:]
            srt = sorted(data_trs, key=lambda tr: "".join(x.text or "" for x in tr.findall("w:tc", NS)[0].findall(".//w:t", NS)).strip().lower())
            for r in data_trs:
                last_tbl._tbl.remove(r)
            for idx, r in enumerate(srt):
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
    doc.save(dst)
    print(f"Gespeichert: {dst}", flush=True)
    return len(targets), len(pending)


if __name__ == "__main__":
    jobs = [
        ("docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx", "docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_FR.docx"),
        ("docs/system/ARCHON_OS_FEATURELISTE_2026.docx", "docs/system/ARCHON_OS_FEATURELISTE_2026_FR.docx"),
        ("docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.docx", "docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_FR.docx"),
    ]
    for s, d in jobs:
        process_one(s, d)
