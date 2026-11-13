# Archon OS 2026 — Architektur-Spezifikation: Säule 3 „WIRTSCHAFT & ERP“

**Stand:** 01.11.2026  
**Status:** Verabschiedet (Locked-in nach Architecture Review / Grill-Me)

---

## 1. Leitprinzipien & Grundsatzentscheidungen

1. **Eigene System-Säule in der Hauptnavigation (`WIRTSCHAFT & ERP`):**
   - Wird als **Säule 3** zwischen *Kognition & Wissen* (Säule 2) und *Infrastruktur & Governance* (Säule 4) in [static/index.html](../../static/index.html) verankert.
   - Umfasst 5 eigenständige Hauptansichten mit je eigenem Sidebar-Icon und 80px-Header inkl. 72px-Cadre-Subtab-Kacheln:
     1. **Adressen & CRM** (`nav-addresses`)
     2. **Artikel & Leistungen** (`nav-items`)
     3. **Vorgänge & Verträge** (`nav-operations-erp`)
     4. **Rechnungswesen** (`nav-finance` – zieht aus Infrastruktur hierher um)
     5. **Corporate & Vorlagen** (`nav-corporate` – zieht aus Infrastruktur hierher um)
   - *Infrastruktur & Governance* (Säule 4) enthält künftig ausschließlich technische Governance-Funktionen (`Approval Policies`, `Guardian`, `Log Stream`).

2. **Physische Mandanten-Trennung (DSGVO-Trennungsgebot & GoBD/Z3-Prüfungssicherheit):**
   - Jede eigene Unternehmung (`company_id` aus [corporate_manager.py](../../backend/corporate_manager.py)) erhält eine **physisch isolierte SQLite-Datenbank im WAL-Modus**:
     `data/tenants/{company_id}/erp.db`
   - Keine Vermischung personenbezogener Daten (`crm_contacts`, Kommunikationsverläufe, DSGVO-Opt-Ins) oder steuerlicher Belege zwischen verschiedenen rechtlichen Einheiten.
   - Eigene, lückenlose DATEV-Nummernkreise pro Mandant:
     - **Debitoren (Kunden):** ab `10001`
     - **Kreditoren (Lieferanten):** ab `70001`
     - **Artikel & Leistungen:** ab `ART-1001`
     - **Angebote:** `ANG-{YYYY}-{0001}`
     - **Aufträge:** `AB-{YYYY}-{0001}`
     - **Ausgangsrechnungen:** `RE-{YYYY}-{0001}`

3. **Blueprint-Cloning statt monolithischem Fremd-ERP:**
   - Übernahme des erprobten **Subjekt-/Party-Modells** und des **Zustandsmodells (State-Machine)** aus Systemen wie Nuclos (`draft` -> `approved` -> `booked`/`sent` -> `paid` | `cancelled`), kombiniert mit dem schnellen Look & Feel des bestehenden LinkedIn-CRMs (Progressive Disclosure).

4. **Laptop-PocketBase-Synchronisation:**
   - Das lokale PocketBase-CRM auf dem Laptop (`Port 8090`, Collection `kontakte`) bleibt als mobiles LinkedIn-Werkzeug bestehen.
   - Pro Mandant (`company_id`) kann in `Corporate` eine optionale PocketBase-Sync-Quelle konfiguriert werden.
   - Der Sync gleicht Netzwerk- und Kommunikationsdaten (`name`, `unternehmen`, `rolle`, `rating`, `status`, `tags`, `nachrichtenverlauf`) mit `data/tenants/{company_id}/erp.db` ab, ohne kaufmännische ERP-Felder zu überschreiben.

---

## 2. Relationales Datenbank-Schema pro Mandant (`data/tenants/{company_id}/erp.db`)

