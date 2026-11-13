#!/usr/bin/env python3
"""
ARCHON OS: Lokale OCR-Dokumenten-Pipeline & Ingest-Parser
utils/batch_library_importer.py

Extrahiert Fachbücher, Scans, DIN-Normen und Dokumente (PDF, DOCX, TXT)
vollständig lokal per Text-Extraction und Tesseract OCR, spiegelt strukturierte
Markdown-Kapitel und Bilder in Obsidian (02_Wissensbibliothek/) und liefert
detaillierte Metadaten-Indizes.
"""

import os
import sys
import re
import json
import shutil
import datetime
from pathlib import Path

from archon.core.config import config
from archon.core.paths import OBSIDIAN_VAULT, OPT_DATA_DIR

# Optional dependencies with graceful fallback
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import pypdf
except ImportError:
    try:
        import PyPDF2 as pypdf
    except ImportError:
        pypdf = None

try:
    import pdf2image
    from PIL import Image
except ImportError:
    pdf2image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import docx
except ImportError:
    docx = None


def resolve_vault_path() -> str:
    """Ermittelt den aktiven Obsidian Vault Pfad."""
    env_path = config.obsidian_vault_path
    if env_path and os.path.exists(env_path):
        return env_path
    
    candidates = [
        OBSIDIAN_VAULT,
        r"./obsidian_vault",
        r"./obsidian_vault",
        "/app/agent_workspace/obsidian_vault",
        "/app/data/exported_vault",
        "agent_workspace/obsidian_vault"
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.isdir(c):
            return c
    
    # Fallback to local agent_workspace
    fallback = os.path.abspath("agent_workspace/obsidian_vault")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def resolve_raw_docs_dir() -> str:
    """Ermittelt das Verzeichnis für hochgeladene Rohdokumente."""
    candidates = [
        os.path.join(OPT_DATA_DIR, "workspace", "library", "raw_docs"),
        "/app/library/raw_docs",
        "library/raw_docs",
        r"./obsidian_vault\02_Wissensbibliothek\raw_docs"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    
    # Standard: ./library/raw_docs
    default_dir = os.path.abspath("library/raw_docs")
    os.makedirs(default_dir, exist_ok=True)
    return default_dir


def slugify(text: str) -> str:
    """Wandelt Text in einen sauberen Dateinamen-Slug um."""
    text = text.lower().strip()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_") or "dokument"


def classify_domain(filename: str, sample_text: str = "") -> tuple[str, str]:
    """Klassifiziert das Dokument in eine passende Unterkategorie oder legt ein neues Thema an."""
    combined = (filename + " " + sample_text[:2000]).lower()
    
    # 1. Cannabis / Hanf / Anbau / CSC / Medizin
    if any(k in combined for k in ["cannabis", "hanf", "thc", "cbd", "csc", "anbau", "terpene", "cannabinoid", "kcang", "medizinalcannabis", "bluete", "steckling", "grow"]):
        return "06_Cannabis_Wirtschaft_Medizin", "Cannabis & Agrarwirtschaft"
        
    # 2. Betriebswirtschaft / Finanzen / Controlling / Buchhaltung / Bilanzen
    elif any(k in combined for k in ["betriebswirtschaft", "bwl", "controlling", "buchhaltung", "rechnungswesen", "bilanz", "guv", "cashflow", "kostenrechnung", "unternehmensfuehrung", "deckungsbeitrag", "kalkulation"]):
        return "07_Betriebswirtschaft_Finanzen", "Betriebswirtschaft & Finanzen"
        
    # 3. Projektmanagement / Agile / Scrum / Führung / Organisation
    elif any(k in combined for k in ["projektmanagement", "scrum", "agile", "pmo", "meilenstein", "projektleitung", "gantt", "kanban", "sprint", "wasserfall", "stakeholder", "retrospektive"]):
        return "08_Projektmanagement_Organisation", "Projektmanagement & Organisation"
        
    # 4. Immobilien / Bau / DIN-Normen / Modulbau / Statik / Tragwerk
    elif any(k in combined for k in ["immo", "bau", "din", "modul", "grundst", "plan", "architekt", "tragwerk", "b-plan", "statik", "wohn", "quartier", "hochbau"]):
        return "01_Immobilien_Modulbau", "Immobilien & Objektentwicklung"
        
    # 5. Recht / Steuern / BGB / Verträge / Compliance / Holding
    elif any(k in combined for k in ["recht", "steuer", "bgb", "gesetz", "vertrag", "dsgvo", "compliance", "holding", "vvgmbh", "notar", "urteil", "paragraph", "§"]):
        return "02_Recht_Steuern", "Recht & Steuern"
        
    # 6. Strategie / Markt / M&A / Marketing / Vertrieb
    elif any(k in combined for k in ["strategie", "markt", "m&a", "finance", "business", "pe", "marketing", "vertrieb", "turnaround", "kpi", "roadmap", "pitch"]):
        return "03_Strategie_Markt", "Strategie & Marktanalyse"
        
    # 7. IT / Tech / Software / KI / Machine Learning / Cloud / Code
    elif any(k in combined for k in ["python", "software", "api", "docker", "kubernetes", "cloud", "programmierung", "ki", "llm", "neural", "database", "sql"]):
        return "09_Tech_Software_KI", "Tech, Software & KI"
        
    # 8. Medizin / Pharmazie / Gesundheit
    elif any(k in combined for k in ["medizin", "gesundheit", "klinik", "diagnostik", "therapie", "pharmakologie", "biologie", "anatomie"]):
        return "10_Medizin_Gesundheit", "Medizin & Gesundheit"
        
    else:
        return "04_Allgemein", "Allgemeine Fachbibliothek"


def format_table_as_markdown(table: list[list]) -> str:
    """Konvertiert eine zweidimensionale Liste in eine Markdown-Tabelle."""
    if not table or not table[0]:
        return ""
    
    cleaned = []
    for row in table:
        cleaned_row = [re.sub(r"\s+", " ", str(cell or "").strip()) for cell in row]
        cleaned.append(cleaned_row)
    
    if len(cleaned) == 0:
        return ""
        
    num_cols = max(len(row) for row in cleaned)
    header = cleaned[0] + [""] * (num_cols - len(cleaned[0]))
    
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * num_cols) + " |")
    
    for row in cleaned[1:]:
        padded = row + [""] * (num_cols - len(row))
        lines.append("| " + " | ".join(padded) + " |")
        
    return "\n".join(lines) + "\n\n"


