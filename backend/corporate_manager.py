"""
Corporate Manager & Multi-Company Hub for Archon OS
Provides master data storage, Corporate Design profiles, and
legal/correspondence templates (DIN 5008, § 14 UStG Invoices, NDAs, Offers).
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PROFILES_FILE = os.path.join(DATA_DIR, "corporate_profiles.json")

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
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_companies(self) -> List[Dict[str, Any]]:
        data = self._load_data()
        active_id = data.get("active_company_id", "")
        result = []
        for c in data.get("companies", []):
            result.append({
                "id": c.get("id"),
                "name": c.get("name"),
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
        if data.get("companies"):
            return data["companies"][0]
        return None

    def set_active_company(self, company_id: str) -> bool:
        data = self._load_data()
        for c in data.get("companies", []):
            if c.get("id") == company_id:
                data["active_company_id"] = company_id
                self._save_data(data)
                return True
        return False

    def save_company(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._load_data()
        company_id = payload.get("id") or str(uuid.uuid4())[:8]
        now_iso = datetime.utcnow().isoformat() + "Z"

        existing_idx = None
        for i, c in enumerate(data.get("companies", [])):
            if c.get("id") == company_id:
                existing_idx = i
                break

        company_record = {
            "id": company_id,
            "name": payload.get("name", "Neues Unternehmen"),
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
                                    "price": ln.get("unit_price_net", 0.0)
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

        bank = company.get("bank", {})
        c_bankname = bank.get("bank_name", "")
        c_iban = bank.get("iban", "")
        c_bic = bank.get("bic", "")

        des = company.get("design", {})
        c_primary = des.get("primary_color", "#4f46e5")
        c_secondary = des.get("secondary_color", "#06b6d4")
        c_font = des.get("font_family", "Inter, sans-serif")
        c_logo = des.get("logo_url", "")

        recipient_name = custom.get("recipient_name", "Musterempfänger GmbH")
        recipient_contact = custom.get("recipient_contact", "Herrn Max Mustermann")
        recipient_street = custom.get("recipient_street", "Musterweg 42")
        recipient_city = custom.get("recipient_city", "10115 Berlin")
        
        subject = custom.get("subject", "Geschäftliche Mitteilung")
        body_text = custom.get("body_text", "Sehr geehrte Damen und Herren,\n\nvielen Dank für die angenehme Zusammenarbeit...")

        rendered_html = ""

        if template_type == "letterhead":
            # DIN 5008 Geschäftsbrief
            rendered_html = f"""
            <div style="font-family: {c_font}; color: #1e293b; max-width: 800px; margin: 0 auto; background: #ffffff; padding: 48px; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); min-height: 1050px; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <!-- Briefkopf / Header -->
                <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid {c_primary}; padding-bottom: 20px; margin-bottom: 30px;">
                  <div>
                    <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: {c_primary}; letter-spacing: -0.02em;">{c_name}</h1>
                    <div style="font-size: 11px; color: #64748b; font-weight: 500; margin-top: 4px;">{c_slogan}</div>
                  </div>
                  <div style="text-align: right; font-size: 11px; color: #475569; line-height: 1.5;">
                    <div>{c_street}</div>
                    <div>{c_zip} {c_city}</div>
                    <div>Tel: {c_phone} | {c_email}</div>
                    <div style="color: {c_primary}; font-weight: 600;">{c_web}</div>
                  </div>
                </div>

                <!-- Rücksendeangabe (DIN 5008) & Anschriftfeld -->
                <div style="margin-bottom: 35px;">
                  <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 8px; letter-spacing: 0.02em;">
                    {c_name} • {c_street} • {c_zip} {c_city}
                  </div>
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a; font-weight: 500;">
                    <div>{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                </div>

                <!-- Datum & Infoleiste -->
                <div style="display: flex; justify-content: space-between; font-size: 12px; color: #64748b; margin-bottom: 24px; border-top: 1px solid #f1f5f9; padding-top: 10px;">
                  <div>Ihre Nachricht vom: {custom.get('ref_date', '-')}</div>
                  <div>Unser Zeichen: {custom.get('ref_code', 'AS-2026/01')}</div>
                  <div style="font-weight: 600; color: #0f172a;">{c_city}, den {today_de}</div>
                </div>

                <!-- Betreff & Text -->
                <div style="margin-bottom: 20px;">
                  <h2 style="font-size: 15px; font-weight: 700; color: #0f172a; margin: 0 0 16px 0;">{subject}</h2>
                  <div style="font-size: 13px; line-height: 1.7; color: #334155; white-space: pre-line;">
                    {body_text}
                  </div>
                </div>

                <!-- Grußformel -->
                <div style="margin-top: 35px; font-size: 13px; color: #334155;">
                  <div>Mit freundlichen Grüßen,</div>
                  <div style="font-weight: 700; color: {c_primary}; margin-top: 24px;">{c_name}</div>
                  <div style="font-size: 11px; color: #64748b;">{c_directors}</div>
                </div>
              </div>

              <!-- Fußzeile nach HGB / GmbHG -->
              <div style="border-top: 1px solid #e2e8f0; padding-top: 14px; margin-top: 40px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; font-size: 9.5px; color: #64748b; line-height: 1.4;">
                <div>
                  <div style="font-weight: 700; color: #334155;">Geschäftsführung:</div>
                  <div>{c_directors}</div>
                  <div style="margin-top: 2px;">Registergericht: {c_court}</div>
                  <div>Reg.-Nr.: {c_hrb}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Steuer-Informationen:</div>
                  <div>USt-IdNr.: {c_vatid}</div>
                  <div>Steuernummer: {c_taxnum}</div>
                  <div>Gerichtsstand: {c_city}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Bankverbindung:</div>
                  <div>Bank: {c_bankname}</div>
                  <div>IBAN: {c_iban}</div>
                  <div>BIC: {c_bic}</div>
                </div>
              </div>
            </div>
            """

        elif template_type == "invoice":
            # Ausgangsrechnung nach § 14 UStG
            invoice_num = custom.get("invoice_num", f"RE-{datetime.now().strftime('%Y%m')}-001")
            items = custom.get("items", [
                {"pos": 1, "desc": "Archon OS Enterprise Subscription (Monatlich)", "qty": 1, "unit": "Monat", "price": 490.00},
                {"pos": 2, "desc": "Dedizierter Agenten-Cluster & Setup", "qty": 1, "unit": "Pauschal", "price": 1250.00}
            ])

            net_total = sum(i["qty"] * i["price"] for i in items)
            tax_rate = 0.0 if is_small else 0.19
            tax_amount = net_total * tax_rate
            gross_total = net_total + tax_amount

            items_rows_html = "".join([
                f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                  <td style="padding: 10px 8px; font-size: 12px; color: #64748b;">{item['pos']}</td>
                  <td style="padding: 10px 8px; font-size: 12px; font-weight: 600; color: #0f172a;">{item['desc']}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: center; color: #334155;">{item['qty']} {item.get('unit', 'Stk')}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; color: #334155;">{item['price']:,.2f} €</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; font-weight: 700; color: #0f172a;">{(item['qty'] * item['price']):,.2f} €</td>
                </tr>
                """ for item in items
            ])

            tax_row_html = (
                f"""
                <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                  <span>Umsatzsteuer (19%):</span>
                  <span style="font-weight: 600;">{tax_amount:,.2f} €</span>
                </div>
                """ if not is_small else
                """
                <div style="font-size: 10px; color: #64748b; font-style: italic; margin-top: 4px;">
                  Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerstatus).
                </div>
                """
            )

            rendered_html = f"""
            <div style="font-family: {c_font}; color: #1e293b; max-width: 800px; margin: 0 auto; background: #ffffff; padding: 48px; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); min-height: 1050px; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <!-- Header -->
                <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid {c_primary}; padding-bottom: 20px; margin-bottom: 25px;">
                  <div>
                    <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: {c_primary};">{c_name}</h1>
                    <div style="font-size: 11px; color: #64748b;">{c_slogan}</div>
                  </div>
                  <div style="text-align: right; font-size: 11px; color: #475569; line-height: 1.5;">
                    <div>{c_street}</div>
                    <div>{c_zip} {c_city}</div>
                    <div>USt-IdNr.: <strong>{c_vatid}</strong></div>
                    <div>Steuernummer: <strong>{c_taxnum}</strong></div>
                  </div>
                </div>

                <!-- Empfänger & Rechnungs-Metadaten -->
                <div style="display: flex; justify-content: space-between; margin-bottom: 30px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">
                      {c_name} • {c_street} • {c_zip} {c_city}
                    </div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; min-width: 220px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {c_primary}; font-size: 13px; margin-bottom: 4px;">RECHNUNG</div>
                    <div>Rechnungs-Nr.: <strong>{invoice_num}</strong></div>
                    <div>Rechnungsdatum: <strong>{today_de}</strong></div>
                    <div>Leistungsdatum: <strong>{today_de}</strong></div>
                    <div>Zahlungsziel: <strong>{due_date_de}</strong></div>
                  </div>
                </div>

                <!-- Positionstabelle -->
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
                  <thead>
                    <tr style="background: #f1f5f9; border-bottom: 2px solid #cbd5e1; font-size: 11px; text-transform: uppercase; color: #475569; letter-spacing: 0.03em;">
                      <th style="padding: 10px 8px; text-align: left; width: 40px;">Pos</th>
                      <th style="padding: 10px 8px; text-align: left;">Bezeichnung / Leistung</th>
                      <th style="padding: 10px 8px; text-align: center; width: 100px;">Menge</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Einzelpreis</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Gesamt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items_rows_html}
                  </tbody>
                </table>

                <!-- Summenblock -->
                <div style="display: flex; justify-content: flex-end; margin-bottom: 30px;">
                  <div style="width: 280px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                      <span>Nettobetrag:</span>
                      <span style="font-weight: 600;">{net_total:,.2f} €</span>
                    </div>
                    {tax_row_html}
                    <div style="display: flex; justify-content: space-between; padding: 8px 0 0 0; margin-top: 6px; border-top: 2px solid {c_primary}; font-size: 14px; font-weight: 800; color: #0f172a;">
                      <span>Gesamtbetrag:</span>
                      <span style="color: {c_primary};">{gross_total:,.2f} €</span>
                    </div>
                  </div>
                </div>

                <!-- Zahlungsaufforderung -->
                <div style="font-size: 12px; color: #334155; line-height: 1.6; background: #eff6ff; border-left: 4px solid {c_primary}; padding: 12px 16px; border-radius: 0 4px 4px 0; margin-bottom: 25px;">
                  Bitte überweisen Sie den Rechnungsbetrag von <strong>{gross_total:,.2f} €</strong> bis zum <strong>{due_date_de}</strong> auf das unten genannte Geschäftskonto unter Angabe der Rechnungsnummer <strong>{invoice_num}</strong>.
                </div>
              </div>

              <!-- Fußzeile -->
              <div style="border-top: 1px solid #e2e8f0; padding-top: 14px; margin-top: 40px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; font-size: 9.5px; color: #64748b; line-height: 1.4;">
                <div>
                  <div style="font-weight: 700; color: #334155;">{c_name}</div>
                  <div>{c_street}, {c_zip} {c_city}</div>
                  <div>Geschäftsführung: {c_directors}</div>
                  <div>{c_court}, {c_hrb}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Steuer-Identifikation:</div>
                  <div>USt-IdNr.: {c_vatid}</div>
                  <div>Steuernummer: {c_taxnum}</div>
                  <div>E-Mail: {c_email}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Bankverbindung:</div>
                  <div>{c_bankname}</div>
                  <div>IBAN: <strong>{c_iban}</strong></div>
                  <div>BIC: <strong>{c_bic}</strong></div>
                </div>
              </div>
            </div>
            """

        elif template_type in ("offer", "ang", "angebot"):
            # Angebot nach DIN 5008
            offer_num = custom.get("offer_num", f"ANG-{datetime.now().strftime('%Y%m')}-001")
            valid_until_de = custom.get("valid_until_de", (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y"))
            items = custom.get("items", [
                {"pos": 1, "desc": "Archon OS Enterprise Lizenz & KI-Agenten Setup", "qty": 1, "unit": "Pauschal", "price": 4500.00},
                {"pos": 2, "desc": "Architektur-Consulting & Anbindung Primärsysteme", "qty": 16, "unit": "Std.", "price": 180.00}
            ])

            net_total = sum(i["qty"] * i["price"] for i in items)
            tax_rate = 0.0 if is_small else 0.19
            tax_amount = net_total * tax_rate
            gross_total = net_total + tax_amount

            items_rows_html = "".join([
                f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                  <td style="padding: 10px 8px; font-size: 12px; color: #64748b;">{item['pos']}</td>
                  <td style="padding: 10px 8px; font-size: 12px; font-weight: 600; color: #0f172a;">{item['desc']}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: center; color: #334155;">{item['qty']} {item.get('unit', 'Stk')}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; color: #334155;">{item['price']:,.2f} €</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; font-weight: 700; color: #0f172a;">{(item['qty'] * item['price']):,.2f} €</td>
                </tr>
                """ for item in items
            ])

            tax_row_html = (
                f"""
                <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                  <span>Umsatzsteuer (19%):</span>
                  <span style="font-weight: 600;">{tax_amount:,.2f} €</span>
                </div>
                """ if not is_small else
                """
                <div style="font-size: 10px; color: #64748b; font-style: italic; margin-top: 4px;">
                  Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.
                </div>
                """
            )

            rendered_html = f"""
            <div style="font-family: {c_font}; color: #1e293b; max-width: 800px; margin: 0 auto; background: #ffffff; padding: 48px; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); min-height: 1050px; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <!-- Header -->
                <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid {c_primary}; padding-bottom: 20px; margin-bottom: 25px;">
                  <div>
                    <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: {c_primary};">{c_name}</h1>
                    <div style="font-size: 11px; color: #64748b;">{c_slogan}</div>
                  </div>
                  <div style="text-align: right; font-size: 11px; color: #475569; line-height: 1.5;">
                    <div>{c_street}</div>
                    <div>{c_zip} {c_city}</div>
                    <div>USt-IdNr.: <strong>{c_vatid}</strong></div>
                    <div>Steuernummer: <strong>{c_taxnum}</strong></div>
                  </div>
                </div>

                <!-- Empfänger & Angebots-Metadaten -->
                <div style="display: flex; justify-content: space-between; margin-bottom: 25px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">
                      {c_name} • {c_street} • {c_zip} {c_city}
                    </div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; min-width: 220px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {c_primary}; font-size: 13px; margin-bottom: 4px;">ANGEBOT</div>
                    <div>Angebots-Nr.: <strong>{offer_num}</strong></div>
                    <div>Angebotsdatum: <strong>{today_de}</strong></div>
                    <div>Gültig bis: <strong>{valid_until_de}</strong></div>
                    <div>Kunden-Nr.: <strong>{custom.get('debtor_no', '10001')}</strong></div>
                  </div>
                </div>

                <div style="font-size: 12.5px; color: #334155; line-height: 1.6; margin-bottom: 20px;">
                  Sehr geehrte Damen und Herren,<br>
                  vielen Dank für Ihr Interesse und die freundlichen Vorgespräche. Gerne unterbreiten wir Ihnen auf Basis Ihrer Anforderungen folgendes freibleibendes Angebot:
                </div>

                <!-- Positionstabelle -->
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
                  <thead>
                    <tr style="background: #f1f5f9; border-bottom: 2px solid #cbd5e1; font-size: 11px; text-transform: uppercase; color: #475569; letter-spacing: 0.03em;">
                      <th style="padding: 10px 8px; text-align: left; width: 40px;">Pos</th>
                      <th style="padding: 10px 8px; text-align: left;">Bezeichnung / Leistungsumfang</th>
                      <th style="padding: 10px 8px; text-align: center; width: 100px;">Menge</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Einzelpreis</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Gesamt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items_rows_html}
                  </tbody>
                </table>

                <!-- Summenblock -->
                <div style="display: flex; justify-content: flex-end; margin-bottom: 25px;">
                  <div style="width: 280px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                      <span>Nettobetrag:</span>
                      <span style="font-weight: 600;">{net_total:,.2f} €</span>
                    </div>
                    {tax_row_html}
                    <div style="display: flex; justify-content: space-between; padding: 8px 0 0 0; margin-top: 6px; border-top: 2px solid {c_primary}; font-size: 14px; font-weight: 800; color: #0f172a;">
                      <span>Gesamtangebot:</span>
                      <span style="color: {c_primary};">{gross_total:,.2f} €</span>
                    </div>
                  </div>
                </div>

                <!-- Konditionen & Annahme -->
                <div style="font-size: 11.5px; color: #334155; line-height: 1.6; background: #f8fafc; border: 1px solid #e2e8f0; padding: 14px 16px; border-radius: 6px; margin-bottom: 25px;">
                  <div style="font-weight: 700; color: #0f172a; margin-bottom: 4px;">Konditionen &amp; Zahlungsbedingungen:</div>
                  <div>• Zahlungsziel: 14 Tage netto nach Rechnungserhalt ohne Abzug.</div>
                  <div>• Projektstart / Leistungsbereitstellung erfolgt unmittelbar nach Auftragsbestätigung.</div>
                  <div>• Es gelten unsere Allgemeinen Geschäftsbedingungen (AGB).</div>
                </div>

                <!-- Annahmeerklärung / Unterschrift -->
                <div style="border: 1px dashed #cbd5e1; border-radius: 6px; padding: 14px; margin-bottom: 20px;">
                  <div style="font-size: 11px; font-weight: 700; color: #0f172a; margin-bottom: 8px;">Auftragserteilung / Angebotsannahme:</div>
                  <div style="font-size: 10.5px; color: #64748b; margin-bottom: 25px;">Hiermit nehmen wir das vorstehende Angebot mit der Angebots-Nr. <strong>{offer_num}</strong> verbindlich an.</div>
                  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px; font-size: 11px;">
                    <div style="border-top: 1px solid #94a3b8; padding-top: 4px; color: #64748b;">Ort, Datum</div>
                    <div style="border-top: 1px solid #94a3b8; padding-top: 4px; color: #64748b;">Rechtsverbindliche Unterschrift Auftraggeber</div>
                  </div>
                </div>
              </div>

              <!-- Fußzeile -->
              <div style="border-top: 1px solid #e2e8f0; padding-top: 14px; margin-top: 30px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; font-size: 9.5px; color: #64748b; line-height: 1.4;">
                <div>
                  <div style="font-weight: 700; color: #334155;">{c_name}</div>
                  <div>{c_street}, {c_zip} {c_city}</div>
                  <div>Geschäftsführung: {c_directors}</div>
                  <div>{c_court}, {c_hrb}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Steuer-Identifikation:</div>
                  <div>USt-IdNr.: {c_vatid}</div>
                  <div>Steuernummer: {c_taxnum}</div>
                  <div>E-Mail: {c_email}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Bankverbindung:</div>
                  <div>{c_bankname}</div>
                  <div>IBAN: <strong>{c_iban}</strong></div>
                  <div>BIC: <strong>{c_bic}</strong></div>
                </div>
              </div>
            </div>
            """

        elif template_type in ("order_confirmation", "order", "ab", "auftrag"):
            # Auftragsbestätigung nach DIN 5008
            order_num = custom.get("order_num", f"AB-{datetime.now().strftime('%Y%m')}-001")
            items = custom.get("items", [
                {"pos": 1, "desc": "Archon OS Enterprise Subscription (Q4-2026)", "qty": 1, "unit": "Monat", "price": 490.00},
                {"pos": 2, "desc": "Autonome Agenten-Workflows & Tool-Integration", "qty": 40, "unit": "Std.", "price": 180.00}
            ])

            net_total = sum(i["qty"] * i["price"] for i in items)
            tax_rate = 0.0 if is_small else 0.19
            tax_amount = net_total * tax_rate
            gross_total = net_total + tax_amount

            items_rows_html = "".join([
                f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                  <td style="padding: 10px 8px; font-size: 12px; color: #64748b;">{item['pos']}</td>
                  <td style="padding: 10px 8px; font-size: 12px; font-weight: 600; color: #0f172a;">{item['desc']}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: center; color: #334155;">{item['qty']} {item.get('unit', 'Stk')}</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; color: #334155;">{item['price']:,.2f} €</td>
                  <td style="padding: 10px 8px; font-size: 12px; text-align: right; font-weight: 700; color: #0f172a;">{(item['qty'] * item['price']):,.2f} €</td>
                </tr>
                """ for item in items
            ])

            tax_row_html = (
                f"""
                <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                  <span>Umsatzsteuer (19%):</span>
                  <span style="font-weight: 600;">{tax_amount:,.2f} €</span>
                </div>
                """ if not is_small else
                """
                <div style="font-size: 10px; color: #64748b; font-style: italic; margin-top: 4px;">
                  Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.
                </div>
                """
            )

            rendered_html = f"""
            <div style="font-family: {c_font}; color: #1e293b; max-width: 800px; margin: 0 auto; background: #ffffff; padding: 48px; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); min-height: 1050px; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <!-- Header -->
                <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid {c_primary}; padding-bottom: 20px; margin-bottom: 25px;">
                  <div>
                    <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: {c_primary};">{c_name}</h1>
                    <div style="font-size: 11px; color: #64748b;">{c_slogan}</div>
                  </div>
                  <div style="text-align: right; font-size: 11px; color: #475569; line-height: 1.5;">
                    <div>{c_street}</div>
                    <div>{c_zip} {c_city}</div>
                    <div>USt-IdNr.: <strong>{c_vatid}</strong></div>
                    <div>Steuernummer: <strong>{c_taxnum}</strong></div>
                  </div>
                </div>

                <!-- Empfänger & Auftrags-Metadaten -->
                <div style="display: flex; justify-content: space-between; margin-bottom: 25px;">
                  <div style="font-size: 13px; line-height: 1.5; color: #0f172a;">
                    <div style="font-size: 9px; text-decoration: underline; color: #94a3b8; margin-bottom: 6px;">
                      {c_name} • {c_street} • {c_zip} {c_city}
                    </div>
                    <div style="font-weight: 700;">{recipient_name}</div>
                    <div>{recipient_contact}</div>
                    <div>{recipient_street}</div>
                    <div>{recipient_city}</div>
                  </div>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; min-width: 220px; font-size: 11.5px; line-height: 1.6;">
                    <div style="font-weight: 800; color: {c_primary}; font-size: 13px; margin-bottom: 4px;">AUFTRAGSBESTÄTIGUNG</div>
                    <div>Auftrags-Nr.: <strong>{order_num}</strong></div>
                    <div>Auftragsdatum: <strong>{today_de}</strong></div>
                    <div>Ausführung: <strong>Nach Vereinbarung</strong></div>
                    <div>Kunden-Nr.: <strong>{custom.get('debtor_no', '10001')}</strong></div>
                  </div>
                </div>

                <div style="font-size: 12.5px; color: #334155; line-height: 1.6; margin-bottom: 20px;">
                  Sehr geehrte Damen und Herren,<br>
                  vielen Dank für Ihren Auftrag. Wir bestätigen die Durchführung der nachfolgend aufgeführten Leistungen und Lieferungen zu den vereinbarten Konditionen:
                </div>

                <!-- Positionstabelle -->
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
                  <thead>
                    <tr style="background: #f1f5f9; border-bottom: 2px solid #cbd5e1; font-size: 11px; text-transform: uppercase; color: #475569; letter-spacing: 0.03em;">
                      <th style="padding: 10px 8px; text-align: left; width: 40px;">Pos</th>
                      <th style="padding: 10px 8px; text-align: left;">Bezeichnung / Leistungsumfang</th>
                      <th style="padding: 10px 8px; text-align: center; width: 100px;">Menge</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Einzelpreis</th>
                      <th style="padding: 10px 8px; text-align: right; width: 110px;">Gesamt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items_rows_html}
                  </tbody>
                </table>

                <!-- Summenblock -->
                <div style="display: flex; justify-content: flex-end; margin-bottom: 25px;">
                  <div style="width: 280px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #475569;">
                      <span>Nettobetrag:</span>
                      <span style="font-weight: 600;">{net_total:,.2f} €</span>
                    </div>
                    {tax_row_html}
                    <div style="display: flex; justify-content: space-between; padding: 8px 0 0 0; margin-top: 6px; border-top: 2px solid {c_primary}; font-size: 14px; font-weight: 800; color: #0f172a;">
                      <span>Auftragsvolumen:</span>
                      <span style="color: {c_primary};">{gross_total:,.2f} €</span>
                    </div>
                  </div>
                </div>

                <!-- Bestätigungshinweis -->
                <div style="font-size: 12px; color: #334155; line-height: 1.6; background: #f0fdf4; border-left: 4px solid #16a34a; padding: 12px 16px; border-radius: 0 4px 4px 0; margin-bottom: 25px;">
                  Wir sichern Ihnen eine fachgerechte und termingetreue Ausführung zu. Bei Fragen zur Auftragsabwicklung steht Ihnen unser Projektteam jederzeit zur Verfügung.
                </div>
              </div>

              <!-- Fußzeile -->
              <div style="border-top: 1px solid #e2e8f0; padding-top: 14px; margin-top: 30px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; font-size: 9.5px; color: #64748b; line-height: 1.4;">
                <div>
                  <div style="font-weight: 700; color: #334155;">{c_name}</div>
                  <div>{c_street}, {c_zip} {c_city}</div>
                  <div>Geschäftsführung: {c_directors}</div>
                  <div>{c_court}, {c_hrb}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Steuer-Identifikation:</div>
                  <div>USt-IdNr.: {c_vatid}</div>
                  <div>Steuernummer: {c_taxnum}</div>
                  <div>E-Mail: {c_email}</div>
                </div>
                <div>
                  <div style="font-weight: 700; color: #334155;">Bankverbindung:</div>
                  <div>{c_bankname}</div>
                  <div>IBAN: <strong>{c_iban}</strong></div>
                  <div>BIC: <strong>{c_bic}</strong></div>
                </div>
              </div>
            </div>
            """

        elif template_type == "nda":
            # Vertraulichkeitsvereinbarung / NDA
            rendered_html = f"""
            <div style="font-family: {c_font}; color: #1e293b; max-width: 800px; margin: 0 auto; background: #ffffff; padding: 48px; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); min-height: 1050px; display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <div style="text-align: center; border-bottom: 2px solid {c_primary}; padding-bottom: 16px; margin-bottom: 30px;">
                  <h1 style="margin: 0; font-size: 20px; font-weight: 800; color: {c_primary}; text-transform: uppercase; letter-spacing: 0.05em;">Vertraulichkeitsvereinbarung (NDA)</h1>
                  <div style="font-size: 11px; color: #64748b; margin-top: 4px;">Non-Disclosure Agreement zur Wahrung von Geschäfts- und Betriebsgeheimnissen</div>
                </div>

                <div style="font-size: 12.5px; line-height: 1.7; color: #334155; margin-bottom: 24px;">
                  <p>Zwischen</p>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-bottom: 12px;">
                    <strong>{c_name}</strong>, {c_street}, {c_zip} {c_city}, gesetzlich vertreten durch die Geschäftsführung (nachfolgend <em>Partei 1</em>)
                  </div>
                  <p>und</p>
                  <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-bottom: 20px;">
                    <strong>{recipient_name}</strong>, {recipient_street}, {recipient_city}, vertreten durch {recipient_contact} (nachfolgend <em>Partei 2</em>)
                  </div>

                  <h3 style="font-size: 13px; font-weight: 700; color: #0f172a; margin: 16px 0 6px 0;">§ 1 Gegenstand & Definition Vertraulicher Informationen</h3>
                  <p>Die Parteien beabsichtigen Gespräche über eine strategische Kooperation und Softwareentwicklung im Bereich künstlicher Intelligenz. Vertrauliche Informationen im Sinne dieser Vereinbarung umfassen alle technischen Daten, Quellcodes, Schnittstellendesigns, Geschäftsmodelle und Prozessabläufe.</p>

                  <h3 style="font-size: 13px; font-weight: 700; color: #0f172a; margin: 16px 0 6px 0;">§ 2 Geheimhaltungspflichten & Datensicherheit</h3>
                  <p>Die empfangende Partei verpflichtet sich, sämtliche überlassenen Informationen streng vertraulich zu behandeln, sie vor unbefugtem Zugriff Dritter durch dem Stand der Technik entsprechende Sicherheitsmaßnahmen zu schützen und ausschließlich zum vertraglich vereinbarten Zweck zu nutzen.</p>

                  <h3 style="font-size: 13px; font-weight: 700; color: #0f172a; margin: 16px 0 6px 0;">§ 3 Laufzeit & Rückgabepflicht</h3>
                  <p>Diese Vereinbarung tritt mit Unterzeichnung in Kraft. Die Geheimhaltungspflicht besteht für einen Zeitraum von 5 Jahren über die Beendigung der Gespräche hinaus fort. Auf schriftliche Anforderung sind sämtliche Unterlagen und Datenträger vollständig zu vernichten oder herauszugeben.</p>
                </div>

                <!-- Unterschriftenblock -->
                <div style="margin-top: 50px; display: grid; grid-template-columns: 1fr 1fr; gap: 40px; font-size: 12px;">
                  <div>
                    <div style="color: #64748b; margin-bottom: 40px;">{c_city}, den {today_de}</div>
                    <div style="border-top: 1px solid #0f172a; padding-top: 8px;">
                      <div style="font-weight: 700; color: #0f172a;">{c_name}</div>
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

              <!-- Footer -->
              <div style="border-top: 1px solid #e2e8f0; padding-top: 10px; margin-top: 30px; text-align: center; font-size: 9.5px; color: #94a3b8;">
                {c_name} • {c_court} {c_hrb} • USt-IdNr.: {c_vatid} • Vertraulichkeitsstufe: DSGVO / Geschäftsgeheimnisgesetz
              </div>
            </div>
            """

        else:
            rendered_html = f"<div style='font-family: sans-serif; padding: 20px;'>Unbekannter Vorlagentyp: {template_type}</div>"

        return {
            "template_type": template_type,
            "company_id": company.get("id"),
            "company_name": c_name,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "html": rendered_html
        }


# Singleton instance
corporate_manager = CorporateManager()
