"""
Corporate Manager & Multi-Company Hub for Archon OS
Provides master data storage, Corporate Design profiles, and
legal/correspondence templates (DIN 5008, § 14 UStG Invoices, NDAs, Offers).
"""

import html
import os
import json
import re
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PROFILES_FILE = os.path.join(DATA_DIR, "corporate_profiles.json")

# F-03: EIN Lock fuer alle Load-Aendern-Speichern-Sequenzen (RMW). Vorher
# schrieben parallele Aufrufer direkt ueber die Zieldatei — ein Abbruch
# mitten im write hinterliess eine kaputte/leere Datei, und der naechste
# save_company() legte nur noch die Default-Firma an (alle uebrigen weg).
_DATA_LOCK = threading.RLock()

DEFAULT_PRIMARY_COMPANY = {
    "id": "archon-systems",
    "name": "Archon Systems GmbH",
    "legal_form": "GmbH",
    "slogan": "Autonomous Agentic Operating System & Enterprise Intelligence",
    "address": {
        "street": "Friedrichstraße 123",
        "postal_code": "10117",
        "city": "Berlin",
        "country": "Deutschland"
    },
    "contact": {
        "phone": "+49 30 98765432",
        "email": "info@archon-systems.de",
        "website": "https://archon-systems.de"
    },
    "registry": {
        "court": "Amtsgericht Charlottenburg",
        "number": "HRB 248910 B",
        "managing_directors": "Michael & Team"
    },
    "tax": {
        "tax_number": "30/215/12345",
        "vat_id": "DE345678901",
        "small_business": False
    },
    "bank": {
        "bank_name": "Deutsche Bank Berlin",
        "iban": "DE89 1007 0000 0123 4567 89",
        "bic": "DEUTDEDDBER"
    },
    "design": {
        "primary_color": "#4f46e5",
        "secondary_color": "#06b6d4",
        "accent_color": "#10b981",
        "logo_url": "/static/img/archon-logo.png",
        "font_family": "Inter, system-ui, sans-serif"
    },
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-10-31T18:00:00Z"
}


DEFAULT_TEMPLATE_LAYOUT: Dict[str, Any] = {
    "margin_mm": 15,
    "footer_columns": 3,
    "show_logo": True,
    "show_girocode": True,
    "show_fold_marks": True,
    "show_bank_footer": True,
    "header_style": "bar",
    "font_family": "",
    "intro_text": "",
    "outro_text": "",
    "dunning_level": 1,
    "dunning_fee": 0.0,
    "dunning_interest_pct": 0.0,
}

_SAFE_LOGO_URL_RE = re.compile(r"^(?:/[A-Za-z0-9_./%-]+|https?://[^\s\"'<>]+|data:image/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=]+)$")
_PLACEHOLDER_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _esc(val: Any) -> str:
    """Idempotentes HTML-Escaping (verhindert XSS ohne Doppel-Encoding)."""
    return html.escape(html.unescape(str(val if val is not None else "")), quote=True)


def _normalize_template_type(template_type: str) -> str:
    t = str(template_type or "letterhead").strip().lower()
    if t in ("offer", "ang", "angebot"):
        return "offer"
    if t in ("order_confirmation", "order", "ab", "auftrag"):
        return "order_confirmation"
    if t in ("dunning", "mahnung", "reminder"):
        return "dunning"
    if t in ("invoice", "re", "rechnung"):
        return "invoice"
    if t in ("nda", "contract", "vertrag"):
        return "nda"
    if t in ("letter", "letterhead", "brief"):
        return "letterhead"
    return t


def _normalize_layout(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_TEMPLATE_LAYOUT)
    try:
        out["margin_mm"] = max(8, min(30, int(src.get("margin_mm", out["margin_mm"]))))
    except (TypeError, ValueError):
        pass
    try:
        cols = int(src.get("footer_columns", out["footer_columns"]))
        out["footer_columns"] = 2 if cols == 2 else 3
    except (TypeError, ValueError):
        pass
    for bkey in ("show_logo", "show_girocode", "show_fold_marks", "show_bank_footer"):
        if bkey in src:
            out[bkey] = bool(src[bkey])
    hstyle = str(src.get("header_style") or out["header_style"]).strip().lower()
    out["header_style"] = hstyle if hstyle in ("bar", "minimal") else "bar"
    out["font_family"] = str(src.get("font_family") or "").strip()[:120]
    out["intro_text"] = str(src.get("intro_text") or "")[:4000]
    out["outro_text"] = str(src.get("outro_text") or "")[:4000]
    try:
        out["dunning_level"] = max(1, min(3, int(src.get("dunning_level", 1))))
    except (TypeError, ValueError):
        out["dunning_level"] = 1
    try:
        out["dunning_fee"] = round(max(0.0, float(src.get("dunning_fee") or 0.0)), 2)
    except (TypeError, ValueError):
        out["dunning_fee"] = 0.0
    try:
        out["dunning_interest_pct"] = round(max(0.0, float(src.get("dunning_interest_pct") or 0.0)), 2)
    except (TypeError, ValueError):
        out["dunning_interest_pct"] = 0.0
    return out