def extract_pdf(pdf_path: str, assets_dir: str, doc_slug: str) -> dict:
    """Extrahiert Text, Struktur und Bilder aus einer PDF-Datei (Ultra-Fast Engine)."""
    pages_data = []
    total_images = 0
    ocr_pages_done = 0
    ocr_used = False
    
    # 1. Schnelle digitale Extraktion mit pdfplumber (ohne teure Tabellen-Gitterberechnung)
    if pdfplumber:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_doc_pages = len(pdf.pages)
                for page_idx, page in enumerate(pdf.pages, start=1):
                    # Blitzschnelle Textextraktion (ca. 0.005s pro Seite)
                    page_text = page.extract_text(layout=False) or ""
                    page_content = ""
                    
                    if page_text.strip():
                        page_content += page_text.strip() + "\n\n"
                    
                    # OCR-Schutz: Nur wenn Seite digital komplett leer ist (Scan) und maximal 5 Seiten
                    if len(page_text.strip()) < 20 and ocr_pages_done < 5 and pdf2image and pytesseract:
                        try:
                            images = pdf2image.convert_from_path(
                                pdf_path,
                                first_page=page_idx,
                                last_page=page_idx,
                                dpi=100, # Schnelles Low-Res Rendering
                                fmt="jpeg"
                            )
                            if images:
                                ocr_text = pytesseract.image_to_string(images[0], lang="deu+eng", config="--psm 3")
                                if ocr_text.strip():
                                    page_content += "\n> 🔍 *OCR-Extrahierter Text:*\n\n" + ocr_text.strip() + "\n\n"
                                    ocr_used = True
                                    ocr_pages_done += 1
                        except Exception as ocr_err:
                            page_content += f"\n<!-- OCR notice: {ocr_err} -->\n"
                    
                    # Bild-Extraktion (maximal 5 Bilder pro Buch, nur signifikante Grafiken)
                    if total_images < 5 and hasattr(page, "images"):
                        try:
                            for img_idx, img_obj in enumerate(page.images, start=1):
                                if total_images >= 5:
                                    break
                                bbox = (img_obj.get('x0', 0), img_obj.get('top', 0), img_obj.get('x1', 0), img_obj.get('bottom', 0))
                                width = bbox[2] - bbox[0]
                                height = bbox[3] - bbox[1]
                                if width > 180 and height > 180: # Nur echte Großgrafiken/Pläne
                                    cropped = page.crop(bbox).to_image(resolution=90)
                                    img_filename = f"{doc_slug}_p{page_idx}_{img_idx}.png"
                                    img_full_path = os.path.join(assets_dir, img_filename)
                                    cropped.save(img_full_path, format="PNG")
                                    page_content += f"\n![[{img_filename}]]\n*Abbildung {page_idx}.{img_idx}*\n\n"
                                    total_images += 1
                        except Exception:
                            pass
                    
                    pages_data.append({
                        "page_num": page_idx,
                        "content": page_content
                    })
        except Exception as e:
            print(f"pdfplumber error on {pdf_path}: {e}", file=sys.stderr)
            pages_data = []

    # 2. Fallback: pypdf falls pdfplumber fehlgeschlagen oder leer
    if not pages_data and pypdf:
        try:
            reader = pypdf.PdfReader(pdf_path)
            for page_idx, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                pages_data.append({
                    "page_num": page_idx,
                    "content": text.strip() + "\n\n"
                })
        except Exception as e:
            print(f"pypdf fallback error on {pdf_path}: {e}", file=sys.stderr)

    return {
        "pages": pages_data,
        "total_pages": len(pages_data),
        "total_images": total_images,
        "ocr_used": ocr_used
    }


