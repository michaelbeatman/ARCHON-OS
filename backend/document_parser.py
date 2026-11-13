"""
backend/document_parser.py
Erweitertes Dokumenten-Parsing & Tabellenextraktion für Archon OS (t-539b65, Pillar 4).
Parst komplexe Dokumente (PDF, DOCX, XLSX, CSV, Markdown, TXT) ohne zwingende externe Abhängigkeiten:
- DOCX: Native Extraktion von Absätzen, Überschriften und Tabellen aus word/document.xml per zipfile/etree.
- XLSX: Native Extraktion von Tabellenblättern aus xl/worksheets/ per zipfile/etree.
- CSV / TSV: Robuste Delimiter-Erkennung (Komma, Semikolon, Tab).
- PDF: Strukturierte Textextraktion mit PDF-Stream-Decoder und Unterstützung für pypdf/fitz/pdfplumber falls installiert.
- Markdown / Tabellen: Konvertiert extrahierte Tabellen in normgerechtes GitHub-Flavored Markdown.
"""

import os
import re
import csv
import sys
import json
import zlib
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple


class DocumentParserEngine:
    """Universeller Parser für Dokumentformate mit nativer XML/ZIP-Extraktion."""

    @classmethod
    def parse_file(cls, filepath: str) -> Dict[str, Any]:
        """Erkennt Dateityp und parst das Dokument."""
        if not os.path.exists(filepath):
            return {"status": "error", "message": f"Datei '{filepath}' existiert nicht."}

        ext = os.path.splitext(filepath)[1].lower()
        filename = os.path.basename(filepath)
        size_bytes = os.path.getsize(filepath)

        if ext == ".docx":
            res = cls.parse_docx(filepath)
        elif ext in [".xlsx", ".xlsm"]:
            res = cls.parse_xlsx(filepath)
        elif ext in [".csv", ".tsv"]:
            res = cls.parse_csv(filepath)
        elif ext in [".md", ".markdown", ".txt", ".json", ".log"]:
            res = cls.parse_text_file(filepath)
        elif ext == ".pdf":
            res = cls.parse_pdf(filepath)
        else:
            # Fallback als Textdatei versuchen
            res = cls.parse_text_file(filepath)

        res["filename"] = filename
        res["file_size_bytes"] = size_bytes
        res["extension"] = ext
        return res

    @classmethod
    def parse_docx(cls, filepath: str) -> Dict[str, Any]:
        """Parst DOCX-Dateien über den internen XML-Baum (word/document.xml)."""
        paragraphs: List[str] = []
        tables: List[List[List[str]]] = []
        markdown_blocks: List[str] = []

        try:
            with zipfile.ZipFile(filepath, "r") as z:
                xml_content = z.read("word/document.xml")

            root = ET.fromstring(xml_content)
            # Word namespaces
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

            body = root.find("w:body", ns)
            if body is None:
                body = root

            for elem in body:
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

                # 1. Absatz / Überschrift
                if tag == "p":
                    p_text = "".join(elem.itertext()).strip()
                    if p_text:
                        # Überschriften-Prüfung anhand Style
                        p_style = elem.find(".//w:pStyle", ns)
                        style_val = p_style.attrib.get(f"{{{ns['w']}}}val", "") if p_style is not None else ""
                        if "Heading1" in style_val or "Titel" in style_val:
                            formatted = f"# {p_text}"
                        elif "Heading2" in style_val or "Untertitel" in style_val:
                            formatted = f"## {p_text}"
                        elif "Heading3" in style_val:
                            formatted = f"### {p_text}"
                        else:
                            formatted = p_text

                        paragraphs.append(p_text)
                        markdown_blocks.append(formatted)

                # 2. Tabelle
                elif tag == "tbl":
                    table_matrix: List[List[str]] = []
                    for row in elem.findall("w:tr", ns):
                        row_cells = []
                        for cell in row.findall("w:tc", ns):
                            cell_text = "".join(cell.itertext()).strip()
                            row_cells.append(cell_text)
                        if any(row_cells):
                            table_matrix.append(row_cells)

                    if table_matrix:
                        tables.append(table_matrix)
                        md_table = cls.matrix_to_markdown_table(table_matrix)
                        markdown_blocks.append(md_table)

            full_markdown = "\n\n".join(markdown_blocks)
            return {
                "status": "success",
                "format": "docx",
                "text": "\n".join(paragraphs),
                "markdown": full_markdown,
                "paragraph_count": len(paragraphs),
                "table_count": len(tables),
                "tables": tables
            }
        except Exception as e:
            return {"status": "error", "format": "docx", "message": f"Fehler beim DOCX-Parsing: {str(e)}"}

    @classmethod
    def parse_xlsx(cls, filepath: str) -> Dict[str, Any]:
        """Parst Tabellen aus XLSX-Arbeitsmappen über xl/sharedStrings.xml & worksheets."""
        try:
            shared_strings = []
            tables_by_sheet: Dict[str, List[List[str]]] = {}
            markdown_blocks: List[str] = []

            with zipfile.ZipFile(filepath, "r") as z:
                # Shared strings laden
                if "xl/sharedStrings.xml" in z.namelist():
                    ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                    for si in ss_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                        shared_strings.append("".join(si.itertext()).strip())

                # Arbeitsblätter ermitteln
                sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
                sheets = sorted(sheets)

                for sheet_name in sheets:
                    sheet_root = ET.fromstring(z.read(sheet_name))
                    matrix: List[List[str]] = []

                    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for row in sheet_root.findall(".//s:row", ns):
                        row_cells = []
                        for c in row.findall("s:c", ns):
                            cell_type = c.attrib.get("t")
                            v_elem = c.find("s:v", ns)
                            val = ""
                            if v_elem is not None and v_elem.text:
                                val = v_elem.text
                                if cell_type == "s":
                                    idx = int(val)
                                    val = shared_strings[idx] if idx < len(shared_strings) else val
                            row_cells.append(val.strip())
                        if any(row_cells):
                            matrix.append(row_cells)

                    clean_name = os.path.basename(sheet_name).replace(".xml", "")
                    tables_by_sheet[clean_name] = matrix
                    if matrix:
                        markdown_blocks.append(f"### Arbeitsblatt: {clean_name}")
                        markdown_blocks.append(cls.matrix_to_markdown_table(matrix))

            return {
                "status": "success",
                "format": "xlsx",
                "sheet_count": len(tables_by_sheet),
                "tables_by_sheet": tables_by_sheet,
                "markdown": "\n\n".join(markdown_blocks)
            }
        except Exception as e:
            return {"status": "error", "format": "xlsx", "message": f"Fehler beim XLSX-Parsing: {str(e)}"}

    @classmethod
    def parse_csv(cls, filepath: str) -> Dict[str, Any]:
        """Parst CSV / TSV Dateien mit automatischer Delimiter-Erkennung."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                    delimiter = dialect.delimiter
                except Exception:
                    # Fallback auf Semikolon oder Komma
                    delimiter = ";" if sample.count(";") > sample.count(",") else ","

                reader = csv.reader(f, delimiter=delimiter)
                matrix = [row for row in reader if any(cell.strip() for cell in row)]

            md = cls.matrix_to_markdown_table(matrix)
            return {
                "status": "success",
                "format": "csv",
                "delimiter": delimiter,
                "row_count": len(matrix),
                "column_count": len(matrix[0]) if matrix else 0,
                "matrix": matrix,
                "markdown": md
            }
        except Exception as e:
            return {"status": "error", "format": "csv", "message": f"Fehler beim CSV-Parsing: {str(e)}"}

    @classmethod
    def parse_text_file(cls, filepath: str) -> Dict[str, Any]:
        """Parst Markdown, JSON oder Plain Text."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            lines = text.splitlines()
            headings = [l for l in lines if l.strip().startswith("#")]

            # Tabellen in Markdown aufspüren
            tables = []
            cur_table = []
            for line in lines:
                if "|" in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if parts and not all(set(p) <= {"-", ":"} for p in parts):
                        cur_table.append(parts)
                else:
                    if len(cur_table) >= 2:
                        tables.append(cur_table)
                    cur_table = []
            if len(cur_table) >= 2:
                tables.append(cur_table)

            return {
                "status": "success",
                "format": "text",
                "text": text,
                "markdown": text,
                "line_count": len(lines),
                "headings": headings,
                "tables_count": len(tables),
                "tables": tables
            }
        except Exception as e:
            return {"status": "error", "format": "text", "message": f"Fehler beim Text-Parsing: {str(e)}"}

    @classmethod
    def parse_pdf(cls, filepath: str) -> Dict[str, Any]:
        """
        Parst PDF-Dokumente.
        Nutzt pypdf / fitz / pdfplumber falls installiert, sonst internen Stream-Decoder.
        """
        # 1. Versuch: pypdf falls vorhanden
        try:
            import pypdf
            reader = pypdf.PdfReader(filepath)
            pages = []
            for i, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                pages.append(f"--- Seite {i+1} ---\n{txt}")
            full_txt = "\n\n".join(pages)
            return {
                "status": "success",
                "format": "pdf",
                "engine": "pypdf",
                "page_count": len(pages),
                "text": full_txt,
                "markdown": full_txt
            }
        except ImportError:
            pass

        # 2. Versuch: pymupdf (fitz) falls vorhanden
        try:
            import fitz
            doc = fitz.open(filepath)
            pages = []
            for i, page in enumerate(doc):
                pages.append(f"--- Seite {i+1} ---\n{page.get_text()}")
            full_txt = "\n\n".join(pages)
            return {
                "status": "success",
                "format": "pdf",
                "engine": "pymupdf",
                "page_count": len(pages),
                "text": full_txt,
                "markdown": full_txt
            }
        except ImportError:
            pass

        # 3. Native Zero-Dependency Extraktion von unkomprimierten Text-Blöcken
        try:
            with open(filepath, "rb") as f:
                data = f.read()

            extracted_chunks = []
            # PDF FlateDecode Blöcke dekomprimieren
            stream_regex = re.compile(rb'stream[\r\n]+(.*?)[\r\n]+endstream', re.DOTALL)
            for m in stream_regex.finditer(data):
                raw_chunk = m.group(1)
                decompressed = None
                try:
                    decompressed = zlib.decompress(raw_chunk)
                except Exception:
                    pass

                chunk_to_scan = decompressed if decompressed else raw_chunk
                # Suche nach Text in Klammern (Text) Tj oder [(Text)] TJ
                tj_matches = re.findall(rb'\(([^\)\\]{2,})\)\s*Tj', chunk_to_scan)
                for tm in tj_matches:
                    try:
                        decoded = tm.decode("utf-8", errors="ignore").strip()
                        if len(decoded) > 1:
                            extracted_chunks.append(decoded)
                    except Exception:
                        pass

            text = "\n".join(extracted_chunks) if extracted_chunks else "PDF enthält keine unverschlüsselten Text-Streams."
            return {
                "status": "success",
                "format": "pdf",
                "engine": "native_stream_extractor",
                "page_count": 1,
                "text": text,
                "markdown": text
            }
        except Exception as e:
            return {"status": "error", "format": "pdf", "message": f"Fehler beim PDF-Parsing: {str(e)}"}

    @classmethod
    def matrix_to_markdown_table(cls, matrix: List[List[str]]) -> str:
        """Wandelt eine 2D-Zellmatrix in eine saubere Markdown-Tabelle um."""
        if not matrix or not matrix[0]:
            return ""

        # Maximale Spaltenbreite bestimmen
        col_count = max(len(row) for row in matrix)
        normalized = []
        for row in matrix:
            padded = list(row) + [""] * (col_count - len(row))
            # Newlines in Zellen bereinigen
            cleaned = [c.replace("\n", " ").replace("\r", " ").strip() for c in padded]
            normalized.append(cleaned)

        header = normalized[0]
        divider = ["---"] * col_count

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(divider) + " |"
        ]

        for row in normalized[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)


# Globaler Singleton
document_parser = DocumentParserEngine()
