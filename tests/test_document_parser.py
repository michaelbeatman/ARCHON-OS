"""
tests/test_document_parser.py
Unit-Tests für das Dokumenten-Parsing & Tabellenextraktion (t-539b65).
"""

import os
import sys
import zipfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.document_parser import DocumentParserEngine


class TestDocumentParser(unittest.TestCase):

    def test_matrix_to_markdown_table(self):
        matrix = [
            ["Produkt", "Menge", "Preis"],
            ["Server Hosting", "1", "99,00 €"],
            ["Backup Lizenz", "2", "29,00 €"]
        ]
        md = DocumentParserEngine.matrix_to_markdown_table(matrix)
        self.assertIn("| Produkt | Menge | Preis |", md)
        self.assertIn("| --- | --- | --- |", md)
        self.assertIn("| Server Hosting | 1 | 99,00 € |", md)

    def test_parse_csv(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8") as f:
            f.write("Kunde;Umsatz;Status\nFirma A;15000;Aktiv\nFirma B;25000;Verhandlung\n")
            f_path = f.name

        try:
            res = DocumentParserEngine.parse_csv(f_path)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["delimiter"], ";")
            self.assertEqual(res["row_count"], 3)
            self.assertIn("| Firma A | 15000 | Aktiv |", res["markdown"])
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)

    def test_parse_markdown_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8") as f:
            f.write("# Projektübersicht\n\nDas ist ein Test.\n\n| Modul | Status |\n|---|---|\n| Core | OK |\n")
            f_path = f.name

        try:
            res = DocumentParserEngine.parse_file(f_path)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["format"], "text")
            self.assertIn("# Projektübersicht", res["headings"])
            self.assertGreaterEqual(res["tables_count"], 1)
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)

    def test_parse_docx_native(self):
        # Erstelle ein minimales synthetisches DOCX (ZIP mit word/document.xml)
        minimal_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Vertragsübersicht</w:t></w:r></w:p>
                <w:p><w:r><w:t>Dieser Vertrag regelt die Nutzung.</w:t></w:r></w:p>
                <w:tbl>
                    <w:tr>
                        <w:tc><w:p><w:r><w:t>Spalte 1</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>Spalte 2</w:t></w:r></w:p></w:tc>
                    </w:tr>
                    <w:tr>
                        <w:tc><w:p><w:r><w:t>Wert A</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>Wert B</w:t></w:r></w:p></w:tc>
                    </w:tr>
                </w:tbl>
            </w:body>
        </w:document>"""

        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".docx") as f:
            f_path = f.name

        try:
            with zipfile.ZipFile(f_path, "w") as z:
                z.writestr("word/document.xml", minimal_xml.encode("utf-8"))

            res = DocumentParserEngine.parse_docx(f_path)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["paragraph_count"], 2)
            self.assertEqual(res["table_count"], 1)
            self.assertIn("# Vertragsübersicht", res["markdown"])
            self.assertIn("| Spalte 1 | Spalte 2 |", res["markdown"])
            self.assertIn("| Wert A | Wert B |", res["markdown"])
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)

    def test_nonexistent_file(self):
        res = DocumentParserEngine.parse_file("does_not_exist_99.pdf")
        self.assertEqual(res["status"], "error")


if __name__ == "__main__":
    unittest.main()