def extract_docx(docx_path: str, assets_dir: str, doc_slug: str) -> dict:
    """Extrahiert Text, Tabellen und Grafiken aus einer DOCX-Datei."""
    if not docx:
        return {"pages": [{"page_num": 1, "content": "python-docx nicht installiert."}], "total_pages": 1, "total_images": 0, "ocr_used": False}
    
    doc = docx.Document(docx_path)
    full_text = []
    
    for para in doc.paragraphs:
        if para.text.strip():
            if para.style.name.startswith("Heading 1"):
                full_text.append(f"# {para.text.strip()}\n")
            elif para.style.name.startswith("Heading 2"):
                full_text.append(f"## {para.text.strip()}\n")
            elif para.style.name.startswith("Heading 3"):
                full_text.append(f"### {para.text.strip()}\n")
            else:
                full_text.append(f"{para.text.strip()}\n\n")
                
    for table in doc.tables:
        t_data = []
        for row in table.rows:
            t_data.append([cell.text.strip() for cell in row.cells])
        full_text.append(format_table_as_markdown(t_data))
        
    content_str = "".join(full_text)
    return {
        "pages": [{"page_num": 1, "content": content_str}],
        "total_pages": max(1, len(content_str) // 2500),
        "total_images": 0,
        "ocr_used": False
    }


def extract_epub(epub_path: str, assets_dir: str, doc_slug: str) -> dict:
    """Extrahiert Kapitel, Volltext und eingebettete Grafiken aus einer EPUB-E-Book-Datei."""
    try:
        import zipfile
        import html
        import xml.etree.ElementTree as ET

        pages_data = []
        total_images = 0

        with zipfile.ZipFile(epub_path, 'r') as z:
            # 1. Container finden
            try:
                container_xml = z.read("META-INF/container.xml")
                root = ET.fromstring(container_xml)
                opf_rel_path = root.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile").attrib["full-path"]
            except Exception:
                opf_candidates = [n for n in z.namelist() if n.endswith(".opf")]
                if opf_candidates:
                    opf_rel_path = opf_candidates[0]
                else:
                    return {"pages": [{"page_num": 1, "content": "Ungültiges EPUB-Archiv: Keine OPF-Datei gefunden."}], "total_pages": 1, "total_images": 0, "ocr_used": False}

            opf_dir = os.path.dirname(opf_rel_path)
            opf_xml = z.read(opf_rel_path)
            opf_root = ET.fromstring(opf_xml)

            # 2. Manifest lesen (id -> href, media-type)
            manifest = {}
            for item in opf_root.findall(".//{http://www.idpf.org/2007/opf}item"):
                item_id = item.attrib.get("id")
                href = item.attrib.get("href")
                mtype = item.attrib.get("media-type", "")
                if item_id and href:
                    manifest[item_id] = {"href": href, "mtype": mtype}

            if not manifest:
                for item in opf_root.findall(".//item"):
                    item_id = item.attrib.get("id")
                    href = item.attrib.get("href")
                    mtype = item.attrib.get("media-type", "")
                    if item_id and href:
                        manifest[item_id] = {"href": href, "mtype": mtype}

            # 3. Spine lesen (Reihenfolge der Kapitel)
            spine_ids = []
            for itemref in opf_root.findall(".//{http://www.idpf.org/2007/opf}itemref"):
                idref = itemref.attrib.get("idref")
                if idref:
                    spine_ids.append(idref)

            if not spine_ids:
                for itemref in opf_root.findall(".//itemref"):
                    idref = itemref.attrib.get("idref")
                    if idref:
                        spine_ids.append(idref)

            if not spine_ids:
                chapter_files = [n for n in z.namelist() if n.endswith((".html", ".xhtml", ".htm"))]
            else:
                chapter_files = []
                for sid in spine_ids:
                    if sid in manifest:
                        href = manifest[sid]["href"]
                        full_href = os.path.normpath(os.path.join(opf_dir, href)).replace("\\", "/")
                        chapter_files.append(full_href)

            # 4. Kapitel extrahieren & in Markdown konvertieren
            page_counter = 1
            for chap_file in chapter_files:
                try:
                    raw_html = z.read(chap_file).decode("utf-8", errors="ignore")
                except Exception:
                    continue

                text_md = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<h4[^>]*>(.*?)</h4>', r'\n#### \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<(b|strong)[^>]*>(.*?)</\1>', r'**\2**', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<(i|em)[^>]*>(.*?)</\1>', r'*\2*', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<br\s*/?>', '\n', text_md, flags=re.IGNORECASE)
                text_md = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text_md, flags=re.DOTALL | re.IGNORECASE)
                text_md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)

                # Bilder aus Kapitel extrahieren
                img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html, flags=re.IGNORECASE)
                for img_src in img_matches:
                    if total_images < 35:
                        chap_dir = os.path.dirname(chap_file)
                        img_zip_path = os.path.normpath(os.path.join(chap_dir, img_src)).replace("\\", "/")
                        if img_zip_path in z.namelist():
                            try:
                                img_data = z.read(img_zip_path)
                                ext_img = os.path.splitext(img_src)[1] or ".png"
                                img_out_name = f"{doc_slug}_epub_img_{total_images + 1}{ext_img}"
                                img_dst = os.path.join(assets_dir, img_out_name)
                                with open(img_dst, "wb") as f_img:
                                    f_img.write(img_data)
                                text_md += f"\n![[{img_out_name}]]\n*Abbildung {total_images + 1}*\n\n"
                                total_images += 1
                            except Exception:
                                pass

                text_md = re.sub(r'<[^>]+>', '', text_md)
                text_md = html.unescape(text_md)
                text_md = re.sub(r'\n{3,}', '\n\n', text_md).strip()

                if len(text_md) > 20:
                    pages_data.append({
                        "page_num": page_counter,
                        "content": text_md + "\n\n"
                    })
                    page_counter += 1

            if not pages_data:
                pages_data = [{"page_num": 1, "content": "Kein lesbarer Text im EPUB gefunden."}]

            return {
                "pages": pages_data,
                "total_pages": len(pages_data),
                "total_images": total_images,
                "ocr_used": False
            }
    except Exception as e:
        return {"pages": [{"page_num": 1, "content": f"Fehler bei EPUB-Extraktion: {e}"}], "total_pages": 1, "total_images": 0, "ocr_used": False}


