"""
backend/gdpr_compliance_engine.py
DSGVO- / GDPR-Compliance Engine für Archon OS 2026.
Implementiert Betroffenenrechte nach:
- Art. 15 DSGVO: Recht auf Auskunft (Datenexport über alle Datenquellen)
- Art. 17 DSGVO: Recht auf Löschung / Recht auf Vergessenwerden (Audit-sichere Anonymisierung/Löschung)
- Art. 30 DSGVO: Manipulationssicheres Verzeichnis von Verarbeitungstätigkeiten & Löschquittungen
"""
import datetime
import glob
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_archon_exc_logger = logging.getLogger("gdpr_compliance_engine")


class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# D03/HIGH: APP_DATA_DIR aus db_paths ist die kanonische Datenwurzel
# (respektiert ARCHON_DATA_DIR). Der Workspace-Pfad bleibt nur als
# Legacy-Zweig — exakt wie in db_backup_manager._tenant_roots().
try:
    from backend.db_paths import APP_DATA_DIR as _APP_DATA_DIR
except Exception:  # pragma: no cover - Modul wird standalone importiert
    _APP_DATA_DIR = os.path.join(WORKSPACE_DIR, "data")

# Epochen-Migration (block_id): neue Quittungen werden mit
# _chain_hash(canonical, next_id) signiert; die ID steht explizit in der Tabelle.
# CUTOFF markiert die erste ID der id-bewussten Epoche. Stabile, persistente
# Variante: ARCHON_GDPR_HMAC_EPOCH_FROM. Ohne ENV wird CUTOFF zur Laufzeit aus
# MAX(id)+1 der DB abgeleitet (siehe _chain_migration_cutoff).
_GDPR_CUTOFF_ENV = "ARCHON_GDPR_HMAC_EPOCH_FROM"
_GDPR_AUDIT_TABLE = "gdpr_audit_log"


def _chain_migration_cutoff(conn, table: str, env_name: str) -> int:
    """Erste Block-ID, ab der der id-bewusste Signaturpfad gilt.

    Die ENV-Variable ist die empfohlene Variante: sie ist ueber Neustarts
    hinweg stabil und kann zusammen mit ARCHON_AUDIT_HMAC_EPOCHS/..._FROM eine
    Key-Rotation ab genau diesem Block markieren. Ohne ENV wird MAX(id)+1 aus
    der DB gelesen — alle heute vorhandenen Bloecke sind dann Legacy und
    bleiben (auch mit altem Verfahren) verifizierbar. Es wird keine Tabelle,
    keine Spalte und keine Zeile hinzugefuegt oder veraendert.
    """
    raw = os.environ.get(env_name, "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return int(conn.execute(
        f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}"
    ).fetchone()[0])


def _resolve_db(name: str) -> str:
    """Delegiert an die zentrale, validierende Auflösung (backend/db_paths.py)."""
    from backend.db_paths import resolve_db
    return resolve_db(name)


def _resolve_obsidian_dir() -> str:
    candidates = [
        "/opt/data/obsidian",
        os.path.join(WORKSPACE_DIR, "obsidian_vault"),
        os.path.expanduser("~/Documents/Obsidian Vault")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[1]


def _pocketbase_db_files() -> List[str]:
    """D03/HIGH: ALLE physisch vorhandenen PocketBase-DBs, unabhängig vom
    `POCKETBASE_ENABLED`-Sync-Flag. Das Flag steuert nur den HTTP-Sync —
    personenbezogene Daten in pb_data/*.db bleiben auch bei deaktiviertem
    PocketBase Art.15/17-pflichtig (und werden regulär gesichert).
    """
    pb_dir = (
        os.getenv("ARCHON_POCKETBASE_DATA_DIR", "").strip()
        or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "pocketbase",
            "pb_data",
        )
    )
    if not os.path.isdir(pb_dir):
        return []
    return sorted(
        p for p in glob.glob(os.path.join(pb_dir, "*.db"))
        if os.path.isfile(p) and os.path.getsize(p) > 0
    )


def _db_copy_kind(name: str) -> Optional[str]:
    """D03/M3 (W1-D): Klassifiziert DB-Dateien fuer die gemeinsame SSOT-Liste.

    Erlaubt: ``<basis>.db``, ``<basis>.db.bak``, ``<basis>.db.before_<tag>``,
    ``<basis>.db-wal``, ``<basis>.db-shm``. Alles andere (``.db-journal``,
    ``.db.json``, ``*.json.bak``, …) wird bewusst abgelehnt, damit Art.15/17
    keine Fremddateien als SQLite oeffnet.

    ``-wal``/``-shm`` sind keine eigenen SQLite-Datenbanken; sie werden in
    Art.15/17 ueber ihre Basis-DB mitbehandelt (WAL-Checkpoint).
    """
    low = name.lower()
    if low.endswith("-wal") or low.endswith("-shm"):
        return "sidecar" if ".db" in low else None
    if low.endswith(".bak") or ".before_" in low:
        return "db" if ".db" in low else None
    if low.endswith(".db"):
        return "db"
    return None


def _tenant_roots() -> List[str]:
    """D03/HIGH + D03/M3: kanonischer Tenant-Root + Workspace-Legacy-Zweig
    + ehemalige Root-DB-Verzeichnisse (``_legacy_root_dbs_*``).

    Die Datenwurzel selbst ist keine "Tenant-Wurzel"; Root-Alt-Kopien
    (``ops.db.before_*``) werden in ``_tenant_db_files()`` ueber das Eltern-
    verzeichnis dieser Wurzeln erfasst.
    """
    # Dynamisch lesen, damit monkeypatch/ARCHON_DATA_DIR zur Laufzeit wirkt.
    try:
        from backend.db_paths import APP_DATA_DIR as canonical
    except Exception:
        canonical = _APP_DATA_DIR
    # __file__ dynamisch auswerten: Tests und Container-Mounts koennen den
    # Workspace-Pfad zur Laufzeit ersetzen (Legacy-Zweig darf nicht hart am
    # Import-Zeitpunkt haengen).
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_roots = [os.path.abspath(canonical)]
    legacy_data = os.path.abspath(os.path.join(workspace, "data"))
    if legacy_data not in data_roots:
        data_roots.append(legacy_data)

    roots: List[str] = []
    for data_root in data_roots:
        tenant_root = os.path.abspath(os.path.join(data_root, "tenants"))
        if tenant_root not in roots:
            roots.append(tenant_root)
        # D03/M3: ehemalige Root-DBs liegen unter _legacy_root_dbs_<ts>/ direkt
        # im Datenroot — als weitere, gleichberechtigte Wurzel aufnehmen.
        for legacy_dir in sorted(glob.glob(os.path.join(data_root, "_legacy_root_dbs_*"))):
            abs_legacy = os.path.abspath(legacy_dir)
            if os.path.isdir(abs_legacy) and abs_legacy not in roots:
                roots.append(abs_legacy)
    return roots


def _tenant_db_files() -> List[str]:
    """D03/M3 (W1-D): gemeinsame SSOT-Liste aller physisch vorhandenen
    DB-Dateien — inklusive Alt-Kopien und WAL/SHM-Sidecars.

    Vorher glomm diese Funktion nur ``root/*/*.db`` und uebersah damit
    ``*.db.bak``, ``ops.db.before_*`` sowie die Legacy-Wurzeln. Eine Art.17-
    Quittung konnte Erfolg melden, während vollstaendige Kopien ungeschwaerzt
    blieben. Alle Konsumenten (Art.15, Art.17, Backup, Restore-Test) muessen
    sich auf diese Liste stuetzen.
    """
    seen: set = set()
    found: List[str] = []

    def _add(path: str) -> None:
        full = os.path.abspath(path)
        if full in seen or not os.path.isfile(full) or os.path.getsize(full) == 0:
            return
        if _db_copy_kind(os.path.basename(full)) is None:
            return
        seen.add(full)
        found.append(full)

    roots = _tenant_roots()
    for root in roots:
        # Tenant-DBs eine Ebene tief + DBs direkt im Root (Legacy-Root-Verzeichnis).
        for pattern in ("*.db*", os.path.join("*", "*.db*")):
            for path in sorted(glob.glob(os.path.join(root, pattern))):
                _add(path)
    # D03/M3: Root-Alt-Kopien (ops.db.before_*) liegen direkt im Datenroot,
    # ausserhalb der Tenant-Verzeichnisse. Live-DBs (*.db) werden hier bewusst
    # nicht erneut gescannt — die erreicht Art.15/17 ueber resolve_db().
    for parent in sorted({os.path.dirname(r) for r in roots}):
        for pattern in ("*.db.bak", "*.db.before_*", "*.db-wal", "*.db-shm"):
            for path in sorted(glob.glob(os.path.join(parent, pattern))):
                _add(path)
    return found


def _maskable_db_files() -> List[str]:
    """D03/M3: aus der SSOT-Liste die als SQLite oeffnenden Ziele (ohne
    ``-wal``/``-shm`` — deren Inhalt wird ueber die Basis-DB mitbehandelt)."""
    return [
        p for p in _tenant_db_files()
        if _db_copy_kind(os.path.basename(p)) == "db"
    ]


