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
import json
import uuid
import sqlite3
import datetime
import urllib.request
import urllib.error
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

            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags_json") or "[]")
                except Exception:
                    d["tags"] = []

                prim = conn.execute("""
                    SELECT id, full_name, role_title, email, phone_direct, linkedin_url, connection_status, rating
                    FROM crm_contacts
                    WHERE entity_id = ?
                    ORDER BY is_primary DESC, rating DESC
                    LIMIT 1
                """, (d["id"],)).fetchone()
                d["primary_contact"] = dict(prim) if prim else None
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
                        billing_email, phone_main, website, industry,
                        rating, tags_json, notes, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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

            docs = []
            for r in rows:
                d = dict(r)
                try:
                    d["recipient_snapshot"] = json.loads(d.get("recipient_snapshot_json") or "{}")
                except Exception:
                    d["recipient_snapshot"] = {}
                lines = conn.execute(
                    "SELECT * FROM erp_document_lines WHERE document_id = ? ORDER BY pos_no ASC",
                    (d["id"],)
                ).fetchall()
                d["lines"] = [dict(l) for l in lines]
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

    def save_document(self, payload: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        conn, cid = self._get_conn(company_id)
        try:
            doc_id = payload.get("id") or f"doc-{uuid.uuid4().hex[:8]}"
            existing = conn.execute("SELECT * FROM erp_documents WHERE id = ?", (doc_id,)).fetchone()
            ex = dict(existing) if existing else {}

            # GoBD-Unveränderbarkeitsschutz: Gebuchte Rechnungen dürfen nur im Status/Mahnlevel aktualisiert werden
            if ex and ex.get("status") in ("booked", "paid") and not payload.get("_allow_status_update_only"):
                new_status = payload.get("status", ex["status"])
                paid_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status == "paid" else ex.get("paid_at")
                with conn:
                    conn.execute(
                        "UPDATE erp_documents SET status = ?, paid_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_status, paid_at, doc_id)
                    )
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