### 2.1 Tabelle `crm_entities` (Geschäftspartner: Firmen & Einzelpersonen)
```sql
CREATE TABLE IF NOT EXISTS crm_entities (
    id TEXT PRIMARY KEY,                          -- z.B. 'ent-8f92a1b2'
    entity_type TEXT NOT NULL DEFAULT 'organization', -- 'organization' | 'person'
    display_name TEXT NOT NULL,                   -- Firmenname oder Vollname
    legal_form TEXT DEFAULT '',                   -- GmbH, AG, UG, e.K., Freelancer
    is_customer INTEGER DEFAULT 0,                -- 1 = Kunde (Debitor)
    is_supplier INTEGER DEFAULT 0,                -- 1 = Lieferant (Kreditor)
    is_partner INTEGER DEFAULT 0,                 -- 1 = Netzwerk / Kooperationspartner
    status TEXT DEFAULT 'lead',                   -- 'lead' | 'active' | 'on_hold' | 'blocked' | 'archived'
    debtor_no TEXT UNIQUE,                        -- DATEV Debitoren-Nr. (ab 10001)
    creditor_no TEXT UNIQUE,                      -- DATEV Kreditoren-Nr. (ab 70001)
    vat_id TEXT DEFAULT '',                       -- USt-IdNr. (z.B. DE123456789)
    tax_number TEXT DEFAULT '',                   -- Steuernummer
    tax_regime TEXT DEFAULT 'standard_19',        -- 'standard_19' | 'reverse_charge' | 'intra_eu' | 'export_0' | 'small_business'
    registry_court TEXT DEFAULT '',               -- Registergericht
    registry_number TEXT DEFAULT '',              -- HRB / HRA
    payment_terms_days INTEGER DEFAULT 14,        -- Zahlungsziel in Tagen
    skonto_pct REAL DEFAULT 0.0,                  -- Skonto %
    skonto_days INTEGER DEFAULT 0,                -- Skonto-Frist in Tagen
    currency TEXT DEFAULT 'EUR',
    credit_limit REAL DEFAULT 0.0,
    dunning_block INTEGER DEFAULT 0,              -- 1 = Mahnstopp aktiv
    bank_name TEXT DEFAULT '',
    iban TEXT DEFAULT '',
    bic TEXT DEFAULT '',
    sepa_mandate_ref TEXT DEFAULT '',
    street TEXT DEFAULT '',
    postal_code TEXT DEFAULT '',
    city TEXT DEFAULT '',
    country_code TEXT DEFAULT 'DE',
    billing_email TEXT DEFAULT '',                -- Rechnungsempfänger E-Mail (ZUGFeRD/PDF)
    website TEXT DEFAULT '',
    industry TEXT DEFAULT '',
    rating INTEGER DEFAULT 0,                     -- 0-5 Sterne (aggregiert oder manuell)
    tags_json TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 Tabelle `crm_contacts` (1:n Ansprechpartner & LinkedIn-Kontakte)
```sql
CREATE TABLE IF NOT EXISTS crm_contacts (
    id TEXT PRIMARY KEY,                          -- z.B. 'cnt-3b19c4d1'
    entity_id TEXT,                               -- FK -> crm_entities.id (NULL erlaubt für lose Kontakte)
    salutation TEXT DEFAULT '',                   -- Herr | Frau | Divers | Dr. | Prof.
    first_name TEXT DEFAULT '',
    last_name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role_title TEXT DEFAULT '',                   -- Position / Rolle
    department TEXT DEFAULT '',
    is_primary INTEGER DEFAULT 0,                 -- 1 = Hauptansprechpartner
    is_billing_recipient INTEGER DEFAULT 0,       -- 1 = Rechnungsempfänger
    email TEXT DEFAULT '',
    phone_direct TEXT DEFAULT '',
    phone_mobile TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    connection_status TEXT DEFAULT 'Vernetzt',    -- 'Vernetzt' | 'Unvernetzt' | 'Gesperrt_1Jahr'
    connected_since TEXT DEFAULT '',              -- YYYY-MM-DD
    rating INTEGER DEFAULT 0,                     -- 0-5 Sterne (LinkedIn-CRM Score)
    tags_json TEXT DEFAULT '[]',
    gdpr_opt_in_status TEXT DEFAULT 'legitimate_interest', -- 'unknown' | 'legitimate_interest' | 'double_opt_in' | 'revoked'
    gdpr_opt_in_date TEXT DEFAULT '',
    pocketbase_id TEXT UNIQUE,                    -- Zuordnung für Laptop-PocketBase-Sync
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES crm_entities(id) ON DELETE SET NULL
);
```

### 2.3 Tabelle `crm_interactions` (Nachrichtenverlauf & Kontakt-Timeline)
```sql
CREATE TABLE IF NOT EXISTS crm_interactions (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    contact_id TEXT,
    channel TEXT NOT NULL DEFAULT 'email_in',     -- 'email_in' | 'email_out' | 'linkedin' | 'telegram' | 'call' | 'note' | 'meeting'
    direction TEXT DEFAULT 'inbound',             -- 'inbound' | 'outbound' | 'internal'
    external_msg_id TEXT UNIQUE,                  -- Duplikatsschutz (messageId aus Outlook/LinkedIn)
    sender_name TEXT DEFAULT '',
    sender_email TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    body_text TEXT DEFAULT '',
    security_status TEXT DEFAULT 'safe',
    occurred_at TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES crm_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id) REFERENCES crm_contacts(id) ON DELETE CASCADE
);
```

### 2.4 Tabelle `erp_items` (Artikel- & Leistungsstamm)
```sql
CREATE TABLE IF NOT EXISTS erp_items (
    id TEXT PRIMARY KEY,                          -- z.B. 'itm-9a21f0'
    item_no TEXT UNIQUE NOT NULL,                 -- z.B. 'ART-1001'
    item_type TEXT NOT NULL DEFAULT 'service',    -- 'service' (Zeit) | 'flat_rate' (Werk) | 'saas' (Abo) | 'product' (Physisch)
    title TEXT NOT NULL,
    description TEXT DEFAULT '',                  -- Positionstext für Angebote/Rechnungen
    category TEXT DEFAULT 'Consulting',
    unit TEXT DEFAULT 'Std.',                     -- 'Std.' | 'Tag' | 'Pauschal' | 'Monat' | 'Stk.'
    sales_price_net REAL DEFAULT 0.0,             -- VK Netto
    purchase_price_net REAL DEFAULT 0.0,          -- EK Netto
    tax_rate_pct REAL DEFAULT 19.0,               -- 19.0 | 7.0 | 0.0
    currency TEXT DEFAULT 'EUR',
    billing_interval TEXT DEFAULT 'one_off',      -- 'one_off' | 'monthly' | 'quarterly' | 'yearly'
    supplier_entity_id TEXT,                      -- FK -> crm_entities.id (Hauptlieferant)
    track_inventory INTEGER DEFAULT 0,            -- 0 = Nein, 1 = Lagerbestand führen
    stock_qty REAL DEFAULT 0.0,
    min_stock_qty REAL DEFAULT 0.0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (supplier_entity_id) REFERENCES crm_entities(id) ON DELETE SET NULL
);
```

### 2.5 Tabellen `erp_documents` & `erp_document_lines` (Belegfluss: Angebot -> Auftrag -> Rechnung)
```sql
CREATE TABLE IF NOT EXISTS erp_documents (
    id TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,                       -- 'offer' (ANG) | 'order' (AB) | 'invoice' (RE) | 'credit_note' (GS)
    doc_number TEXT UNIQUE NOT NULL,              -- z.B. 'ANG-2026-0001' oder 'RE-2026-0001'
    status TEXT NOT NULL DEFAULT 'draft',         -- 'draft' | 'sent' | 'accepted' | 'booked' | 'paid' | 'overdue' | 'cancelled'
    entity_id TEXT NOT NULL,                      -- FK -> crm_entities.id
    contact_id TEXT,                              -- FK -> crm_contacts.id
    source_doc_id TEXT,                           -- Vorgänger-Beleg (z.B. Angebot -> Rechnung)
    deal_id TEXT,                                 -- Referenz auf Deal
    contract_id TEXT,                             -- Referenz auf Vertrag
    recipient_snapshot_json TEXT NOT NULL,        -- GoBD-unveränderlicher Adress-Snapshot bei Buchung
    issue_date TEXT NOT NULL,                     -- YYYY-MM-DD
    service_date TEXT DEFAULT '',                 -- Leistungsdatum / -zeitraum
    due_date TEXT DEFAULT '',                     -- Fälligkeitsdatum
    amount_net REAL DEFAULT 0.0,
    tax_amount REAL DEFAULT 0.0,
    amount_gross REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'EUR',
    tax_regime TEXT DEFAULT 'standard_19',
    payment_terms_days INTEGER DEFAULT 14,
    dunning_level INTEGER DEFAULT 0,
    dunning_fee REAL DEFAULT 0.0,
    notes TEXT DEFAULT '',
    booked_at TEXT,                               -- Zeitpunkt der GoBD-Festschreibung
    paid_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES crm_entities(id)
);

