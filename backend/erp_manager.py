"""
backend/erp_manager.py
Archon OS 2026 — Multi-Tenant CRM & Mini-ERP Engine (Säule 3: WIRTSCHAFT & ERP).

Kern-Architektur:
- Physische Mandantentrennung (DSGVO & GoBD): Jede Company (`company_id`) erhält ihre eigene
  isolierte SQLite-WAL-Datenbank unter `data/tenants/{company_id}/erp.db`.
- Party-Modell (`crm_entities`) mit Rollen-Flags (`is_customer`, `is_supplier`, `is_partner`)
  und automatischen DATEV-Nummernkreisen (`10001+` Debitoren, `70001+` Kreditoren).
- 1:n Ansprechpartner (`crm_contacts`) inkl. LinkedIn-CRM-Feldern (0-5 Sterne Rating,
  Verbindungsstatus, DSGVO-Opt-In) und Kommunikations-Timeline (`crm_interactions`).
- Artikel- & Leistungsstamm (`erp_items`) mit VK/EK-Margenkalkulation und optionalem Lagerbestand.
- Belegfluss-Engine (`erp_documents` & `erp_document_lines`): Angebot (ANG) -> Auftrag (AB) ->
  Rechnung (RE) -> Gutschrift (GS) mit GoBD-Adress-Snapshot und 1-Klick-Belegumwandlung.
- Laptop-PocketBase-Synchronisation (`kontakte` Collection) pro Mandant.
"""

import os
import re
import csv
import io
import json
import uuid
import hashlib
import sqlite3
import datetime
import urllib.request
import urllib.error
import collections
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TENANTS_BASE_DIR = os.path.join(WORKSPACE_DIR, "data", "tenants")


def _sanitize_company_id(company_id: Optional[str]) -> str:
    if not company_id:
        try:
            from backend.corporate_manager import corporate_manager
            active = corporate_manager.get_company()
            if active and active.get("id"):
                company_id = active["id"]
        except Exception:
            pass
    cid = (company_id or "archon-systems").strip()
    cid = re.sub(r"[^a-zA-Z0-9_-]", "-", cid)
    return cid or "archon-systems"


def get_tenant_db_path(company_id: Optional[str] = None) -> str:
    cid = _sanitize_company_id(company_id)
    tenant_dir = os.path.join(TENANTS_BASE_DIR, cid)
    os.makedirs(tenant_dir, exist_ok=True)
    return os.path.join(tenant_dir, "erp.db")