def _tenant_resolution_errors() -> List[str]:
    """Fail-Closed: ein vorhandener, aber unbenutzbarer Tenant-Root ist ein Fehler."""
    errors: List[str] = []
    for root in _tenant_roots():
        if os.path.exists(root) and not os.path.isdir(root):
            errors.append(f"Tenant-Root ist keine Directory: {root}")
    return errors


_TENANT_TARGETS: Dict[str, List[str]] = {
    "crm_contacts": [
        "first_name", "last_name", "full_name", "email",
        "phone_direct", "phone_mobile", "linkedin_url", "notes",
    ],
    "crm_entities": [
        "display_name", "billing_email", "phone_main", "street", "iban", "notes",
    ],
    "crm_interactions": [
        "sender_name", "sender_email", "subject", "body_text",
    ],
    "contracts": ["contract_name", "partner_name", "notes"],
    "deals": ["title", "partner_name", "contact_email", "notes"],
    "kontakte": [
        "name", "email", "telefon_1", "telefon_2", "unternehmen", "firma",
        "kommentar", "nachrichtenverlauf", "linkedin_url", "adresse", "naechster_schritt",
    ],
    # D03/HIGH: PocketBase-Auth-Tabellen enthalten ebenfalls personenbezogene
    # Daten (v. a. email) und liegen im gleichen physischen Bestand.
    "users": ["email", "username", "name"],
    "_superusers": ["email", "username", "name"],
    "erp_bank_transactions": ["counterparty_name", "counterparty_iban", "remittance_info"],
    "bank_transactions": ["counterparty_name", "counterparty_iban", "remittance_info", "purpose"],
    # D03/MED (F012): unter FULL_TENANT_ISOLATION liegt die echte memory.db
    # unter data/tenants/<tid>/memory.db. Diese Tabellen wurden vorher nie
    # gescannt -> Learnings/Chats/Entwuerfe blieben ungeschwaerzt.
    # GoBD-geschuetzte Tabellen (erp_documents, receipts, invoices, ...) bleiben
    # bewusst ausgenommen und werden ueber die Sperrpruefung behandelt.
    "learnings": ["summary", "content", "title"],
    "conversations": ["content", "summary", "title"],
    "human_feedback": ["comment", "corrected_text", "task_prompt"],
    "email_drafts": ["subject", "recipient", "body_text"],
}

_DEFAULT_ROPA_ACTIVITIES: List[Dict[str, str]] = [
    {
        "activity_id": "vvt-crm-erp",
        "name": "Kunden-, Lieferanten- und Auftragsverwaltung (ERP & CRM)",
        "purpose": "Vertragsanbahnung, Auftragsabwicklung, Stammdaten- und Kontaktpflege",
        "legal_basis": "Art. 6 Abs. 1 lit. b, c DSGVO",
        "data_categories": "Name, Anschrift, E-Mail, Telefon, USt-IdNr., Bankverbindung, Kommunikationshistorie",
        "data_subjects": "Kunden, Interessenten, Lieferanten, Ansprechpartner",
        "recipient_categories": "Interne Fachabteilungen, Steuerberater, ggf. Zahlungsdienstleister",
        "third_country_transfers": "Keine (lokale Datenhaltung / On-Premise)",
        "retention_period": "8 Jahre ab Jahresschluss für Buchungsbelege (BEG IV / § 147 Abs. 3 AO); 6 Jahre für Handelsbriefe",
        "technical_organizational_measures": "Mandantenisolation (SQLite WAL je Tenant), RBAC, Audit-Hashkette, PII-Scrubber",
    },
    {
        "activity_id": "vvt-finance-gobd",
        "name": "Finanzbuchhaltung, Rechnungslegung & Zahlungsabgleich (GoBD / EN 16931)",
        "purpose": "Rechnungsstellung, E-Rechnung (XRechnung/ZUGFeRD), DATEV-/GoBD-Z3-Export, Bankabgleich",
        "legal_basis": "Art. 6 Abs. 1 lit. c DSGVO i.V.m. §§ 14, 14b UStG, § 147 AO, § 257 HGB",
        "data_categories": "Rechnungsdaten, Leistungspositionen, IBAN, Transaktionsdaten, Belegempfänger-Snapshots",
        "data_subjects": "Geschäftspartner, Debitoren, Kreditoren",
        "recipient_categories": "Steuerberatung, Finanzbehörden (GoBD Z3 / Betriebsprüfung)",
        "third_country_transfers": "Keine",
        "retention_period": "8 Jahre für Buchungsbelege (BEG IV seit 01.01.2025); 10 Jahre für Jahresabschlüsse & steuerliche Sonderfristen",
        "technical_organizational_measures": "GoBD-Unveränderbarkeit, Storno-Gegenbuchung (381), SHA-256-Hashkette",
    },
    {
        "activity_id": "vvt-dunning",
        "name": "Forderungsmanagement & Mahnwesen (§§ 286, 288 BGB)",
        "purpose": "Überwachung offener Posten, Zahlungserinnerungen und Mahnläufe mit HITL-Freigabe",
        "legal_basis": "Art. 6 Abs. 1 lit. b, f DSGVO",
        "data_categories": "Name, Rechnungsnummer, E-Mail, Anschrift, Fälligkeit, Mahnhistorie",
        "data_subjects": "Säumige Geschäftskunden und Privatkunden",
        "recipient_categories": "Interne Buchhaltung, ggf. Rechtsberatung / Inkasso nach HITL-Freigabe",
        "third_country_transfers": "Keine",
        "retention_period": "3 Jahre Regelverjährung (§ 195 BGB) bzw. 8 Jahre bei Verknüpfung mit Buchungsbelegen",
        "technical_organizational_measures": "Human-in-the-Loop-Freigabe vor Versand, B2B/B2C-Trennung",
    },
    {
        "activity_id": "vvt-contracts-esign",
        "name": "Vertragsmanagement & elektronische Signatur (DocuSeal)",
        "purpose": "Vertragsprüfung, Fristenüberwachung (§§ 187, 188 BGB) und digitale Signaturarchivierung",
        "legal_basis": "Art. 6 Abs. 1 lit. b, c DSGVO",
        "data_categories": "Vertragsinhalte, Unterzeichnername, E-Mail, Signatur-PDF, Zeitstempel",
        "data_subjects": "Vertragspartner, Bevollmächtigte, Mitarbeitende",
        "recipient_categories": "Interne Rechtsabteilung, Vertragspartner, lokal gehosteter DocuSeal-Dienst",
        "third_country_transfers": "Keine (lokales DocuSeal-Deployment)",
        "retention_period": "6 Jahre nach Vertragsende (§ 257 HGB) bzw. 10 Jahre bei steuerlich relevanten Urkunden",
        "technical_organizational_measures": "Mandantengetrennte PDF-Ablage, HMAC-/Webhook-Prüfung, RBAC",
    },
    {
        "activity_id": "vvt-ai-assistant",
        "name": "KI-Assistenz, Wissensspeicher & Kommunikationsverarbeitung",
        "purpose": "Bearbeitung interner Aufgaben, E-Mail-/Chat-Auswertung und Wissensmanagement",
        "legal_basis": "Art. 6 Abs. 1 lit. a, b, f DSGVO",
        "data_categories": "Chat-Nachrichten, Aufgabeninhalte, Feedback, Notizen",
        "data_subjects": "Nutzende, Ansprechpartner, Projektbeteiligte",
        "recipient_categories": "Lokale KI-Modelle (Zero-Egress); externe KI-APIs nur nach PII-Maskierung/Freigabe",
        "third_country_transfers": "Nur bei expliziter Freigabe externer APIs mit Art. 46 DSGVO Standardvertragsklauseln",
        "retention_period": "Bis Zweckerfüllung oder Widerruf / Art. 17 DSGVO-Löschung",
        "technical_organizational_measures": "Zero-Egress-Guard, PII-Scrubber, Dual-LLM-Sanitizer, Audit-Log",
    },
]


def _compile_subject_regex(term: str) -> re.Pattern:
    """Erstellt ein Wortgrenzen-/Token-Regex, damit kurze Suchbegriffe keine Fremddaten leaken."""
    escaped = re.escape(term)
    if "@" in term:
        return re.compile(rf"(?<![A-Za-z0-9._%+-]){escaped}(?![A-Za-z0-9._%+-])", re.IGNORECASE)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def _matches_subject(value: Any, pattern: re.Pattern) -> bool:
    if value is None:
        return False
    return bool(pattern.search(str(value)))


def _is_within_retention_period(
    date_str: Optional[str],
    retention_years: int = 8,
    as_of: Optional[datetime.date] = None,
) -> bool:
    """Prüft gesetzliche Aufbewahrung (§ 147 Abs. 3, 4 AO / § 257 HGB / BEG IV: 8J bzw. 10J Sonderfristen)."""
    today = as_of or datetime.date.today()
    raw = str(date_str or "").strip()
    m = re.match(r"^(\d{4})", raw)
    if not m:
        return True
    year = int(m.group(1))
    # Beginn am Schluss des Kalenderjahres (§ 147 Abs. 4 AO)
    expiry = datetime.date(year + int(retention_years), 12, 31)
    return today <= expiry