CREATE TABLE IF NOT EXISTS erp_document_lines (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    pos_no INTEGER NOT NULL,
    item_id TEXT,                                 -- FK -> erp_items.id (optional bei Freitextposition)
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
);
```

---

## 3. UI-Aufbau der 5 Ansichten in Säule 3 (`WIRTSCHAFT & ERP`)

| Sidebar-Menüpunkt | Sub-Tabs (72px Cadre-Kacheln im 80px-Header) | Kernfunktionen |
| :--- | :--- | :--- |
| **1. Adressen & CRM** (`nav-addresses`) | `Alle` · `Netzwerk (LinkedIn)` · `Kunden (10000+)` · `Lieferanten (70000+)` | Split-View wie im LinkedIn-CRM: Links Filter/Karten mit 0–5 Sternen & Status; Rechts Akte mit *Timeline/Nachrichten*, *1:n Ansprechpartnern*, *BWL-Konditionen* und *PocketBase-Sync*. |
| **2. Artikel & Leistungen** (`nav-items`) | `Alle Artikel` · `Dienstleistungen` · `SaaS & Abos` · `Produkte` | Verwaltung von `ART-1001+`, VK-Netto, EK-Netto, automatische Margenberechnung (€ / %), Hauptlieferant und optionalem Lagerbestand. |
| **3. Vorgänge & Verträge** (`nav-operations-erp`) | `Deal-Pipeline` · `Angebote & Aufträge` · `Verträge & Fristen` | Kanban-/Forecast-Pipeline, Angebotserstellung mit Artikel-Auswahl, 1-Klick-Wandlung *Angebot $\rightarrow$ Auftrag $\rightarrow$ Rechnung* sowie Vertrags-Fristenradar. |
| **4. Rechnungswesen** (`nav-finance`) | `Ausgangsrechnungen` · `Eingangsbelege (OCR)` · `Mahnwesen` · `Analytics & DATEV` | GoBD-konforme Rechnungen, Vision-OCR-Belegimport mit Lieferanten-Matching, 3-stufiges Mahnwesen (respektiert `dunning_block`) und DATEV-Export. |
| **5. Corporate & Vorlagen** (`nav-corporate`) | `Stammdaten & Design` · `Vorlagen-Studio` · `Mandanten-DB & Sync` | Multi-Company-Umschalter (schaltet aktiv `data/tenants/{company_id}/erp.db` um), DIN 5008 / § 14 UStG Vorlagen mit Live-CRM-Empfänger- und Artikel-Auswahl. |