class ERPManager:
    """Mandantenfähige CRM- & Mini-ERP-Engine für Archon OS."""

    def __init__(self):
        os.makedirs(TENANTS_BASE_DIR, exist_ok=True)
        self._initialized_tenants = set()

    def _get_conn(self, company_id: Optional[str] = None) -> Tuple[sqlite3.Connection, str]:
        cid = _sanitize_company_id(company_id)
        db_path = get_tenant_db_path(cid)
        is_new_file = not os.path.exists(db_path)

        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row

        if cid not in self._initialized_tenants or is_new_file:
            self._init_schema(conn, cid, is_new_file)
            self._initialized_tenants.add(cid)

        return conn, cid

    def _init_schema(self, conn: sqlite3.Connection, cid: str, is_new_file: bool):
        with conn:
            # 1. Nummernkreise (DATEV & Belege)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS erp_sequences (
                    seq_key TEXT PRIMARY KEY,
                    current_val INTEGER NOT NULL
                )
            """)
            default_sequences = [
                ("debtor", 10000),      # Nächster Kunde: 10001
                ("creditor", 70000),    # Nächster Lieferant: 70001
                ("item", 1000),         # Nächster Artikel: ART-1001
                ("offer", 0),           # ANG-YYYY-0001
                ("order", 0),           # AB-YYYY-0001
                ("invoice", 0),         # RE-YYYY-0001
                ("credit_note", 0),     # GS-YYYY-0001
            ]
            for k, v in default_sequences:
                conn.execute(
                    "INSERT OR IGNORE INTO erp_sequences (seq_key, current_val) VALUES (?, ?)",
                    (k, v)
                )

            # 2. PocketBase Sync-Konfiguration pro Mandant
            conn.execute("""
                CREATE TABLE IF NOT EXISTS erp_sync_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    pocketbase_url TEXT DEFAULT 'http://127.0.0.1:8090',
                    collection_name TEXT DEFAULT 'kontakte',
                    sync_enabled INTEGER DEFAULT 1,
                    last_sync_at TEXT DEFAULT '',
                    last_sync_status TEXT DEFAULT 'idle',
                    last_sync_summary TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO erp_sync_config (id, pocketbase_url, collection_name, sync_enabled)
                VALUES (1, 'http://127.0.0.1:8090', 'kontakte', ?)
            """, (1 if cid == "archon-systems" else 0,))

            # 3. Geschäftspartner / Adressen (crm_entities)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crm_entities (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL DEFAULT 'organization',
                    display_name TEXT NOT NULL,
                    legal_form TEXT DEFAULT '',
                    is_customer INTEGER DEFAULT 0,
                    is_supplier INTEGER DEFAULT 0,
                    is_partner INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'lead',
                    debtor_no TEXT,
                    creditor_no TEXT,
                    vat_id TEXT DEFAULT '',
                    tax_number TEXT DEFAULT '',
                    tax_regime TEXT DEFAULT 'standard_19',
                    registry_court TEXT DEFAULT '',
                    registry_number TEXT DEFAULT '',
                    payment_terms_days INTEGER DEFAULT 14,
                    skonto_pct REAL DEFAULT 0.0,
                    skonto_days INTEGER DEFAULT 0,
                    currency TEXT DEFAULT 'EUR',
                    credit_limit REAL DEFAULT 0.0,
                    dunning_block INTEGER DEFAULT 0,
                    bank_name TEXT DEFAULT '',
                    iban TEXT DEFAULT '',
                    bic TEXT DEFAULT '',
                    sepa_mandate_ref TEXT DEFAULT '',
                    street TEXT DEFAULT '',
                    postal_code TEXT DEFAULT '',
                    city TEXT DEFAULT '',
                    country_code TEXT DEFAULT 'DE',
                    billing_email TEXT DEFAULT '',
                    phone_main TEXT DEFAULT '',
                    website TEXT DEFAULT '',
                    industry TEXT DEFAULT '',
                    leitweg_id TEXT DEFAULT '',
                    rating INTEGER DEFAULT 0,
                    tags_json TEXT DEFAULT '[]',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON crm_entities(display_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_roles ON crm_entities(is_customer, is_supplier, is_partner);")

            # 4. Ansprechpartner & LinkedIn-Kontakte (1:n crm_contacts)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crm_contacts (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT,
                    salutation TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    last_name TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role_title TEXT DEFAULT '',
                    department TEXT DEFAULT '',
                    is_primary INTEGER DEFAULT 0,
                    is_billing_recipient INTEGER DEFAULT 0,
                    email TEXT DEFAULT '',
                    phone_direct TEXT DEFAULT '',
                    phone_mobile TEXT DEFAULT '',
                    linkedin_url TEXT DEFAULT '',
                    connection_status TEXT DEFAULT 'Vernetzt',
                    connected_since TEXT DEFAULT '',
                    rating INTEGER DEFAULT 0,
                    tags_json TEXT DEFAULT '[]',
                    gdpr_opt_in_status TEXT DEFAULT 'legitimate_interest',
                    gdpr_opt_in_date TEXT DEFAULT '',
                    pocketbase_id TEXT,
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES crm_entities(id) ON DELETE SET NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_entity ON crm_contacts(entity_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON crm_contacts(email);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_pb ON crm_contacts(pocketbase_id);")

            # 5. Kommunikations-Timeline (crm_interactions)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crm_interactions (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT,
                    contact_id TEXT,
                    channel TEXT NOT NULL DEFAULT 'email_in',
                    direction TEXT DEFAULT 'inbound',
                    external_msg_id TEXT UNIQUE,
                    sender_name TEXT DEFAULT '',
                    sender_email TEXT DEFAULT '',
                    subject TEXT DEFAULT '',
                    body_text TEXT DEFAULT '',
                    security_status TEXT DEFAULT 'safe',
                    occurred_at TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES crm_entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_entity ON crm_interactions(entity_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_contact ON crm_interactions(contact_id);")

            # 6. Artikel- & Leistungsstamm (erp_items)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS erp_items (
                    id TEXT PRIMARY KEY,
                    item_no TEXT UNIQUE NOT NULL,
                    item_type TEXT NOT NULL DEFAULT 'service',
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category TEXT DEFAULT 'Consulting',
                    unit TEXT DEFAULT 'Std.',
                    sales_price_net REAL DEFAULT 0.0,
                    purchase_price_net REAL DEFAULT 0.0,
                    tax_rate_pct REAL DEFAULT 19.0,
                    currency TEXT DEFAULT 'EUR',
                    billing_interval TEXT DEFAULT 'one_off',
                    supplier_entity_id TEXT,
                    track_inventory INTEGER DEFAULT 0,
                    stock_qty REAL DEFAULT 0.0,
                    min_stock_qty REAL DEFAULT 0.0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (supplier_entity_id) REFERENCES crm_entities(id) ON DELETE SET NULL
                )
            """)

            # 7. Kaufmännische Belege (erp_documents: Angebot, Auftrag, Rechnung, Gutschrift)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS erp_documents (
                    id TEXT PRIMARY KEY,
                    doc_type TEXT NOT NULL,
                    doc_number TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    entity_id TEXT NOT NULL,
                    contact_id TEXT,
                    source_doc_id TEXT,
                    deal_id TEXT,
                    contract_id TEXT,
                    recipient_snapshot_json TEXT NOT NULL,
                    issue_date TEXT NOT NULL,
                    service_date TEXT DEFAULT '',
                    due_date TEXT DEFAULT '',
                    amount_net REAL DEFAULT 0.0,
                    tax_amount REAL DEFAULT 0.0,
                    amount_gross REAL DEFAULT 0.0,
                    currency TEXT DEFAULT 'EUR',
                    tax_regime TEXT DEFAULT 'standard_19',
                    payment_terms_days INTEGER DEFAULT 14,
                    dunning_level INTEGER DEFAULT 0,
                    dunning_fee REAL DEFAULT 0.0,
                    stock_deducted INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    booked_at TEXT,
                    paid_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES crm_entities(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_type_status ON erp_documents(doc_type, status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_entity ON erp_documents(entity_id);")

            # 8. Belegpositionen (erp_document_lines)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS erp_document_lines (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    pos_no INTEGER NOT NULL,
                    item_id TEXT,
                    item_no_snapshot TEXT DEFAULT '',
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    quantity REAL NOT NULL DEFAULT 1.0,
                    unit TEXT DEFAULT 'Stk.',
                    unit_price_net REAL NOT NULL DEFAULT 0.0,
                    discount_pct REAL DEFAULT 0.0,
                    tax_rate_pct REAL NOT NULL DEFAULT 19.0,
                    line_net REAL NOT NULL DEFAULT 0.0,
                    line_tax REAL NOT NULL DEFAULT 0.0,
                    line_gross REAL NOT NULL DEFAULT 0.0,
                    FOREIGN KEY (document_id) REFERENCES erp_documents(id) ON DELETE CASCADE,
                    FOREIGN KEY (item_id) REFERENCES erp_items(id) ON DELETE SET NULL
                )
            """)

            # 9. Banktransaktionen & OPOS-Zahlungsabgleich (M28: CAMT.053 / MT940 / Bank-CSV)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS erp_bank_transactions (
                    id TEXT PRIMARY KEY,
                    booking_date TEXT NOT NULL,
                    value_date TEXT DEFAULT '',
                    amount REAL NOT NULL,
                    currency TEXT DEFAULT 'EUR',
                    counterparty_name TEXT DEFAULT '',
                    counterparty_iban TEXT DEFAULT '',
                    remittance_info TEXT DEFAULT '',
                    end_to_end_id TEXT DEFAULT '',
                    source_format TEXT DEFAULT 'csv',
                    tx_hash TEXT UNIQUE NOT NULL,
                    matched_doc_id TEXT DEFAULT '',
                    matched_doc_number TEXT DEFAULT '',
                    match_confidence REAL DEFAULT 0.0,
                    match_status TEXT DEFAULT 'unmatched',
                    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_tx_status ON erp_bank_transactions(match_status, booking_date);")

            # Safe schema migrations for pre-existing tenant DBs (M28)
            ent_cols = {r["name"] for r in conn.execute("PRAGMA table_info(crm_entities)").fetchall()}
            if "leitweg_id" not in ent_cols:
                conn.execute("ALTER TABLE crm_entities ADD COLUMN leitweg_id TEXT DEFAULT ''")
            doc_cols = {r["name"] for r in conn.execute("PRAGMA table_info(erp_documents)").fetchall()}
            if "stock_deducted" not in doc_cols:
                conn.execute("ALTER TABLE erp_documents ADD COLUMN stock_deducted INTEGER DEFAULT 0")

        # Seed initial basis data ONLY for primary company if completely empty
        if cid == "archon-systems":
            count_ent = conn.execute("SELECT COUNT(*) FROM crm_entities").fetchone()[0]
            if count_ent == 0:
                self._seed_primary_tenant(conn)

    def _next_sequence(self, conn: sqlite3.Connection, seq_key: str) -> int:
        conn.execute(
            "UPDATE erp_sequences SET current_val = current_val + 1 WHERE seq_key = ?",
            (seq_key,)
        )
        row = conn.execute(
            "SELECT current_val FROM erp_sequences WHERE seq_key = ?",
            (seq_key,)
        ).fetchone()
        return int(row["current_val"]) if row else 1

    def _format_doc_number(self, conn: sqlite3.Connection, doc_type: str) -> str:
        prefix_map = {
            "offer": "ANG",
            "order": "AB",
            "invoice": "RE",
            "credit_note": "GS"
        }
        seq_key = doc_type if doc_type in prefix_map else "offer"
        num = self._next_sequence(conn, seq_key)
        year = datetime.date.today().year
        return f"{prefix_map.get(doc_type, 'DOK')}-{year}-{num:04d}"

    def _seed_primary_tenant(self, conn: sqlite3.Connection):
        """Legt initiale Referenzdaten für den Hauptmandanten archon-systems an."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.date.today().isoformat()
        due_14 = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()

        with conn:
            # 1. Kunde (Debitor 10001)
            deb_1 = str(self._next_sequence(conn, "debtor"))
            conn.execute("""
                INSERT INTO crm_entities (
                    id, entity_type, display_name, legal_form, is_customer, is_supplier, is_partner,
                    status, debtor_no, vat_id, tax_regime, registry_court, registry_number,
                    payment_terms_days, skonto_pct, skonto_days, credit_limit,
                    street, postal_code, city, country_code, billing_email, phone_main, website,
                    industry, rating, tags_json, notes, created_at, updated_at
                ) VALUES (?, 'organization', 'Nordstern Digital AG', 'AG', 1, 0, 1,
                    'active', ?, 'DE298410552', 'standard_19', 'AG Hamburg', 'HRB 154820',
                    14, 2.0, 7, 25000.0,
                    'speicherstadt 18', '20457', 'Hamburg', 'DE', 'rechnung@nordstern-digital.de',
                    '+49 40 319840-0', 'https://nordstern-digital.de',
                    'IT & Enterprise Cloud', 5, '["Enterprise", "Key Account", "LinkedIn"]',
                    'Strategischer Hauptkunde für autonome Agenten-Cluster.', ?, ?)
            """, ("ent-nordstern", deb_1, now, now))

            conn.execute("""
                INSERT INTO crm_contacts (
                    id, entity_id, salutation, first_name, last_name, full_name, role_title,
                    department, is_primary, is_billing_recipient, email, phone_direct,
                    linkedin_url, connection_status, connected_since, rating, tags_json,
                    gdpr_opt_in_status, gdpr_opt_in_date
                ) VALUES (
                    'cnt-nordstern-1', 'ent-nordstern', 'Herr', 'Dr. Lukas', 'Bergmann', 'Dr. Lukas Bergmann',
                    'CTO & Vorstand Technik', 'Executive Board', 1, 0,
                    'l.bergmann@nordstern-digital.de', '+49 40 319840-12',
                    'https://www.linkedin.com/in/lukas-bergmann-cto', 'Vernetzt', '2025-04-12', 5,
                    '["Entscheider", "Tech"]', 'double_opt_in', '2025-04-15'
                )
            """)
            conn.execute("""
                INSERT INTO crm_contacts (
                    id, entity_id, salutation, first_name, last_name, full_name, role_title,
                    department, is_primary, is_billing_recipient, email, phone_direct,
                    linkedin_url, connection_status, connected_since, rating, tags_json,
                    gdpr_opt_in_status
                ) VALUES (
                    'cnt-nordstern-2', 'ent-nordstern', 'Frau', 'Sabine', 'Krämer', 'Sabine Krämer',
                    'Head of Procurement & Finance', 'Einkauf / Buchhaltung', 0, 1,
                    'rechnung@nordstern-digital.de', '+49 40 319840-45',
                    'https://www.linkedin.com/in/sabine-kraemer-fin', 'Vernetzt', '2025-06-01', 4,
                    '["Buchhaltung", "Rechnungsempfänger"]', 'legitimate_interest'
                )
            """)

            # 2. Lieferant (Kreditor 70001)
            cred_1 = str(self._next_sequence(conn, "creditor"))
            conn.execute("""
                INSERT INTO crm_entities (
                    id, entity_type, display_name, legal_form, is_customer, is_supplier, is_partner,
                    status, creditor_no, vat_id, tax_regime, payment_terms_days,
                    bank_name, iban, bic,
                    street, postal_code, city, country_code, billing_email, website,
                    industry, rating, tags_json, notes, created_at, updated_at
                ) VALUES (?, 'organization', 'Hetzner Cloud Infrastructure GmbH', 'GmbH', 0, 1, 0,
                    'active', ?, 'DE812871812', 'standard_19', 14,
                    'Commerzbank Nürnberg', 'DE71 7604 0061 0123 4567 00', 'COBADEFFXXX',
                    'Industriestr. 25', '91710', 'Gunzenhausen', 'DE', 'billing@hetzner.com',
                    'https://www.hetzner.com', 'Cloud & Rechenzentrum', 5,
                    '["Lieferant", "Server", "GPU-Cluster"]',
                    'Primärer Infrastruktur-Lieferant für Archon Dedicated Nodes.', ?, ?)
            """, ("ent-hetzner", cred_1, now, now))

            # 3. LinkedIn-Lead / Netzwerk-Kontakt (ohne Debitoren-Nr.)
            conn.execute("""
                INSERT INTO crm_entities (
                    id, entity_type, display_name, legal_form, is_customer, is_supplier, is_partner,
                    status, street, postal_code, city, country_code, website,
                    industry, rating, tags_json, notes, created_at, updated_at
                ) VALUES ('ent-velox', 'organization', 'Velox MedTech Solutions GmbH', 'GmbH', 0, 0, 1,
                    'lead', 'Sendlinger Str. 44', '80331', 'München', 'DE', 'https://velox-medtech.de',
                    'Medizintechnik / ISO 13485', 4, '["LinkedIn Lead", "AI Act", "MedTech"]',
                    'Interesse an Archon Compliance-Modul (ISO 13485 & EU AI Act).', ?, ?)
            """, (now, now))

            conn.execute("""
                INSERT INTO crm_contacts (
                    id, entity_id, salutation, first_name, last_name, full_name, role_title,
                    department, is_primary, is_billing_recipient, email, phone_direct,
                    linkedin_url, connection_status, connected_since, rating, tags_json,
                    gdpr_opt_in_status
                ) VALUES (
                    'cnt-velox-1', 'ent-velox', 'Frau', 'lena', 'Vogel', 'Lena Vogel',
                    'VP Regulatory & Quality', 'QMS / Regulatory', 1, 1,
                    'l.vogel@velox-medtech.de', '+49 89 452190-10',
                    'https://www.linkedin.com/in/lena-vogel-qms', 'Vernetzt', '2026-09-18', 4,
                    '["LinkedIn Import", "MedTech"]', 'legitimate_interest'
                )
            """)

            # 4. Beispiel-Interaktionen (Timeline)
            conn.execute("""
                INSERT INTO crm_interactions (
                    id, entity_id, contact_id, channel, direction, external_msg_id,
                    sender_name, sender_email, subject, body_text, occurred_at
                ) VALUES (
                    'int-01', 'ent-nordstern', 'cnt-nordstern-1', 'email_in', 'inbound', 'seed_msg_01',
                    'Dr. Lukas Bergmann', 'l.bergmann@nordstern-digital.de',
                    'Freigabe Q4 Rollout Archon Enterprise Cluster',
                    'Hallo Michael, wir haben das Budget für den Q4-Ausbau freigegeben. Bitte schicke uns das aktualisierte Angebot inkl. Setup-Pauschale.',
                    ?
                )
            """, (today + " 09:15:00",))

            conn.execute("""
                INSERT INTO crm_interactions (
                    id, entity_id, contact_id, channel, direction, external_msg_id,
                    sender_name, sender_email, subject, body_text, occurred_at
                ) VALUES (
                    'int-02', 'ent-velox', 'cnt-velox-1', 'linkedin', 'outbound', 'seed_msg_02',
                    'Michael Keller', 'kontakt@archon-systems.de',
                    'LinkedIn Follow-up: Automatisierte ISO 13485 & AI Act Audits',
                    'Hallo Lena, vielen Dank für die Vernetzung! Wie besprochen sende ich dir gerne unsere Architektur-Übersicht für das regulatorische Dossier-Modul.',
                    ?
                )
            """, (today + " 10:05:00",))

            # 5. Artikelstamm (erp_items)
            items_seed = [
                (
                    "itm-01", f"ART-{self._next_sequence(conn, 'item')}", "saas",
                    "Archon OS Enterprise Node (Monatslizenz)",
                    "Dedizierter Agentic-OS-Cluster inkl. 57 Expertenprofilen, OmniRoute-Gateway & Security-Guard.",
                    "SaaS & Lizenzen", "Monat", 890.00, 145.00, 19.0, "monthly", "ent-hetzner", 0, 0, 0
                ),
                (
                    "itm-02", f"ART-{self._next_sequence(conn, 'item')}", "flat_rate",
                    "Onboarding & Custom RAG-Vault Integration",
                    "Schlüsselfertige Einrichtung des Mandanten-Wissensspeichers, DSGVO-Rollenkonzept und Team-Einweisung.",
                    " Implementierung", "Pauschal", 2400.00, 400.00, 19.0, "one_off", None, 0, 0, 0
                ),
                (
                    "itm-03", f"ART-{self._next_sequence(conn, 'item')}", "service",
                    "Senior AI Solution Architect (Tagessatz)",
                    "Architekturberatung, Prompt-Engineering nach ASD-STE100 und Custom-Skill-Entwicklung.",
                    "Consulting", "Tag", 1450.00, 0.00, 19.0, "one_off", None, 0, 0, 0
                ),
                (
                    "itm-04", f"ART-{self._next_sequence(conn, 'item')}", "product",
                    "Archon Edge AI Appliance (Local Inference Box)",
                    "Vorkonfigurierter Edge-Server (64 GB Unified Memory, NVMe RAID) für 100% lokale Air-Gapped LLMs.",
                    "IT-Hardware", "Stk.", 3490.00, 2150.00, 19.0, "one_off", "ent-hetzner", 1, 4.0, 2.0
                ),
            ]
            for itm in items_seed:
                conn.execute("""
                    INSERT INTO erp_items (
                        id, item_no, item_type, title, description, category, unit,
                        sales_price_net, purchase_price_net, tax_rate_pct, billing_interval,
                        supplier_entity_id, track_inventory, stock_qty, min_stock_qty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, itm)

            # 6. Beispiel-Angebot (ANG) & Beispiel-Rechnung (RE)
            snapshot_nordstern = json.dumps({
                "display_name": "Nordstern Digital AG",
                "legal_form": "AG",
                "debtor_no": deb_1,
                "vat_id": "DE298410552",
                "contact_name": "Dr. Lukas Bergmann",
                "street": "Speicherstadt 18",
                "postal_code": "20457",
                "city": "Hamburg",
                "country_code": "DE"
            }, ensure_ascii=False)

            offer_no = self._format_doc_number(conn, "offer")
            conn.execute("""
                INSERT INTO erp_documents (
                    id, doc_type, doc_number, status, entity_id, contact_id,
                    recipient_snapshot_json, issue_date, service_date, due_date,
                    amount_net, tax_amount, amount_gross, currency, tax_regime, payment_terms_days,
                    notes
                ) VALUES (
                    'doc-offer-01', 'offer', ?, 'sent', 'ent-nordstern', 'cnt-nordstern-1',
                    ?, ?, ?, ?, 3290.00, 625.10, 3915.10, 'EUR', 'standard_19', 14,
                    'Angebot gültig für 30 Tage. Inkl. kostenfreiem Support im ersten Monat.'
                )
            """, (offer_no, snapshot_nordstern, today, today, due_14))

            conn.execute("""
                INSERT INTO erp_document_lines (
                    id, document_id, pos_no, item_id, item_no_snapshot, title, description,
                    quantity, unit, unit_price_net, discount_pct, tax_rate_pct,
                    line_net, line_tax, line_gross
                ) VALUES
                ('line-off-1', 'doc-offer-01', 1, 'itm-01', 'ART-1001',
                 'Archon OS Enterprise Node (Monatslizenz)',
                 'Dedizierter Agentic-OS-Cluster inkl. 57 Expertenprofilen',
                 1.0, 'Monat', 890.00, 0.0, 19.0, 890.00, 169.10, 1059.10),
                ('line-off-2', 'doc-offer-01', 2, 'itm-02', 'ART-1002',
                 'Onboarding & Custom RAG-Vault Integration',
                 'Schlüsselfertige Einrichtung des Mandanten-Wissensspeichers',
                 1.0, 'Pauschal', 2400.00, 0.0, 19.0, 2400.00, 456.00, 2856.00)
            """)

            inv_no = self._format_doc_number(conn, "invoice")
            conn.execute("""
                INSERT INTO erp_documents (
                    id, doc_type, doc_number, status, entity_id, contact_id, source_doc_id,
                    recipient_snapshot_json, issue_date, service_date, due_date,
                    amount_net, tax_amount, amount_gross, currency, tax_regime, payment_terms_days,
                    booked_at, notes
                ) VALUES (
                    'doc-inv-01', 'invoice', ?, 'booked', 'ent-nordstern', 'cnt-nordstern-2', 'doc-offer-01',
                    ?, ?, ?, ?, 1450.00, 275.50, 1725.50, 'EUR', 'standard_19', 14,
                    ?, 'Vielen Dank für Ihren Auftrag.'
                )
            """, (inv_no, snapshot_nordstern, today, today, due_14, now))

            conn.execute("""
                INSERT INTO erp_document_lines (
                    id, document_id, pos_no, item_id, item_no_snapshot, title, description,
                    quantity, unit, unit_price_net, discount_pct, tax_rate_pct,
                    line_net, line_tax, line_gross
                ) VALUES (
                    'line-inv-1', 'doc-inv-01', 1, 'itm-03', 'ART-1003',
                    'Senior AI Solution Architect (Tagessatz)',
                    'Architektur-Workshop & Sicherheits-Audit vor Ort',
                    1.0, 'Tag', 1450.00, 0.0, 19.0, 1450.00, 275.50, 1725.50
                )
            """)

    # =========================================================================
    # ÜBERSICHT / DASHBOARD-METRIKEN PRO MANDANT
    # =========================================================================

    def get_tenant_overview(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            total_entities = conn.execute("SELECT COUNT(*) FROM crm_entities WHERE status != 'archived'").fetchone()[0]
            customers_count = conn.execute("SELECT COUNT(*) FROM crm_entities WHERE is_customer = 1 AND status != 'archived'").fetchone()[0]
            suppliers_count = conn.execute("SELECT COUNT(*) FROM crm_entities WHERE is_supplier = 1 AND status != 'archived'").fetchone()[0]
            leads_count = conn.execute("SELECT COUNT(*) FROM crm_entities WHERE status = 'lead'").fetchone()[0]
            contacts_count = conn.execute("SELECT COUNT(*) FROM crm_contacts").fetchone()[0]
            items_count = conn.execute("SELECT COUNT(*) FROM erp_items WHERE is_active = 1").fetchone()[0]

            offers_open = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_net), 0) FROM erp_documents WHERE doc_type = 'offer' AND status IN ('draft', 'sent')"
            ).fetchone()
            invoices_open = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_gross), 0) FROM erp_documents WHERE doc_type = 'invoice' AND status IN ('booked', 'sent', 'overdue')"
            ).fetchone()
            invoices_paid = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_gross), 0) FROM erp_documents WHERE doc_type = 'invoice' AND status = 'paid'"
            ).fetchone()

            sync_row = conn.execute("SELECT * FROM erp_sync_config WHERE id = 1").fetchone()

            return {
                "company_id": cid,
                "db_path": f"data/tenants/{cid}/erp.db",
                "counts": {
                    "entities": total_entities,
                    "customers": customers_count,
                    "suppliers": suppliers_count,
                    "leads": leads_count,
                    "contacts": contacts_count,
                    "items": items_count,
                    "open_offers": offers_open[0],
                    "open_offers_volume_net": round(float(offers_open[1]), 2),
                    "open_invoices": invoices_open[0],
                    "open_invoices_volume_gross": round(float(invoices_open[1]), 2),
                    "paid_invoices": invoices_paid[0],
                    "paid_invoices_volume_gross": round(float(invoices_paid[1]), 2),
                },
                "sync_config": dict(sync_row) if sync_row else {}
            }
        finally:
            conn.close()

    # =========================================================================
    # 1. ADRESSEN & CRM (crm_entities, crm_contacts, crm_interactions)
    # =========================================================================

    def list_entities(
        self,
        company_id: Optional[str] = None,
        role_filter: str = "all",
        search: str = "",
        status: str = ""
    ) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            clauses = ["e.status != 'archived'"]
            params: List[Any] = []

            rf = (role_filter or "all").lower()
            if rf == "customers":
                clauses.append("e.is_customer = 1")
            elif rf == "suppliers":
                clauses.append("e.is_supplier = 1")
            elif rf == "leads":
                clauses.append("e.status = 'lead'")
            elif rf == "network":
                clauses.append("(e.is_partner = 1 OR (e.is_customer = 0 AND e.is_supplier = 0))")

            if status:
                clauses.append("e.status = ?")
                params.append(status)

            if search and search.strip():
                q = f"%{search.strip()}%"
                clauses.append("""(
                    e.display_name LIKE ? OR
                    e.city LIKE ? OR
                    e.debtor_no LIKE ? OR
                    e.creditor_no LIKE ? OR
                    e.industry LIKE ? OR
                    e.tags_json LIKE ? OR
                    EXISTS (
                        SELECT 1 FROM crm_contacts c
                        WHERE c.entity_id = e.id
                        AND (c.full_name LIKE ? OR c.email LIKE ? OR c.role_title LIKE ?)
                    )
                )""")
                params.extend([q, q, q, q, q, q, q, q, q])

            where_sql = " AND ".join(clauses)
            rows = conn.execute(f"""
                SELECT e.*,
                    (SELECT COUNT(*) FROM crm_contacts c WHERE c.entity_id = e.id) AS contacts_count,
                    (SELECT COUNT(*) FROM crm_interactions i WHERE i.entity_id = e.id) AS interactions_count,
                    (SELECT COALESCE(SUM(d.amount_gross), 0) FROM erp_documents d WHERE d.entity_id = e.id AND d.doc_type = 'invoice' AND d.status != 'cancelled') AS revenue_gross
                FROM crm_entities e
                WHERE {where_sql}
                ORDER BY e.rating DESC, e.updated_at DESC
            """, params).fetchall()

            # P-05: Batch-Query fuer Primary Contacts vermeidet N+1 SELECTs
            entity_ids = [r["id"] for r in rows]
            primary_contacts = {}
            if entity_ids:
                placeholders = ",".join("?" for _ in entity_ids)
                contact_rows = conn.execute(f"""
                    SELECT entity_id, id, full_name, role_title, email, phone_direct, linkedin_url, connection_status, rating
                    FROM (
                        SELECT entity_id, id, full_name, role_title, email, phone_direct, linkedin_url, connection_status, rating,
                               ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY is_primary DESC, rating DESC) as rn
                        FROM crm_contacts
                        WHERE entity_id IN ({placeholders})
                    )
                    WHERE rn = 1
                """, entity_ids).fetchall()
                for cr in contact_rows:
                    cd = dict(cr)
                    cd.pop("rn", None)
                    eid = cd.pop("entity_id")
                    primary_contacts[eid] = cd

            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags_json") or "[]")
                except Exception:
                    d["tags"] = []

                d["primary_contact"] = primary_contacts.get(d["id"])
                items.append(d)

            return {
                "company_id": cid,
                "total": len(items),
                "items": items
            }
        finally:
            conn.close()

    def get_entity_detail(self, entity_id: str, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn, cid = self._get_conn(company_id)
        try:
            row = conn.execute("SELECT * FROM crm_entities WHERE id = ?", (entity_id,)).fetchone()
            if not row:
                return None
            entity = dict(row)
            try:
                entity["tags"] = json.loads(entity.get("tags_json") or "[]")
            except Exception:
                entity["tags"] = []

            contacts = [
                dict(c) for c in conn.execute(
                    "SELECT * FROM crm_contacts WHERE entity_id = ? ORDER BY is_primary DESC, is_billing_recipient DESC, last_name ASC",
                    (entity_id,)
                ).fetchall()
            ]
            for c in contacts:
                try:
                    c["tags"] = json.loads(c.get("tags_json") or "[]")
                except Exception:
                    c["tags"] = []

            interactions = [
                dict(i) for i in conn.execute(
                    "SELECT * FROM crm_interactions WHERE entity_id = ? ORDER BY occurred_at DESC LIMIT 100",
                    (entity_id,)
                ).fetchall()
            ]

            documents = [
                dict(doc) for doc in conn.execute(
                    "SELECT * FROM erp_documents WHERE entity_id = ? ORDER BY issue_date DESC, created_at DESC",
                    (entity_id,)
                ).fetchall()
            ]

            return {
                "company_id": cid,
                "entity": entity,
                "contacts": contacts,
                "interactions": interactions,
                "documents": documents
            }
        finally:
            conn.close()

    def save_entity(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            eid = payload.get("id") or f"ent-{uuid.uuid4().hex[:8]}"
            existing = conn.execute("SELECT * FROM crm_entities WHERE id = ?", (eid,)).fetchone()
            existing_dict = dict(existing) if existing else {}

            is_customer = 1 if payload.get("is_customer", existing_dict.get("is_customer", 0)) else 0
            is_supplier = 1 if payload.get("is_supplier", existing_dict.get("is_supplier", 0)) else 0
            is_partner = 1 if payload.get("is_partner", existing_dict.get("is_partner", 0)) else 0

            debtor_no = payload.get("debtor_no") or existing_dict.get("debtor_no")
            creditor_no = payload.get("creditor_no") or existing_dict.get("creditor_no")

            with conn:
                # Automatische DATEV-Nummernvergabe bei Aktivierung der Rolle
                if is_customer and not debtor_no:
                    debtor_no = str(self._next_sequence(conn, "debtor"))
                if is_supplier and not creditor_no:
                    creditor_no = str(self._next_sequence(conn, "creditor"))

                tags = payload.get("tags")
                if isinstance(tags, list):
                    tags_json = json.dumps(tags, ensure_ascii=False)
                elif isinstance(tags, str) and tags.strip():
                    tags_json = json.dumps([t.strip() for t in tags.split(",") if t.strip()], ensure_ascii=False)
                else:
                    tags_json = existing_dict.get("tags_json", "[]")

                status = payload.get("status", existing_dict.get("status", "lead"))
                if (is_customer or is_supplier) and status == "lead" and "status" not in payload:
                    status = "active"

                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                conn.execute("""
                    INSERT INTO crm_entities (
                        id, entity_type, display_name, legal_form,
                        is_customer, is_supplier, is_partner, status,
                        debtor_no, creditor_no, vat_id, tax_number, tax_regime,
                        registry_court, registry_number, payment_terms_days,
                        skonto_pct, skonto_days, currency, credit_limit, dunning_block,
                        bank_name, iban, bic, sepa_mandate_ref,
                        street, postal_code, city, country_code,
                        billing_email, phone_main, website, industry, leitweg_id,
                        rating, tags_json, notes, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        entity_type=excluded.entity_type,
                        display_name=excluded.display_name,
                        legal_form=excluded.legal_form,
                        is_customer=excluded.is_customer,
                        is_supplier=excluded.is_supplier,
                        is_partner=excluded.is_partner,
                        status=excluded.status,
                        debtor_no=excluded.debtor_no,
                        creditor_no=excluded.creditor_no,
                        vat_id=excluded.vat_id,
                        tax_number=excluded.tax_number,
                        tax_regime=excluded.tax_regime,
                        registry_court=excluded.registry_court,
                        registry_number=excluded.registry_number,
                        payment_terms_days=excluded.payment_terms_days,
                        skonto_pct=excluded.skonto_pct,
                        skonto_days=excluded.skonto_days,
                        currency=excluded.currency,
                        credit_limit=excluded.credit_limit,
                        dunning_block=excluded.dunning_block,
                        bank_name=excluded.bank_name,
                        iban=excluded.iban,
                        bic=excluded.bic,
                        sepa_mandate_ref=excluded.sepa_mandate_ref,
                        street=excluded.street,
                        postal_code=excluded.postal_code,
                        city=excluded.city,
                        country_code=excluded.country_code,
                        billing_email=excluded.billing_email,
                        phone_main=excluded.phone_main,
                        website=excluded.website,
                        industry=excluded.industry,
                        leitweg_id=excluded.leitweg_id,
                        rating=excluded.rating,
                        tags_json=excluded.tags_json,
                        notes=excluded.notes,
                        updated_at=excluded.updated_at
                """, (
                    eid,
                    payload.get("entity_type", existing_dict.get("entity_type", "organization")),
                    payload.get("display_name", existing_dict.get("display_name", "Neue Adresse")).strip(),
                    payload.get("legal_form", existing_dict.get("legal_form", "")),
                    is_customer,
                    is_supplier,
                    is_partner,
                    status,
                    debtor_no,
                    creditor_no,
                    payload.get("vat_id", existing_dict.get("vat_id", "")),
                    payload.get("tax_number", existing_dict.get("tax_number", "")),
                    payload.get("tax_regime", existing_dict.get("tax_regime", "standard_19")),
                    payload.get("registry_court", existing_dict.get("registry_court", "")),
                    payload.get("registry_number", existing_dict.get("registry_number", "")),
                    int(payload.get("payment_terms_days", existing_dict.get("payment_terms_days", 14))),
                    float(payload.get("skonto_pct", existing_dict.get("skonto_pct", 0.0))),
                    int(payload.get("skonto_days", existing_dict.get("skonto_days", 0))),
                    payload.get("currency", existing_dict.get("currency", "EUR")),
                    float(payload.get("credit_limit", existing_dict.get("credit_limit", 0.0))),
                    1 if payload.get("dunning_block", existing_dict.get("dunning_block", 0)) else 0,
                    payload.get("bank_name", existing_dict.get("bank_name", "")),
                    payload.get("iban", existing_dict.get("iban", "")),
                    payload.get("bic", existing_dict.get("bic", "")),
                    payload.get("sepa_mandate_ref", existing_dict.get("sepa_mandate_ref", "")),
                    payload.get("street", existing_dict.get("street", "")),
                    payload.get("postal_code", existing_dict.get("postal_code", "")),
                    payload.get("city", existing_dict.get("city", "")),
                    payload.get("country_code", existing_dict.get("country_code", "DE")),
                    payload.get("billing_email", existing_dict.get("billing_email", "")),
                    payload.get("phone_main", existing_dict.get("phone_main", "")),
                    payload.get("website", existing_dict.get("website", "")),
                    payload.get("industry", existing_dict.get("industry", "")),
                    payload.get("leitweg_id", existing_dict.get("leitweg_id", "")),
                    int(payload.get("rating", existing_dict.get("rating", 0))),
                    tags_json,
                    payload.get("notes", existing_dict.get("notes", "")),
                    existing_dict.get("created_at", now),
                    now
                ))

            # Optional: Direkt mitgelieferten Hauptansprechpartner anlegen/aktualisieren
            if isinstance(payload.get("primary_contact"), dict):
                cp = dict(payload["primary_contact"])
                cp["entity_id"] = eid
                cp.setdefault("is_primary", 1)
                if cp.get("last_name") or cp.get("full_name"):
                    self.save_contact(cp, company_id=cid)

            return self.get_entity_detail(eid, company_id=cid)
        finally:
            conn.close()

    def save_contact(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            cnt_id = payload.get("id") or f"cnt-{uuid.uuid4().hex[:8]}"
            existing = conn.execute("SELECT * FROM crm_contacts WHERE id = ?", (cnt_id,)).fetchone()
            ex = dict(existing) if existing else {}

            first_name = payload.get("first_name", ex.get("first_name", "")).strip()
            last_name = payload.get("last_name", ex.get("last_name", "")).strip()
            full_name = payload.get("full_name", "").strip()
            if not full_name:
                full_name = f"{first_name} {last_name}".strip() or "Unbenannter Kontakt"
            if not last_name:
                parts = full_name.split(" ")
                last_name = parts[-1]
                first_name = " ".join(parts[:-1])

            entity_id = payload.get("entity_id", ex.get("entity_id"))
            is_primary = 1 if payload.get("is_primary", ex.get("is_primary", 0)) else 0
            is_billing = 1 if payload.get("is_billing_recipient", ex.get("is_billing_recipient", 0)) else 0

            tags = payload.get("tags")
            if isinstance(tags, list):
                tags_json = json.dumps(tags, ensure_ascii=False)
            else:
                tags_json = ex.get("tags_json", "[]")

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with conn:
                if is_primary and entity_id:
                    conn.execute("UPDATE crm_contacts SET is_primary = 0 WHERE entity_id = ?", (entity_id,))

                conn.execute("""
                    INSERT INTO crm_contacts (
                        id, entity_id, salutation, first_name, last_name, full_name,
                        role_title, department, is_primary, is_billing_recipient,
                        email, phone_direct, phone_mobile, linkedin_url,
                        connection_status, connected_since, rating, tags_json,
                        gdpr_opt_in_status, gdpr_opt_in_date, pocketbase_id, notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        entity_id=excluded.entity_id,
                        salutation=excluded.salutation,
                        first_name=excluded.first_name,
                        last_name=excluded.last_name,
                        full_name=excluded.full_name,
                        role_title=excluded.role_title,
                        department=excluded.department,
                        is_primary=excluded.is_primary,
                        is_billing_recipient=excluded.is_billing_recipient,
                        email=excluded.email,
                        phone_direct=excluded.phone_direct,
                        phone_mobile=excluded.phone_mobile,
                        linkedin_url=excluded.linkedin_url,
                        connection_status=excluded.connection_status,
                        connected_since=excluded.connected_since,
                        rating=excluded.rating,
                        tags_json=excluded.tags_json,
                        gdpr_opt_in_status=excluded.gdpr_opt_in_status,
                        gdpr_opt_in_date=excluded.gdpr_opt_in_date,
                        pocketbase_id=COALESCE(excluded.pocketbase_id, crm_contacts.pocketbase_id),
                        notes=excluded.notes,
                        updated_at=excluded.updated_at
                """, (
                    cnt_id,
                    entity_id,
                    payload.get("salutation", ex.get("salutation", "")),
                    first_name,
                    last_name,
                    full_name,
                    payload.get("role_title", ex.get("role_title", "")),
                    payload.get("department", ex.get("department", "")),
                    is_primary,
                    is_billing,
                    payload.get("email", ex.get("email", "")),
                    payload.get("phone_direct", ex.get("phone_direct", "")),
                    payload.get("phone_mobile", ex.get("phone_mobile", "")),
                    payload.get("linkedin_url", ex.get("linkedin_url", "")),
                    payload.get("connection_status", ex.get("connection_status", "Vernetzt")),
                    payload.get("connected_since", ex.get("connected_since", "")),
                    int(payload.get("rating", ex.get("rating", 0))),
                    tags_json,
                    payload.get("gdpr_opt_in_status", ex.get("gdpr_opt_in_status", "legitimate_interest")),
                    payload.get("gdpr_opt_in_date", ex.get("gdpr_opt_in_date", "")),
                    payload.get("pocketbase_id", ex.get("pocketbase_id")),
                    payload.get("notes", ex.get("notes", "")),
                    ex.get("created_at", now),
                    now
                ))

            row = conn.execute("SELECT * FROM crm_contacts WHERE id = ?", (cnt_id,)).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def add_interaction(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            iid = payload.get("id") or f"int-{uuid.uuid4().hex[:8]}"
            ext_id = payload.get("external_msg_id") or f"manual_{iid}"
            occurred_at = payload.get("occurred_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entity_id = payload.get("entity_id")
            contact_id = payload.get("contact_id")

            with conn:
                conn.execute("""
                    INSERT OR IGNORE INTO crm_interactions (
                        id, entity_id, contact_id, channel, direction, external_msg_id,
                        sender_name, sender_email, subject, body_text, security_status, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    iid,
                    entity_id,
                    contact_id,
                    payload.get("channel", "note"),
                    payload.get("direction", "outbound"),
                    ext_id,
                    payload.get("sender_name", "Archon User"),
                    payload.get("sender_email", ""),
                    payload.get("subject", "Notiz / Interaktion"),
                    payload.get("body_text", ""),
                    payload.get("security_status", "safe"),
                    occurred_at
                ))
            row = conn.execute("SELECT * FROM crm_interactions WHERE external_msg_id = ?", (ext_id,)).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    # =========================================================================
    # 2. ARTIKEL & LEISTUNGEN (erp_items)
    # =========================================================================

    @staticmethod
    def _enrich_item_margins(item: Dict[str, Any]) -> Dict[str, Any]:
        vk = float(item.get("sales_price_net") or 0.0)
        ek = float(item.get("purchase_price_net") or 0.0)
        margin_eur = round(vk - ek, 2)
        margin_pct = round((margin_eur / vk) * 100.0, 1) if vk > 0 else 0.0
        item["margin_eur"] = margin_eur
        item["margin_pct"] = margin_pct
        item["sales_price_gross"] = round(vk * (1.0 + float(item.get("tax_rate_pct") or 19.0) / 100.0), 2)
        return item

    def list_items(
        self,
        company_id: Optional[str] = None,
        item_type: str = "all",
        search: str = ""
    ) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            clauses = ["i.is_active = 1"]
            params: List[Any] = []

            if item_type and item_type != "all":
                clauses.append("i.item_type = ?")
                params.append(item_type)

            if search and search.strip():
                q = f"%{search.strip()}%"
                clauses.append("(i.item_no LIKE ? OR i.title LIKE ? OR i.description LIKE ? OR i.category LIKE ?)")
                params.extend([q, q, q, q])

            where_sql = " AND ".join(clauses)
            rows = conn.execute(f"""
                SELECT i.*, e.display_name AS supplier_name, e.creditor_no AS supplier_creditor_no
                FROM erp_items i
                LEFT JOIN crm_entities e ON i.supplier_entity_id = e.id
                WHERE {where_sql}
                ORDER BY i.item_no ASC
            """, params).fetchall()

            items = [self._enrich_item_margins(dict(r)) for r in rows]
            return {"company_id": cid, "total": len(items), "items": items}
        finally:
            conn.close()

    def save_item(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            iid = payload.get("id") or f"itm-{uuid.uuid4().hex[:8]}"
            existing = conn.execute("SELECT * FROM erp_items WHERE id = ?", (iid,)).fetchone()
            ex = dict(existing) if existing else {}

            item_no = (payload.get("item_no") or ex.get("item_no") or "").strip()
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with conn:
                if not item_no:
                    seq = self._next_sequence(conn, "item")
                    item_no = f"ART-{seq}"

                conn.execute("""
                    INSERT INTO erp_items (
                        id, item_no, item_type, title, description, category, unit,
                        sales_price_net, purchase_price_net, tax_rate_pct, currency,
                        billing_interval, supplier_entity_id, track_inventory,
                        stock_qty, min_stock_qty, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        item_no=excluded.item_no,
                        item_type=excluded.item_type,
                        title=excluded.title,
                        description=excluded.description,
                        category=excluded.category,
                        unit=excluded.unit,
                        sales_price_net=excluded.sales_price_net,
                        purchase_price_net=excluded.purchase_price_net,
                        tax_rate_pct=excluded.tax_rate_pct,
                        currency=excluded.currency,
                        billing_interval=excluded.billing_interval,
                        supplier_entity_id=excluded.supplier_entity_id,
                        track_inventory=excluded.track_inventory,
                        stock_qty=excluded.stock_qty,
                        min_stock_qty=excluded.min_stock_qty,
                        is_active=excluded.is_active,
                        updated_at=excluded.updated_at
                """, (
                    iid,
                    item_no,
                    payload.get("item_type", ex.get("item_type", "service")),
                    payload.get("title", ex.get("title", "Neuer Artikel")).strip(),
                    payload.get("description", ex.get("description", "")),
                    payload.get("category", ex.get("category", "Consulting")),
                    payload.get("unit", ex.get("unit", "Std.")),
                    float(payload.get("sales_price_net", ex.get("sales_price_net", 0.0))),
                    float(payload.get("purchase_price_net", ex.get("purchase_price_net", 0.0))),
                    float(payload.get("tax_rate_pct", ex.get("tax_rate_pct", 19.0))),
                    payload.get("currency", ex.get("currency", "EUR")),
                    payload.get("billing_interval", ex.get("billing_interval", "one_off")),
                    payload.get("supplier_entity_id") or ex.get("supplier_entity_id"),
                    1 if payload.get("track_inventory", ex.get("track_inventory", 0)) else 0,
                    float(payload.get("stock_qty", ex.get("stock_qty", 0.0))),
                    float(payload.get("min_stock_qty", ex.get("min_stock_qty", 0.0))),
                    int(payload.get("is_active", ex.get("is_active", 1))),
                    ex.get("created_at", now),
                    now
                ))

            row = conn.execute("SELECT * FROM erp_items WHERE id = ?", (iid,)).fetchone()
            return self._enrich_item_margins(dict(row)) if row else {}
        finally:
            conn.close()

    # =========================================================================
    # 3. BELEGE & VORGÄNGE (erp_documents & erp_document_lines)
    # =========================================================================

    def list_documents(
        self,
        company_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        status: Optional[str] = None,
        entity_id: Optional[str] = None
    ) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            clauses = ["1=1"]
            params: List[Any] = []

            if doc_type and doc_type != "all":
                clauses.append("d.doc_type = ?")
                params.append(doc_type)
            if status and status != "all":
                clauses.append("d.status = ?")
                params.append(status)
            if entity_id:
                clauses.append("d.entity_id = ?")
                params.append(entity_id)

            where_sql = " AND ".join(clauses)
            rows = conn.execute(f"""
                SELECT d.*, e.display_name AS entity_name, e.debtor_no, e.dunning_block
                FROM erp_documents d
                LEFT JOIN crm_entities e ON d.entity_id = e.id
                WHERE {where_sql}
                ORDER BY d.issue_date DESC, d.created_at DESC
            """, params).fetchall()

            # P-05: Batch-Query fuer Document-Lines vermeidet N+1 SELECTs
            doc_ids = [r["id"] for r in rows]
            lines_by_doc = collections.defaultdict(list)
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                lines = conn.execute(
                    f"SELECT * FROM erp_document_lines WHERE document_id IN ({placeholders}) ORDER BY pos_no ASC",
                    doc_ids
                ).fetchall()
                for l in lines:
                    ld = dict(l)
                    lines_by_doc[ld["document_id"]].append(ld)

            docs = []
            for r in rows:
                d = dict(r)
                try:
                    d["recipient_snapshot"] = json.loads(d.get("recipient_snapshot_json") or "{}")
                except Exception:
                    d["recipient_snapshot"] = {}
                d["lines"] = lines_by_doc.get(d["id"], [])
                docs.append(d)

            return {"company_id": cid, "total": len(docs), "items": docs}
        finally:
            conn.close()

    def get_document(self, doc_id: str, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn, cid = self._get_conn(company_id)
        try:
            row = conn.execute("""
                SELECT d.*, e.display_name AS entity_name, e.debtor_no, e.dunning_block
                FROM erp_documents d
                LEFT JOIN crm_entities e ON d.entity_id = e.id
                WHERE d.id = ?
            """, (doc_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["recipient_snapshot"] = json.loads(d.get("recipient_snapshot_json") or "{}")
            except Exception:
                d["recipient_snapshot"] = {}
            lines = conn.execute(
                "SELECT * FROM erp_document_lines WHERE document_id = ? ORDER BY pos_no ASC",
                (doc_id,)
            ).fetchall()
            d["lines"] = [dict(l) for l in lines]
            return d
        finally:
            conn.close()

    def _apply_inventory_stock_delta(self, conn: sqlite3.Connection, doc_id: str, sign: int) -> None:
        """Passt Lagerbestände (`stock_qty`) für Artikel mit `track_inventory = 1` atomar an (-1 Abbuchung, +1 Storno)."""
        lines = conn.execute(
            "SELECT item_id, quantity FROM erp_document_lines WHERE document_id = ? AND item_id IS NOT NULL",
            (doc_id,),
        ).fetchall()
        for row in lines:
            qty = float(row["quantity"] or 0.0)
            if qty <= 0:
                continue
            conn.execute(
                """
                UPDATE erp_items
                SET stock_qty = stock_qty + ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND track_inventory = 1
                """,
                (round(sign * qty, 4), row["item_id"]),
            )
        conn.execute(
            "UPDATE erp_documents SET stock_deducted = ? WHERE id = ?",
            (1 if sign < 0 else 0, doc_id),
        )

    def save_document(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            doc_id = payload.get("id") or f"doc-{uuid.uuid4().hex[:8]}"
            existing = conn.execute("SELECT * FROM erp_documents WHERE id = ?", (doc_id,)).fetchone()
            ex = dict(existing) if existing else {}

            # GoBD-Unveränderbarkeitsschutz: Gebuchte, versendete, bezahlte oder stornierte Belege dürfen nicht zurück
            # in den Entwurf und ändern keine Positionen/Beträge/Stammdaten mehr in-place.
            if ex and (ex.get("status") in ("booked", "sent", "paid", "cancelled") or ex.get("booked_at")) and not payload.get("_allow_status_update_only"):
                cur_status = ex.get("status")
                new_status = payload.get("status", cur_status)
                if new_status == "draft":
                    raise ValueError(f"GoBD-Verstoß: Ein festgeschriebener Beleg ('{cur_status}') darf nicht zurück in den Entwurf ('draft') gesetzt werden.")
                if cur_status == "paid" and new_status != "paid":
                    raise ValueError(f"GoBD-Verstoß: Ein bezahlter Beleg darf nicht auf '{new_status}' zurückgesetzt werden.")
                if cur_status == "cancelled" and new_status != "cancelled":
                    raise ValueError(f"GoBD-Verstoß: Ein stornierter Beleg darf nicht auf '{new_status}' reaktiviert werden.")
                paid_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status == "paid" else ex.get("paid_at")
                booked_at = ex.get("booked_at")
                if new_status in ("booked", "sent") and not booked_at:
                    booked_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with conn:
                    conn.execute(
                        "UPDATE erp_documents SET status = ?, paid_at = ?, booked_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_status, paid_at, booked_at, doc_id)
                    )
                    if ex.get("doc_type") == "invoice":
                        if new_status == "cancelled" and int(ex.get("stock_deducted") or 0) == 1:
                            self._apply_inventory_stock_delta(conn, doc_id, sign=1)
                        elif new_status in ("booked", "paid") and int(ex.get("stock_deducted") or 0) == 0:
                            self._apply_inventory_stock_delta(conn, doc_id, sign=-1)
                return self.get_document(doc_id, company_id=cid)

            doc_type = payload.get("doc_type", ex.get("doc_type", "offer"))
            entity_id = payload.get("entity_id", ex.get("entity_id"))
            if not entity_id:
                raise ValueError("entity_id ist für einen kaufmännischen Beleg erforderlich.")

            ent_row = conn.execute("SELECT * FROM crm_entities WHERE id = ?", (entity_id,)).fetchone()
            if not ent_row:
                raise ValueError(f"Geschäftspartner {entity_id} nicht gefunden.")
            ent = dict(ent_row)

            contact_id = payload.get("contact_id", ex.get("contact_id"))
            cnt = None
            if contact_id:
                c_row = conn.execute("SELECT * FROM crm_contacts WHERE id = ?", (contact_id,)).fetchone()
                if c_row:
                    cnt = dict(c_row)
            if not cnt:
                c_row = conn.execute(
                    "SELECT * FROM crm_contacts WHERE entity_id = ? ORDER BY is_billing_recipient DESC, is_primary DESC LIMIT 1",
                    (entity_id,)
                ).fetchone()
                if c_row:
                    cnt = dict(c_row)
                    contact_id = cnt["id"]

            snapshot = {
                "display_name": ent.get("display_name", ""),
                "legal_form": ent.get("legal_form", ""),
                "debtor_no": ent.get("debtor_no", ""),
                "vat_id": ent.get("vat_id", ""),
                "leitweg_id": ent.get("leitweg_id", ""),
                "contact_name": cnt.get("full_name", "") if cnt else "",
                "contact_email": (cnt.get("email") if cnt and cnt.get("email") else ent.get("billing_email", "")),
                "street": ent.get("street", ""),
                "postal_code": ent.get("postal_code", ""),
                "city": ent.get("city", ""),
                "country_code": ent.get("country_code", "DE"),
            }

            tax_regime = payload.get("tax_regime") or ent.get("tax_regime") or "standard_19"
            zero_tax = tax_regime in ("reverse_charge", "intra_eu", "export_0", "small_business")

            if "lines" in payload:
                raw_lines = payload.get("lines", [])
                lines_provided = True
            elif ex:
                # Bestehende Positionen laden, damit Summen bei reinem Metadaten-Update
                # (z. B. Notizen, Fälligkeit) nicht auf 0.00 genullt werden (R-03)
                existing_lines = conn.execute(
                    "SELECT * FROM erp_document_lines WHERE document_id = ? ORDER BY pos_no ASC",
                    (doc_id,)
                ).fetchall()
                raw_lines = [dict(r) for r in existing_lines]
                lines_provided = False
            else:
                raw_lines = []
                lines_provided = True

            computed_lines = []
            total_net = 0.0
            total_tax = 0.0

            for idx, ln in enumerate(raw_lines, start=1):
                item_id = ln.get("item_id")
                item_no_snap = ln.get("item_no_snapshot", "")
                title = ln.get("title", "")
                desc = ln.get("description", "")
                unit = ln.get("unit", "Stk.")
                qty = float(ln.get("quantity", 1.0))
                price = float(ln.get("unit_price_net", 0.0))
                disc = float(ln.get("discount_pct", 0.0))
                tax_rate = 0.0 if zero_tax else float(ln.get("tax_rate_pct", 19.0))

                if item_id:
                    itm_row = conn.execute("SELECT * FROM erp_items WHERE id = ?", (item_id,)).fetchone()
                    if itm_row:
                        itm = dict(itm_row)
                        item_no_snap = item_no_snap or itm["item_no"]
                        title = title or itm["title"]
                        desc = desc or itm["description"]
                        unit = ln.get("unit") or itm["unit"]
                        if "unit_price_net" not in ln:
                            price = float(itm["sales_price_net"])
                        if not zero_tax and "tax_rate_pct" not in ln:
                            tax_rate = float(itm["tax_rate_pct"])

                line_net = round(qty * price * (1.0 - disc / 100.0), 2)
                line_tax = round(line_net * (tax_rate / 100.0), 2)
                line_gross = round(line_net + line_tax, 2)

                total_net += line_net
                total_tax += line_tax

                computed_lines.append({
                    "id": ln.get("id") or f"dl-{uuid.uuid4().hex[:8]}",
                    "pos_no": idx,
                    "item_id": item_id,
                    "item_no_snapshot": item_no_snap,
                    "title": title or "Position",
                    "description": desc,
                    "quantity": qty,
                    "unit": unit,
                    "unit_price_net": price,
                    "discount_pct": disc,
                    "tax_rate_pct": tax_rate,
                    "line_net": line_net,
                    "line_tax": line_tax,
                    "line_gross": line_gross
                })

            if not lines_provided and ex:
                total_net = float(ex.get("amount_net", 0.0))
                total_tax = float(ex.get("tax_amount", 0.0))
                total_gross = float(ex.get("amount_gross", 0.0))
            else:
                total_net = round(total_net, 2)
                total_tax = round(total_tax, 2)
                total_gross = round(total_net + total_tax, 2)

            issue_date = payload.get("issue_date") or ex.get("issue_date") or datetime.date.today().isoformat()
            pay_days = int(payload.get("payment_terms_days", ent.get("payment_terms_days", 14)))
            due_date = payload.get("due_date") or ex.get("due_date")
            if not due_date:
                try:
                    dt_issue = datetime.date.fromisoformat(issue_date)
                    due_date = (dt_issue + datetime.timedelta(days=pay_days)).isoformat()
                except Exception:
                    due_date = issue_date

            status = payload.get("status", ex.get("status", "draft"))
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            booked_at = ex.get("booked_at")
            if status in ("booked", "sent") and not booked_at:
                booked_at = now

            with conn:
                doc_number = ex.get("doc_number") or payload.get("doc_number")
                if not doc_number:
                    doc_number = self._format_doc_number(conn, doc_type)

                conn.execute("""
                    INSERT INTO erp_documents (
                        id, doc_type, doc_number, status, entity_id, contact_id,
                        source_doc_id, deal_id, contract_id, recipient_snapshot_json,
                        issue_date, service_date, due_date,
                        amount_net, tax_amount, amount_gross, currency,
                        tax_regime, payment_terms_days, notes, booked_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status=excluded.status,
                        entity_id=excluded.entity_id,
                        contact_id=excluded.contact_id,
                        recipient_snapshot_json=excluded.recipient_snapshot_json,
                        issue_date=excluded.issue_date,
                        service_date=excluded.service_date,
                        due_date=excluded.due_date,
                        amount_net=excluded.amount_net,
                        tax_amount=excluded.tax_amount,
                        amount_gross=excluded.amount_gross,
                        tax_regime=excluded.tax_regime,
                        payment_terms_days=excluded.payment_terms_days,
                        notes=excluded.notes,
                        booked_at=COALESCE(crm_entities_booked.booked_at, excluded.booked_at),
                        updated_at=excluded.updated_at
                """.replace("COALESCE(crm_entities_booked.booked_at, excluded.booked_at)", "COALESCE(erp_documents.booked_at, excluded.booked_at)"), (
                    doc_id,
                    doc_type,
                    doc_number,
                    status,
                    entity_id,
                    contact_id,
                    payload.get("source_doc_id", ex.get("source_doc_id")),
                    payload.get("deal_id", ex.get("deal_id")),
                    payload.get("contract_id", ex.get("contract_id")),
                    json.dumps(snapshot, ensure_ascii=False),
                    issue_date,
                    payload.get("service_date", ex.get("service_date", issue_date)),
                    due_date,
                    total_net,
                    total_tax,
                    total_gross,
                    payload.get("currency", ent.get("currency", "EUR")),
                    tax_regime,
                    pay_days,
                    payload.get("notes", ex.get("notes", "")),
                    booked_at,
                    ex.get("created_at", now),
                    now
                ))

                if lines_provided and computed_lines:
                    conn.execute("DELETE FROM erp_document_lines WHERE document_id = ?", (doc_id,))
                    for cl in computed_lines:
                        conn.execute("""
                            INSERT INTO erp_document_lines (
                                id, document_id, pos_no, item_id, item_no_snapshot,
                                title, description, quantity, unit, unit_price_net,
                                discount_pct, tax_rate_pct, line_net, line_tax, line_gross
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            cl["id"], doc_id, cl["pos_no"], cl["item_id"], cl["item_no_snapshot"],
                            cl["title"], cl["description"], cl["quantity"], cl["unit"],
                            cl["unit_price_net"], cl["discount_pct"], cl["tax_rate_pct"],
                            cl["line_net"], cl["line_tax"], cl["line_gross"]
                        ))

                # Falls Rechnung erstellt wird -> Entität automatisch als Kunde (Debitor) markieren
                if doc_type == "invoice" and not ent.get("is_customer"):
                    deb_no = ent.get("debtor_no") or str(self._next_sequence(conn, "debtor"))
                    conn.execute(
                        "UPDATE crm_entities SET is_customer = 1, debtor_no = ?, status = 'active' WHERE id = ?",
                        (deb_no, entity_id)
                    )

                # M28: Automatische Lagerbestands-Abbuchung bei festgeschriebener Rechnung
                already_deducted = int(ex.get("stock_deducted") or 0) == 1 if ex else False
                if doc_type == "invoice" and status in ("booked", "paid") and not already_deducted:
                    self._apply_inventory_stock_delta(conn, doc_id, sign=-1)

            return self.get_document(doc_id, company_id=cid)
        finally:
            conn.close()

    def convert_document(
        self,
        source_doc_id: str,
        target_doc_type: str = "invoice",
        company_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Wandelt z.B. ein Angebot (offer) per 1-Klick in einen Auftrag (order) oder eine Rechnung (invoice)."""
        src = self.get_document(source_doc_id, company_id=company_id)
        if not src:
            raise ValueError(f"Quellbeleg {source_doc_id} nicht gefunden.")

        copied_lines = []
        for l in src.get("lines", []):
            cl = dict(l)
            cl.pop("id", None)
            cl.pop("document_id", None)
            copied_lines.append(cl)

        new_payload = {
            "doc_type": target_doc_type,
            "status": "booked" if target_doc_type == "invoice" else "sent",
            "entity_id": src["entity_id"],
            "contact_id": src.get("contact_id"),
            "source_doc_id": src["id"],
            "deal_id": src.get("deal_id"),
            "contract_id": src.get("contract_id"),
            "tax_regime": src.get("tax_regime", "standard_19"),
            "payment_terms_days": src.get("payment_terms_days", 14),
            "notes": f"Erstellt aus {src['doc_number']}. " + (src.get("notes") or ""),
            "lines": copied_lines
        }
        created = self.save_document(new_payload, company_id=company_id)

        # Quellbeleg auf 'accepted' setzen
        conn, cid = self._get_conn(company_id)
        try:
            with conn:
                conn.execute(
                    "UPDATE erp_documents SET status = 'accepted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (source_doc_id,)
                )
        finally:
            conn.close()

        return created

    # =========================================================================
    # 3b. E-RECHNUNG (XRECHNUNG 3.0 / EN 16931 UBL) & DATEV EXTF EXPORT (M28)
    # =========================================================================

    @staticmethod
    def _map_ubl_unit_code(unit_label: str) -> str:
        norm = str(unit_label or "").strip().lower().rstrip(".")
        return {
            "std": "HUR",
            "h": "HUR",
            "stunde": "HUR",
            "stunden": "HUR",
            "hour": "HUR",
            "hours": "HUR",
            "tag": "DAY",
            "tage": "DAY",
            "day": "DAY",
            "monat": "MON",
            "monate": "MON",
            "month": "MON",
            "pauschal": "LS",
            "pauschale": "LS",
            "jahr": "ANN",
        }.get(norm, "C62")

    @staticmethod
    def _tax_category_for_doc(tax_regime: str, rate_pct: float) -> Tuple[str, Optional[str]]:
        if rate_pct > 0:
            return ("S", None)
        if tax_regime == "reverse_charge":
            return ("AE", "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)")
        if tax_regime == "intra_eu":
            return ("K", "Innergemeinschaftliche Lieferung / Leistung (§ 4 Nr. 1b UStG)")
        if tax_regime == "small_business":
            return ("E", "Kein Ausweis von Umsatzsteuer gem. § 19 UStG (Kleinunternehmer)")
        return ("Z", "Steuerfreie Ausfuhrlieferung / Zero-Rated")

    @staticmethod
    def _csv_safe(val: Any) -> str:
        s = str(val if val is not None else "").replace("\r", " ").replace("\n", " ").strip()
        if s and s[0] in ("=", "+", "-", "@", "\t"):
            s = "'" + s
        return '"' + s.replace('"', '""') + '"'

    def _prepare_einvoice_context(self, doc_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Bereitet alle normalisierten E-Rechnungs-Metadaten (UBL XRechnung & CII ZUGFeRD) zentral vor."""
        doc = self.get_document(doc_id, company_id=company_id)
        if not doc:
            raise ValueError(f"Beleg {doc_id} nicht gefunden.")

        cid = _sanitize_company_id(company_id)
        seller: Dict[str, Any] = {}
        try:
            from backend.corporate_manager import corporate_manager, DEFAULT_PRIMARY_COMPANY
            seller = corporate_manager.get_company(cid) or dict(DEFAULT_PRIMARY_COMPANY)
        except Exception:
            seller = {}

        seller_addr = seller.get("address") if isinstance(seller.get("address"), dict) else {}
        seller_contact = seller.get("contact") if isinstance(seller.get("contact"), dict) else {}
        seller_tax = seller.get("tax") if isinstance(seller.get("tax"), dict) else {}
        seller_bank = seller.get("bank") if isinstance(seller.get("bank"), dict) else {}

        ent_detail = self.get_entity_detail(doc["entity_id"], company_id=cid) or {}
        ent = ent_detail.get("entity") if isinstance(ent_detail.get("entity"), dict) else ent_detail
        snap = doc.get("recipient_snapshot") if isinstance(doc.get("recipient_snapshot"), dict) else {}

        doc_num = str(doc.get("doc_number") or doc_id)
        currency = str(doc.get("currency") or "EUR").upper()
        issue_date = str(doc.get("issue_date") or datetime.date.today().isoformat())[:10]
        due_date = str(doc.get("due_date") or issue_date)[:10]
        type_code = "381" if doc.get("doc_type") == "credit_note" else "380"

        buyer_ref = str(ent.get("leitweg_id") or snap.get("leitweg_id") or ent.get("debtor_no") or doc_num).strip()
        seller_country_raw = str(seller_addr.get("country") or "DE")
        seller_country = "DE" if seller_country_raw.lower().startswith("de") else seller_country_raw[:2].upper()

        tax_regime = str(doc.get("tax_regime") or "standard_19")
        lines = doc.get("lines") or []
        if not lines:
            lines = [{
                "pos_no": 1,
                "title": f"Leistung gemäß Beleg {doc_num}",
                "description": doc.get("notes") or "",
                "quantity": 1.0,
                "unit": "Pauschal",
                "unit_price_net": float(doc.get("amount_net") or 0.0),
                "tax_rate_pct": 19.0 if float(doc.get("tax_amount") or 0.0) > 0 else 0.0,
                "line_net": float(doc.get("amount_net") or 0.0),
                "line_tax": float(doc.get("tax_amount") or 0.0),
            }]

        tax_buckets: Dict[Tuple[str, float, Optional[str]], Dict[str, float]] = {}
        for ln in lines:
            rate = float(ln.get("tax_rate_pct") or 0.0)
            cat_id, reason = self._tax_category_for_doc(tax_regime, rate)
            key = (cat_id, round(rate, 2), reason)
            bucket = tax_buckets.setdefault(key, {"taxable": 0.0, "tax": 0.0})
            bucket["taxable"] += float(ln.get("line_net") or 0.0)
            bucket["tax"] += float(ln.get("line_tax") or 0.0)

        total_net = round(float(doc.get("amount_net") or sum(b["taxable"] for b in tax_buckets.values())), 2)
        total_tax = round(float(doc.get("tax_amount") or sum(b["tax"] for b in tax_buckets.values())), 2)
        total_gross = round(float(doc.get("amount_gross") or (total_net + total_tax)), 2)

        return {
            "cid": cid,
            "doc": doc,
            "seller": seller,
            "buyer": {
                "display_name": snap.get("display_name") or ent.get("display_name") or "Kunde",
                "street": snap.get("street") or ent.get("street") or "-",
                "postal_code": snap.get("postal_code") or ent.get("postal_code") or "00000",
                "city": snap.get("city") or ent.get("city") or "-",
                "country_code": str(snap.get("country_code") or ent.get("country_code") or "DE")[:2].upper(),
                "vat_id": str(snap.get("vat_id") or ent.get("vat_id") or "").replace(" ", ""),
                "email": str(snap.get("contact_email") or ent.get("billing_email") or "billing@example.invalid"),
                "leitweg_id": ent.get("leitweg_id") or snap.get("leitweg_id") or "",
                "debtor_no": ent.get("debtor_no") or snap.get("debtor_no") or "",
            },
            "doc_num": doc_num,
            "currency": currency,
            "issue_date": issue_date,
            "due_date": due_date,
            "type_code": type_code,
            "buyer_ref": buyer_ref,
            "seller_flat": {
                "name": str(seller.get("name") or "Archon Systems GmbH"),
                "street": str(seller_addr.get("street") or "Friedrichstraße 123"),
                "zip": str(seller_addr.get("postal_code") or "10117"),
                "city": str(seller_addr.get("city") or "Berlin"),
                "country": seller_country,
                "vat_id": str(seller_tax.get("vat_id") or "").replace(" ", ""),
                "tax_no": str(seller_tax.get("tax_number") or ""),
                "email": str(seller_contact.get("email") or "billing@archon.local"),
                "phone": str(seller_contact.get("phone") or "+49 30 000000"),
                "iban": str(seller_bank.get("iban") or "").replace(" ", ""),
                "bic": str(seller_bank.get("bic") or "").replace(" ", ""),
            },
            "tax_regime": tax_regime,
            "lines": lines,
            "tax_buckets": tax_buckets,
            "total_net": total_net,
            "total_tax": total_tax,
            "total_gross": total_gross,
        }

    def export_xrechnung_xml(self, doc_id: str, company_id: Optional[str] = None) -> Tuple[str, str]:
        """Erzeugt eine EN-16931 / XRechnung-3.0-konforme UBL-2.1-XML-E-Rechnung (oder Gutschrift)."""
        ctx = self._prepare_einvoice_context(doc_id, company_id=company_id)
        doc = ctx["doc"]
        doc_num = ctx["doc_num"]
        currency = ctx["currency"]
        issue_date = ctx["issue_date"]
        due_date = ctx["due_date"]
        type_code = ctx["type_code"]
        buyer_ref = ctx["buyer_ref"]
        sf = ctx["seller_flat"]
        seller_name, seller_street, seller_zip = sf["name"], sf["street"], sf["zip"]
        seller_city, seller_country, seller_vat = sf["city"], sf["country"], sf["vat_id"]
        seller_tax_no, seller_email, seller_phone = sf["tax_no"], sf["email"], sf["phone"]
        seller_iban, seller_bic = sf["iban"], sf["bic"]
        bf = ctx["buyer"]
        buyer_name, buyer_street, buyer_zip = str(bf["display_name"]), str(bf["street"]), str(bf["postal_code"])
        buyer_city, buyer_country, buyer_vat, buyer_email = str(bf["city"]), str(bf["country_code"]), str(bf["vat_id"]), str(bf["email"])
        tax_regime = ctx["tax_regime"]
        lines = ctx["lines"]
        tax_buckets = ctx["tax_buckets"]
        total_net, total_tax, total_gross = ctx["total_net"], ctx["total_tax"], ctx["total_gross"]

        subtotals_xml = []
        for (cat_id, rate, reason), b in tax_buckets.items():
            reason_xml = f"\n      <cac:TaxCategory><cbc:ID>{_xml_escape(cat_id)}</cbc:ID><cbc:Percent>{rate:.2f}</cbc:Percent><cbc:TaxExemptionReason>{_xml_escape(reason)}</cbc:TaxExemptionReason><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>" if reason else f"\n      <cac:TaxCategory><cbc:ID>{_xml_escape(cat_id)}</cbc:ID><cbc:Percent>{rate:.2f}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
            subtotals_xml.append(
                f"""    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="{_xml_escape(currency)}">{b['taxable']:.2f}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="{_xml_escape(currency)}">{b['tax']:.2f}</cbc:TaxAmount>{reason_xml}
    </cac:TaxSubtotal>"""
            )

        invoice_lines_xml = []
        for idx, ln in enumerate(lines, start=1):
            pos = int(ln.get("pos_no") or idx)
            qty = float(ln.get("quantity") or 1.0)
            unit_code = self._map_ubl_unit_code(ln.get("unit") or "Stk.")
            line_net = float(ln.get("line_net") or 0.0)
            unit_price = float(ln.get("unit_price_net") or 0.0)
            rate = float(ln.get("tax_rate_pct") or 0.0)
            cat_id, _ = self._tax_category_for_doc(tax_regime, rate)
            title = _xml_escape(str(ln.get("title") or f"Position {pos}"))
            desc = _xml_escape(str(ln.get("description") or ""))
            desc_tag = f"\n      <cbc:Description>{desc}</cbc:Description>" if desc else ""
            invoice_lines_xml.append(
                f"""  <cac:InvoiceLine>
    <cbc:ID>{pos}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="{_xml_escape(unit_code)}">{qty:.2f}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="{_xml_escape(currency)}">{line_net:.2f}</cbc:LineExtensionAmount>
    <cac:Item>{desc_tag}
      <cbc:Name>{title}</cbc:Name>
      <cac:ClassifiedTaxCategory>
        <cbc:ID>{_xml_escape(cat_id)}</cbc:ID>
        <cbc:Percent>{rate:.2f}</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount currencyID="{_xml_escape(currency)}">{unit_price:.2f}</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>"""
            )

        seller_tax_scheme_xml = ""
        if seller_vat:
            seller_tax_scheme_xml += f"""
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{_xml_escape(seller_vat)}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>"""
        if seller_tax_no:
            seller_tax_scheme_xml += f"""
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{_xml_escape(seller_tax_no)}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>FC</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>"""

        buyer_vat_xml = ""
        if buyer_vat:
            buyer_vat_xml = f"""
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{_xml_escape(buyer_vat)}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>"""

        payment_xml = ""
        if seller_iban:
            bic_xml = f"\n        <cac:FinancialInstitutionBranch><cbc:ID>{_xml_escape(seller_bic)}</cbc:ID></cac:FinancialInstitutionBranch>" if seller_bic else ""
            payment_xml = f"""
  <cac:PaymentMeans>
    <cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cbc:PaymentID>{_xml_escape(doc_num)}</cbc:PaymentID>
    <cac:PayeeFinancialAccount>
      <cbc:ID>{_xml_escape(seller_iban)}</cbc:ID>{bic_xml}
    </cac:PayeeFinancialAccount>
  </cac:PaymentMeans>"""

        xml_doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>{_xml_escape(doc_num)}</cbc:ID>
  <cbc:IssueDate>{_xml_escape(issue_date)}</cbc:IssueDate>
  <cbc:DueDate>{_xml_escape(due_date)}</cbc:DueDate>
  <cbc:InvoiceTypeCode>{type_code}</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>{_xml_escape(currency)}</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>{_xml_escape(buyer_ref)}</cbc:BuyerReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cbc:EndpointID schemeID="EM">{_xml_escape(seller_email)}</cbc:EndpointID>
      <cac:PartyName><cbc:Name>{_xml_escape(seller_name)}</cbc:Name></cac:PartyName>
      <cac:PostalAddress>
        <cbc:StreetName>{_xml_escape(seller_street)}</cbc:StreetName>
        <cbc:CityName>{_xml_escape(seller_city)}</cbc:CityName>
        <cbc:PostalZone>{_xml_escape(seller_zip)}</cbc:PostalZone>
        <cac:Country><cbc:IdentificationCode>{_xml_escape(seller_country)}</cbc:IdentificationCode></cac:Country>
      </cac:PostalAddress>{seller_tax_scheme_xml}
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>{_xml_escape(seller_name)}</cbc:RegistrationName>
      </cac:PartyLegalEntity>
      <cac:Contact>
        <cbc:Name>{_xml_escape(seller_name)}</cbc:Name>
        <cbc:Telephone>{_xml_escape(seller_phone)}</cbc:Telephone>
        <cbc:ElectronicMail>{_xml_escape(seller_email)}</cbc:ElectronicMail>
      </cac:Contact>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cbc:EndpointID schemeID="EM">{_xml_escape(buyer_email)}</cbc:EndpointID>
      <cac:PartyName><cbc:Name>{_xml_escape(buyer_name)}</cbc:Name></cac:PartyName>
      <cac:PostalAddress>
        <cbc:StreetName>{_xml_escape(buyer_street)}</cbc:StreetName>
        <cbc:CityName>{_xml_escape(buyer_city)}</cbc:CityName>
        <cbc:PostalZone>{_xml_escape(buyer_zip)}</cbc:PostalZone>
        <cac:Country><cbc:IdentificationCode>{_xml_escape(buyer_country)}</cbc:IdentificationCode></cac:Country>
      </cac:PostalAddress>{buyer_vat_xml}
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>{_xml_escape(buyer_name)}</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>{payment_xml}
  <cac:PaymentTerms>
    <cbc:Note>{_xml_escape(f"Zahlbar innerhalb von {int(doc.get('payment_terms_days') or 14)} Tagen ohne Abzug.")}</cbc:Note>
  </cac:PaymentTerms>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="{_xml_escape(currency)}">{total_tax:.2f}</cbc:TaxAmount>
{chr(10).join(subtotals_xml)}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="{_xml_escape(currency)}">{total_net:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="{_xml_escape(currency)}">{total_net:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="{_xml_escape(currency)}">{total_gross:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="{_xml_escape(currency)}">{total_gross:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{chr(10).join(invoice_lines_xml)}
</Invoice>
"""
        return doc_num, xml_doc

    def export_zugferd_cii_xml(self, doc_id: str, company_id: Optional[str] = None) -> Tuple[str, str]:
        """Erzeugt ZUGFeRD-2.2-/Factur-X-EN-16931-konformes UN/CEFACT Cross Industry Invoice XML (CII D16B)."""
        ctx = self._prepare_einvoice_context(doc_id, company_id=company_id)
        doc = ctx["doc"]
        doc_num = ctx["doc_num"]
        currency = ctx["currency"]
        issue_cii = ctx["issue_date"].replace("-", "")
        due_cii = ctx["due_date"].replace("-", "")
        type_code = ctx["type_code"]
        buyer_ref = ctx["buyer_ref"]
        sf = ctx["seller_flat"]
        bf = ctx["buyer"]
        tax_regime = ctx["tax_regime"]
        lines = ctx["lines"]
        tax_buckets = ctx["tax_buckets"]
        total_net, total_tax, total_gross = ctx["total_net"], ctx["total_tax"], ctx["total_gross"]

        line_items_xml = []
        for idx, ln in enumerate(lines, start=1):
            pos = int(ln.get("pos_no") or idx)
            qty = float(ln.get("quantity") or 1.0)
            unit_code = self._map_ubl_unit_code(ln.get("unit") or "Stk.")
            line_net = float(ln.get("line_net") or 0.0)
            unit_price = float(ln.get("unit_price_net") or 0.0)
            rate = float(ln.get("tax_rate_pct") or 0.0)
            cat_id, _ = self._tax_category_for_doc(tax_regime, rate)
            title = _xml_escape(str(ln.get("title") or f"Position {pos}"))
            desc = _xml_escape(str(ln.get("description") or ""))
            desc_el = f"\n      <ram:Description>{desc}</ram:Description>" if desc else ""
            line_items_xml.append(
                f"""    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>{pos}</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct>
        <ram:Name>{title}</ram:Name>{desc_el}
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice><ram:ChargeAmount>{unit_price:.2f}</ram:ChargeAmount></ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="{_xml_escape(unit_code)}">{qty:.2f}</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax>
          <ram:TypeCode>VAT</ram:TypeCode>
          <ram:CategoryCode>{_xml_escape(cat_id)}</ram:CategoryCode>
          <ram:RateApplicablePercent>{rate:.2f}</ram:RateApplicablePercent>
        </ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>{line_net:.2f}</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>"""
            )

        tax_xml = []
        for (cat_id, rate, reason), b in tax_buckets.items():
            reason_el = f"\n        <ram:ExemptionReason>{_xml_escape(reason)}</ram:ExemptionReason>" if reason else ""
            tax_xml.append(
                f"""      <ram:ApplicableTradeTax>
        <ram:CalculatedAmount>{b['tax']:.2f}</ram:CalculatedAmount>
        <ram:TypeCode>VAT</ram:TypeCode>{reason_el}
        <ram:BasisAmount>{b['taxable']:.2f}</ram:BasisAmount>
        <ram:CategoryCode>{_xml_escape(cat_id)}</ram:CategoryCode>
        <ram:RateApplicablePercent>{rate:.2f}</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>"""
            )

        seller_tax_regs = ""
        if sf["vat_id"]:
            seller_tax_regs += f'\n        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{_xml_escape(sf["vat_id"])}</ram:ID></ram:SpecifiedTaxRegistration>'
        if sf["tax_no"]:
            seller_tax_regs += f'\n        <ram:SpecifiedTaxRegistration><ram:ID schemeID="FC">{_xml_escape(sf["tax_no"])}</ram:ID></ram:SpecifiedTaxRegistration>'

        buyer_vat_reg = ""
        if bf["vat_id"]:
            buyer_vat_reg = f'\n        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{_xml_escape(bf["vat_id"])}</ram:ID></ram:SpecifiedTaxRegistration>'

        payment_means_xml = ""
        if sf["iban"]:
            bic_el = f"\n        <ram:PayeeSpecifiedCreditorFinancialInstitution><ram:BICID>{_xml_escape(sf['bic'])}</ram:BICID></ram:PayeeSpecifiedCreditorFinancialInstitution>" if sf["bic"] else ""
            payment_means_xml = f"""
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:TypeCode>58</ram:TypeCode>
        <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{_xml_escape(sf['iban'])}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>{bic_el}
      </ram:SpecifiedTradeSettlementPaymentMeans>"""

        cii_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
                          xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
                          xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
                          xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:BusinessProcessSpecifiedDocumentContextParameter>
      <ram:ID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</ram:ID>
    </ram:BusinessProcessSpecifiedDocumentContextParameter>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{_xml_escape(doc_num)}</ram:ID>
    <ram:TypeCode>{type_code}</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">{_xml_escape(issue_cii)}</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
{chr(10).join(line_items_xml)}
    <ram:ApplicableHeaderTradeAgreement>
      <ram:BuyerReference>{_xml_escape(buyer_ref)}</ram:BuyerReference>
      <ram:SellerTradeParty>
        <ram:Name>{_xml_escape(sf['name'])}</ram:Name>
        <ram:DefinedTradeContact>
          <ram:PersonName>{_xml_escape(sf['name'])}</ram:PersonName>
          <ram:TelephoneUniversalCommunication><ram:CompleteNumber>{_xml_escape(sf['phone'])}</ram:CompleteNumber></ram:TelephoneUniversalCommunication>
          <ram:EmailURIUniversalCommunication><ram:URIID>{_xml_escape(sf['email'])}</ram:URIID></ram:EmailURIUniversalCommunication>
        </ram:DefinedTradeContact>
        <ram:PostalTradeAddress>
          <ram:PostcodeCode>{_xml_escape(sf['zip'])}</ram:PostcodeCode>
          <ram:LineOne>{_xml_escape(sf['street'])}</ram:LineOne>
          <ram:CityName>{_xml_escape(sf['city'])}</ram:CityName>
          <ram:CountryID>{_xml_escape(sf['country'])}</ram:CountryID>
        </ram:PostalTradeAddress>{seller_tax_regs}
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{_xml_escape(str(bf['display_name']))}</ram:Name>
        <ram:PostalTradeAddress>
          <ram:PostcodeCode>{_xml_escape(str(bf['postal_code']))}</ram:PostcodeCode>
          <ram:LineOne>{_xml_escape(str(bf['street']))}</ram:LineOne>
          <ram:CityName>{_xml_escape(str(bf['city']))}</ram:CityName>
          <ram:CountryID>{_xml_escape(str(bf['country_code']))}</ram:CountryID>
        </ram:PostalTradeAddress>{buyer_vat_reg}
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:PaymentReference>{_xml_escape(doc_num)}</ram:PaymentReference>
      <ram:InvoiceCurrencyCode>{_xml_escape(currency)}</ram:InvoiceCurrencyCode>{payment_means_xml}
{chr(10).join(tax_xml)}
      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>{_xml_escape(f"Zahlbar innerhalb von {int(doc.get('payment_terms_days') or 14)} Tagen ohne Abzug.")}</ram:Description>
        <ram:DueDateDateTime><udt:DateTimeString format="102">{_xml_escape(due_cii)}</udt:DateTimeString></ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{total_net:.2f}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{total_net:.2f}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="{_xml_escape(currency)}">{total_tax:.2f}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{total_gross:.2f}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{total_gross:.2f}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
        return doc_num, cii_xml

    def export_datev_extf_csv(
        self,
        company_id: Optional[str] = None,
        include_drafts: bool = False,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> str:
        """Erzeugt einen DATEV-EXTF-kompatiblen Buchungsstapel (SKR03, Semikolon-CSV)."""
        conn, cid = self._get_conn(company_id)
        try:
            clauses = ["d.doc_type IN ('invoice', 'credit_note')"]
            params: List[Any] = []
            if not include_drafts:
                clauses.append("d.status IN ('booked', 'paid')")
            else:
                clauses.append("d.status != 'cancelled'")
            if date_from:
                clauses.append("d.issue_date >= ?")
                params.append(str(date_from)[:10])
            if date_to:
                clauses.append("d.issue_date <= ?")
                params.append(str(date_to)[:10])

            sql = f"""
                SELECT d.*, e.display_name AS entity_name, e.debtor_no, e.creditor_no
                FROM erp_documents d
                LEFT JOIN crm_entities e ON d.entity_id = e.id
                WHERE {' AND '.join(clauses)}
                ORDER BY d.issue_date ASC, d.doc_number ASC
            """
            docs = [dict(r) for r in conn.execute(sql, params).fetchall()]

            now_stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S000")
            year_start = f"{datetime.date.today().year}0101"
            extf_meta = (
                f'"EXTF";700;21;"Buchungsstapel";13;{now_stamp};;"RE";"ArchonOS";'
                f'"{cid}";1;1;{year_start};4;;;"Archon Buchungsstapel";;;0;"EUR";;;;;;;;'
            )
            col_header = (
                "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;WKZ Umsatz;Kurs;Basis-Umsatz;"
                "WKZ Basis-Umsatz;Konto;Gegenkonto (ohne BU-Schlüssel);BU-Schlüssel;Belegdatum;"
                "Belegfeld 1;Belegfeld 2;Skonto;Buchungstext"
            )
            rows = [extf_meta, col_header]

            for d in docs:
                lines = conn.execute(
                    "SELECT tax_rate_pct, line_gross FROM erp_document_lines WHERE document_id = ?",
                    (d["id"],),
                ).fetchall()
                rate_totals: Dict[float, float] = collections.defaultdict(float)
                for ln in lines:
                    rate_totals[round(float(ln["tax_rate_pct"] or 0.0), 2)] += float(ln["line_gross"] or 0.0)
                if not rate_totals:
                    inferred_rate = 19.0 if float(d.get("tax_amount") or 0.0) > 0 else 0.0
                    rate_totals[inferred_rate] = float(d.get("amount_gross") or 0.0)

                issue_raw = str(d.get("issue_date") or datetime.date.today().isoformat())
                try:
                    dt = datetime.date.fromisoformat(issue_raw[:10])
                    belegdatum = dt.strftime("%d%m")
                except ValueError:
                    belegdatum = datetime.date.today().strftime("%d%m")

                sh_flag = "H" if d.get("doc_type") == "credit_note" else "S"
                deb_acct = str(d.get("debtor_no") or "10000")
                doc_num = str(d.get("doc_number") or d["id"])[:36]
                partner_name = str(d.get("entity_name") or "Kunde")[:40]
                currency = str(d.get("currency") or "EUR").upper()
                regime = str(d.get("tax_regime") or "standard_19")

                for rate, gross_sum in rate_totals.items():
                    amt_val = round(abs(gross_sum), 2)
                    if amt_val <= 0:
                        continue
                    amt_de = f"{amt_val:.2f}".replace(".", ",")
                    if abs(rate - 19.0) < 0.01:
                        rev_acct, bu_key = "8400", "3"
                    elif abs(rate - 7.0) < 0.01:
                        rev_acct, bu_key = "8300", "2"
                    elif regime == "intra_eu":
                        rev_acct, bu_key = "8125", ""
                    elif regime == "reverse_charge":
                        rev_acct, bu_key = "8337", ""
                    else:
                        rev_acct, bu_key = "8120", ""

                    buchungstext = f"{doc_num} {partner_name}"[:60]
                    rows.append(";".join([
                        amt_de,
                        sh_flag,
                        self._csv_safe(currency),
                        "",
                        "",
                        "",
                        deb_acct,
                        rev_acct,
                        bu_key,
                        belegdatum,
                        self._csv_safe(doc_num),
                        "",
                        "",
                        self._csv_safe(buchungstext),
                    ]))

            return "\r\n".join(rows) + "\r\n"
        finally:
            conn.close()

    def export_zugferd_pdf(self, doc_id: str, company_id: Optional[str] = None) -> Tuple[str, bytes]:
        """Erzeugt ein ZUGFeRD-2.2-/Factur-X-Hybrid-PDF (A4-Beleg + eingebettetes EN-16931-CII-XML `factur-x.xml`)."""
        from backend.erp_zugferd_pdf import build_zugferd_invoice_pdf

        ctx = self._prepare_einvoice_context(doc_id, company_id=company_id)
        doc_num, cii_xml_str = self.export_zugferd_cii_xml(doc_id=doc_id, company_id=company_id)
        pdf_bytes = build_zugferd_invoice_pdf(
            doc=ctx["doc"],
            seller=ctx["seller"],
            buyer=ctx["buyer"],
            embedded_xml=cii_xml_str,
        )
        return doc_num, pdf_bytes

    # =========================================================================
    # 3c. BANKKONTEN-IMPORT (CAMT.053 XML / MT940 / CSV) & OPOS-ABGLEICH (M28)
    # =========================================================================

    @staticmethod
    def _parse_de_amount(raw: Any) -> float:
        s = str(raw or "0").strip().replace("EUR", "").replace("€", "").replace(" ", "")
        if not s:
            return 0.0
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        return round(float(s), 2)

    @staticmethod
    def _xml_local(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    @classmethod
    def _xml_first_text(cls, elem: ET.Element, path_names: Tuple[str, ...]) -> str:
        cur: Optional[ET.Element] = elem
        for name in path_names:
            if cur is None:
                return ""
            nxt = None
            for child in list(cur):
                if cls._xml_local(child.tag) == name:
                    nxt = child
                    break
            cur = nxt
        return (cur.text or "").strip() if cur is not None and cur.text else ""

    @classmethod
    def parse_bank_statement(cls, raw_content: str, fmt: str = "auto") -> List[Dict[str, Any]]:
        """Parst ISO 20022 CAMT.053 XML, SWIFT MT940 (.sta) oder Bank-CSV in normierte Umsatz-Dicts."""
        text = str(raw_content or "").lstrip("\ufeff").strip()
        if not text:
            return []

        detected = (fmt or "auto").strip().lower()
        if detected == "auto":
            if text.startswith("<") and ("BkToCstmrStmt" in text or "Ntry" in text or "camt.053" in text.lower()):
                detected = "camt053"
            elif ":61:" in text and (":20:" in text or ":86:" in text):
                detected = "mt940"
            else:
                detected = "csv"

        if detected == "camt053":
            upper_head = text[:4096].upper()
            if "<!DOCTYPE" in upper_head or "<!ENTITY" in upper_head:
                raise ValueError("XXE-/DTD-Deklarationen sind im CAMT.053-Import nicht zulässig.")
            root = ET.fromstring(text)
            txs: List[Dict[str, Any]] = []
            for ntry in root.iter():
                if cls._xml_local(ntry.tag) != "Ntry":
                    continue
                amt_el = next((c for c in list(ntry) if cls._xml_local(c.tag) == "Amt"), None)
                if amt_el is None or not (amt_el.text or "").strip():
                    continue
                raw_amt = cls._parse_de_amount(amt_el.text)
                ccy = (amt_el.attrib.get("Ccy") or "EUR").upper()
                ind = cls._xml_first_text(ntry, ("CdtDbtInd",)).upper()
                signed_amt = -abs(raw_amt) if ind == "DBIT" else abs(raw_amt)
                book_dt = cls._xml_first_text(ntry, ("BookgDt", "Dt")) or cls._xml_first_text(ntry, ("BookgDt", "DtTm"))[:10]
                val_dt = cls._xml_first_text(ntry, ("ValDt", "Dt")) or book_dt

                # Extrahiere Detail-Transaktionen (falls mehrere TxDtls unter NtryDtls, sonst 1 Summenbuchung)
                tx_details = [e for e in ntry.iter() if cls._xml_local(e.tag) == "TxDtls"]
                targets = tx_details or [ntry]
                for td in targets:
                    e2e = cls._xml_first_text(td, ("Refs", "EndToEndId"))
                    dbtr_name = (
                        cls._xml_first_text(td, ("RltdPties", "Dbtr", "Nm"))
                        or cls._xml_first_text(td, ("RltdPties", "Cdtr", "Nm"))
                    )
                    dbtr_iban = (
                        cls._xml_first_text(td, ("RltdPties", "DbtrAcct", "Id", "IBAN"))
                        or cls._xml_first_text(td, ("RltdPties", "CdtrAcct", "Id", "IBAN"))
                    )
                    ustrd_parts = [
                        (u.text or "").strip()
                        for u in td.iter()
                        if cls._xml_local(u.tag) == "Ustrd" and (u.text or "").strip()
                    ]
                    remittance = " ".join(ustrd_parts).strip() or cls._xml_first_text(ntry, ("AddtlNtryInf",))
                    td_amt_el = next((c for c in td.iter() if cls._xml_local(c.tag) == "Amt" and c is not amt_el), None)
                    tx_amt = signed_amt
                    if td_amt_el is not None and (td_amt_el.text or "").strip():
                        v = cls._parse_de_amount(td_amt_el.text)
                        tx_amt = -abs(v) if ind == "DBIT" else abs(v)
                    txs.append({
                        "booking_date": book_dt or datetime.date.today().isoformat(),
                        "value_date": val_dt or book_dt or "",
                        "amount": round(tx_amt, 2),
                        "currency": ccy,
                        "counterparty_name": dbtr_name,
                        "counterparty_iban": dbtr_iban.replace(" ", "").upper(),
                        "remittance_info": remittance,
                        "end_to_end_id": e2e,
                        "source_format": "camt053",
                    })
            return txs

        if detected == "mt940":
            txs = []
            current: Optional[Dict[str, Any]] = None
            stmt_re = re.compile(r"^:61:(\d{6})(?:\d{4})?(C|D|RC|RD)([A-Z]?)([\d,\.]+)")
            for raw_line in text.splitlines():
                line = raw_line.strip()
                m = stmt_re.match(line)
                if m:
                    if current:
                        txs.append(current)
                    yymmdd, cd, _, amt_str = m.groups()
                    bdate = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
                    val = cls._parse_de_amount(amt_str)
                    signed = -abs(val) if "D" in cd else abs(val)
                    current = {
                        "booking_date": bdate,
                        "value_date": bdate,
                        "amount": round(signed, 2),
                        "currency": "EUR",
                        "counterparty_name": "",
                        "counterparty_iban": "",
                        "remittance_info": "",
                        "end_to_end_id": "",
                        "source_format": "mt940",
                    }
                elif line.startswith(":86:") and current is not None:
                    info = line[4:].strip()
                    current["remittance_info"] = (current["remittance_info"] + " " + info).strip()
                    name_m = re.search(r"\?32([^?]+)", info)
                    iban_m = re.search(r"\?31([A-Z]{2}\d{2}[A-Z0-9]{10,30})", info.replace(" ", ""))
                    if name_m and not current["counterparty_name"]:
                        current["counterparty_name"] = name_m.group(1).strip()
                    if iban_m and not current["counterparty_iban"]:
                        current["counterparty_iban"] = iban_m.group(1).strip()
                elif current is not None and line and not line.startswith(":"):
                    current["remittance_info"] = (current["remittance_info"] + " " + line).strip()
            if current:
                txs.append(current)
            return txs

        # Bank-CSV (Semikolon oder Komma, Standard-Spaltennamen DE/EN)
        delim = ";" if text.splitlines()[0].count(";") >= text.splitlines()[0].count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        txs = []
        for row in reader:
            norm = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items()}
            amt_raw = norm.get("betrag") or norm.get("amount") or norm.get("umsatz") or ""
            if not amt_raw:
                continue
            bdate = (
                norm.get("buchungstag")
                or norm.get("booking_date")
                or norm.get("datum")
                or norm.get("date")
                or datetime.date.today().isoformat()
            )
            if re.match(r"^\d{2}\.\d{2}\.\d{4}$", bdate):
                dd, mm, yyyy = bdate.split(".")
                bdate = f"{yyyy}-{mm}-{dd}"
            vdate = norm.get("valutadatum") or norm.get("value_date") or bdate
            if re.match(r"^\d{2}\.\d{2}\.\d{4}$", vdate):
                dd, mm, yyyy = vdate.split(".")
                vdate = f"{yyyy}-{mm}-{dd}"
            txs.append({
                "booking_date": bdate,
                "value_date": vdate,
                "amount": cls._parse_de_amount(amt_raw),
                "currency": (norm.get("waehrung") or norm.get("währung") or norm.get("currency") or "EUR").upper(),
                "counterparty_name": norm.get("auftraggeber") or norm.get("empfaenger") or norm.get("empfänger") or norm.get("name") or norm.get("counterparty") or "",
                "counterparty_iban": (norm.get("iban") or norm.get("konto/iban") or "").replace(" ", "").upper(),
                "remittance_info": norm.get("verwendungszweck") or norm.get("buchungstext") or norm.get("purpose") or norm.get("reference") or "",
                "end_to_end_id": norm.get("ende-zu-ende-referenz") or norm.get("end_to_end_id") or "",
                "source_format": "csv",
            })
        return txs

    def import_and_reconcile_bank_statement(
        self,
        raw_content: str,
        fmt: str = "auto",
        auto_mark_paid: bool = False,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Importiert Bankumsätze (CAMT.053/MT940/CSV), dedupliziert via SHA-256 und gleicht sie gegen offene Rechnungen (OPOS) ab."""
        parsed = self.parse_bank_statement(raw_content, fmt=fmt)
        conn, cid = self._get_conn(company_id)
        imported = 0
        duplicates = 0
        matched = 0
        auto_paid = 0
        items_out: List[Dict[str, Any]] = []
        docs_to_mark_paid: List[str] = []

        try:
            open_invoices = [
                dict(r)
                for r in conn.execute("""
                    SELECT d.id, d.doc_number, d.amount_gross, d.currency, d.status,
                           e.display_name, e.iban AS entity_iban
                    FROM erp_documents d
                    LEFT JOIN crm_entities e ON d.entity_id = e.id
                    WHERE d.doc_type = 'invoice' AND d.status = 'booked'
                """).fetchall()
            ]
            already_assigned_docs: set[str] = set()

            with conn:
                for idx, tx in enumerate(parsed):
                    raw_sig = "|".join([
                        str(tx.get("booking_date") or ""),
                        f"{float(tx.get('amount') or 0.0):.2f}",
                        str(tx.get("currency") or "EUR"),
                        str(tx.get("counterparty_iban") or ""),
                        str(tx.get("end_to_end_id") or ""),
                        str(tx.get("remittance_info") or ""),
                    ])
                    tx_hash = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()
                    if conn.execute("SELECT 1 FROM erp_bank_transactions WHERE tx_hash = ?", (tx_hash,)).fetchone():
                        duplicates += 1
                        continue

                    best_doc: Optional[Dict[str, Any]] = None
                    best_score = 0.0
                    tx_amt = float(tx.get("amount") or 0.0)
                    remit_upper = f"{tx.get('remittance_info', '')} {tx.get('end_to_end_id', '')}".upper()
                    tx_iban = str(tx.get("counterparty_iban") or "").replace(" ", "").upper()
                    tx_name = str(tx.get("counterparty_name") or "").lower()

                    if tx_amt > 0:
                        for inv in open_invoices:
                            if inv["id"] in already_assigned_docs:
                                continue
                            score = 0.0
                            inv_no = str(inv.get("doc_number") or "").upper()
                            if inv_no and inv_no in remit_upper:
                                score += 0.65
                            if abs(tx_amt - float(inv.get("amount_gross") or 0.0)) <= 0.02:
                                score += 0.30
                            ent_iban = str(inv.get("entity_iban") or "").replace(" ", "").upper()
                            if tx_iban and ent_iban and tx_iban == ent_iban:
                                score += 0.45 if inv_no not in remit_upper else 0.15
                            ent_name = str(inv.get("display_name") or "").lower()
                            if ent_name and tx_name and (ent_name[:8] in tx_name or tx_name[:8] in ent_name):
                                score += 0.10
                            score = min(1.0, round(score, 2))
                            if score > best_score:
                                best_score = score
                                best_doc = inv

                    m_doc_id = ""
                    m_doc_num = ""
                    m_status = "unmatched"
                    if best_doc and best_score >= 0.65:
                        m_doc_id = best_doc["id"]
                        m_doc_num = best_doc["doc_number"]
                        already_assigned_docs.add(m_doc_id)
                        matched += 1
                        if auto_mark_paid and best_score >= 0.90:
                            m_status = "paid_applied"
                            docs_to_mark_paid.append(m_doc_id)
                            auto_paid += 1
                        else:
                            m_status = "matched"
                    else:
                        best_score = 0.0

                    tx_id = f"btx-{uuid.uuid4().hex[:10]}"
                    conn.execute("""
                        INSERT INTO erp_bank_transactions (
                            id, booking_date, value_date, amount, currency,
                            counterparty_name, counterparty_iban, remittance_info, end_to_end_id,
                            source_format, tx_hash, matched_doc_id, matched_doc_number,
                            match_confidence, match_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tx_id,
                        tx["booking_date"],
                        tx["value_date"],
                        tx_amt,
                        tx["currency"],
                        tx["counterparty_name"],
                        tx["counterparty_iban"],
                        tx["remittance_info"],
                        tx["end_to_end_id"],
                        tx["source_format"],
                        tx_hash,
                        m_doc_id,
                        m_doc_num,
                        best_score,
                        m_status,
                    ))
                    imported += 1
                    items_out.append({
                        "id": tx_id,
                        "booking_date": tx["booking_date"],
                        "amount": tx_amt,
                        "currency": tx["currency"],
                        "counterparty_name": tx["counterparty_name"],
                        "remittance_info": tx["remittance_info"],
                        "matched_doc_id": m_doc_id,
                        "matched_doc_number": m_doc_num,
                        "match_confidence": best_score,
                        "match_status": m_status,
                    })
        finally:
            conn.close()

        for doc_id in docs_to_mark_paid:
            self.save_document({"id": doc_id, "status": "paid"}, company_id=cid)

        return {
            "company_id": cid,
            "parsed": len(parsed),
            "imported": imported,
            "duplicates_skipped": duplicates,
            "matched": matched,
            "auto_paid": auto_paid,
            "transactions": items_out,
        }

    def list_bank_transactions(
        self,
        company_id: Optional[str] = None,
        match_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            sql = "SELECT * FROM erp_bank_transactions"
            params: List[Any] = []
            if match_status and match_status != "all":
                sql += " WHERE match_status = ?"
                params.append(match_status)
            sql += " ORDER BY booking_date DESC, imported_at DESC LIMIT 200"
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            return {"company_id": cid, "total": len(rows), "items": rows}
        finally:
            conn.close()

    def match_bank_transaction(
        self,
        tx_id: str,
        doc_id: str,
        mark_paid: bool = True,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verknüpft eine Banktransaktion manuell mit einer Ausgangsrechnung und verbucht sie optional als 'paid'."""
        doc = self.get_document(doc_id, company_id=company_id)
        if not doc:
            raise ValueError(f"Beleg {doc_id} nicht gefunden.")
        conn, cid = self._get_conn(company_id)
        try:
            row = conn.execute("SELECT * FROM erp_bank_transactions WHERE id = ?", (tx_id,)).fetchone()
            if not row:
                raise ValueError(f"Banktransaktion {tx_id} nicht gefunden.")
            new_m_status = "paid_applied" if mark_paid else "matched"
            with conn:
                conn.execute(
                    """
                    UPDATE erp_bank_transactions
                    SET matched_doc_id = ?, matched_doc_number = ?, match_confidence = 1.0, match_status = ?
                    WHERE id = ?
                    """,
                    (doc["id"], doc["doc_number"], new_m_status, tx_id),
                )
            updated_tx = dict(conn.execute("SELECT * FROM erp_bank_transactions WHERE id = ?", (tx_id,)).fetchone())
        finally:
            conn.close()

        if mark_paid and doc.get("status") != "paid":
            self.save_document({"id": doc_id, "status": "paid"}, company_id=cid)
        return {"transaction": updated_tx, "document": self.get_document(doc_id, company_id=cid)}

    # =========================================================================
    # 4. LAPTOP-POCKETBASE SYNC BRÜCKE (PRO MANDANT)
    # =========================================================================

    def update_sync_config(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            with conn:
                conn.execute("""
                    UPDATE erp_sync_config
                    SET pocketbase_url = ?,
                        collection_name = ?,
                        sync_enabled = ?
                    WHERE id = 1
                """, (
                    payload.get("pocketbase_url", "http://127.0.0.1:8090").rstrip("/"),
                    payload.get("collection_name", "kontakte").strip(),
                    1 if payload.get("sync_enabled", True) else 0
                ))
            row = conn.execute("SELECT * FROM erp_sync_config WHERE id = 1").fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def sync_with_pocketbase(
        self,
        company_id: Optional[str] = None,
        mock_records: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Synchronisiert Kontakte & Nachrichtenverläufe aus dem Laptop-PocketBase
        in die isolierte Mandanten-DB (`data/tenants/{company_id}/erp.db`),
        ohne kaufmännische Stammdaten (Debitorennr., USt-IdNr., Rechnungen) zu überschreiben.
        """
        conn, cid = self._get_conn(company_id)
        try:
            cfg_row = conn.execute("SELECT * FROM erp_sync_config WHERE id = 1").fetchone()
            cfg = dict(cfg_row) if cfg_row else {
                "pocketbase_url": "http://127.0.0.1:8090",
                "collection_name": "kontakte",
                "sync_enabled": 1
            }

            pb_records: List[Dict[str, Any]] = []
            if mock_records is not None:
                pb_records = mock_records
            elif os.getenv("POCKETBASE_ENABLED", "false").strip().lower() not in ("1", "true", "yes"):
                return {
                    "success": False,
                    "status": "disabled",
                    "company_id": cid,
                    "message": "PocketBase-Sync deaktiviert (POCKETBASE_ENABLED=false) – Mandanten-DB arbeitet lokal autark."
                }
            else:
                pb_url = cfg["pocketbase_url"]
                coll = cfg["collection_name"]
                url = f"{pb_url}/api/collections/{coll}/records?perPage=500"
                try:
                    req = urllib.request.Request(url, headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=4.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            pb_records = data.get("items", [])
                except Exception as e:
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with conn:
                        conn.execute("""
                            UPDATE erp_sync_config
                            SET last_sync_at = ?, last_sync_status = 'offline',
                                last_sync_summary = ?
                            WHERE id = 1
                        """, (now_str, f"PocketBase unter {pb_url} derzeit nicht erreichbar ({e}). Lokale Mandanten-DB aktiv."))
                    return {
                        "success": False,
                        "status": "offline",
                        "company_id": cid,
                        "message": f"Laptop-PocketBase ({pb_url}) nicht erreichbar – Mandanten-DB arbeitet lokal autark."
                    }

            created_entities = 0
            synced_contacts = 0
            synced_messages = 0
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for rec in pb_records:
                pb_id = rec.get("id")
                full_name = (rec.get("name") or "").strip()
                if not full_name or full_name.lower() == "ohne namen":
                    continue

                company_name = (rec.get("unternehmen") or "").strip()
                role_title = (rec.get("rolle") or "").strip()
                email = (rec.get("email") or "").strip()
                linkedin_url = (rec.get("linkedin_url") or "").strip()
                conn_status = (rec.get("status") or "Vernetzt").strip()
                conn_since = (rec.get("vernetzt_am") or "").strip()
                rating = int(rec.get("rating") or 0)
                tags = rec.get("tags") if isinstance(rec.get("tags"), list) else ["LinkedIn Sync"]

                entity_id = None
                if company_name:
                    ent_row = conn.execute(
                        "SELECT id, rating FROM crm_entities WHERE LOWER(display_name) = LOWER(?)",
                        (company_name,)
                    ).fetchone()
                    if ent_row:
                        entity_id = ent_row["id"]
                        if rating > (ent_row["rating"] or 0):
                            with conn:
                                conn.execute("UPDATE crm_entities SET rating = ? WHERE id = ?", (rating, entity_id))
                    else:
                        entity_id = f"ent-{uuid.uuid4().hex[:8]}"
                        with conn:
                            conn.execute("""
                                INSERT INTO crm_entities (
                                    id, entity_type, display_name, is_partner, status,
                                    rating, tags_json, created_at, updated_at
                                ) VALUES (?, 'organization', ?, 1, 'lead', ?, ?, ?, ?)
                            """, (
                                entity_id, company_name, rating,
                                json.dumps(tags, ensure_ascii=False), now_str, now_str
                            ))
                        created_entities += 1

                # Kontakt abgleichen (über pocketbase_id, linkedin_url oder Name)
                cnt_row = None
                if pb_id:
                    cnt_row = conn.execute("SELECT id FROM crm_contacts WHERE pocketbase_id = ?", (pb_id,)).fetchone()
                if not cnt_row and linkedin_url:
                    cnt_row = conn.execute("SELECT id FROM crm_contacts WHERE LOWER(linkedin_url) = LOWER(?)", (linkedin_url,)).fetchone()
                if not cnt_row:
                    cnt_row = conn.execute("SELECT id FROM crm_contacts WHERE LOWER(full_name) = LOWER(?)", (full_name,)).fetchone()

                contact_payload = {
                    "id": cnt_row["id"] if cnt_row else f"cnt-{uuid.uuid4().hex[:8]}",
                    "entity_id": entity_id,
                    "full_name": full_name,
                    "role_title": role_title,
                    "email": email,
                    "linkedin_url": linkedin_url,
                    "connection_status": conn_status,
                    "connected_since": conn_since,
                    "rating": rating,
                    "tags": tags,
                    "pocketbase_id": pb_id,
                    "is_primary": 1 if entity_id else 0
                }
                saved_cnt = self.save_contact(contact_payload, company_id=cid)
                synced_contacts += 1

                # Nachrichtenverlauf importieren
                history = rec.get("nachrichtenverlauf") or []
                if isinstance(history, list):
                    for msg in history:
                        if not isinstance(msg, dict):
                            continue
                        msg_id = msg.get("messageId") or f"pb_{pb_id}_{hash(msg.get('text', ''))}"
                        self.add_interaction({
                            "entity_id": entity_id,
                            "contact_id": saved_cnt.get("id"),
                            "channel": "linkedin" if "linkedin" in str(msg_id).lower() else "email_in",
                            "direction": msg.get("type", "inbound"),
                            "external_msg_id": msg_id,
                            "sender_name": msg.get("sender_name", full_name),
                            "sender_email": msg.get("sender_email", email),
                            "subject": msg.get("subject", "Nachricht"),
                            "body_text": msg.get("text", ""),
                            "occurred_at": msg.get("timestamp") or now_str
                        }, company_id=cid)
                        synced_messages += 1

            summary = f"{synced_contacts} Kontakte, {created_entities} neue Firmen und {synced_messages} Nachrichten synchronisiert."
            with conn:
                conn.execute("""
                    UPDATE erp_sync_config
                    SET last_sync_at = ?, last_sync_status = 'ok', last_sync_summary = ?
                    WHERE id = 1
                """, (now_str, summary))

            return {
                "success": True,
                "status": "ok",
                "company_id": cid,
                "created_entities": created_entities,
                "synced_contacts": synced_contacts,
                "synced_messages": synced_messages,
                "summary": summary
            }
        finally:
            conn.close()


erp_manager = ERPManager()