def extract_mobi(mobi_path: str, assets_dir: str, doc_slug: str) -> dict:
    """Extrahiert Volltext und Kapitel aus einer Amazon MOBI/AZW E-Book-Datei."""
    try:
        import struct
        import html

        def decompress_palmdoc(data: bytes) -> bytes:
            out = bytearray()
            i = 0
            n = len(data)
            while i < n:
                byte = data[i]
                i += 1
                if byte == 0:
                    out.append(0)
                elif byte <= 8:
                    out.extend(data[i:i+byte])
                    i += byte
                elif byte <= 0x7f:
                    out.append(byte)
                elif byte <= 0xbf:
                    if i >= n:
                        break
                    next_byte = data[i]
                    i += 1
                    distance = ((byte & 0x03) << 8) | next_byte
                    length = ((byte >> 2) & 0x0f) + 3
                    start = len(out) - distance
                    if start < 0:
                        continue
                    for j in range(length):
                        if start + j < len(out):
                            out.append(out[start + j])
                else:
                    out.append(32)
                    out.append(byte ^ 0x80)
            return bytes(out)

        with open(mobi_path, "rb") as f:
            data = f.read()

        if len(data) < 78:
            return {"pages": [{"page_num": 1, "content": "Ungültiges MOBI-Format: Datei zu kurz."}], "total_pages": 1, "total_images": 0, "ocr_used": False}

        num_records = struct.unpack(">H", data[76:78])[0]
        if num_records < 1:
            return {"pages": [{"page_num": 1, "content": "Keine Datensätze in MOBI-Datei gefunden."}], "total_pages": 1, "total_images": 0, "ocr_used": False}

        record_offsets = []
        for i in range(num_records):
            offset = struct.unpack(">I", data[78 + i*8 : 78 + i*8 + 4])[0]
            record_offsets.append(offset)
        record_offsets.append(len(data))

        rec0 = data[record_offsets[0] : record_offsets[1]]
        compression = struct.unpack(">H", rec0[0:2])[0]
        text_record_count = struct.unpack(">H", rec0[8:10])[0]

        text_parts = []
        for i in range(1, min(text_record_count + 1, num_records)):
            chunk = data[record_offsets[i] : record_offsets[i+1]]
            if compression == 1:
                decomp = chunk
            elif compression == 2:
                decomp = decompress_palmdoc(chunk)
            else:
                decomp = chunk
            try:
                text_parts.append(decomp.decode("utf-8", errors="ignore"))
            except Exception:
                text_parts.append(decomp.decode("latin-1", errors="ignore"))

        raw_html = "".join(text_parts)

        text_md = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<h4[^>]*>(.*?)</h4>', r'\n#### \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<(b|strong)[^>]*>(.*?)</\1>', r'**\2**', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<(i|em)[^>]*>(.*?)</\1>', r'*\2*', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<br\s*/?>', '\n', text_md, flags=re.IGNORECASE)
        text_md = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text_md, flags=re.DOTALL | re.IGNORECASE)
        text_md = re.sub(r'<[^>]+>', '', text_md)
        text_md = html.unescape(text_md)
        text_md = re.sub(r'\n{3,}', '\n\n', text_md).strip()

        chunk_size = 4000
        sections = [text_md[i:i+chunk_size] for i in range(0, len(text_md), chunk_size)]
        if not sections:
            sections = [text_md or "Kein lesbarer Text in MOBI gefunden."]

        pages_data = []
        for p_idx, s_txt in enumerate(sections, start=1):
            pages_data.append({
                "page_num": p_idx,
                "content": s_txt + "\n\n"
            })

        return {
            "pages": pages_data,
            "total_pages": len(pages_data),
            "total_images": 0,
            "ocr_used": False
        }
    except Exception as e:
        return {"pages": [{"page_num": 1, "content": f"Fehler bei MOBI-Extraktion: {e}"}], "total_pages": 1, "total_images": 0, "ocr_used": False}