class CorporateManager:
    def __init__(self, filepath: str = PROFILES_FILE):
        self.filepath = filepath
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            initial_data = {
                "active_company_id": "archon-systems",
                "companies": [DEFAULT_PRIMARY_COMPANY]
            }
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)

    def _load_data(self) -> Dict[str, Any]:
        self._ensure_storage()
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "active_company_id": "archon-systems",
                "companies": [DEFAULT_PRIMARY_COMPANY]
            }

    def _save_data(self, data: Dict[str, Any]):
        # F-03: atomar (Temp-Datei im selben Verzeichnis + fsync + os.replace),
        # damit ein Abbruch nie eine Halbdatei/kaputte Firmenliste hinterlaesst.
        with _DATA_LOCK:
            target = self.filepath
            d = os.path.dirname(os.path.abspath(target)) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".corporate_profiles_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def list_companies(self) -> List[Dict[str, Any]]:
        data = self._load_data()
        active_id = data.get("active_company_id", "")
        result = []
        for c in data.get("companies", []):
            result.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "entity_type": c.get("entity_type", "operative_gmbh"),
                "legal_form": c.get("legal_form", ""),
                "city": c.get("address", {}).get("city", ""),
                "vat_id": c.get("tax", {}).get("vat_id", ""),
                "primary_color": c.get("design", {}).get("primary_color", "#4f46e5"),
                "is_active": c.get("id") == active_id,
                "updated_at": c.get("updated_at", "")
            })
        return result

    def get_company(self, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        data = self._load_data()
        target_id = company_id or data.get("active_company_id")
        for c in data.get("companies", []):
            if c.get("id") == target_id:
                res = dict(c)
                res["is_active"] = (c.get("id") == data.get("active_company_id"))
                return res
        # R-21: Eine EXPLIZIT angefragte, unbekannte company_id darf NICHT still
        # auf eine andere Rechtsperson (companies[0]) ausweichen — sonst druckt
        # ein vertipptes/deaktiviertes Firmenprofil die falschen Stammdaten
        # (Steuernummer, IBAN) auf Rechnung/Angebot. Nur die Aufloesung ohne
        # company_id (aktive Firma) darf auf den ersten Eintrag zurueckfallen.
        if not company_id and data.get("companies"):
            res = dict(data["companies"][0])
            res["is_active"] = res.get("id") == data.get("active_company_id")
            return res
        return None

    def set_active_company(self, company_id: str) -> bool:
        with _DATA_LOCK:
            data = self._load_data()
            for c in data.get("companies", []):
                if c.get("id") == company_id:
                    data["active_company_id"] = company_id
                    self._save_data(data)
                    return True
        return False

    def save_company(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with _DATA_LOCK:
            data = self._load_data()
            company_id = payload.get("id") or str(uuid.uuid4())[:8]
            now_iso = datetime.utcnow().isoformat() + "Z"

            existing_idx = None
            existing_layouts: Dict[str, Any] = {}
            for i, c in enumerate(data.get("companies", [])):
                if c.get("id") == company_id:
                    existing_idx = i
                    if isinstance(c.get("template_layouts"), dict):
                        existing_layouts = dict(c["template_layouts"])
                    break

            incoming_layouts = payload.get("template_layouts")
            merged_layouts = existing_layouts
            if isinstance(incoming_layouts, dict):
                merged_layouts = {k: _normalize_layout(v) for k, v in incoming_layouts.items()}

            company_record = {
                "id": company_id,
                "name": payload.get("name", "Neues Unternehmen"),
                "entity_type": payload.get("entity_type", "operative_gmbh"),
                "legal_form": payload.get("legal_form", ""),
                "slogan": payload.get("slogan", ""),
                "address": {
                    "street": payload.get("address", {}).get("street", ""),
                    "postal_code": payload.get("address", {}).get("postal_code", ""),
                    "city": payload.get("address", {}).get("city", ""),
                    "country": payload.get("address", {}).get("country", "Deutschland")
                },
                "contact": {
                    "phone": payload.get("contact", {}).get("phone", ""),
                    "email": payload.get("contact", {}).get("email", ""),
                    "website": payload.get("contact", {}).get("website", "")
                },
                "registry": {
                    "court": payload.get("registry", {}).get("court", ""),
                    "number": payload.get("registry", {}).get("number", ""),
                    "managing_directors": payload.get("registry", {}).get("managing_directors", "")
                },
                "tax": {
                    "tax_number": payload.get("tax", {}).get("tax_number", ""),
                    "vat_id": payload.get("tax", {}).get("vat_id", ""),
                    "small_business": bool(payload.get("tax", {}).get("small_business", False))
                },
                "bank": {
                    "bank_name": payload.get("bank", {}).get("bank_name", ""),
                    "iban": payload.get("bank", {}).get("iban", ""),
                    "bic": payload.get("bank", {}).get("bic", "")
                },
                "design": {
                    "primary_color": payload.get("design", {}).get("primary_color", "#4f46e5"),
                    "secondary_color": payload.get("design", {}).get("secondary_color", "#06b6d4"),
                    "accent_color": payload.get("design", {}).get("accent_color", "#10b981"),
                    "logo_url": payload.get("design", {}).get("logo_url", ""),
                    "font_family": payload.get("design", {}).get("font_family", "Inter, system-ui, sans-serif")
                },
                "template_layouts": merged_layouts,
                "created_at": payload.get("created_at") or now_iso,
                "updated_at": now_iso
            }

            if existing_idx is not None:
                data["companies"][existing_idx] = company_record
            else:
                data.setdefault("companies", []).append(company_record)

            if not data.get("active_company_id") or len(data["companies"]) == 1:
                data["active_company_id"] = company_id

            self._save_data(data)
            return company_record

    def delete_company(self, company_id: str) -> bool:
        with _DATA_LOCK:
            data = self._load_data()
            companies = data.get("companies", [])
            if len(companies) <= 1:
                return False  # Mindestens ein Unternehmen muss verbleiben

            filtered = [c for c in companies if c.get("id") != company_id]
            if len(filtered) == len(companies):
                return False

            data["companies"] = filtered
            if data.get("active_company_id") == company_id:
                data["active_company_id"] = filtered[0]["id"]

            self._save_data(data)
            return True

    def get_template_layout(self, company_id: Optional[str], template_type: str) -> Dict[str, Any]:
        """Liefert die gespeicherte Formular-/Layout-Konfiguration für eine Vorlage."""
        norm_type = _normalize_template_type(template_type)
        company = self.get_company(company_id)
        if not company:
            if company_id:
                raise ValueError(f"Unbekannte Company-ID: {company_id}")
            company = DEFAULT_PRIMARY_COMPANY
        layouts = company.get("template_layouts") if isinstance(company.get("template_layouts"), dict) else {}
        return _normalize_layout(layouts.get(norm_type))

    def save_template_layout(
        self,
        company_id: Optional[str],
        template_type: str,
        layout: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Speichert Layout- & Textblock-Voreinstellungen pro Mandant & Belegtyp (M29)."""
        norm_type = _normalize_template_type(template_type)
        clean_layout = _normalize_layout(layout)
        with _DATA_LOCK:
            data = self._load_data()
            target_id = company_id or data.get("active_company_id")
            companies = data.get("companies", [])
            matched = None
            for c in companies:
                if c.get("id") == target_id:
                    matched = c
                    break
            if matched is None and not company_id and companies:
                matched = companies[0]
            if matched is None:
                raise ValueError(f"Unbekannte Company-ID: {company_id}")
            layouts = matched.get("template_layouts")
            if not isinstance(layouts, dict):
                layouts = {}
            layouts[norm_type] = clean_layout
            matched["template_layouts"] = layouts
            matched["updated_at"] = datetime.utcnow().isoformat() + "Z"
            self._save_data(data)
        return clean_layout

    @staticmethod
    def validate_ustg_compliance(
        company: Dict[str, Any],
        template_type: str,
        custom: Dict[str, Any],
        net_total: float,
        gross_total: float,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Prüft § 14 Abs. 4 UStG / HGB Pflichtangaben am aktuellen Beleg (M29 Live-Check)."""
        norm_type = _normalize_template_type(template_type)
        addr = company.get("address") if isinstance(company.get("address"), dict) else {}
        tax = company.get("tax") if isinstance(company.get("tax"), dict) else {}
        bank = company.get("bank") if isinstance(company.get("bank"), dict) else {}

        has_supplier = bool(
            str(company.get("name") or "").strip()
            and str(addr.get("street") or "").strip()
            and str(addr.get("city") or "").strip()
        )
        has_recipient = bool(
            str(custom.get("recipient_name") or "").strip()
            and str(custom.get("recipient_street") or "").strip()
            and str(custom.get("recipient_city") or "").strip()
        )
        has_tax_id = bool(str(tax.get("vat_id") or "").strip() or str(tax.get("tax_number") or "").strip())
        has_issue_date = bool(str(custom.get("issue_date") or datetime.now().strftime("%d.%m.%Y")).strip())

        if norm_type == "invoice":
            doc_num = str(custom.get("invoice_num") or "").strip()
        elif norm_type == "offer":
            doc_num = str(custom.get("offer_num") or "").strip()
        elif norm_type == "order_confirmation":
            doc_num = str(custom.get("order_num") or "").strip()
        elif norm_type == "dunning":
            doc_num = str(custom.get("dunning_num") or custom.get("invoice_num") or "").strip()
        else:
            doc_num = str(custom.get("ref_code") or "OK").strip()

        has_doc_num = bool(doc_num)
        has_items = len(items) > 0 and all(bool(str(i.get("desc") or "").strip()) and float(i.get("qty") or 0) > 0 for i in items)
        has_supply_date = bool(str(custom.get("supply_date") or custom.get("service_date") or custom.get("issue_date") or "").strip())
        iban_clean = re.sub(r"\s+", "", str(bank.get("iban") or ""))
        has_iban = len(iban_clean) >= 15
        is_small_amount = norm_type == "invoice" and 0.0 < gross_total <= 250.0

        checks: List[Dict[str, Any]] = [
            {
                "id": "supplier_identity",
                "law": "§ 14 Abs. 4 Nr. 1 UStG",
                "label": "Name & Anschrift des Leistenden",
                "ok": has_supplier,
                "severity": "error" if not has_supplier else "ok",
                "detail": "Vollständige Firmenanschrift vorhanden." if has_supplier else "Firmenname, Straße oder Ort fehlt im Firmenstamm.",
            },
            {
                "id": "recipient_identity",
                "law": "§ 14 Abs. 4 Nr. 1 UStG",
                "label": "Name & Anschrift des Empfängers",
                "ok": has_recipient or is_small_amount,
                "severity": "ok" if (has_recipient or is_small_amount) else "error",
                "detail": (
                    "Kleinstbetragsrechnung <= 250 € (§ 33 UStDV)."
                    if (is_small_amount and not has_recipient)
                    else ("Empfängeranschrift vollständig." if has_recipient else "Empfängername, Straße oder PLZ/Ort fehlt.")
                ),
            },
            {
                "id": "tax_identifier",
                "law": "§ 14 Abs. 4 Nr. 2 UStG",
                "label": "Steuernummer oder USt-IdNr.",
                "ok": has_tax_id,
                "severity": "ok" if has_tax_id else "error",
                "detail": "Steuerliche ID ausgewiesen." if has_tax_id else "Weder Steuernummer noch USt-IdNr. hinterlegt.",
            },
            {
                "id": "issue_date",
                "law": "§ 14 Abs. 4 Nr. 3 UStG",
                "label": "Ausstellungsdatum",
                "ok": has_issue_date,
                "severity": "ok" if has_issue_date else "error",
                "detail": "Ausstellungsdatum gesetzt.",
            },
        ]

        if norm_type in ("invoice", "offer", "order_confirmation", "dunning"):
            checks.extend([
                {
                    "id": "sequential_number",
                    "law": "§ 14 Abs. 4 Nr. 4 UStG",
                    "label": "Fortlaufende Belegnummer",
                    "ok": has_doc_num,
                    "severity": "ok" if has_doc_num else "error",
                    "detail": f"Belegnummer {doc_num} vorhanden." if has_doc_num else "Belegnummer fehlt.",
                },
                {
                    "id": "line_items",
                    "law": "§ 14 Abs. 4 Nr. 5 UStG",
                    "label": "Menge & Art der Leistung",
                    "ok": has_items,
                    "severity": "ok" if has_items else "error",
                    "detail": f"{len(items)} Position(en) mit Menge & Bezeichnung." if has_items else "Mindestens eine Leistungsposition erforderlich.",
                },
                {
                    "id": "supply_date",
                    "law": "§ 14 Abs. 4 Nr. 6 UStG",
                    "label": "Leistungs-/Lieferzeitpunkt",
                    "ok": has_supply_date,
                    "severity": "ok" if has_supply_date else "warn",
                    "detail": "Leistungsdatum angegeben.",
                },
                {
                    "id": "bank_girocode",
                    "law": "SEPA / EPC069-12",
                    "label": "IBAN für Überweisung & GiroCode",
                    "ok": has_iban,
                    "severity": "ok" if has_iban else "warn",
                    "detail": "Gültige IBAN für Überweisung/GiroCode vorhanden." if has_iban else "IBAN unvollständig — kein GiroCode generierbar.",
                },
            ])

        passed = sum(1 for c in checks if c["ok"])
        total = max(1, len(checks))
        errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
        return {
            "template_type": norm_type,
            "valid": len(errors) == 0,
            "score_pct": int(round((passed / total) * 100)),
            "passed_count": passed,
            "total_count": total,
            "small_amount_rule": is_small_amount,
            "checks": checks,
        }

    def render_template(
        self,
        template_type: str,
        company_id: Optional[str] = None,
        custom: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Renders DIN 5008 letterhead, § 14 UStG invoice, NDA, or offer.
        Returns HTML snippet and metadata.
        """
        company = self.get_company(company_id)
        if not company:
            # R-21: unbekannte, explizit angefragte company_id -> Fehler statt
            # stillem Ausweichen auf eine andere Rechtsperson (falsche USt/IBAN).
            if company_id:
                raise ValueError(f"Unbekannte Company-ID: {company_id}")
            company = DEFAULT_PRIMARY_COMPANY

        custom = dict(custom or {})
        active_cid = company.get("id") or "archon-systems"

        # Falls entity_id oder document_id aus dem ERP übergeben wurde -> Live-Stammdaten auflösen
        if custom.get("entity_id") or custom.get("document_id"):
            try:
                from backend.erp_manager import erp_manager
                if custom.get("document_id"):
                    doc = erp_manager.get_document(custom["document_id"], company_id=active_cid)
                    if doc:
                        snap = doc.get("recipient_snapshot") or {}
                        custom.setdefault("recipient_name", snap.get("display_name") or doc.get("entity_name") or "")
                        if snap.get("contact_name"):
                            custom.setdefault("recipient_contact", snap["contact_name"])
                        if snap.get("street"):
                            custom.setdefault("recipient_street", snap["street"])
                        if snap.get("postal_code") or snap.get("city"):
                            custom.setdefault("recipient_city", f"{snap.get('postal_code', '')} {snap.get('city', '')}".strip())
                        custom.setdefault("invoice_num", doc.get("doc_number"))
                        custom.setdefault("offer_num", doc.get("doc_number"))
                        custom.setdefault("order_num", doc.get("doc_number"))
                        if doc.get("doc_type") in ("offer", "ang") and template_type in ("letterhead", "default"):
                            template_type = "offer"
                        elif doc.get("doc_type") in ("order", "order_confirmation", "ab") and template_type in ("letterhead", "default"):
                            template_type = "order_confirmation"
                        elif doc.get("doc_type") == "invoice" and template_type in ("letterhead", "default"):
                            template_type = "invoice"
                        if doc.get("lines"):
                            custom["items"] = [
                                {
                                    "pos": ln.get("pos_no", idx + 1),
                                    "desc": ln.get("title", ""),
                                    "qty": ln.get("quantity", 1),
                                    "unit": ln.get("unit", "Stk."),
                                    "price": ln.get("unit_price_net", 0.0),
                                    # R-23: Zeilensteuersatz und -rabatt aus dem
                                    # ERP-Beleg mitschleppen, sonst rechnet das
                                    # Template fest mit 19 % ohne Rabatt.
                                    "discount_pct": ln.get("discount_pct", 0.0),
                                    "tax_rate_pct": ln.get("tax_rate_pct", 19.0)
                                }
                                for idx, ln in enumerate(doc["lines"])
                            ]
                elif custom.get("entity_id"):
                    detail = erp_manager.get_entity_detail(custom["entity_id"], company_id=active_cid)
                    if detail and detail.get("entity"):
                        ent = detail["entity"]
                        contacts = detail.get("contacts") or []
                        prim = contacts[0] if contacts else {}
                        custom["recipient_name"] = ent.get("display_name", "Musterempfänger GmbH")
                        if prim.get("full_name"):
                            sal = prim.get("salutation", "")
                            custom["recipient_contact"] = f"{sal} {prim['full_name']}".strip()
                        if ent.get("street"):
                            custom["recipient_street"] = ent["street"]
                        if ent.get("postal_code") or ent.get("city"):
                            custom["recipient_city"] = f"{ent.get('postal_code', '')} {ent.get('city', '')}".strip()
            except Exception:
                pass

        today_de = datetime.now().strftime("%d.%m.%Y")
        due_date_de = custom.get("due_date") or datetime.now().strftime("%d.%m.%Y")
        
        # Basis-Stammdaten
        c_name = company.get("name", "Unternehmen")
        c_legal = company.get("legal_form", "")
        c_slogan = company.get("slogan", "")
        addr = company.get("address", {})
        c_street = addr.get("street", "")
        c_zip = addr.get("postal_code", "")
        c_city = addr.get("city", "")
        c_country = addr.get("country", "Deutschland")
        
        cont = company.get("contact", {})
        c_phone = cont.get("phone", "")
        c_email = cont.get("email", "")
        c_web = cont.get("website", "")

        reg = company.get("registry", {})
        c_court = reg.get("court", "")
        c_hrb = reg.get("number", "")
        c_directors = reg.get("managing_directors", "")

        tax = company.get("tax", {})
        c_taxnum = tax.get("tax_number", "")
        c_vatid = tax.get("vat_id", "")
        is_small = tax.get("small_business", False)

        # R-23: Positionen mit eigenem Steuersatz (z. B. 7 %) und Rabatt rechnen.
        # Vorher: fest `0.0 if is_small else 0.19` und Summen aus qty*price —
        # ein ERP-Beleg mit 7-%-Position druckte 19 % USt und einen hoheren
        # Bruttobetrag als gespeichert (§14-UStG-Verstoß).
        def _line_net(item):
            qty = float(item.get("qty", 1) or 1)
            price = float(item.get("price", 0) or 0)
            disc = float(item.get("discount_pct", 0) or 0)
            return round(max(0.0, qty * price * (1.0 - disc / 100.0)), 2)

        def _line_tax_rate(item):
            if is_small:
                return 0.0
            raw = item.get("tax_rate_pct")
            if raw is None or raw == "":
                return 0.19
            return float(raw) / 100.0

        def _tax_buckets(items):
            buckets: Dict[float, float] = {}
            for item in items:
                r = _line_tax_rate(item)
                buckets[r] = round(buckets.get(r, 0.0) + _line_net(item) * r, 2)
            return buckets

        def _tax_rows_html(buckets, small_note):
            if is_small:
                return small_note
            return "\n".join(
                f"""
                <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                  <span>Umsatzsteuer ({int(round(r * 100))}%):</span>
                  <span style="font-weight: 600;">{t:,.2f} €</span>
                </div>
                """ for r, t in sorted(buckets.items(), reverse=True)
            )

        bank = company.get("bank", {})
        c_bankname = bank.get("bank_name", "")
        c_iban = bank.get("iban", "")
        c_bic = bank.get("bic", "")

        des = company.get("design", {})
        c_primary = des.get("primary_color", "#4f46e5")
        c_secondary = des.get("secondary_color", "#06b6d4")

        saved_layouts = company.get("template_layouts") if isinstance(company.get("template_layouts"), dict) else {}
        norm_type = _normalize_template_type(template_type)
        merged_layout_raw = dict(saved_layouts.get(norm_type) or {})
        if isinstance(custom.get("layout"), dict):
            merged_layout_raw.update(custom["layout"])
        for k in DEFAULT_TEMPLATE_LAYOUT:
            if k in custom and custom[k] not in (None, ""):
                merged_layout_raw[k] = custom[k]
        layout = _normalize_layout(merged_layout_raw)

        c_font = layout["font_family"] or des.get("font_family", "Inter, sans-serif")
        c_logo = str(custom.get("logo_url") or des.get("logo_url", "") or "").strip()
        margin_mm = layout["margin_mm"]
        pad_px = max(24, min(68, int(round(margin_mm * 2.8))))

        recipient_name = _esc(custom.get("recipient_name", "Musterempfänger GmbH"))
        recipient_contact = _esc(custom.get("recipient_contact", "Herrn Max Mustermann"))
        recipient_street = _esc(custom.get("recipient_street", "Musterweg 42"))
        recipient_city = _esc(custom.get("recipient_city", "10115 Berlin"))

        raw_subject = str(custom.get("subject", "Geschäftliche Mitteilung") or "")
        raw_body_text = str(
            custom.get(
                "body_text",
                "Sehr geehrte Damen und Herren,\n\nvielen Dank für die angenehme Zusammenarbeit...",
            )
            or ""
        )

        # Vorab Dokumentnummer & Positionen berechnen, damit {{doc.*}} & § 14 UStG Live-Check sie nutzen können
        items: List[Dict[str, Any]] = []
        net_total = 0.0
        tax_buckets: Dict[float, float] = {}
        tax_amount = 0.0
        gross_total = 0.0
        doc_number = _esc(custom.get("ref_code", "AS-2026/01"))

        if norm_type == "invoice":
            doc_number = _esc(custom.get("invoice_num", f"RE-{datetime.now().strftime('%Y%m')}-001"))
            items = custom.get("items") or [
                {"pos": 1, "desc": "Archon OS Enterprise Subscription (Monatlich)", "qty": 1, "unit": "Monat", "price": 490.00},
                {"pos": 2, "desc": "Dedizierter Agenten-Cluster & Setup", "qty": 1, "unit": "Pauschal", "price": 1250.00},
            ]
        elif norm_type == "offer":
            doc_number = _esc(custom.get("offer_num", f"ANG-{datetime.now().strftime('%Y%m')}-001"))
            items = custom.get("items") or [
                {"pos": 1, "desc": "Archon OS Enterprise Lizenz & KI-Agenten Setup", "qty": 1, "unit": "Pauschal", "price": 4500.00},
                {"pos": 2, "desc": "Architektur-Consulting & Anbindung Primärsysteme", "qty": 16, "unit": "Std.", "price": 180.00},
            ]
        elif norm_type == "order_confirmation":
            doc_number = _esc(custom.get("order_num", f"AB-{datetime.now().strftime('%Y%m')}-001"))
            items = custom.get("items") or [
                {"pos": 1, "desc": "Archon OS Enterprise Subscription (Q4-2026)", "qty": 1, "unit": "Monat", "price": 490.00},
                {"pos": 2, "desc": "Autonome Agenten-Workflows & Tool-Integration", "qty": 40, "unit": "Std.", "price": 180.00},
            ]
        elif norm_type == "dunning":
            doc_number = _esc(custom.get("dunning_num") or custom.get("invoice_num") or f"MAHN-{datetime.now().strftime('%Y%m')}-001")
            orig_amt = float(custom.get("open_amount") or custom.get("amount_gross") or 1740.00)
            fee = float(layout["dunning_fee"]) if layout["dunning_level"] >= 2 else 0.0
            items = custom.get("items") or [
                {"pos": 1, "desc": f"Offene Forderung aus Rechnung {custom.get('invoice_num') or doc_number}", "qty": 1, "unit": "Beleg", "price": round(orig_amt, 2), "tax_rate_pct": 0.0},
                *([{"pos": 2, "desc": f"Mahngebühr (Mahnstufe {layout['dunning_level']})", "qty": 1, "unit": "Pauschal", "price": fee, "tax_rate_pct": 0.0}] if fee > 0 else []),
            ]

        if items:
            net_total = round(sum(_line_net(i) for i in items), 2)
            tax_buckets = _tax_buckets(items)
            tax_amount = round(sum(tax_buckets.values()), 2)
            gross_total = round(net_total + tax_amount, 2)

        placeholder_map: Dict[str, str] = {
            "company.name": _esc(c_name),
            "company.street": _esc(c_street),
            "company.city": f"{_esc(c_zip)} {_esc(c_city)}".strip(),
            "company.vat_id": _esc(c_vatid),
            "company.tax_number": _esc(c_taxnum),
            "company.iban": _esc(c_iban),
            "company.bic": _esc(c_bic),
            "company.managing_directors": _esc(c_directors),
            "customer.name": recipient_name,
            "customer.contact": recipient_contact,
            "customer.street": recipient_street,
            "customer.city": recipient_city,
            "doc.number": doc_number,
            "doc.date": _esc(custom.get("issue_date") or today_de),
            "doc.due_date": _esc(due_date_de),
            "doc.net_total": f"{net_total:,.2f} €",
            "doc.gross_total": f"{gross_total:,.2f} €",
            "doc.subject": _esc(raw_subject),
        }

        def _subst(raw_text: str, extra_table: str = "") -> str:
            escaped = _esc(raw_text)
            def _repl(m: re.Match) -> str:
                key = m.group(1)
                if key == "invoice.items_table":
                    return extra_table
                return placeholder_map.get(key, m.group(0))
            return _PLACEHOLDER_TOKEN_RE.sub(_repl, escaped)

        def _render_logo_html() -> str:
            if not layout["show_logo"] or not c_logo or not _SAFE_LOGO_URL_RE.match(c_logo):
                return ""
            safe_src = _esc(c_logo)
            return f'<img src="{safe_src}" alt="{_esc(c_name)} Logo" style="max-height: 44px; max-width: 140px; object-fit: contain; margin-bottom: 6px; display: block;">'

        def _render_fold_marks_html() -> str:
            if not layout["show_fold_marks"]:
                return ""
            return (
                '<div aria-hidden="true" style="position:absolute; left:0; top:105mm; width:5mm; border-top:1px solid #cbd5e1;"></div>'
                '<div aria-hidden="true" style="position:absolute; left:0; top:148.5mm; width:7mm; border-top:1px solid #94a3b8;"></div>'
                '<div aria-hidden="true" style="position:absolute; left:0; top:210mm; width:5mm; border-top:1px solid #cbd5e1;"></div>'
            )

        def _render_header_html(right_lines: List[str]) -> str:
            border_css = f"2px solid {_esc(c_primary)}" if layout["header_style"] == "bar" else "1px solid #cbd5e1"
            logo_block = _render_logo_html()
            right_html = "".join(f"<div>{ln}</div>" for ln in right_lines)
            return f"""
                <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: {border_css}; padding-bottom: 18px; margin-bottom: 24px;">
                  <div>
                    {logo_block}
                    <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: {_esc(c_primary)}; letter-spacing: -0.02em;">{_esc(c_name)}</h1>
                    <div style="font-size: 11px; color: #64748b; font-weight: 500; margin-top: 3px;">{_esc(c_slogan)}</div>
                  </div>
                  <div style="text-align: right; font-size: 11px; color: #475569; line-height: 1.5;">
                    {right_html}
                  </div>
                </div>"""

        def _render_footer_html(hgb_style: bool = False) -> str:
            cols = layout["footer_columns"]
            grid_cols = "1fr 1fr" if cols == 2 else "1fr 1fr 1fr"
            col1 = (
                f"""<div>
                  <div style="font-weight: 700; color: #334155;">Geschäftsführung:</div>
                  <div>{_esc(c_directors)}</div>
                  <div style="margin-top: 2px;">Registergericht: {_esc(c_court)}</div>
                  <div>Reg.-Nr.: {_esc(c_hrb)}</div>
                </div>"""
                if hgb_style
                else f"""<div>
                  <div style="font-weight: 700; color: #334155;">{_esc(c_name)}</div>
                  <div>{_esc(c_street)}, {_esc(c_zip)} {_esc(c_city)}</div>
                  <div>Geschäftsführung: {_esc(c_directors)}</div>
                  <div>{_esc(c_court)}, {_esc(c_hrb)}</div>
                </div>"""
            )
            col2 = f"""<div>
                  <div style="font-weight: 700; color: #334155;">Steuer-Identifikation:</div>
                  <div>USt-IdNr.: {_esc(c_vatid)}</div>
                  <div>Steuernummer: {_esc(c_taxnum)}</div>
                  <div>E-Mail: {_esc(c_email)}</div>
                </div>"""
            col3 = (
                f"""<div>
                  <div style="font-weight: 700; color: #334155;">Bankverbindung:</div>
                  <div>{_esc(c_bankname)}</div>
                  <div>IBAN: <strong>{_esc(c_iban)}</strong></div>
                  <div>BIC: <strong>{_esc(c_bic)}</strong></div>
                </div>"""
                if layout["show_bank_footer"] and cols == 3
                else ""
            )
            if cols == 2 or not layout["show_bank_footer"]:
                grid_cols = "1fr 1fr"
            return f"""
              <div style="border-top: 1px solid #e2e8f0; padding-top: 14px; margin-top: 30px; display: grid; grid-template-columns: {grid_cols}; gap: 15px; font-size: 9.5px; color: #64748b; line-height: 1.4;">
                {col1}{col2}{col3}
              </div>"""

        def _render_items_table_html(header_col_label: str = "Bezeichnung / Leistung") -> str:
            rows = "".join([
                f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                  <td style="padding: 10px 8px; font-size: 12px; color: #64748b;">{_esc(item.get('pos', ''))}</td>
                  <td style="padding: 10px 8px; font-size: 12px; font-weight: 600; color: #0f172a;">{_esc(item.get('desc', ''))}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: center; color: #334155;">{_esc(item.get('qty', 1))} {_esc(item.get('unit', 'Stk'))}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; color: #334155;">{float(item.get('price') or 0.0):,.2f} €</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; font-weight: 700; color: #0f172a;">{_line_net(item):,.2f} €</td>
                </tr>"""
                for item in items
            ])
            return f"""
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 22px;">
                  <thead>
                    <tr style="background: #f1f5f9; border-bottom: 2px solid #cbd5e1; font-size: 11px; text-transform: uppercase; color: #475569; letter-spacing: 0.03em;">
                      <th style="padding: 10px 8px; text-align: left; width: 40px;">Pos</th>
                      <th style="padding: 10px 8px; text-align: left;">{header_col_label}</th>
                      <th style="padding: 10px 8px; text-align: center; width: 100px;">Menge</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Einzelpreis</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Gesamt</th>
                    </tr>
                  </thead>
                  <tbody>{rows}</tbody>
                </table>"""

        epc_qr_payload = ""
        girocode_html = ""
        clean_iban = re.sub(r"\s+", "", str(c_iban or ""))
        if norm_type in ("invoice", "dunning") and layout["show_girocode"] and len(clean_iban) >= 15 and gross_total > 0:
            try:
                from backend.qr_girocode import build_epc_qr_payload, render_qr_svg
                epc_qr_payload = build_epc_qr_payload(
                    recipient_name=c_name,
                    iban=clean_iban,
                    amount_eur=gross_total,
                    currency=str(custom.get("currency") or "EUR"),
                    bic=c_bic,
                    reference=html.unescape(doc_number),
                )
                qr_svg = render_qr_svg(epc_qr_payload, size_px=88, title=f"GiroCode {html.unescape(doc_number)}")
                girocode_html = (
                    '<div style="display:flex; flex-direction:column; align-items:center; shrink:0; padding:8px; border:1px solid #cbd5e1; border-radius:6px; background:#ffffff;">'
                    f'{qr_svg}'
                    '<span style="font-size:8.5px; font-weight:700; color:#475569; margin-top:4px; letter-spacing:0.04em;">GIROCODE EPC-QR</span>'
                    '</div>'
                )
            except Exception:
                epc_qr_payload = ""
                girocode_html = ""

        page_wrap_open = f'<div style="position: relative; font-family: {_esc(c_font)}; color: #1e293b; max-width: 800px; margin: 0 auto; background: #ffffff; padding: {pad_px}px; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); min-height: 1050px; display: flex; flex-direction: column; justify-content: space-between;">{_render_fold_marks_html()}'
        subject = _subst(raw_subject)
        body_text = _subst(raw_body_text)
        intro_html = f'<div style="font-size: 12.5px; color: #334155; line-height: 1.6; margin-bottom: 18px; white-space: pre-line;">{_subst(layout["intro_text"])}</div>' if layout["intro_text"].strip() else ""
        outro_html = f'<div style="font-size: 12px; color: #334155; line-height: 1.6; margin-top: 14px; white-space: pre-line;">{_subst(layout["outro_text"])}</div>' if layout["outro_text"].strip() else ""

        rendered_html = ""
        doc_title_label = "BELEG"
        meta_pairs: List[Tuple[str, str]] = []

        if norm_type == "letterhead":
            doc_title_label = "DIN 5008 Geschäftsbrief"
            rendered_html = f"""
            {page_wrap_open}
              <div>
                {_render_header_html([_esc(c_street), f"{_esc(c_zip)} {_esc(c_city)}", f"Tel: {_esc(c_phone)} | {_esc(c_email)}", f'<span style="color:{_esc(c_primary)}; font-weight:600;">{_esc(c_web)}</span>'])}
                <div style="margin-bottom: 35px;">
                  <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 8px; letter-spacing: 0.02em;">
                    {_esc(c_name)} • {_esc(c_street)} • {_esc(c_zip)} {_esc(c_city)}
                  </div>
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a; font-weight: 500;">
                    <div>{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 12px; color: #64748b; margin-bottom: 24px; border-top: 1px solid #f1f5f9; padding-top: 10px;">
                  <div>Ihre Nachricht vom: {_esc(custom.get('ref_date', '-'))}</div>
                  <div>Unser Zeichen: {doc_number}</div>
                  <div style="font-weight: 600; color: #0f172a;">{_esc(c_city)}, den {_esc(today_de)}</div>
                </div>
                <div style="margin-bottom: 20px;">
                  <h2 style="font-size: 15px; font-weight: 700; color: #0f172a; margin: 0 0 16px 0;">{subject}</h2>
                  {intro_html}
                  <div style="font-size: 13px; line-height: 1.7; color: #334155; white-space: pre-line;">{body_text}</div>
                  {outro_html}
                </div>
                <div style="margin-top: 35px; font-size: 13px; color: #334155;">
                  <div>Mit freundlichen Grüßen,</div>
                  <div style="font-weight: 700; color: {_esc(c_primary)}; margin-top: 24px;">{_esc(c_name)}</div>
                  <div style="font-size: 11px; color: #64748b;">{_esc(c_directors)}</div>
                </div>
              </div>
              {_render_footer_html(hgb_style=True)}
            </div>"""
            meta_pairs = [("Datum:", today_de), ("Zeichen:", html.unescape(doc_number))]

        elif norm_type == "invoice":
            doc_title_label = "RECHNUNG"
            tax_row_html = _tax_rows_html(
                tax_buckets,
                '<div style="font-size: 10px; color: #64748b; font-style: italic; margin-top: 4px;">Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerstatus).</div>',
            )
            table_html = _render_items_table_html("Bezeichnung / Leistung")
            rendered_html = f"""
            {page_wrap_open}
              <div>
                {_render_header_html([_esc(c_street), f"{_esc(c_zip)} {_esc(c_city)}", f"USt-IdNr.: <strong>{_esc(c_vatid)}</strong>", f"Steuernummer: <strong>{_esc(c_taxnum)}</strong>"])}
                <div style="display: flex; justify-content: space-between; margin-bottom: 26px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">{_esc(c_name)} • {_esc(c_street)} • {_esc(c_zip)} {_esc(c_city)}</div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; min-width: 220px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {_esc(c_primary)}; font-size: 13px; margin-bottom: 4px;">RECHNUNG</div>
                    <div>Rechnungs-Nr.: <strong>{doc_number}</strong></div>
                    <div>Rechnungsdatum: <strong>{_esc(today_de)}</strong></div>
                    <div>Leistungsdatum: <strong>{_esc(custom.get('supply_date') or today_de)}</strong></div>
                    <div>Zahlungsziel: <strong>{_esc(due_date_de)}</strong></div>
                  </div>
                </div>
                {intro_html}
                {table_html}
                <div style="display: flex; justify-content: flex-end; margin-bottom: 24px;">
                  <div style="width: 280px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                      <span>Nettobetrag:</span>
                      <span style="font-weight: 600;">{net_total:,.2f} €</span>
                    </div>
                    {tax_row_html}
                    <div style="display: flex; justify-content: space-between; padding: 8px 0 0 0; margin-top: 6px; border-top: 2px solid {_esc(c_primary)}; font-size: 14px; font-weight: 800; color: #0f172a;">
                      <span>Gesamtbetrag:</span>
                      <span style="color: {_esc(c_primary)};">{gross_total:,.2f} €</span>
                    </div>
                  </div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom: 20px;">
                  <div style="flex:1; font-size: 12px; color: #334155; line-height: 1.6; background: #eff6ff; border-left: 4px solid {_esc(c_primary)}; padding: 12px 16px; border-radius: 0 4px 4px 0;">
                    Bitte überweisen Sie den Rechnungsbetrag von <strong>{gross_total:,.2f} €</strong> bis zum <strong>{_esc(due_date_de)}</strong> auf das unten genannte Geschäftskonto unter Angabe der Rechnungsnummer <strong>{doc_number}</strong>.
                  </div>
                  {girocode_html}
                </div>
                {outro_html}
              </div>
              {_render_footer_html()}
            </div>"""
            meta_pairs = [("Rechnungs-Nr.:", html.unescape(doc_number)), ("Rechnungsdatum:", today_de), ("Fällig bis:", str(due_date_de))]

        elif norm_type == "offer":
            doc_title_label = "ANGEBOT"
            valid_until_de = _esc(custom.get("valid_until_de", (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")))
            tax_row_html = _tax_rows_html(
                tax_buckets,
                '<div style="font-size: 10px; color: #64748b; font-style: italic; margin-top: 4px;">Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.</div>',
            )
            default_intro = intro_html or '<div style="font-size: 12.5px; color: #334155; line-height: 1.6; margin-bottom: 20px;">Sehr geehrte Damen und Herren,<br>vielen Dank für Ihr Interesse und die freundlichen Vorgespräche. Gerne unterbreiten wir Ihnen auf Basis Ihrer Anforderungen folgendes freibleibendes Angebot:</div>'
            rendered_html = f"""
            {page_wrap_open}
              <div>
                {_render_header_html([_esc(c_street), f"{_esc(c_zip)} {_esc(c_city)}", f"USt-IdNr.: <strong>{_esc(c_vatid)}</strong>", f"Steuernummer: <strong>{_esc(c_taxnum)}</strong>"])}
                <div style="display: flex; justify-content: space-between; margin-bottom: 24px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">{_esc(c_name)} • {_esc(c_street)} • {_esc(c_zip)} {_esc(c_city)}</div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; min-width: 220px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {_esc(c_primary)}; font-size: 13px; margin-bottom: 4px;">ANGEBOT</div>
                    <div>Angebots-Nr.: <strong>{doc_number}</strong></div>
                    <div>Angebotsdatum: <strong>{_esc(today_de)}</strong></div>
                    <div>Gültig bis: <strong>{valid_until_de}</strong></div>
                    <div>Kunden-Nr.: <strong>{_esc(custom.get('debtor_no', '10001'))}</strong></div>
                  </div>
                </div>
                {default_intro}
                {_render_items_table_html("Bezeichnung / Leistungsumfang")}
                <div style="display: flex; justify-content: flex-end; margin-bottom: 24px;">
                  <div style="width: 280px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                      <span>Nettobetrag:</span>
                      <span style="font-weight: 600;">{net_total:,.2f} €</span>
                    </div>
                    {tax_row_html}
                    <div style="display: flex; justify-content: space-between; padding: 8px 0 0 0; margin-top: 6px; border-top: 2px solid {_esc(c_primary)}; font-size: 14px; font-weight: 800; color: #0f172a;">
                      <span>Gesamtangebot:</span>
                      <span style="color: {_esc(c_primary)};">{gross_total:,.2f} €</span>
                    </div>
                  </div>
                </div>
                <div style="font-size: 11.5px; color: #334155; line-height: 1.6; background: #f8fafc; border: 1px solid #e2e8f0; padding: 14px 16px; border-radius: 6px; margin-bottom: 20px;">
                  <div style="font-weight: 700; color: #0f172a; margin-bottom: 4px;">Konditionen &amp; Zahlungsbedingungen:</div>
                  <div>• Zahlungsziel: 14 Tage netto nach Rechnungserhalt ohne Abzug.</div>
                  <div>• Projektstart / Leistungsbereitstellung erfolgt unmittelbar nach Auftragsbestätigung.</div>
                  <div>• Es gelten unsere Allgemeinen Geschäftsbedingungen (AGB).</div>
                </div>
                <div style="border: 1px dashed #cbd5e1; border-radius: 6px; padding: 14px; margin-bottom: 18px;">
                  <div style="font-size: 11px; font-weight: 700; color: #0f172a; margin-bottom: 8px;">Auftragserteilung / Angebotsannahme:</div>
                  <div style="font-size: 10.5px; color: #64748b; margin-bottom: 25px;">Hiermit nehmen wir das vorstehende Angebot mit der Angebots-Nr. <strong>{doc_number}</strong> verbindlich an.</div>
                  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px; font-size: 11px;">
                    <div style="border-top: 1px solid #94a3b8; padding-top: 4px; color: #64748b;">Ort, Datum</div>
                    <div style="border-top: 1px solid #94a3b8; padding-top: 4px; color: #64748b;">Rechtsverbindliche Unterschrift Auftraggeber</div>
                  </div>
                </div>
                {outro_html}
              </div>
              {_render_footer_html()}
            </div>"""
            meta_pairs = [("Angebots-Nr.:", html.unescape(doc_number)), ("Datum:", today_de), ("Gültig bis:", html.unescape(valid_until_de))]

        elif norm_type == "order_confirmation":
            doc_title_label = "AUFTRAGSBESTÄTIGUNG"
            tax_row_html = _tax_rows_html(
                tax_buckets,
                '<div style="font-size: 10px; color: #64748b; font-style: italic; margin-top: 4px;">Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.</div>',
            )
            default_intro = intro_html or '<div style="font-size: 12.5px; color: #334155; line-height: 1.6; margin-bottom: 20px;">Sehr geehrte Damen und Herren,<br>vielen Dank für Ihren Auftrag. Wir bestätigen die Durchführung der nachfolgend aufgeführten Leistungen und Lieferungen zu den vereinbarten Konditionen:</div>'
            rendered_html = f"""
            {page_wrap_open}
              <div>
                {_render_header_html([_esc(c_street), f"{_esc(c_zip)} {_esc(c_city)}", f"USt-IdNr.: <strong>{_esc(c_vatid)}</strong>", f"Steuernummer: <strong>{_esc(c_taxnum)}</strong>"])}
                <div style="display: flex; justify-content: space-between; margin-bottom: 24px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">{_esc(c_name)} • {_esc(c_street)} • {_esc(c_zip)} {_esc(c_city)}</div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; min-width: 220px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {_esc(c_primary)}; font-size: 13px; margin-bottom: 4px;">AUFTRAGSBESTÄTIGUNG</div>
                    <div>Auftrags-Nr.: <strong>{doc_number}</strong></div>
                    <div>Auftragsdatum: <strong>{_esc(today_de)}</strong></div>
                    <div>Ausführung: <strong>Nach Vereinbarung</strong></div>
                    <div>Kunden-Nr.: <strong>{_esc(custom.get('debtor_no', '10001'))}</strong></div>
                  </div>
                </div>
                {default_intro}
                {_render_items_table_html("Bezeichnung / Leistungsumfang")}
                <div style="display: flex; justify-content: flex-end; margin-bottom: 24px;">
                  <div style="width: 280px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                      <span>Nettobetrag:</span>
                      <span style="font-weight: 600;">{net_total:,.2f} €</span>
                    </div>
                    {tax_row_html}
                    <div style="display: flex; justify-content: space-between; padding: 8px 0 0 0; margin-top: 6px; border-top: 2px solid {_esc(c_primary)}; font-size: 14px; font-weight: 800; color: #0f172a;">
                      <span>Auftragsvolumen:</span>
                      <span style="color: {_esc(c_primary)};">{gross_total:,.2f} €</span>
                    </div>
                  </div>
                </div>
                <div style="font-size: 12px; color: #334155; line-height: 1.6; background: #f0fdf4; border-left: 4px solid #16a34a; padding: 12px 16px; border-radius: 0 4px 4px 0; margin-bottom: 20px;">
                  Wir sichern Ihnen eine fachgerechte und termingetreue Ausführung zu. Bei Fragen zur Auftragsabwicklung steht Ihnen unser Projektteam jederzeit zur Verfügung.
                </div>
                {outro_html}
              </div>
              {_render_footer_html()}
            </div>"""
            meta_pairs = [("Auftrags-Nr.:", html.unescape(doc_number)), ("Datum:", today_de)]

        elif norm_type == "dunning":
            lvl = layout["dunning_level"]
            level_titles = {
                1: "ZAHLUNGSERINNERUNG (STUFE 1)",
                2: "ZWEITE MAHNUNG (§ 286 / § 288 BGB)",
                3: "LETZTE AUSSERGERICHTLICHE MAHNUNG (STUFE 3)",
            }
            doc_title_label = level_titles.get(lvl, level_titles[1])
            accent_warn = "#d97706" if lvl == 1 else ("#ea580c" if lvl == 2 else "#dc2626")
            default_dunning_intro = intro_html or (
                f'<div style="font-size: 12.5px; color: #334155; line-height: 1.6; margin-bottom: 18px;">'
                f'Sehr geehrte Damen und Herren,<br>bei der Prüfung unserer offenen Posten (OPOS) mussten wir feststellen, '
                f'dass nachfolgende Forderung aus Beleg <strong>{doc_number}</strong> bislang noch nicht beglichen wurde:</div>'
            )
            rendered_html = f"""
            {page_wrap_open}
              <div>
                {_render_header_html([_esc(c_street), f"{_esc(c_zip)} {_esc(c_city)}", f"USt-IdNr.: <strong>{_esc(c_vatid)}</strong>", f"E-Mail: {_esc(c_email)}"])}
                <div style="display: flex; justify-content: space-between; margin-bottom: 24px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">{_esc(c_name)} • {_esc(c_street)} • {_esc(c_zip)} {_esc(c_city)}</div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 14px; min-width: 230px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {accent_warn}; font-size: 12.5px; margin-bottom: 4px;">{doc_title_label}</div>
                    <div>Beleg / Referenz: <strong>{doc_number}</strong></div>
                    <div>Mahn-Datum: <strong>{_esc(today_de)}</strong></div>
                    <div>Neue Frist bis: <strong>{_esc(due_date_de)}</strong></div>
                  </div>
                </div>
                {default_dunning_intro}
                {_render_items_table_html("Offene Posten / Verzugspositionen")}
                <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom: 22px;">
                  <div style="flex:1; font-size: 12px; color: #334155; line-height: 1.6; background: #fff7ed; border-left: 4px solid {accent_warn}; padding: 12px 16px; border-radius: 0 4px 4px 0;">
                    Bitte überweisen Sie den offenen Gesamtbetrag von <strong>{gross_total:,.2f} €</strong> innerhalb von 7 Tagen bis spätestens <strong>{_esc(due_date_de)}</strong> unter Angabe von <strong>{doc_number}</strong>. Sollte sich Ihre Zahlung mit diesem Schreiben überschnitten haben, betrachten Sie diese Nachricht bitte als gegenstandslos.
                  </div>
                  {girocode_html}
                </div>
                {outro_html}
              </div>
              {_render_footer_html()}
            </div>"""
            meta_pairs = [("Mahnstufe:", str(lvl)), ("Referenz:", html.unescape(doc_number)), ("Frist bis:", str(due_date_de))]

        elif norm_type == "nda":
            doc_title_label = "VERTRAULICHKEITSVEREINBARUNG (NDA)"
            rendered_html = f"""
            {page_wrap_open}
              <div>
                <div style="text-align: center; border-bottom: 2px solid {_esc(c_primary)}; padding-bottom: 16px; margin-bottom: 30px;">
                  <h1 style="margin: 0; font-size: 20px; font-weight: 800; color: {_esc(c_primary)}; text-transform: uppercase; letter-spacing: 0.05em;">Vertraulichkeitsvereinbarung (NDA)</h1>
                  <div style="font-size: 11px; color: #64748b; margin-top: 4px;">Non-Disclosure Agreement zur Wahrung von Geschäfts- und Betriebsgeheimnissen</div>
                </div>
                {intro_html}
                <div style="font-size: 12.5px; line-height: 1.7; color: #334155; margin-bottom: 24px;">
                  <p>Zwischen</p>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-bottom: 12px;">
                    <strong>{_esc(c_name)}</strong>, {_esc(c_street)}, {_esc(c_zip)} {_esc(c_city)}, gesetzlich vertreten durch die Geschäftsführung (nachfolgend <em>Partei 1</em>)
                  </div>
                  <p>und</p>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-bottom: 20px;">
                    <strong>{recipient_name}</strong>, {recipient_street}, {recipient_city}, vertreten durch {recipient_contact} (nachfolgend <em>Partei 2</em>)
                  </div>
                  <h3 style="font-size: 13px; font-weight: 700; color: #0f172a; margin: 16px 0 6px 0;">§ 1 Gegenstand &amp; Definition Vertraulicher Informationen</h3>
                  <p>Die Parteien beabsichtigen Gespräche über eine strategische Kooperation und Softwareentwicklung im Bereich künstlicher Intelligenz. Vertrauliche Informationen im Sinne dieser Vereinbarung umfassen alle technischen Daten, Quellcodes, Schnittstellendesigns, Geschäftsmodelle und Prozessabläufe.</p>
                  <h3 style="font-size: 13px; font-weight: 700; color: #0f172a; margin: 16px 0 6px 0;">§ 2 Geheimhaltungspflichten &amp; Datensicherheit</h3>
                  <p>Die empfangende Partei verpflichtet sich, sämtliche überlassenen Informationen streng vertraulich zu behandeln, sie vor unbefugtem Zugriff Dritter durch dem Stand der Technik entsprechende Sicherheitsmaßnahmen zu schützen und ausschließlich zum vertraglich vereinbarten Zweck zu nutzen.</p>
                  <h3 style="font-size: 13px; font-weight: 700; color: #0f172a; margin: 16px 0 6px 0;">§ 3 Laufzeit &amp; Rückgabepflicht</h3>
                  <p>Diese Vereinbarung tritt mit Unterzeichnung in Kraft. Die Geheimhaltungspflicht besteht für einen Zeitraum von 5 Jahren über die Beendigung der Gespräche hinaus fort. Auf schriftliche Anforderung sind sämtliche Unterlagen und Datenträger vollständig zu vernichten oder herauszugeben.</p>
                </div>
                {outro_html}
                <div style="margin-top: 50px; display: grid; grid-template-columns: 1fr 1fr; gap: 40px; font-size: 12px;">
                  <div>
                    <div style="color: #64748b; margin-bottom: 40px;">{_esc(c_city)}, den {_esc(today_de)}</div>
                    <div style="border-top: 1px solid #0f172a; padding-top: 8px;">
                      <div style="font-weight: 700; color: #0f172a;">{_esc(c_name)}</div>
                      <div style="color: #64748b; font-size: 10px;">(Unterschrift / Geschäftsführung)</div>
                    </div>
                  </div>
                  <div>
                    <div style="color: #64748b; margin-bottom: 40px;">Ort, Datum: _____________________</div>
                    <div style="border-top: 1px solid #0f172a; padding-top: 8px;">
                      <div style="font-weight: 700; color: #0f172a;">{recipient_name}</div>
                      <div style="color: #64748b; font-size: 10px;">(Unterschrift / Bevollmächtigter)</div>
                    </div>
                  </div>
                </div>
              </div>
              <div style="border-top: 1px solid #e2e8f0; padding-top: 10px; margin-top: 30px; text-align: center; font-size: 9.5px; color: #94a3b8;">
                {_esc(c_name)} • {_esc(c_court)} {_esc(c_hrb)} • USt-IdNr.: {_esc(c_vatid)} • Vertraulichkeitsstufe: DSGVO / Geschäftsgeheimnisgesetz
              </div>
            </div>"""
            meta_pairs = [("Datum:", today_de), ("Typ:", "NDA / Vertraulichkeit")]

        else:
            rendered_html = f"<div style='font-family: sans-serif; padding: 20px;'>Unbekannter Vorlagentyp: {_esc(template_type)}</div>"

        compliance = self.validate_ustg_compliance(
            company=company,
            template_type=norm_type,
            custom={**custom, "issue_date": custom.get("issue_date") or today_de},
            net_total=net_total,
            gross_total=gross_total,
            items=items,
        )

        pdf_items = [
            {
                "pos": item.get("pos", idx + 1),
                "desc": item.get("desc", ""),
                "qty": item.get("qty", 1),
                "unit": item.get("unit", "Stk"),
                "price": float(item.get("price") or 0.0),
                "line_net": _line_net(item),
            }
            for idx, item in enumerate(items)
        ]

        return {
            "template_type": template_type,
            "normalized_type": norm_type,
            "company_id": company.get("id"),
            "company_name": c_name,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "layout": layout,
            "compliance": compliance,
            "placeholders": sorted(list(placeholder_map.keys()) + ["invoice.items_table"]),
            "html": rendered_html,
            "pdf_meta": {
                "doc_title": doc_title_label,
                "doc_number": html.unescape(doc_number),
                "company_name": c_name,
                "company_address": f"{c_street} | {c_zip} {c_city}".strip(" |"),
                "company_tax": f"USt-IdNr.: {c_vatid} | Steuernr.: {c_taxnum} | {c_court} {c_hrb}",
                "company_bank": f"{c_bankname} | IBAN: {c_iban} | BIC: {c_bic}",
                "recipient_lines": [
                    html.unescape(recipient_name),
                    html.unescape(recipient_contact),
                    html.unescape(recipient_street),
                    html.unescape(recipient_city),
                ],
                "meta_pairs": meta_pairs,
                "subject": html.unescape(subject) if norm_type == "letterhead" else "",
                "intro_text": (
                    html.unescape(_subst(layout["intro_text"] or (raw_body_text if norm_type == "letterhead" else "")))
                ),
                "outro_text": html.unescape(_subst(layout["outro_text"])),
                "items": pdf_items,
                "net_total": net_total,
                "tax_amount": tax_amount,
                "gross_total": gross_total,
                "currency": str(custom.get("currency") or "EUR"),
                "epc_qr_payload": epc_qr_payload,
            },
        }


# Singleton instance
corporate_manager = CorporateManager()
