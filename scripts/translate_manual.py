#!/usr/bin/env python3
"""
CLI-Übersetzungsskript für Archon OS Word-Handbücher (.docx -> Zielsprache .docx + komprimiertes .pdf).

Unterstützte Provider (über eigenen API-Key aus .env oder --api-key):
  - openai      (OPENAI_API_KEY,     Default-Modell: gpt-4o-mini)
  - gemini      (GEMINI_API_KEY,     Default-Modell: gemini-2.5-flash über OpenAI-Kompatibilität)
  - openrouter  (OPENROUTER_API_KEY, Default-Modell: google/gemini-2.5-flash)
  - custom      (--base-url + --api-key + --model)

Beispiele:
  python scripts/translate_manual.py --input docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx --lang es --provider openai --pdf
  python scripts/translate_manual.py --input docs/system/ARCHON_OS_FEATURELISTE_2026.docx --lang fr --provider gemini --pdf
  python scripts/translate_manual.py --input docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.docx --lang es --stats
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

LANG_META = {
    "en": ("English (Technical US)", "en-US", "Table of Contents", "p. ", "EN"),
    "es": ("Spanish (Español técnico)", "es-ES", "Índice", "p. ", "ES"),
    "fr": ("French (Français technique)", "fr-FR", "Table des matières", "p. ", "FR"),
    "pt": ("Portuguese (Português técnico)", "pt-BR", "Sumário", "p. ", "PT"),
    "it": ("Italian (Italiano tecnico)", "it-IT", "Sommario", "p. ", "IT"),
    "nl": ("Dutch (Nederlands)", "nl-NL", "Inhoudsopgave", "p. ", "NL"),
    "ru": ("Russian (Технический русский)", "ru-RU", "Содержание", "стр. ", "RU"),
    "ja": ("Japanese (日本語)", "ja-JP", "目次", "p. ", "JA"),
    "ko": ("Korean (한국어)", "ko-KR", "목차", "p. ", "KO"),
    "zh": ("Simplified Chinese (简体中文)", "zh-CN", "目录", "第", "ZH"),
}

PROVIDER_DEFAULTS = {
    "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", "gpt-4o-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY", "google/gemini-2.5-flash"),
}


def load_dotenv(path: str = ".env") -> dict:
    env = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, v = s.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_system_prompt(target_lang_name: str) -> str:
    return f"""You are a senior technical translator converting Archon OS v0.5.1 German software documentation into natural, concise {target_lang_name}.

STRICT RULES:
1. Input is a JSON object mapping string integer keys ("0", "1", ...) to German segments.
2. Output MUST be ONLY a valid JSON object with the exact same keys mapped to translations.
3. Preserve leading/trailing whitespace if present.
4. NEVER translate code paths, file names, URLs, CLI commands, ports, env variables, JSON keys, roles (`admin`, `operator`, `viewer`), identifiers (`company_id`, `v0.5.1`, `break_glass_vault.enc`), or standard acronyms (`RBAC`, `TLS`, `AES`, `PBKDF2-HMAC-SHA256`, `Argon2id`, `SHA-256`, `RAG`, `CRM`, `ERP`, `DATEV`, `MCP`, `API`, `OKR`).
5. Keep product module names recognizable (`Archon OS`, `Mission Control`, `Decision Engine`, `Showroom`, `Research Lab`, `Token Guard`, `System Control Center`, `Hermes Core`, `OmniRoute`, `AnythingLLM`, `ChromaDB`, `PocketBase`, `Obsidian`, `n8n`, `Caddy`, `Authelia`).
6. For English outputs follow these exact fixed translations:
   - Operative Steuerung -> Control & Operations
   - Kognition & Wissen -> Cognition & Knowledge
   - Wirtschaft & ERP -> Business & ERP
   - Infrastruktur & Governance -> Infrastructure & Governance
   - Agenten-Kader -> Specialist Fleet
   - Zentralbibliothek -> Central Library
   - Posteingang & Ereignis-Stream -> Inbox & Event Triage
   - Lokales Privacy-Routing -> Zero-Egress Privacy Routing
   - DSGVO -> GDPR | Abb. -> Fig.