def extract_txt(txt_path: str) -> dict:
    """Liest reine Text- oder Markdown-Dateien ein."""
    try:
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {
            "pages": [{"page_num": 1, "content": content}],
            "total_pages": max(1, len(content) // 2500),
            "total_images": 0,
            "ocr_used": False
        }
    except Exception as e:
        return {"pages": [{"page_num": 1, "content": f"Fehler beim Lesen: {e}"}], "total_pages": 1, "total_images": 0, "ocr_used": False}


def process_document(file_path: str, vault_dir: str, target_category: str = "auto") -> dict:
    """Verarbeitet ein einzelnes Dokument und erzeugt Obsidian-Notizen."""
    filename = os.path.basename(file_path)
    clean_title = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()
    doc_slug = slugify(os.path.splitext(filename)[0])
    ext = os.path.splitext(filename)[1].lower()
    
    # Zielordner im Vault
    bib_dir = os.path.join(vault_dir, "02_Wissensbibliothek")
    assets_dir = os.path.join(bib_dir, "_assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    # Extraktion durchführen
    if ext == ".pdf":
        res = extract_pdf(file_path, assets_dir, doc_slug)
    elif ext in [".docx", ".doc"]:
        res = extract_docx(file_path, assets_dir, doc_slug)
    elif ext == ".epub":
        res = extract_epub(file_path, assets_dir, doc_slug)
    elif ext in [".mobi", ".azw"]:
        res = extract_mobi(file_path, assets_dir, doc_slug)
    elif ext in [".txt", ".md"]:
        res = extract_txt(file_path)
    else:
        return {"status": "skipped", "file": filename, "reason": f"Nicht unterstütztes Format: {ext}"}
    
    pages = res.get("pages", [])
    total_pages = res.get("total_pages", len(pages))
    sample_text = pages[0]["content"] if pages else ""
    
    # Domain klassifizieren oder vorgegebene Kategorie nutzen
    if target_category and target_category != "auto":
        clean_cat = os.path.basename(str(target_category).replace("\\", "/")).strip()
        if not clean_cat or clean_cat in (".", ".."):
            sub_folder, domain_title = classify_domain(filename, sample_text)
        else:
            sub_folder = clean_cat
            domain_title = clean_cat.replace("_", " ").title()
    else:
        sub_folder, domain_title = classify_domain(filename, sample_text)
        
    from utils.path_jail import safe_path_within, PathJailError
    candidate_target = os.path.join(bib_dir, sub_folder)
    try:
        target_category_dir = safe_path_within(candidate_target, [bib_dir], allow_write=True, allow_dirs=True)
    except PathJailError:
        sub_folder, domain_title = classify_domain(filename, sample_text)
        target_category_dir = safe_path_within(os.path.join(bib_dir, sub_folder), [bib_dir], allow_write=True, allow_dirs=True)

    os.makedirs(target_category_dir, exist_ok=True)
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Fallunterscheidung: Kapitel-Splitting (> 25 Seiten) vs. Einzeldokument (<= 25 Seiten)
    chapters_created = []
    
    if total_pages > 25 and len(pages) > 25:
        # Dokumenten-Ordner für Kapitel anlegen
        book_dir = os.path.join(target_category_dir, doc_slug)
        os.makedirs(book_dir, exist_ok=True)
        
        # Seiten in Blöcke (ca. 10-15 Seiten pro Kapitel) bündeln
        chunk_size = 15
        total_chunks = (len(pages) + chunk_size - 1) // chunk_size
        
        for chunk_idx in range(total_chunks):
            start_p = chunk_idx * chunk_size
            end_p = min(start_p + chunk_size, len(pages))
            chunk_pages = pages[start_p:end_p]
            
            chap_num_str = f"{chunk_idx + 1:02d}"
            chap_name = f"Kapitel_{chap_num_str}"
            chap_file = os.path.join(book_dir, f"{chap_name}.md")
            
            chap_content = f"""---
title: "{clean_title} — {chap_name}"
source_file: "{filename}"
book_slug: "{doc_slug}"
chapter: "{chap_name}"
pages: "{start_p + 1} - {end_p}"
indexed_at: "{now_str}"
tags: [fachbibliothek, kapitel, ocr_mirror]
---

# 📖 {clean_title}
## {chap_name} (Seiten {start_p + 1} bis {end_p})

[[_Index_{doc_slug}|⬅ Zurück zum Buch-Index]]

---

"""
            for p in chunk_pages:
                chap_content += f"### Seite {p['page_num']}\n\n{p['content']}\n\n---\n\n"
            
            with open(chap_file, "w", encoding="utf-8") as f:
                f.write(chap_content)
                
            chapters_created.append(chap_name)
        
        # Zentraler Buch-Index
        index_file = os.path.join(target_category_dir, f"_Index_{doc_slug}.md")
        index_content = f"""---
title: "{clean_title}"
source_file: "{filename}"
indexed_at: "{now_str}"
type: reference_book
domain: "{domain_title}"
tags: [fachbibliothek, offline_reference, ocr_mirror]
total_pages: {total_pages}
ocr_used: {str(res.get('ocr_used', False)).lower()}
chapters_count: {len(chapters_created)}
images_count: {res.get('total_images', 0)}
---

# 📖 {clean_title}

> **Kategorie:** `{domain_title}`  
> **Quelldatei:** `{filename}` | **Umfang:** {total_pages} Seiten | **Extrahiert:** {now_str}  
> **OCR-Status:** {'🔍 Per OCR eingelesen' if res.get('ocr_used') else '📄 Digitaler Volltext'}

---

## 📑 Inhaltsverzeichnis & Kapitel
"""
        for c in chapters_created:
            index_content += f"- [[{doc_slug}/{c}|📖 {c.replace('_', ' ')}]]\n"
            
        index_content += f"""
---

## 🖼️ Extrahierte Abbildungen & Pläne ({res.get('total_images', 0)})
*Alle Zeichnungen und Pläne sind hochauflösend im Vault-Ordner `_assets/` gespeichert.*
"""
        with open(index_file, "w", encoding="utf-8") as f:
            f.write(index_content)
            
    else:
        # Einzeldokument (<= 25 Seiten)
        single_file = os.path.join(target_category_dir, f"{doc_slug}.md")
        doc_content = f"""---
title: "{clean_title}"
source_file: "{filename}"
indexed_at: "{now_str}"
type: reference_doc
domain: "{domain_title}"
tags: [fachbibliothek, ocr_mirror]
total_pages: {total_pages}
ocr_used: {str(res.get('ocr_used', False)).lower()}
images_count: {res.get('total_images', 0)}
---

# 📄 {clean_title}

> **Kategorie:** `{domain_title}`  
> **Quelldatei:** `{filename}` | **Umfang:** {total_pages} Seiten | **Extrahiert:** {now_str}  
> **OCR-Status:** {'🔍 Per OCR eingelesen' if res.get('ocr_used') else '📄 Digitaler Volltext'}

---

"""
        for p in pages:
            if len(pages) > 1:
                doc_content += f"## Seite {p['page_num']}\n\n"
            doc_content += f"{p['content']}\n\n"
            
        with open(single_file, "w", encoding="utf-8") as f:
            f.write(doc_content)
            
        chapters_created.append("Komplettdokument")

    return {
        "status": "success",
        "file": filename,
        "title": clean_title,
        "slug": doc_slug,
        "category": sub_folder,
        "domain": domain_title,
        "total_pages": total_pages,
        "total_images": res.get("total_images", 0),
        "ocr_used": res.get("ocr_used", False),
        "chapters_count": len(chapters_created)
    }


def run_batch_ingest() -> dict:
    """Führt den Scan & Batch-Ingest über alle Rohdokumente aus."""
    raw_dir = resolve_raw_docs_dir()
    vault_dir = resolve_vault_path()
    
    supported_exts = {".pdf", ".docx", ".doc", ".txt", ".md", ".epub"}
    files_to_process = []
    
    for root, _, files in os.walk(raw_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in supported_exts:
                files_to_process.append(os.path.join(root, f))
                
    results = []
    total_pages_sum = 0
    total_images_sum = 0
    total_chapters_sum = 0
    
    for fpath in sorted(files_to_process):
        try:
            res = process_document(fpath, vault_dir)
            results.append(res)
            if res.get("status") == "success":
                total_pages_sum += res.get("total_pages", 0)
                total_images_sum += res.get("total_images", 0)
                total_chapters_sum += res.get("chapters_count", 0)
        except Exception as e:
            results.append({"status": "error", "file": os.path.basename(fpath), "error": str(e)})

    # Also mirror into agent_workspace/obsidian_vault if different
    alt_vault = os.path.abspath("agent_workspace/obsidian_vault")
    if os.path.exists(alt_vault) and os.path.abspath(vault_dir) != alt_vault:
        src_bib = os.path.join(vault_dir, "02_Wissensbibliothek")
        dst_bib = os.path.join(alt_vault, "02_Wissensbibliothek")
        if os.path.exists(src_bib):
            try:
                shutil.copytree(src_bib, dst_bib, dirs_exist_ok=True)
            except Exception:
                pass

    return {
        "status": "success",
        "total_files": len(files_to_process),
        "processed_pages": total_pages_sum,
        "extracted_images": total_images_sum,
        "created_chapters": total_chapters_sum,
        "vault_path": vault_dir,
        "raw_docs_dir": raw_dir,
        "items": results
    }


def list_indexed_books(vault_dir: str = None) -> list[dict]:
    """Liest alle gespiegelten Fachbücher und Dokumente aus 02_Wissensbibliothek aus."""
    if not vault_dir:
        vault_dir = resolve_vault_path()
        
    bib_dir = os.path.join(vault_dir, "02_Wissensbibliothek")
    if not os.path.exists(bib_dir):
        return []
        
    books = []
    for root, dirs, files in os.walk(bib_dir):
        if "_assets" in root:
            continue
            
        for f in files:
            if f.endswith(".md"):
                fpath = os.path.join(root, f)
                rel_path = os.path.relpath(fpath, bib_dir).replace("\\", "/")
                
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as note_f:
                        head = note_f.read(2000)
                        
                    title = f.replace(".md", "").replace("_Index_", "").replace("_", " ").title()
                    m_title = re.search(r'title:\s*["\']?([^"\']+)["\']?', head)
                    if m_title:
                        title = m_title.group(1)
                        
                    pages = 1
                    m_pages = re.search(r'total_pages:\s*(\d+)', head)
                    if m_pages:
                        pages = int(m_pages.group(1))
                        
                    ocr = "ocr_used: true" in head.lower()
                    
                    parts = rel_path.split("/")
                    if len(parts) > 1:
                        category = parts[0]
                    else:
                        category = "Hauptkatalog"
                        
                    books.append({
                        "filename": f,
                        "title": title,
                        "rel_path": rel_path,
                        "category": category,
                        "total_pages": pages,
                        "ocr_used": ocr,
                        "is_index": f.startswith("_Index_"),
                        "size_bytes": os.path.getsize(fpath)
                    })
                except Exception:
                    pass
                    
    return sorted(books, key=lambda b: (b["category"], b["title"]))


if __name__ == "__main__":
    print("=" * 60)
    print("ARCHON OS — BATCH OCR & FACHBUCH-INGEST PIPELINE")
    print("=" * 60)
    
    summary = run_batch_ingest()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    
    books = list_indexed_books(summary["vault_path"])
    print(f"\n[OK] Insgesamt {len(books)} Werke in 02_Wissensbibliothek registriert.")