class GDPRComplianceEngine:
    """Steuert Datenauskunft und Datenlöschung über alle Speicherschichten."""

    def __init__(self):
        self.memory_db = _resolve_db("agentic_memory.db")
        self.kanban_db = _resolve_db("kanban.db")
        self.state_db = _resolve_db("state.db")
        self.obsidian_dir = _resolve_obsidian_dir()
        self._init_audit_table()

    def _get_conn(self, db_path: str, readonly: bool = False) -> sqlite3.Connection:
        # D03/HIGH: FK-Integritaet und busy_timeout-SSOT auf JEDER Verbindung.
        # Bewusst KEIN journal_mode-Write-PRAGMA: PocketBase besitzt die WAL
        # seiner DBs; Art.17 darf dort nur die Zeilen aendern.
        from backend.db_paths import DB_BUSY_TIMEOUT_MS
        timeout = DB_BUSY_TIMEOUT_MS / 1000.0
        if readonly and os.path.exists(db_path):
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=timeout)
        else:
            conn = sqlite3.connect(db_path, timeout=timeout)
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_audit_table(self):
        """Erstellt die manipulationssichere Tabelle für DSGVO-Löschquittungen sowie Art. 30 VVT."""
        if os.path.exists(self.memory_db):
            try:
                with sqlite3.connect(self.memory_db, timeout=5.0, factory=_ArchonClosingConn) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS gdpr_audit_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            receipt_id TEXT UNIQUE NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            action TEXT NOT NULL,
                            identifier_hash TEXT NOT NULL,
                            records_affected INTEGER NOT NULL,
                            details_json TEXT,
                            prev_hash TEXT,
                            hash TEXT NOT NULL
                        )
                    """)
                    # H3 (Audit 23.11.2026): DSGVO-Löschquittungen sind
                    # revisionsrelevant -> append-only wie die Zentralkette.
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS gdpr_audit_no_update
                        BEFORE UPDATE ON gdpr_audit_log
                        BEGIN
                            SELECT RAISE(ABORT, 'gdpr_audit_log is append-only');
                        END
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS gdpr_audit_no_delete
                        BEFORE DELETE ON gdpr_audit_log
                        BEGIN
                            SELECT RAISE(ABORT, 'gdpr_audit_log is append-only');
                        END
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS gdpr_ropa_activities (
                            activity_id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            purpose TEXT NOT NULL,
                            legal_basis TEXT NOT NULL,
                            data_categories TEXT NOT NULL,
                            data_subjects TEXT NOT NULL,
                            recipient_categories TEXT NOT NULL,
                            third_country_transfers TEXT DEFAULT 'Keine',
                            retention_period TEXT NOT NULL,
                            technical_organizational_measures TEXT DEFAULT '',
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cnt = conn.execute("SELECT COUNT(*) FROM gdpr_ropa_activities").fetchone()[0]
                    if cnt == 0:
                        for act in _DEFAULT_ROPA_ACTIVITIES:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO gdpr_ropa_activities (
                                    activity_id, name, purpose, legal_basis, data_categories,
                                    data_subjects, recipient_categories, third_country_transfers,
                                    retention_period, technical_organizational_measures
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    act["activity_id"], act["name"], act["purpose"], act["legal_basis"],
                                    act["data_categories"], act["data_subjects"], act["recipient_categories"],
                                    act["third_country_transfers"], act["retention_period"],
                                    act["technical_organizational_measures"],
                                ),
                            )
                    conn.commit()
            except Exception as e:
                print(f"[GDPR] Audit-Tabellen-Initialisierung fehlgeschlagen: {e}", file=sys.stderr)

    @staticmethod
    def _build_art15_disclosures() -> Dict[str, Any]:
        """Pflichtangaben gemäß Art. 15 Abs. 1 & 2 DSGVO."""
        return {
            "purposes": [
                "Vertragsabwicklung, Angebotserstellung, Abrechnung und Zahlungsabgleich (Art. 6 Abs. 1 lit. b DSGVO)",
                "Erfüllung handels- und steuerrechtlicher Aufbewahrungspflichten (Art. 6 Abs. 1 lit. c DSGVO i.V.m. AO/HGB/UStG)",
                "IT-Sicherheit, Revisionssicherheit und Forderungsmanagement (Art. 6 Abs. 1 lit. f DSGVO)",
                "Kommunikation und KI-gestützte Assistenz auf Basis von Vertrag oder Einwilligung (Art. 6 Abs. 1 lit. a/b DSGVO)",
            ],
            "data_categories": [
                "Stammdaten & Kontaktdaten (Name, Anschrift, E-Mail, Telefon, USt-IdNr.)",
                "Vertrags-, Rechnungs- und Zahlungsdaten (inkl. IBAN, Belegpositionen, Signaturstatus)",
                "Kommunikations-, Aufgaben- und Protokolldaten (Chat, E-Mail-Entwürfe, Kanban, Notizen)",
            ],
            "recipient_categories": [
                "Interne Fachabteilungen (Vertrieb, Buchhaltung, Recht, Support)",
                "Steuerberatung sowie Finanz- und Aufsichtsbehörden im Rahmen gesetzlicher Vorlagepflichten (z. B. GoBD Z3)",
                "Auftragsverarbeiter / Zahlungs- und Versanddienstleister (z. B. SMTP-Provider, lokal betriebenes DocuSeal)",
            ],
            "retention_periods": {
                "accounting_records_beg_iv": "8 Jahre ab Schluss des Kalenderjahres für Buchungsbelege, Rechnungen und Zahlungsdaten (BEG IV seit 01.01.2025, § 147 Abs. 3 AO, § 257 Abs. 4 HGB)",
                "tax_special_and_statements": "10 Jahre ab Jahresschluss für Jahresabschlüsse, Bilanzen, Inventare und steuerliche Sonderfristen (§ 147 Abs. 1 Nr. 1 AO)",
                "commercial_correspondence_and_contracts": "6 Jahre ab Jahresschluss für Handelsbriefe und Vertragsunterlagen (§ 257 Abs. 1 Nr. 2 HGB)",
                "operational_chat_and_tasks": "Löschung bzw. Anonymisierung nach Zweckerfüllung, Widerruf oder Art. 17 DSGVO-Antrag",
            },
            "data_subject_rights": (
                "Recht auf Berichtigung (Art. 16 DSGVO), Löschung (Art. 17 DSGVO), Einschränkung der Verarbeitung "
                "(Art. 18 DSGVO), Datenübertragbarkeit (Art. 20 DSGVO), Widerspruch (Art. 21 DSGVO) sowie "
                "Widerruf erteilter Einwilligungen (Art. 7 Abs. 3 DSGVO)."
            ),
            "supervisory_authority_complaint": (
                "Sie haben gemäß Art. 77 DSGVO das Recht, sich bei einer Datenschutz-Aufsichtsbehörde über die "
                "Verarbeitung Ihrer personenbezogenen Daten zu beschweren."
            ),
            "automated_decision_making": (
                "Hinweis gemäß Art. 15 Abs. 1 lit. h i.V.m. Art. 22 DSGVO: Es findet keine ausschließlich "
                "automatisierte Entscheidungsfindung einschließlich Profiling mit rechtlicher Wirkung statt; "
                "kritische Vorgänge (z. B. Mahnwesen, E-Mail-Versand, Vertragsfreigaben) unterliegen einer "
                "menschlichen Prüfung (Human-in-the-Loop)."
            ),
            "data_source": "Direkterhebung bei der betroffenen Person, Vertrags-/Rechnungsverkehr sowie interne Projektkommunikation (Art. 15 Abs. 1 lit. g DSGVO).",
        }

    def export_subject_data(self, identifier: str, max_messages: Optional[int] = None) -> Dict[str, Any]:
        """Art. 15 DSGVO: Erstellt einen vollständigen Datenauszug für eine Person (E-Mail, Name, Telefon)."""
        term = identifier.strip()
        if not term or len(term) < 3:
            raise ValueError("Suchbegriff muss mindestens 3 Zeichen lang sein.")
        term_pat = _compile_subject_regex(term)

        now_iso = datetime.datetime.now().isoformat()
        export: Dict[str, Any] = {
            "requested_identifier": term,
            "export_timestamp": now_iso,
            "legal_basis": "Art. 15 DSGVO (Auskunftsrecht)",
            "mandatory_art15_disclosures": self._build_art15_disclosures(),
            "is_truncated": False,
            "sources": {
                "kanban_tasks": [],
                "chat_messages": [],
                "memory_learnings": [],
                "feedback_and_evals": [],
                "crm_contacts": [],
                "tenant_records": [],
                "receipts": [],
                "esign_contracts": [],
                "invoices": [],
                "obsidian_notes": [],
            },
            "total_records_found": 0,
        }

        # 1. Kanban Tasks (kanban.db)
        if os.path.exists(self.kanban_db):
            try:
                with self._get_conn(self.kanban_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, title, body, assignee, status, created_at, result
                        FROM tasks
                        WHERE title LIKE ? OR body LIKE ? OR result LIKE ?
                    """, (f"%{term}%", f"%{term}%", f"%{term}%"))
                    for r in cur.fetchall():
                        d = dict(r)
                        if any(_matches_subject(d.get(k), term_pat) for k in ("title", "body", "result")):
                            export["sources"]["kanban_tasks"].append(d)
            except Exception as e:
                export["sources"]["kanban_tasks_error"] = str(e)

        # 2. Chat-Nachrichten (state.db) — standardmäßig paginierter Voll-Export (Art. 15 DSGVO)
        if os.path.exists(self.state_db):
            try:
                with self._get_conn(self.state_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    matched_msgs: List[Dict[str, Any]] = []
                    page_size = 500
                    offset = 0
                    while True:
                        cur.execute("""
                            SELECT id, session_id, role, content, timestamp
                            FROM messages
                            WHERE content LIKE ?
                            ORDER BY id ASC
                            LIMIT ? OFFSET ?
                        """, (f"%{term}%", page_size, offset))
                        chunk = [dict(r) for r in cur.fetchall()]
                        if not chunk:
                            break
                        for row_d in chunk:
                            if _matches_subject(row_d.get("content"), term_pat):
                                matched_msgs.append(row_d)
                        if len(chunk) < page_size:
                            break
                        offset += page_size
                    total_count = len(matched_msgs)
                    if max_messages is not None and max_messages > 0:
                        msgs = matched_msgs[: int(max_messages)]
                        truncated = total_count > len(msgs)
                    else:
                        msgs = matched_msgs
                        truncated = False
                    export["sources"]["chat_messages"] = msgs
                    export["sources"]["chat_messages_truncated"] = truncated
                    export["sources"]["chat_messages_total_count"] = total_count
                    if truncated:
                        export["is_truncated"] = True
            except Exception as e:
                export["sources"]["chat_messages_error"] = str(e)

        # 3. Langzeitgedächtnis, Beleg-Scanner, E-Signatur & Mahnwesen (agentic_memory.db)
        if os.path.exists(self.memory_db):
            try:
                with self._get_conn(self.memory_db, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learnings'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM learnings WHERE summary LIKE ?", (f"%{term}%",))
                        for r in cur.fetchall():
                            d = dict(r)
                            if _matches_subject(d.get("summary"), term_pat):
                                export["sources"]["memory_learnings"].append(d)

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='human_feedback'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM human_feedback WHERE comment LIKE ? OR corrected_text LIKE ? OR task_prompt LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        for r in cur.fetchall():
                            d = dict(r)
                            if any(_matches_subject(d.get(k), term_pat) for k in ("comment", "corrected_text", "task_prompt")):
                                export["sources"]["feedback_and_evals"].append(d)

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='receipts'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM receipts WHERE sender LIKE ? OR merchant LIKE ? OR details_json LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        for r in cur.fetchall():
                            d = dict(r)
                            if any(_matches_subject(d.get(k), term_pat) for k in ("sender", "merchant", "details_json")):
                                export["sources"]["receipts"].append(d)

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='esign_contracts'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM esign_contracts WHERE signer_email LIKE ? OR signer_name LIKE ? OR title LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        for r in cur.fetchall():
                            d = dict(r)
                            if any(_matches_subject(d.get(k), term_pat) for k in ("signer_email", "signer_name", "title")):
                                export["sources"]["esign_contracts"].append(d)

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoices'")
                    if cur.fetchone():
                        cur.execute("SELECT * FROM invoices WHERE customer_name LIKE ? OR customer_email LIKE ? OR recipient_address LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        for r in cur.fetchall():
                            d = dict(r)
                            if any(_matches_subject(d.get(k), term_pat) for k in ("customer_name", "customer_email", "recipient_address")):
                                export["sources"]["invoices"].append(d)
            except Exception as e:
                export["sources"]["memory_error"] = str(e)

        # 3b. Multi-Tenant-DBs (ERP, Contracts, Deals, CRM crm.db, Banktransaktionen)
        # D03/HIGH: APP_DATA_DIR (ARCHON_DATA_DIR) ist kanonisch, Workspace-Legacy
        # bleibt ergaenzend erhalten — kein stilles Leer-Globbing mehr.
        tenant_db_files = _tenant_db_files()
        export["sources"]["tenant_roots"] = _tenant_roots()
        export["sources"]["tenant_dbs_scanned"] = len(tenant_db_files)
        resolution_errors = _tenant_resolution_errors()
        if resolution_errors:
            export["sources"]["tenant_resolver_errors"] = resolution_errors
        # D03/HIGH: PocketBase-Bestand unabhaengig vom POCKETBASE_ENABLED-Flag
        # in Art.15/17 einbeziehen (die DBs liegen physisch im Repo und werden
        # auch gesichert — "deaktiviert" darf nicht "unloeschbar" bedeuten).
        # D03/M3: SQL-Ziele aus der gemeinsamen SSOT-Liste; -wal/-shm sind
        # keine DBs und werden ueber ihre Basis-DB (WAL-Checkpoint) behandelt.
        mask_targets = [
            p for p in tenant_db_files
            if _db_copy_kind(os.path.basename(p)) == "db"
        ] + _pocketbase_db_files()
        like_pat = f"%{term}%"
        for tdb in mask_targets:
            tenant_name = os.path.basename(os.path.dirname(tdb))
            db_name = os.path.basename(tdb)
            try:
                with self._get_conn(tdb, readonly=True) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    for tbl, cols in _TENANT_TARGETS.items():
                        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                        if not cur.fetchone():
                            continue
                        cur.execute(f"PRAGMA table_info({tbl})")
                        avail = {r[1] for r in cur.fetchall()}
                        use_cols = [c for c in cols if c in avail]
                        if not use_cols:
                            continue
                        where_sql = " OR ".join(f"{c} LIKE ?" for c in use_cols)
                        sel_cols = (["id"] if "id" in avail else []) + use_cols
                        sel_sql = f"SELECT {', '.join(sel_cols)} FROM {tbl} WHERE {where_sql}"
                        for row in cur.execute(sel_sql, [like_pat] * len(use_cols)).fetchall():
                            d = dict(row)
                            if any(_matches_subject(d.get(c), term_pat) for c in use_cols):
                                d["_tenant"] = tenant_name
                                d["_db"] = db_name
                                d["_table"] = tbl
                                export["sources"]["tenant_records"].append(d)
            except Exception as e:
                export["sources"][f"tenant_error_{tenant_name}_{db_name}"] = str(e)

        # 4. PocketBase CRM Kontakte (nur aktiv, wenn explizit POCKETBASE_ENABLED=true)
        if os.getenv("POCKETBASE_ENABLED", "false").strip().lower() in ("1", "true", "yes"):
            pb_urls = [os.getenv("POCKETBASE_URL", "http://pocketbase:8090"), "http://127.0.0.1:8090"]
            for pb in pb_urls:
                try:
                    filter_q = urllib.parse.quote(f'name ~ "{term}" || email ~ "{term}" || firma ~ "{term}"')
                    url = f"{pb.rstrip('/')}/api/collections/kontakte/records?filter={filter_q}"
                    req = urllib.request.Request(url, headers={"User-Agent": "ArchonGDPR/1.0"})
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            items = [
                                it for it in data.get("items", [])
                                if any(_matches_subject(it.get(k), term_pat) for k in ("name", "email", "firma"))
                            ]
                            export["sources"]["crm_contacts"] = items
                            break
                except Exception:
                    continue

        # 5. Obsidian Vault Notizen
        if os.path.exists(self.obsidian_dir):
            try:
                target_subdirs = {"00_HR_Agenten", "Bewerbung", "Bewerbungen", "01_PROJEKTE", "Kontakte"}
                opened = 0
                for root, dirs, files in os.walk(self.obsidian_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                        "node_modules", ".git", "AgenticOS-2026", "__pycache__", ".venv", ".pytest_cache", "attachments", "Archiv", "02_Wissensbibliothek"
                    )]
                    rel = os.path.relpath(root, self.obsidian_dir)
                    top = rel.split(os.sep)[0]
                    is_relevant_dir = (rel == ".") or (top in target_subdirs)

                    for f in files:
                        if f.endswith(".md"):
                            fpath = os.path.join(root, f)
                            if _matches_subject(f, term_pat):
                                export["sources"]["obsidian_notes"].append({
                                    "file": f,
                                    "path": fpath,
                                    "size_bytes": os.path.getsize(fpath),
                                    "match_type": "filename"
                                })
                                continue

                            if is_relevant_dir and opened < 150:
                                opened += 1
                                try:
                                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                                        if _matches_subject(fh.read(), term_pat):
                                            export["sources"]["obsidian_notes"].append({
                                                "file": f,
                                                "path": fpath,
                                                "size_bytes": os.path.getsize(fpath),
                                                "match_type": "content"
                                            })
                                except Exception as _exc:
                                    _archon_exc_logger.debug("[gdpr_compliance_engine] Ignorierte Ausnahme (Z.510): %s", _exc)
            except Exception as e:
                export["sources"]["obsidian_error"] = str(e)

        total = sum(len(v) for k, v in export["sources"].items() if isinstance(v, list))
        # R-33: Gesamtanzahl beruecksichtigt ungedeckelte Zaehler
        if export.get("is_truncated") and "chat_messages_total_count" in export["sources"]:
            total = total - len(export["sources"]["chat_messages"]) + export["sources"]["chat_messages_total_count"]
        export["total_records_found"] = total
        return export

    def erase_subject_data(self, identifier: str, dry_run: bool = False, anonymize: bool = True) -> Dict[str, Any]:
        """Art. 17 DSGVO: Löscht oder anonymisiert alle Daten zu einer Person und erstellt eine Hash-Löschquittung."""
        term = identifier.strip()
        if not term or len(term) < 3:
            raise ValueError("Suchbegriff muss mindestens 3 Zeichen lang sein.")
        term_pat = _compile_subject_regex(term)

        replacement = "[ANONYMISIERT_DSGVO_ART17]" if anonymize else ""
        errors: List[str] = []
        legal_holds: List[Dict[str, Any]] = []
        results: Dict[str, Any] = {
            "requested_identifier": term,
            "dry_run": dry_run,
            "mode": "anonymize" if anonymize else "purge",
            "timestamp": datetime.datetime.now().isoformat(),
            "retention_policy": {
                "beg_iv_accounting_years": 8,
                "tax_special_years": 10,
                "commercial_letters_years": 6,
            },
            "affected": {
                "kanban_tasks": 0,
                "chat_messages": 0,
                "memory_conversations": 0,
                "memory_learnings": 0,
                "feedback_entries": 0,
                "crm_contacts": 0,
                "tenant_records": 0,
                # W1-B: tenant-scoped lossless Session-DAG (Turns/Summaries)
                "lossless_turns": 0,
                "lossless_summaries": 0,
                "receipts": 0,
                "esign_contracts": 0,
                "invoices": 0,
                "obsidian_notes": 0,
            },
            "legal_holds": legal_holds,
            "total_affected": 0,
            "receipt": None,
        }

        def _redact_ci(val: Optional[str]) -> str:
            # Art. 17: das GANZE Feld anonymisieren, nicht nur das gematchte
            # Token. Vorher wurde aus "Michael Keller" "[ANONYMISIERT] Keller"
            # — der Nachname blieb personenbezogen.
            text = str(val or "")
            return replacement if _matches_subject(text, term_pat) else text

        # 1. Kanban Tasks
        if os.path.exists(self.kanban_db):
            try:
                with self._get_conn(self.kanban_db, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, title, body, result FROM tasks
                        WHERE title LIKE ? OR body LIKE ? OR result LIKE ?
                    """, (f"%{term}%", f"%{term}%", f"%{term}%"))
                    rows = [
                        r for r in cur.fetchall()
                        if any(_matches_subject(r[idx], term_pat) for idx in (1, 2, 3))
                    ]
                    results["affected"]["kanban_tasks"] = len(rows)

                    if not dry_run and rows:
                        for tid, t_title, t_body, t_res in rows:
                            cur.execute("""
                                UPDATE tasks SET title = ?, body = ?, result = ?
                                WHERE id = ?
                            """, (_redact_ci(t_title), _redact_ci(t_body), _redact_ci(t_res), tid))
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Kanban-Löschung: {e}", file=sys.stderr)
                errors.append(f"Kanban: {e}")

        # 2. Chat Nachrichten (state.db)
        if os.path.exists(self.state_db):
            try:
                with self._get_conn(self.state_db, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, content FROM messages WHERE content LIKE ?", (f"%{term}%",))
                    rows = [r for r in cur.fetchall() if _matches_subject(r[1], term_pat)]
                    results["affected"]["chat_messages"] = len(rows)

                    if not dry_run and rows:
                        for mid, cont in rows:
                            cur.execute("UPDATE messages SET content = ? WHERE id = ?", (_redact_ci(cont), mid))
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Chat-Löschung: {e}", file=sys.stderr)
                errors.append(f"Chat: {e}")

        # 3. Langzeitgedächtnis, Belege, E-Signatur & Mahnwesen (agentic_memory.db)
        if os.path.exists(self.memory_db):
            try:
                with self._get_conn(self.memory_db, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learnings'")
                    if cur.fetchone():
                        cur.execute("SELECT id, summary FROM learnings WHERE summary LIKE ?", (f"%{term}%",))
                        l_rows = [r for r in cur.fetchall() if _matches_subject(r[1], term_pat)]
                        results["affected"]["memory_learnings"] = len(l_rows)
                        if not dry_run and l_rows:
                            for lid, s in l_rows:
                                cur.execute("UPDATE learnings SET summary = ? WHERE id = ?",
                                            (_redact_ci(s), lid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'")
                    if cur.fetchone():
                        cur.execute("SELECT id, content FROM conversations WHERE content LIKE ?", (f"%{term}%",))
                        c_rows = [r for r in cur.fetchall() if _matches_subject(r[1], term_pat)]
                        results["affected"]["memory_conversations"] = len(c_rows)
                        if not dry_run and c_rows:
                            for cid, cont in c_rows:
                                cur.execute("UPDATE conversations SET content = ? WHERE id = ?", (_redact_ci(cont), cid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='human_feedback'")
                    if cur.fetchone():
                        cur.execute("SELECT id, comment, corrected_text FROM human_feedback WHERE comment LIKE ? OR corrected_text LIKE ?", (f"%{term}%", f"%{term}%"))
                        f_rows = [r for r in cur.fetchall() if any(_matches_subject(r[idx], term_pat) for idx in (1, 2))]
                        results["affected"]["feedback_entries"] = len(f_rows)
                        if not dry_run and f_rows:
                            for fid, c, cr in f_rows:
                                cur.execute("UPDATE human_feedback SET comment = ?, corrected_text = ? WHERE id = ?",
                                            (_redact_ci(c), _redact_ci(cr), fid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='email_drafts'")
                    if cur.fetchone():
                        cur.execute("SELECT draft_id, subject, recipient, body_text FROM email_drafts WHERE recipient LIKE ? OR subject LIKE ? OR body_text LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        ed_rows = [r for r in cur.fetchall() if any(_matches_subject(r[idx], term_pat) for idx in (1, 2, 3))]
                        results["affected"]["email_drafts"] = len(ed_rows)
                        if not dry_run and ed_rows:
                            for did, subj, recp, btxt in ed_rows:
                                cur.execute("UPDATE email_drafts SET subject = ?, recipient = ?, body_text = ? WHERE draft_id = ?",
                                            (_redact_ci(subj), _redact_ci(recp), _redact_ci(btxt), did))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='receipts'")
                    if cur.fetchone():
                        cur.execute("SELECT id, sender, merchant, details_json, receipt_date, created_at, category FROM receipts WHERE sender LIKE ? OR merchant LIKE ? OR details_json LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        rc_rows = [r for r in cur.fetchall() if any(_matches_subject(r[idx], term_pat) for idx in (1, 2, 3))]
                        for rid, snd, mrc, det, rdt, cdt, cat in rc_rows:
                            cat_low = str(cat or "").lower()
                            ret_years = 10 if any(k in cat_low for k in ("abschluss", "bilanz", "steuer", "anlage", "special")) else 8
                            if _is_within_retention_period(rdt or cdt, retention_years=ret_years):
                                results["affected"]["legal_hold_restricted"] = results["affected"].get("legal_hold_restricted", 0) + 1
                                legal_holds.append({
                                    "table": "receipts",
                                    "record_id": str(rid),
                                    "retention_years": ret_years,
                                    "legal_basis": "§ 147 Abs. 1 Nr. 1 AO (10J Sonderfrist)" if ret_years == 10 else "§ 147 Abs. 3 AO / BEG IV (8J Buchungsbelege)",
                                })
                                continue
                            results["affected"]["receipts"] += 1
                            if not dry_run:
                                cur.execute("UPDATE receipts SET sender = ?, merchant = ?, details_json = ? WHERE id = ?",
                                            (_redact_ci(snd), _redact_ci(mrc), _redact_ci(det), rid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='esign_contracts'")
                    if cur.fetchone():
                        cur.execute("SELECT id, title, signer_email, signer_name FROM esign_contracts WHERE title LIKE ? OR signer_email LIKE ? OR signer_name LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        es_rows = [r for r in cur.fetchall() if any(_matches_subject(r[idx], term_pat) for idx in (1, 2, 3))]
                        results["affected"]["esign_contracts"] = len(es_rows)
                        if not dry_run and es_rows:
                            for eid, etitle, eemail, ename in es_rows:
                                cur.execute("UPDATE esign_contracts SET title = ?, signer_email = ?, signer_name = ? WHERE id = ?",
                                            (_redact_ci(etitle), _redact_ci(eemail), _redact_ci(ename), eid))

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoices'")
                    if cur.fetchone():
                        cur.execute("SELECT id, customer_name, customer_email, recipient_address, invoice_date, status FROM invoices WHERE customer_name LIKE ? OR customer_email LIKE ? OR recipient_address LIKE ?", (f"%{term}%", f"%{term}%", f"%{term}%"))
                        inv_rows = [r for r in cur.fetchall() if any(_matches_subject(r[idx], term_pat) for idx in (1, 2, 3))]
                        for iid, cname, cmail, raddr, idate, istat in inv_rows:
                            if _is_within_retention_period(idate, retention_years=8):
                                results["affected"]["legal_hold_restricted"] = results["affected"].get("legal_hold_restricted", 0) + 1
                                legal_holds.append({
                                    "table": "invoices",
                                    "record_id": str(iid),
                                    "retention_years": 8,
                                    "legal_basis": "§ 147 Abs. 3 AO / § 257 Abs. 4 HGB / BEG IV (8 Jahre)",
                                })
                                continue
                            results["affected"]["invoices"] += 1
                            if not dry_run:
                                cur.execute("UPDATE invoices SET customer_name = ?, customer_email = ?, recipient_address = ? WHERE id = ?",
                                            (_redact_ci(cname), _redact_ci(cmail), _redact_ci(raddr), iid))

                    if not dry_run:
                        conn.commit()
            except Exception as e:
                print(f"[GDPR] Fehler bei Memory-Löschung: {e}", file=sys.stderr)
                errors.append(f"Memory: {e}")

        # 3b. Multi-Tenant-DBs (ERP, Contracts, Deals, CRM crm.db, Banktransaktionen) mit BEG IV / § 147 AO Sperrprüfung
        # D03/HIGH: gleiche Root-Auflösung wie in Art.15 (APP_DATA_DIR + Legacy).
        tenant_db_files = _tenant_db_files()
        results["tenant_db_files_scanned"] = len(tenant_db_files)
        results["tenant_roots"] = _tenant_roots()
        errors.extend(_tenant_resolution_errors())
        # D03/M3: SQL-Ziele aus der gemeinsamen SSOT-Liste; -wal/-shm sind
        # keine DBs und werden ueber ihre Basis-DB (WAL-Checkpoint) behandelt.
        mask_targets = [
            p for p in tenant_db_files
            if _db_copy_kind(os.path.basename(p)) == "db"
        ]
        # W1-B: die lossless Session-DAG liegt in memory.db/lcm_sessions.db —
        # sowohl pro Tenant als auch in der zentralen (konsolidierten) memory.db.
        dag_db_files = [
            p for p in mask_targets
            if os.path.basename(p) in ("memory.db", "lcm_sessions.db")
        ]
        if os.path.isfile(self.memory_db) and self.memory_db not in dag_db_files:
            dag_db_files.append(self.memory_db)
        # D03/HIGH: PocketBase-Bestand unabhaengig vom POCKETBASE_ENABLED-Flag
        # in Art.15/17 einbeziehen (die DBs liegen physisch im Repo und werden
        # auch gesichert — "deaktiviert" darf nicht "unloeschbar" bedeuten).
        mask_targets += _pocketbase_db_files()
        like_pat = f"%{term}%"
        for tdb in mask_targets:
            try:
                with self._get_conn(tdb, readonly=dry_run) as conn:
                    cur = conn.cursor()
                    protected_entity_reasons: Dict[str, Tuple[int, str]] = {}
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='erp_documents'")
                    if cur.fetchone():
                        cur.execute("PRAGMA table_info(erp_documents)")
                        erp_cols = {r[1] for r in cur.fetchall()}
                        sel_fields = ["entity_id", "status"]
                        for opt_col in ("issue_date", "booked_at", "doc_type", "tax_regime"):
                            if opt_col in erp_cols:
                                sel_fields.append(opt_col)
                        for erp_row in cur.execute(
                            f"SELECT {', '.join(sel_fields)} FROM erp_documents WHERE status IN ('booked', 'paid', 'cancelled') AND entity_id IS NOT NULL"
                        ).fetchall():
                            row_map = dict(zip(sel_fields, erp_row))
                            if row_map.get("status") == "cancelled" and not row_map.get("booked_at"):
                                continue
                            doc_type_val = str(row_map.get("doc_type") or "")
                            tax_reg_val = str(row_map.get("tax_regime") or "")
                            ret_years = 10 if (
                                doc_type_val in ("annual_statement", "tax_special", "balance_sheet", "inventory")
                                or tax_reg_val == "tax_special_10y"
                            ) else 8
                            ref_date = row_map.get("issue_date") or row_map.get("booked_at")
                            if _is_within_retention_period(ref_date, retention_years=ret_years):
                                ent_key = str(row_map["entity_id"])
                                prev_yr = protected_entity_reasons.get(ent_key, (0, ""))[0]
                                if ret_years >= prev_yr:
                                    basis = (
                                        "§ 147 Abs. 1 Nr. 1 AO (10 Jahre Sonderfrist)"
                                        if ret_years == 10
                                        else "§ 147 Abs. 3 AO / § 257 Abs. 4 HGB / BEG IV (8 Jahre)"
                                    )
                                    protected_entity_reasons[ent_key] = (ret_years, basis)

                    for tbl, cols in _TENANT_TARGETS.items():
                        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                        if not cur.fetchone():
                            continue
                        cur.execute(f"PRAGMA table_info({tbl})")
                        avail = {r[1] for r in cur.fetchall()}
                        use_cols = [c for c in cols if c in avail]
                        # email_drafts nutzt draft_id statt id — sonst bleibt
                        # genau diese Tabelle unter FULL_TENANT_ISOLATION ungeschwaerzt.
                        id_col = "id" if "id" in avail else ("draft_id" if "draft_id" in avail else None)
                        if not use_cols or not id_col:
                            continue
                        extra_cols = [c for c in ("booking_date", "value_date") if c in avail and c not in use_cols]
                        where_sql = " OR ".join(f"{c} LIKE ?" for c in use_cols)
                        sel_sql = f"SELECT {id_col}, {', '.join(use_cols + extra_cols)} FROM {tbl} WHERE {where_sql}"
                        t_rows = cur.execute(sel_sql, [like_pat] * len(use_cols)).fetchall()
                        for row in t_rows:
                            if not any(_matches_subject(row[idx + 1], term_pat) for idx in range(len(use_cols))):
                                continue
                            rid = str(row[0])
                            if tbl == "crm_entities" and rid in protected_entity_reasons:
                                ret_years, basis = protected_entity_reasons[rid]
                                results["affected"]["legal_hold_restricted"] = results["affected"].get("legal_hold_restricted", 0) + 1
                                legal_holds.append({
                                    "table": tbl,
                                    "record_id": rid,
                                    "retention_years": ret_years,
                                    "legal_basis": basis,
                                })
                                if not dry_run and "notes" in avail:
                                    cur.execute(
                                        "UPDATE crm_entities SET notes = ? WHERE id = ?",
                                        (f"[DSGVO Art. 18 Sperre: Aufbewahrungspflicht gem. {basis}]", rid),
                                    )
                                continue
                            if tbl in ("erp_bank_transactions", "bank_transactions"):
                                bdate = row[1 + len(use_cols)] if extra_cols else None
                                if _is_within_retention_period(bdate, retention_years=8):
                                    results["affected"]["legal_hold_restricted"] = results["affected"].get("legal_hold_restricted", 0) + 1
                                    legal_holds.append({
                                        "table": tbl,
                                        "record_id": rid,
                                        "retention_years": 8,
                                        "legal_basis": "§ 147 Abs. 3 AO / § 257 Abs. 4 HGB / BEG IV (8 Jahre)",
                                    })
                                    continue
                            results["affected"]["tenant_records"] += 1
                            if not dry_run:
                                set_sql = ", ".join(f"{c} = ?" for c in use_cols)
                                upd_sql = f"UPDATE {tbl} SET {set_sql} WHERE {id_col} = ?"
                                vals = [_redact_ci(row[idx + 1]) for idx in range(len(use_cols))]
                                cur.execute(upd_sql, vals + [rid])
                    if not dry_run:
                        conn.commit()
                        # D03/M3: -wal/-shm-Sidecars sind keine SQL-Ziele. Ein
                        # TRUNCATE-Checkpoint schreibt die (geschwaerzten)
                        # Seiten zurueck in die DB und leert das WAL, damit
                        # keine unmaskierte PII im Sidecar zurueckbleibt.
                        try:
                            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                            if str(mode).lower() == "wal":
                                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                        except sqlite3.Error as exc:
                            errors.append(
                                f"WAL-Checkpoint({os.path.basename(tdb)}): {exc}"
                            )
            except Exception as e:
                print(f"[GDPR] Fehler bei Tenant-DB {os.path.basename(tdb)}: {e}", file=sys.stderr)
                errors.append(f"Tenant({os.path.basename(tdb)}): {e}")

        # 3b-2. W1-B: tenant-scoped lossless Session-DAG (Turns + neu
        # signierte Summaries). Ohne diesen Aufruf bleiben personenbezogene
        # Turns/Summaries geschuetzt, obwohl Art.17 eine Quittung ausstellt.
        results["lossless_dag"] = {}
        for dag_db in dag_db_files:
            try:
                from backend.lossless_session_dag import (
                    anonymize_subject_in_lossless_history,
                )
                tenant_id = (
                    os.path.basename(os.path.dirname(dag_db))
                    if os.path.basename(dag_db) in ("memory.db", "lcm_sessions.db")
                    and os.path.basename(os.path.dirname(dag_db)) != "data"
                    else None
                )
                dag_res = anonymize_subject_in_lossless_history(
                    term, tenant_id=tenant_id, dry_run=dry_run, db_path=dag_db
                )
                key = tenant_id or "central"
                results["lossless_dag"][key] = dag_res
                results["affected"]["lossless_turns"] += int(dag_res.get("turns", 0))
                results["affected"]["lossless_summaries"] += int(dag_res.get("summaries", 0))
            except Exception as e:
                print(f"[GDPR] Fehler bei Lossless-DAG {dag_db}: {e}", file=sys.stderr)
                errors.append(f"LosslessDAG({os.path.basename(dag_db)}): {e}")

        # 3c. Obsidian Vault Notizen bereinigen
        if os.path.exists(self.obsidian_dir):
            try:
                target_subdirs = {"00_HR_Agenten", "Bewerbung", "Bewerbungen", "01_PROJEKTE", "Kontakte"}
                opened = 0
                for root, dirs, files in os.walk(self.obsidian_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                        "node_modules", ".git", "AgenticOS-2026", "__pycache__", ".venv", ".pytest_cache", "attachments", "Archiv", "02_Wissensbibliothek"
                    )]
                    rel = os.path.relpath(root, self.obsidian_dir)
                    top = rel.split(os.sep)[0]
                    is_relevant_dir = (rel == ".") or (top in target_subdirs)
                    if not is_relevant_dir:
                        continue
                    for f in files:
                        if f.endswith(".md") and opened < 250:
                            opened += 1
                            fpath = os.path.join(root, f)
                            try:
                                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                                    content = fh.read()
                                if _matches_subject(content, term_pat):
                                    results["affected"]["obsidian_notes"] += 1
                                    if not dry_run:
                                        with open(fpath, "w", encoding="utf-8") as fh:
                                            fh.write(_redact_ci(content))
                            except Exception as e_obs:
                                errors.append(f"Obsidian({f}): {e_obs}")
            except Exception as e:
                errors.append(f"Obsidian: {e}")

        if errors:
            results["errors"] = errors
            results["status"] = "failed"
            results["receipt"] = None
            raise RuntimeError(f"DSGVO Art. 17 Löschung unvollständig, Fehler in Stores: {', '.join(errors)}")

        total = sum(results["affected"].values())
        results["total_affected"] = total

        # D03/HIGH (F012): keine Erfolgs-Quittung ohne Treffer, wenn Mandanten-
        # DBs bekannt sind. Ein 0-Treffer-Lauf bei vorhandenen Tenant-DBs bedeutet
        # praktisch immer eine falsche Root-Auflösung (z. B. ignoriertes
        # ARCHON_DATA_DIR) — genau der Fall, der vorher still als Erfolg galt.
        if total == 0 and results.get("tenant_db_files_scanned", 0) > 0:
            results["status"] = "failed"
            results["receipt"] = None
            raise RuntimeError(
                "DSGVO Art. 17: 0 Treffer bei "
                f"{results['tenant_db_files_scanned']} bekannten Tenant-DBs unter "
                f"{results.get('tenant_roots')} — keine Löschquittung ausgestellt "
                "(Tenant-Root/Resolver prüfen)."
            )

        # 4. Audit-Log Quittung erstellen
        if not dry_run:
            receipt = self._write_audit_receipt(term, total, results["affected"], results["mode"])
            results["receipt"] = receipt

            # NotificationHub informieren
            try:
                from backend.notification_hub import get_notification_hub
                get_notification_hub().dispatch_notification(
                    title="DSGVO-Löschung ausgeführt",
                    message=f"Art. 17 DSGVO Löschung/Anonymisierung für Hash '{receipt['identifier_hash'][:12]}...': {total} Datensätze bereinigt. Quittung: {receipt['receipt_id']}",
                    severity="WARNING",
                    category="gdpr_compliance"
                )
            except Exception as _exc:
                _archon_exc_logger.debug("[gdpr_compliance_engine] Ignorierte Ausnahme (Z.857): %s", _exc)
        else:
            results["receipt"] = {
                "receipt_id": "DRY-RUN-PREVIEW",
                "action": "dry_run_simulation",
                "identifier_hash": hashlib.sha256(term.encode("utf-8")).hexdigest(),
                "records_affected": total,
                "receipt_hash": "SIMULATION_NO_CHANGES_COMMITTED"
            }

        return results

    def list_processing_activities(self) -> List[Dict[str, Any]]:
        """Art. 30 DSGVO: Liefert das Verzeichnis von Verarbeitungstätigkeiten (VVT)."""
        if not os.path.exists(self.memory_db):
            return [dict(a) for a in _DEFAULT_ROPA_ACTIVITIES]
        self._init_audit_table()
        with self._get_conn(self.memory_db, readonly=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM gdpr_ropa_activities ORDER BY activity_id ASC").fetchall()
            if not rows:
                return [dict(a) for a in _DEFAULT_ROPA_ACTIVITIES]
            return [dict(r) for r in rows]

    def upsert_processing_activity(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Art. 30 DSGVO: Legt eine Verarbeitungstätigkeit im VVT an oder aktualisiert sie."""
        import uuid
        aid = str(payload.get("activity_id") or f"vvt-{uuid.uuid4().hex[:8]}").strip()
        name = str(payload.get("name") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        legal_basis = str(payload.get("legal_basis") or "").strip()
        if not name or not purpose or not legal_basis:
            raise ValueError("Art. 30 DSGVO: 'name', 'purpose' und 'legal_basis' sind Pflichtfelder.")
        if not os.path.exists(self.memory_db):
            open(self.memory_db, "a").close()
        self._init_audit_table()
        now_iso = datetime.datetime.now().isoformat()
        with self._get_conn(self.memory_db) as conn:
            conn.execute(
                """
                INSERT INTO gdpr_ropa_activities (
                    activity_id, name, purpose, legal_basis, data_categories,
                    data_subjects, recipient_categories, third_country_transfers,
                    retention_period, technical_organizational_measures, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    name=excluded.name,
                    purpose=excluded.purpose,
                    legal_basis=excluded.legal_basis,
                    data_categories=excluded.data_categories,
                    data_subjects=excluded.data_subjects,
                    recipient_categories=excluded.recipient_categories,
                    third_country_transfers=excluded.third_country_transfers,
                    retention_period=excluded.retention_period,
                    technical_organizational_measures=excluded.technical_organizational_measures,
                    updated_at=excluded.updated_at
                """,
                (
                    aid,
                    name,
                    purpose,
                    legal_basis,
                    str(payload.get("data_categories") or "-"),
                    str(payload.get("data_subjects") or "-"),
                    str(payload.get("recipient_categories") or "-"),
                    str(payload.get("third_country_transfers") or "Keine"),
                    str(payload.get("retention_period") or "8 Jahre (BEG IV) bzw. nach Zweckerfüllung"),
                    str(payload.get("technical_organizational_measures") or ""),
                    now_iso,
                ),
            )
            conn.commit()
        return next((a for a in self.list_processing_activities() if a["activity_id"] == aid), {"activity_id": aid, "name": name})

    def export_processing_register(self, fmt: str = "json") -> Dict[str, Any]:
        """Art. 30 DSGVO: Exportiert das vollständige Verzeichnis von Verarbeitungstätigkeiten (JSON / CSV / Markdown)."""
        activities = self.list_processing_activities()
        controller: Dict[str, Any] = {}
        try:
            from backend.corporate_manager import corporate_manager
            comp = corporate_manager.get_company("archon-systems") or {}
            c_addr = comp.get("address") if isinstance(comp.get("address"), dict) else {}
            c_cnt = comp.get("contact") if isinstance(comp.get("contact"), dict) else {}
            c_reg = comp.get("registry") if isinstance(comp.get("registry"), dict) else {}
            controller = {
                "name": comp.get("name") or "Archon Systems GmbH",
                "address": f"{c_addr.get('street', '')}, {c_addr.get('postal_code', '')} {c_addr.get('city', '')}".strip(", "),  # type: ignore[union-attr]
                "representative": c_reg.get("managing_directors") or "Geschäftsführung",  # type: ignore[union-attr]
                "email": c_cnt.get("email") or "",  # type: ignore[union-attr]
            }
        except Exception:
            controller = {"name": "Archon Systems"}

        out: Dict[str, Any] = {
            "legal_basis": "Art. 30 DSGVO (Verzeichnis von Verarbeitungstätigkeiten)",
            "generated_at": datetime.datetime.now().isoformat(),
            "controller": controller,
            "activity_count": len(activities),
            "activities": activities,
        }
        fmt_low = str(fmt or "json").strip().lower()
        if fmt_low == "csv":
            import csv
            import io
            buf = io.StringIO()
            cols = [
                "activity_id", "name", "purpose", "legal_basis", "data_categories",
                "data_subjects", "recipient_categories", "third_country_transfers",
                "retention_period", "technical_organizational_measures",
            ]
            writer = csv.writer(buf, delimiter=";")
            writer.writerow(cols)
            for act in activities:
                writer.writerow([act.get(c, "") for c in cols])
            out["csv"] = buf.getvalue()
        elif fmt_low in ("md", "markdown"):
            lines = [
                "# Verzeichnis von Verarbeitungstätigkeiten (Art. 30 DSGVO)",
                f"Verantwortlicher: {controller.get('name', '')} ({controller.get('address', '')})",
                "",
            ]
            for act in activities:
                lines.extend([
                    f"## {act.get('name', '')} (`{act.get('activity_id', '')}`)",
                    f"- **Zweck:** {act.get('purpose', '')}",
                    f"- **Rechtsgrundlage:** {act.get('legal_basis', '')}",
                    f"- **Datenkategorien:** {act.get('data_categories', '')}",
                    f"- **Betroffene:** {act.get('data_subjects', '')}",
                    f"- **Empfänger:** {act.get('recipient_categories', '')}",
                    f"- **Drittlandtransfer:** {act.get('third_country_transfers', '')}",
                    f"- **Löschfristen:** {act.get('retention_period', '')}",
                    f"- **TOMs:** {act.get('technical_organizational_measures', '')}",
                    "",
                ])
            out["markdown"] = "\n".join(lines)
        return out

    def _write_audit_receipt(self, term: str, count: int, breakdown: Dict[str, int], mode: str) -> Dict[str, Any]:
        """Schreibt eine kryptografische Löschquittung (ohne das gelöschte PII selbst zu speichern!)."""
        import uuid
        receipt_id = f"gdpr-rcpt-{uuid.uuid4().hex[:8]}"
        id_hash = hashlib.sha256(term.lower().encode("utf-8")).hexdigest()
        # GoBD: eindeutige UTC-Zeitreferenz (früher naive Lokalzeit).
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        details_str = json.dumps({"mode": mode, "breakdown": breakdown})

        prev_hash = "GENESIS"
        with self._get_conn(self.memory_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT hash FROM gdpr_audit_log ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                prev_hash = row[0]

            # Epochen-Migration: Schreib- und Pruefpfad muessen dieselbe ID
            # verwenden, sonst ist eine Key-Rotation mit EPOCH_FROM wirkungslos
            # (gleicher Fix wie in audit_log.record_event / api_key_manager).
            next_id = int(cur.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM gdpr_audit_log"
            ).fetchone()[0])
            record_payload = f"{receipt_id}|ERASE_ART17|{now_iso}|{id_hash}|{count}|{details_str}|{prev_hash}"
            # H3: HMAC mit zentralem Chain-Secret statt nacktem SHA-256.
            # id-bewusst: Epochen-Key des Blocks statt immer juengstem Key.
            from backend.audit_log import _chain_hash
            record_hash = _chain_hash(record_payload, next_id)

            # timestamp explizit schreiben: der kanonische String enthaelt
            # now_iso, der SQLite-Default CURRENT_TIMESTAMP hatte eine andere
            # Form und machte neue Quittungen nicht rekonstruierbar.
            cur.execute("""
                INSERT INTO gdpr_audit_log (id, receipt_id, action, identifier_hash, records_affected, details_json, prev_hash, hash, timestamp)
                VALUES (?, ?, 'ERASE_ART17', ?, ?, ?, ?, ?, ?)
            """, (next_id, receipt_id, id_hash, count, details_str, prev_hash, record_hash, now_iso))
            conn.commit()

        return {
            "receipt_id": receipt_id,
            "timestamp": now_iso,
            "identifier_hash": id_hash,
            "records_affected": count,
            "tamper_proof_hash": record_hash,
            "previous_receipt_hash": prev_hash
        }

    def verify_audit_chain(self) -> Dict[str, Any]:
        """Kryptografische Pruefung der DSGVO-Quittungskette (Legacy + Epoche)."""
        return verify_gdpr_audit_chain(self.memory_db)

    def list_audit_receipts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Gibt die gespeicherten DSGVO-Löschquittungen zurück."""
        if not os.path.exists(self.memory_db):
            return []
        with self._get_conn(self.memory_db, readonly=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM gdpr_audit_log ORDER BY id DESC LIMIT ?", (limit,))
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["details"] = json.loads(d["details_json"])
                except Exception:
                    d["details"] = {}
                rows.append(d)
            return rows


def verify_gdpr_audit_chain(db_path: Optional[str] = None) -> Dict[str, Any]:
    """d05 F-03: DSGVO-Kette + Head-Anker + Trigger."""
    from backend.audit_log import finalize_secondary_chain_verification
    return finalize_secondary_chain_verification(
        "gdpr_audit_log", _verify_gdpr_audit_chain_raw(db_path), db_path=db_path
    )


def _verify_gdpr_audit_chain_raw(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Prueft die gdpr_audit_log-Kette inkl. Epochen-Migration.

    Strategie pro Block:
      * id >= CUTOFF: streng id-bewusst via _verify_hash(canonical, hash, id).
      * id <  CUTOFF: zuerst id-bewusst, danach als Fallback das alte Verfahren
        ohne ID. Der Fallback erhaelt Legacy-Quittungen auch nach einer
        Key-Rotation mit ARCHON_AUDIT_HMAC_EPOCHS / ..._EPOCH_FROM gueltig.

    CUTOFF = ARCHON_GDPR_HMAC_EPOCH_FROM (stabil, dokumentiert), sonst MAX(id)+1
    zur Laufzeit. Die prev_hash-Verkettung ist Verfahren-unabhaengig: der Hash
    einer neuen Quittung haengt vom gespeicherten prev_hash ab, nicht davon,
    wie der Vorgaenger signiert wurde — der Uebergang ist daher bruchfrei.
    """
    from backend.audit_log import HMAC_PREFIX, _hmac_epochs, _verify_hash
    from backend.db_paths import DB_BUSY_TIMEOUT_S
    conn = sqlite3.connect(db_path or _resolve_db("agentic_memory.db"), timeout=DB_BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    try:
        has_tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_GDPR_AUDIT_TABLE,),
        ).fetchone()
        if not has_tbl:
            return {"valid": True, "count": 0, "message": "DSGVO-Kette ist leer."}
        rows = conn.execute("SELECT * FROM gdpr_audit_log ORDER BY id ASC").fetchall()
        if not rows:
            return {"valid": True, "count": 0, "message": "DSGVO-Kette ist leer."}

        cutoff = _chain_migration_cutoff(conn, _GDPR_AUDIT_TABLE, _GDPR_CUTOFF_ENV)
        expected_prev = "GENESIS"
        hmac_blocks = 0
        for r in rows:
            if str(r["prev_hash"]) != expected_prev:
                return {
                    "valid": False, "broken_at_id": r["id"], "cutoff": cutoff,
                    "message": f"Kettenbruch bei DSGVO-Audit ID {r['id']}.",
                }
            # Exakt derselbe kanonische String wie im Schreibpfad.
            canonical = (
                f"{r['receipt_id']}|ERASE_ART17|{r['timestamp']}|"
                f"{r['identifier_hash']}|{int(r['records_affected'])}|"
                f"{r['details_json']}|{r['prev_hash']}"
            )
            stored = str(r["hash"] or "")
            if stored.startswith(HMAC_PREFIX):
                hmac_blocks += 1
            bid = int(r["id"])
            ok = _verify_hash(canonical, stored, bid)
            if not ok and bid < cutoff:
                ok = _verify_hash(canonical, stored, None)
            if not ok:
                return {
                    "valid": False, "broken_at_id": bid, "cutoff": cutoff,
                    "message": f"Payload-Manipulation bei DSGVO-Audit ID {bid}.",
                }
            expected_prev = stored

        key_active = bool(_hmac_epochs())
        first_hmac_id = next(
            (int(r["id"]) for r in rows if str(r["hash"] or "").startswith(HMAC_PREFIX)),
            None,
        )
        if first_hmac_id is not None and any(
            int(r["id"]) > first_hmac_id and not str(r["hash"] or "").startswith(HMAC_PREFIX)
            for r in rows
        ):
            return {
                "valid": False, "cutoff": cutoff, "hmac_active": key_active,
                "message": "HMAC-Signatur auf nacktes SHA-256 zurueckgesetzt (Downgrade).",
            }
        if hmac_blocks and not key_active:
            return {
                "valid": False, "cutoff": cutoff, "hmac_active": False,
                "message": "HMAC-Bloecke ohne passenden ARCHON_AUDIT_HMAC_KEY.",
            }
        return {
            "valid": True, "count": len(rows), "cutoff": cutoff,
            "hmac_active": key_active, "hmac_blocks": hmac_blocks,
            "latest_hash": expected_prev,
        }
    finally:
        conn.close()


gdpr_engine = GDPRComplianceEngine()
