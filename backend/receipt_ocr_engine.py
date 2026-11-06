"""
backend/receipt_ocr_engine.py
Archon OS Receipt OCR & Intelligent Expense Ingestion Engine.
Processes receipt photos from Telegram or Web UI, extracts accounting metadata via Multimodal Vision,
and creates finance tasks in kanban.db and agentic_memory.db.
"""

import os
import sys
import time
import json
import base64
import sqlite3
import datetime
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))
RECEIPTS_DIR = os.path.join(DATA_DIR, "inbox", "receipts")
os.makedirs(RECEIPTS_DIR, exist_ok=True)


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


class ReceiptOCREngine:
    def __init__(self):
        self.memory_db = _resolve_db("agentic_memory.db")
        self.kanban_db = _resolve_db("kanban.db")
        self.omniroute_url = os.getenv("OMNIROUTE_URL", "http://127.0.0.1:20128/v1/chat/completions")
        self._init_receipts_table()

    def _init_receipts_table(self):
        """Initialisiert die receipts Tabelle in agentic_memory.db."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS receipts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            receipt_id TEXT UNIQUE NOT NULL,
                            source TEXT NOT NULL,
                            sender TEXT,
                            merchant TEXT,
                            receipt_date TEXT,
                            amount_gross REAL,
                            currency TEXT,
                            tax_amount REAL,
                            tax_rate_pct REAL,
                            category TEXT,
                            payment_method TEXT,
                            status TEXT DEFAULT 'pending_review',
                            image_path TEXT,
                            details_json TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    conn.commit()
            except Exception as e:
                print(f"[ReceiptOCR] DB Init Warning: {e}", file=sys.stderr)

    def extract_metadata_from_vision(self, image_bytes: bytes, filename: str = "receipt.jpg") -> Dict[str, Any]:
        """Ruft ein Vision-Modell über OmniRoute auf, um strukturierte Belegdaten zu extrahieren."""
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        
        # Bestimme Mime-Type
        mime = "image/jpeg"
        if filename.lower().endswith(".png"):
            mime = "image/png"
        elif filename.lower().endswith(".webp"):
            mime = "image/webp"

        prompt = (
            "Du bist ein präziser Buchhaltungs-Assistent für deutsche und europäische Belege/Quittungen. "
            "Analysiere dieses Bild eines Belegs/einer Rechnung und extrahiere die folgenden Felder ausschließlich als valides JSON:\n"
            "{\n"
            '  "merchant": "Name des Ausstellers/Händlers",\n'
            '  "date": "YYYY-MM-DD",\n'
            '  "amount_gross": 0.00,\n'
            '  "currency": "EUR",\n'
            '  "tax_amount": 0.00,\n'
            '  "tax_rate_pct": 19.0,\n'
            '  "category": "Bewirtung | Reisekosten | Buero | IT-Hardware | Software | Tanken | Sonstiges",\n'
            '  "payment_method": "Bar | EC-Karte | Kreditkarte | PayPal | Rechnung",\n'
            '  "line_items": [{"name": "Artikelname", "price": 0.00}],\n'
            '  "confidence": 0.95\n'
            "}\n"
            "Gib NUR das JSON zurück, ohne Markdown-Backticks oder Erklärungen."
        )

        payload = {
            "model": "auto/best-vision",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64_img}"}
                        }
                    ]
                }
            ],
            "temperature": 0.1
        }

        # 1. Versuch: OmniRoute Vision
        endpoints = [
            self.omniroute_url,
            "http://omniroute:20128/v1/chat/completions"
        ]

        for ep in endpoints:
            try:
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    ep,
                    data=data_bytes,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer internal-archon"}
                )
                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    if resp.status == 200:
                        res = json.loads(resp.read().decode("utf-8"))
                        content = res["choices"][0]["message"]["content"].strip()
                        # Bereinige Markdown Codeblocks falls vorhanden
                        if content.startswith("```"):
                            lines = content.split("\n")
                            content = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
                        return json.loads(content)
            except Exception as e:
                # print(f"[ReceiptOCR] Vision call failed on {ep}: {e}", file=sys.stderr)
                continue

        # Fallback Heuristik, falls kein LLM erreichbar
        return {
            "merchant": "Unbekannter Händler",
            "date": datetime.date.today().isoformat(),
            "amount_gross": 0.0,
            "currency": "EUR",
            "tax_amount": 0.0,
            "tax_rate_pct": 19.0,
            "category": "Sonstiges",
            "payment_method": "Unbekannt",
            "line_items": [],
            "confidence": 0.3,
            "note": "Automatische Vision-Extraktion nicht verfügbar, manuell erfassen."
        }

    def process_receipt(
        self,
        image_bytes: bytes,
        filename: str = "receipt.jpg",
        source: str = "telegram",
        sender: str = "User",
        create_kanban_task: bool = True
    ) -> Dict[str, Any]:
        """Verarbeitet einen Beleg vollständig: Bild speichern, Metadaten extrahieren, in DB & Kanban ablegen."""
        receipt_id = f"rcpt_{int(time.time())}_{os.urandom(3).hex()}"
        save_name = f"{receipt_id}_{filename}"
        img_path = os.path.join(RECEIPTS_DIR, save_name)

        # 1. Bild persistent abspeichern
        with open(img_path, "wb") as fh:
            fh.write(image_bytes)

        # 2. Vision OCR Extraktion
        meta = self.extract_metadata_from_vision(image_bytes, filename=filename)

        merchant = meta.get("merchant") or "Unbekannter Händler"
        receipt_date = meta.get("date") or datetime.date.today().isoformat()
        amount_gross = float(meta.get("amount_gross") or 0.0)
        currency = meta.get("currency") or "EUR"
        tax_amount = float(meta.get("tax_amount") or 0.0)
        tax_rate_pct = float(meta.get("tax_rate_pct") or 19.0)
        category = meta.get("category") or "Sonstiges"
        payment_method = meta.get("payment_method") or "Unbekannt"

        # 3. In SQLite registrieren
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                    conn.execute("""
                        INSERT INTO receipts (
                            receipt_id, source, sender, merchant, receipt_date,
                            amount_gross, currency, tax_amount, tax_rate_pct,
                            category, payment_method, image_path, details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        receipt_id, source, sender, merchant, receipt_date,
                        amount_gross, currency, tax_amount, tax_rate_pct,
                        category, payment_method, img_path, json.dumps(meta, ensure_ascii=False)
                    ))
                    conn.commit()
            except Exception as e:
                print(f"[ReceiptOCR] Error saving receipt to SQLite: {e}", file=sys.stderr)

        # 4. Optional Kanban-Task erstellen (Team Finanzen)
        task_id = None
        if create_kanban_task and os.path.exists(self.kanban_db):
            try:
                task_id = f"task-{receipt_id}"
                title = f"[Beleg] {merchant}: {amount_gross:.2f} {currency} ({category})"
                body = (
                    f"Eingereichter Beleg via {source} von {sender}.\n\n"
                    f"- Datum: {receipt_date}\n"
                    f"- Betrag Brutto: {amount_gross:.2f} {currency}\n"
                    f"- MwSt: {tax_amount:.2f} {currency} ({tax_rate_pct}%)\n"
                    f"- Kategorie: {category}\n"
                    f"- Zahlungsmethode: {payment_method}\n"
                    f"- Belegdatei: {img_path}\n"
                )
                with sqlite3.connect(self.kanban_db, timeout=5.0) as conn:
                    conn.execute("""
                        INSERT INTO tasks (
                            id, title, body, assignee, status, priority, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        task_id, title, body, "finance_lead", "ready", 2, "receipt_ocr_engine",
                        datetime.datetime.now().isoformat()
                    ))
                    conn.commit()
            except Exception as e:
                print(f"[ReceiptOCR] Error creating Kanban task: {e}", file=sys.stderr)

        # 5. Metadaten JSON neben dem Bild ablegen
        meta_json_path = os.path.join(RECEIPTS_DIR, f"{receipt_id}.json")
        result = {
            "receipt_id": receipt_id,
            "status": "success",
            "merchant": merchant,
            "date": receipt_date,
            "amount_gross": amount_gross,
            "currency": currency,
            "tax_amount": tax_amount,
            "tax_rate_pct": tax_rate_pct,
            "category": category,
            "payment_method": payment_method,
            "image_path": img_path,
            "metadata_path": meta_json_path,
            "kanban_task_id": task_id,
            "metadata": meta
        }

        try:
            with open(meta_json_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return result

    def list_receipts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Listet archivierte Belege auf."""
        if not os.path.exists(self.memory_db):
            return []
        try:
            with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT receipt_id, source, sender, merchant, receipt_date,
                           amount_gross, currency, tax_amount, tax_rate_pct, category, payment_method,
                           status, image_path, created_at
                    FROM receipts
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[ReceiptOCR] Error querying receipts: {e}", file=sys.stderr)
            return []

    def get_receipt(self, receipt_id: str) -> Optional[Dict[str, Any]]:
        """Gibt einen einzelnen Beleg zurück."""
        if not os.path.exists(self.memory_db):
            return None
        try:
            with sqlite3.connect(f"file:{self.memory_db}?mode=ro", uri=True, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def update_receipt(self, receipt_id: str, updates: Dict[str, Any]) -> bool:
        """Aktualisiert Belegdaten (Status, Kategorie, Betrag)."""
        if not os.path.exists(self.memory_db):
            return False
        allowed = {"status", "category", "merchant", "amount_gross", "tax_amount", "payment_method"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [receipt_id]
        try:
            with sqlite3.connect(self.memory_db, timeout=5.0) as conn:
                conn.execute(f"UPDATE receipts SET {set_clause} WHERE receipt_id = ?", values)
                conn.commit()
            return True
        except Exception as e:
            print(f"[ReceiptOCR] Update error: {e}", file=sys.stderr)
            return False


receipt_ocr_engine = ReceiptOCREngine()