"""


def should_skip_text(txt: str) -> bool:
    s = txt.strip()
    if len(s) <= 1 or not re.search(r"[A-Za-zÄÖÜäöüß]", s):
        return True
    if re.match(r"^(S\.|p\.)\s*[\d,\s]+$", s):
        return True
    return False


def merge_adjacent_similar_runs(p_el) -> None:
    """Führt benachbarte gleich formatierte Text-Runs zusammen, ohne Fettdruck/Kursiv/Farben zu verlieren."""
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


def call_llm_batch(items: list, url: str, api_key: str, model: str, sys_prompt: str, extra_headers: dict = None) -> list:
    payload_map = {str(i): txt for i, txt in enumerate(items)}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "Translate all values in this JSON:\n" + json.dumps(payload_map, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)

    for attempt in range(6):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read().decode("utf-8"))
                content = resp["choices"][0]["message"]["content"].strip()
                m = re.search(r"\{.*\}", content, re.S)
                if not m:
                    raise ValueError(f"Ungültige JSON-Antwort: {content[:120]}")
                parsed = json.loads(m.group(0))
                return [str(parsed.get(str(i), items[i])) for i in range(len(items))]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "ignore")
            if e.code == 400 and "response_format" in err_body and "response_format" in body:
                body.pop("response_format", None)
                continue
            wait = min(30, 3 + attempt * 4)
            print(f"  [Retry {attempt+1}/6 HTTP {e.code}] warte {wait}s...", flush=True)
            time.sleep(wait)
        except Exception as e:
            wait = 2 + attempt * 3
            print(f"  [Retry {attempt+1}/6 {e}] warte {wait}s...", flush=True)
            time.sleep(wait)
    raise RuntimeError("Batch-Übersetzung nach 6 Versuchen fehlgeschlagen.")


def export_pdf_and_update_glossary_windows(docx_path: str, pdf_path: str, page_prefix: str) -> None:
    """Aktualisiert TOC, berechnet reale Seitenzahlen fürs Glossar und exportiert eine schlanke PDF über Word COM."""
    if os.name != "nt":
        print("Hinweis: Word COM PDF-Export & Seiten-Indizierung erfordert Windows + MS Word.", flush=True)
        return

    doc = docx.Document(docx_path)
    last_h1 = ""
    for p in doc.paragraphs:
        if "Heading 1" in p.style.name or "berschrift" in p.style.name:
            if p.text.strip():
                last_h1 = p.text.strip()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        pm_json = tf.name

    ps_script = os.path.join(tempfile.gettempdir(), "archon_export_helper.ps1")
    ps_code = r"""param([string]$DocPath, [string]$GlossarHeading, [string]$PageMapJson, [string]$PdfOut)
$ErrorActionPreference = "Stop"
$tmpPath = "$env:TEMP\archon_tr_work.docx"
$tmpPdf = "$env:TEMP\archon_tr_work.pdf"
Copy-Item -Path $DocPath -Destination $tmpPath -Force
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$records = New-Object System.Collections.Generic.List[object]
try {
    $doc = $word.Documents.Open($tmpPath, $false, $false)
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Fields.Update() | Out-Null
    $doc.Repaginate()
    if ($PageMapJson -ne "") {
        $tocEnd = if ($doc.TablesOfContents.Count -gt 0) { $doc.TablesOfContents.Item(1).Range.End } else { 0 }
        $gStart = $doc.Content.End
        if ($GlossarHeading -ne "") {
            $rng = $doc.Range($tocEnd, $doc.Content.End)
            $f = $rng.Find; $f.ClearFormatting(); $f.Text = $GlossarHeading
            if ($f.Execute()) { $gStart = $rng.Start }
        }
        foreach ($p in $doc.Paragraphs) {
            $r = $p.Range; $s = $r.Start
            if ($s -le $tocEnd) { continue }
            if ($s -ge $gStart) { break }
            $txt = $r.Text; if ($null -eq $txt -or $txt.Trim().Length -lt 2) { continue }
            $st = ""; try { $st = [string]$p.Style.NameLocal } catch {}
            $records.Add([PSCustomObject]@{ page = [int]$r.Information(3); style = $st; text = $txt.Trim() })
        }
        $records | ConvertTo-Json -Depth 3 -Compress | Set-Content -Path $PageMapJson -Encoding UTF8
    }
    $pages = $doc.ComputeStatistics(2)
    $doc.Save()
    if ($PdfOut -ne "") { $doc.ExportAsFixedFormat($tmpPdf, 17, $false, 1) }
    $doc.Close($false)
    Write-Output "WORD_STATUS: Pages=$pages"
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
Start-Sleep -Seconds 1
Copy-Item -Path $tmpPath -Destination $DocPath -Force
Remove-Item -Path $tmpPath -Force -ErrorAction SilentlyContinue
if ($PdfOut -ne "" -and (Test-Path $tmpPdf)) {
    Copy-Item -Path $tmpPdf -Destination $PdfOut -Force
    Remove-Item -Path $tmpPdf -Force -ErrorAction SilentlyContinue
}
"""
    with open(ps_script, "w", encoding="utf-8") as f:
        f.write(ps_code)

    # Pass 1: Page numbers ermitteln & in letzte Glossar-Tabelle schreiben
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_script,
                    "-DocPath", os.path.abspath(docx_path), "-GlossarHeading", last_h1, "-PageMapJson", pm_json, "-PdfOut", ""], check=True)
    with open(pm_json, "r", encoding="utf-8-sig") as f:
        records = json.load(f)

    doc = docx.Document(docx_path)
    if doc.tables:
        tbl = doc.tables[-1]
        for row in tbl.rows[1:]:
            term = row.cells[0].text.strip()
            needle = term.split(" (")[0].strip()
            hits = Counter()
            h_hits = []
            rx = re.compile(re.escape(needle), re.IGNORECASE)
            for rec in records:
                if rx.search(rec["text"]):
                    if "berschrift" in rec["style"] or "Heading" in rec["style"]:
                        h_hits.append(rec["page"])
                    hits[rec["page"]] += 1
            sel = []
            for p in h_hits + [p for p, _ in hits.most_common(6)]:
                if p not in sel and len(sel) < 4:
                    sel.append(p)
            pg_str = (page_prefix + ", ".join(str(p) for p in sorted(sel))) if sel else "—"
            t_els = row.cells[-1]._tc.findall(".//w:t", NS)
            if t_els:
                t_els[0].text = pg_str
        doc.save(docx_path)

    # Pass 2: Final TOC Update + Screen-Optimierter PDF-Export
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_script,
                    "-DocPath", os.path.abspath(docx_path), "-GlossarHeading", last_h1, "-PageMapJson", "",
                    "-PdfOut", os.path.abspath(pdf_path) if pdf_path else ""], check=True)
    os.remove(pm_json)
    os.remove(ps_script)


def main():
    parser = argparse.ArgumentParser(description="Archon OS Handbuch- & Featurelisten-Übersetzer (.docx -> Zielsprache .docx + .pdf)")
    parser.add_argument("--input", required=True, help="Pfad zur deutschen .docx-Masterdatei")
    parser.add_argument("--output", help="Zielpfad für übersetzte .docx (Standard: <name>_<LANG>.docx)")
    parser.add_argument("--lang", required=True, help="Zielsprachcode, z. B. en, es, fr, pt, it, nl, ru, ja, ko, zh")
    parser.add_argument("--provider", choices=["openai", "gemini", "openrouter", "custom"], default="openai", help="API-Provider")
    parser.add_argument("--api-key", help="API-Key (alternativ aus .env / Umgebungsvariable)")
    parser.add_argument("--model", help="Modell-ID (überschreibt Provider-Standard)")
    parser.add_argument("--base-url", help="Custom Chat-Completions URL (nur bei --provider custom)")
    parser.add_argument("--batch-size", type=int, default=18, help="Segmente pro API-Call (Standard: 18)")
    parser.add_argument("--cache", help="Pfad zur Cache-JSON (Standard: data/translation_cache_<lang>.json)")
    parser.add_argument("--pdf", action="store_true", help="Anschließend über MS Word TOC aktualisieren, Glossar paginieren und .pdf exportieren")
    parser.add_argument("--stats", action="store_true", help="Nur Textsegmente zählen (kein API-Aufruf)")
    args = parser.parse_args()

    lang_code = args.lang.lower()
    lang_name, word_locale, toc_title, page_prefix, tag_upper = LANG_META.get(
        lang_code, (args.lang, args.lang, "Table of Contents", "p. ", args.lang.upper())
    )

    if not os.path.exists(args.input):
        sys.exit(f"Eingabedatei nicht gefunden: {args.input}")

    base, _ = os.path.splitext(args.input)
    out_docx = args.output or f"{base}_{tag_upper}.docx"
    out_pdf = os.path.splitext(out_docx)[0] + ".pdf"
    cache_path = args.cache or os.path.join("data", f"translation_cache_{lang_code}.json")

    doc = docx.Document(args.input)
    body = doc._body._body
    toc_ps = {p_el for sdt in body.findall("w:sdt", NS) for p_el in sdt.findall(".//w:p", NS)}

    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)

    targets = []
    unique_pending = []
    seen_pending = set()
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
                if txt not in cache and txt not in seen_pending:
                    seen_pending.add(txt)
                    unique_pending.append(txt)

    total_chars = sum(len(x) for x in unique_pending)
    print(f"Dokument: {args.input} -> Ziel: {out_docx} ({lang_name})")
    print(f"Segmente gesamt: {len(targets)} | Noch unübersetzt (nicht im Cache): {len(unique_pending)} (~{total_chars:,} Zeichen)")

    if args.stats:
        return

    env = load_dotenv()
    if args.provider == "custom":
        if not args.base_url or not args.model:
            sys.exit("Bei --provider custom sind --base-url und --model erforderlich.")
        url, env_key_name, model = args.base_url, "OPENAI_API_KEY", args.model
    else:
        url, env_key_name, default_model = PROVIDER_DEFAULTS[args.provider]
        model = args.model or default_model

    api_key = args.api_key or os.environ.get(env_key_name) or env.get(env_key_name, "")
    if not api_key:
        sys.exit(f"Fehlender API-Key: Bitte --api-key übergeben oder {env_key_name} in .env setzen.")

    sys_prompt = build_system_prompt(lang_name)
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)

    batch, batch_chars, done = [], 0, 0
    for txt in unique_pending:
        if len(batch) >= args.batch_size or (batch_chars + len(txt) > 3200 and batch):
            tr_list = call_llm_batch(batch, url, api_key, model, sys_prompt)
            for s_src, s_tr in zip(batch, tr_list):
                cache[s_src] = s_tr
            done += len(batch)
            print(f"  Übersetzt: {done}/{len(unique_pending)}...", flush=True)
            with open(cache_path, "w", encoding="utf-8") as cf:
                json.dump(cache, cf, ensure_ascii=False, indent=1)
            batch, batch_chars = [], 0
        batch.append(txt)
        batch_chars += len(txt)
    if batch:
        tr_list = call_llm_batch(batch, url, api_key, model, sys_prompt)
        for s_src, s_tr in zip(batch, tr_list):
            cache[s_src] = s_tr
        done += len(batch)
        with open(cache_path, "w", encoding="utf-8") as cf:
            json.dump(cache, cf, ensure_ascii=False, indent=1)
        print(f"  Übersetzt: {done}/{len(unique_pending)} (fertig).", flush=True)

    # Übersetzungen anwenden + TOC-Titel/Sprachcode anpassen
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

    for sdt in body.findall("w:sdt", NS):
        for t in sdt.findall(".//w:t", NS):
            if t.text and t.text.strip() in ("Inhalt", "Table of Contents"):
                t.text = toc_title

    for el in body.iter():
        if el.tag.endswith("}lang"):
            el.set(qn("w:val"), word_locale)
        elif el.tag.endswith("}t") and el.text and "(DE)" in el.text:
            el.text = el.text.replace("(DE)", f"({tag_upper})")

    # Glossar am Ende alphabetisch in Zielsprache sortieren
    if doc.tables:
        last_tbl = doc.tables[-1]
        trs = last_tbl._tbl.findall("w:tr", NS)
        if len(trs) > 2:
            data_trs = trs[1:]
            sorted_trs = sorted(
                data_trs,
                key=lambda tr_el: "".join(t.text or "" for t in tr_el.findall("w:tc", NS)[0].findall(".//w:t", NS)).strip().lower()
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

    doc.save(out_docx)
    print(f"Gespeichert: {out_docx}")

    if args.pdf:
        export_pdf_and_update_glossary_windows(out_docx, out_pdf, page_prefix)
        print(f"PDF exportiert: {out_pdf} ({os.path.getsize(out_pdf)/1024/1024:.2f} MB)")


if __name__ == "__main__":
    main()
