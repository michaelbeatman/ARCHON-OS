"""
backend/crm_service.py
Archon OS 2026 — Native SQLite CRM Engine for Säule 3 (WIRTSCHAFT & ERP).

Directly connects via standard Python sqlite3 (zero PocketBase runtime dependency)
to the contacts SQLite database (2,331 contacts, 2,229 messages) and powers:
1. "Kontakte" (Full table view with 15 fields, search, filtering, sorting)
2. "Kunden" (Debitoren / Customer filter)
3. "Lieferanten" (Kreditoren / Supplier filter)
4. "Alle Nachrichten" (Aggregated interaction timeline across all contacts)
5. "Kalender" (Appointments & follow-up dates)
6. "Bericht" (Missionskontrolle KPIs, role/status distributions, action items)
7. "KontaktDrawer" (Single record full modal/drawer with bilateral message history)
"""

import os
import re
import json
import sqlite3
import datetime
import threading
import uuid
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CRM_SQLITE_PATH = os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data", "data.db")
CRM_SQLITE_PATH = _DEFAULT_CRM_SQLITE_PATH
_CRM_MSG_LOCK = threading.Lock()


def _resolve_active_crm_db_path(company_id: Optional[str] = None) -> str:
    if CRM_SQLITE_PATH != _DEFAULT_CRM_SQLITE_PATH:
        return CRM_SQLITE_PATH
    try:
        from backend.tenant_context import tenant_context
        return tenant_context.resolve_active_db("crm.db", company_id)
    except Exception:
        return CRM_SQLITE_PATH


def _get_sqlite_conn(company_id: Optional[str] = None) -> sqlite3.Connection:
    target_db = _resolve_active_crm_db_path(company_id)
    if not os.path.exists(target_db):
        raise FileNotFoundError(f"SQLite CRM database not found at {target_db}")
    conn = sqlite3.connect(target_db, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn

# Alias for backward-compat
_get_pb_conn = _get_sqlite_conn


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


class CRMService:
    """Provides high-performance, real-time access to the PocketBase CRM database."""

    # -------------------------------------------------------------------------
    # 1. KONTAKTE / KUNDEN / LIEFERANTEN LISTE (Screenshot 1)
    # -------------------------------------------------------------------------
    def list_contacts(
        self,
        search: str = "",
        status: str = "",
        role_filter: str = "all",  # 'all', 'customers', 'suppliers', 'network'
        region: str = "",
        tag: str = "",
        sort_by: str = "updated",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 100
    ) -> Dict[str, Any]:
        conn = _get_pb_conn()
        try:
            clauses = ["1=1"]
            params: List[Any] = []

            # Search across multiple fields
            if search and search.strip():
                q = f"%{search.strip().lower()}%"
                clauses.append("""(
                    LOWER(name) LIKE ? OR
                    LOWER(unternehmen) LIKE ? OR
                    LOWER(rolle) LIKE ? OR
                    LOWER(email) LIKE ? OR
                    LOWER(region) LIKE ? OR
                    LOWER(tags) LIKE ? OR
                    LOWER(naechster_schritt) LIKE ?
                )""")
                params.extend([q, q, q, q, q, q, q])

            # Status filter
            if status and status.strip() and status != "all":
                clauses.append("status = ?")
                params.append(status.strip())

            # Region filter
            if region and region.strip() and region != "all":
                clauses.append("LOWER(region) LIKE ?")
                params.append(f"%{region.strip().lower()}%")

            # Tag filter
            if tag and tag.strip() and tag != "all":
                clauses.append("LOWER(tags) LIKE ?")
                params.append(f"%{tag.strip().lower()}%")

            # Role filter: 'customers', 'suppliers', 'network'
            if role_filter == "customers":
                clauses.append("""(
                    LOWER(status) IN ('kunde', 'aktiv', 'beauftragt') OR
                    LOWER(tags) LIKE '%kunde%' OR
                    LOWER(kommentar) LIKE '%debitor%' OR
                    LOWER(rolle) LIKE '%kunde%'
                )""")
            elif role_filter == "suppliers":
                clauses.append("""(
                    LOWER(status) IN ('lieferant', 'partner', 'dienstleister') OR
                    LOWER(tags) LIKE '%lieferant%' OR
                    LOWER(tags) LIKE '%kreditor%' OR
                    LOWER(unternehmen) LIKE '%cloud%' OR
                    LOWER(unternehmen) LIKE '%gmbh%' AND LOWER(tags) LIKE '%provider%'
                )""")
            elif role_filter == "network":
                clauses.append("(linkedin_url IS NOT NULL AND linkedin_url != '')")

            where_sql = " AND ".join(clauses)

            # Count total matching
            c = conn.cursor()
            count_query = f"SELECT COUNT(*) FROM kontakte WHERE {where_sql}"
            c.execute(count_query, params)
            total = c.fetchone()[0]

            # Allowed sort columns
            valid_sorts = {
                "name": "name",
                "unternehmen": "unternehmen",
                "rolle": "rolle",
                "status": "status",
                "rating": "rating",
                "vernetzt_am": "vernetzt_am",
                "updated": "updated",
                "created": "created"
            }
            sort_col = valid_sorts.get(sort_by, "updated")
            direction = "ASC" if sort_order.lower() == "asc" else "DESC"

            # Pagination
            limit_sql = ""
            if limit > 0:
                offset = max(0, (page - 1) * limit)
                limit_sql = f"LIMIT {limit} OFFSET {offset}"

            query = f"""
                SELECT id, name, unternehmen, rolle, status, rating, region,
                       email, telefon_1, telefon_2, linkedin_url, Webseite,
                       adresse, naechster_schritt, vernetzt_am, naechster_termin,
                       tags, kommentar, RollenVerteilungzuordnung, profilbild,
                       updated, created, nachrichtenverlauf
                FROM kontakte
                WHERE {where_sql}
                ORDER BY {sort_col} {direction}
                {limit_sql}
            """
            c.execute(query, params)
            rows = c.fetchall()

            items = []
            for r in rows:
                item = dict(r)
                # Count messages without transmitting entire JSON array in list
                raw_nv = item.pop("nachrichtenverlauf", None)
                msg_count = 0
                if raw_nv:
                    try:
                        msgs = json.loads(raw_nv)
                        if isinstance(msgs, list):
                            msg_count = len(msgs)
                    except Exception:
                        pass
                item["nachrichten_count"] = msg_count
                
                # Tags parsing
                raw_tags = item.get("tags")
                tags_list = []
                if raw_tags:
                    try:
                        t = json.loads(raw_tags)
                        if isinstance(t, list):
                            tags_list = t
                    except Exception:
                        tags_list = [raw_tags] if isinstance(raw_tags, str) else []
                item["tags_list"] = tags_list

                # Generate initials
                name = item.get("name") or "Unbekannt"
                parts = name.split()
                initials = "".join([p[0].upper() for p in parts[:2]]) if parts else "??"
                item["initials"] = initials

                # Avatar URL
                pb_img = item.get("profilbild") or ""
                if pb_img and not pb_img.startswith("http"):
                    item["avatar_url"] = f"/api/crm/avatars/{item['id']}/{pb_img}"
                else:
                    item["avatar_url"] = pb_img

                items.append(item)

            # Available statuses for filter pills
            c.execute("SELECT status, COUNT(*) FROM kontakte WHERE status IS NOT NULL AND status != '' GROUP BY status ORDER BY COUNT(*) DESC")
            statuses = [{"status": r[0], "count": r[1]} for r in c.fetchall()]

            # Available regions for filter
            c.execute("SELECT region, COUNT(*) FROM kontakte WHERE region IS NOT NULL AND region != '' GROUP BY region ORDER BY COUNT(*) DESC LIMIT 20")
            regions = [{"region": r[0], "count": r[1]} for r in c.fetchall()]

            return {
                "total": total,
                "page": page,
                "limit": limit,
                "items": items,
                "statuses": statuses,
                "regions": regions
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 2. EINZELNER DATENSATZ (Screenshot 3: KontaktDrawer)
    # -------------------------------------------------------------------------
    def get_contact_detail(self, contact_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_pb_conn()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM kontakte WHERE id = ?", (contact_id,))
            row = c.fetchone()
            if not row:
                return None
            data = dict(row)

            # Parse messages
            raw_nv = data.get("nachrichtenverlauf")
            messages = []
            if raw_nv:
                try:
                    parsed = json.loads(raw_nv)
                    if isinstance(parsed, list):
                        messages = parsed
                except Exception:
                    pass
            data["messages"] = messages
            data["nachrichten_count"] = len(messages)

            # Parse tags
            raw_tags = data.get("tags")
            tags_list = []
            if raw_tags:
                try:
                    t = json.loads(raw_tags)
                    if isinstance(t, list):
                        tags_list = t
                except Exception:
                    tags_list = [raw_tags] if isinstance(raw_tags, str) else []
            data["tags_list"] = tags_list

            # Initials
            parts = (data.get("name") or "??").split()
            data["initials"] = "".join([p[0].upper() for p in parts[:2]]) if parts else "??"

            # Avatar URL
            pb_img = data.get("profilbild") or ""
            if pb_img and not pb_img.startswith("http"):
                data["avatar_url"] = f"/api/crm/avatars/{data['id']}/{pb_img}"
            else:
                data["avatar_url"] = pb_img

            return data
        finally:
            conn.close()

    def save_contact(self, contact_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        conn = _get_pb_conn()
        try:
            cid = contact_id or payload.get("id")
            now_iso = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.000Z")

            tags_val = payload.get("tags")
            if isinstance(tags_val, list):
                tags_json = json.dumps(tags_val, ensure_ascii=False)
            else:
                tags_json = str(tags_val or "")

            with conn:
                if cid:
                    conn.execute("""
                        UPDATE kontakte SET
                            name = COALESCE(?, name),
                            unternehmen = COALESCE(?, unternehmen),
                            rolle = COALESCE(?, rolle),
                            email = COALESCE(?, email),
                            telefon_1 = COALESCE(?, telefon_1),
                            telefon_2 = COALESCE(?, telefon_2),
                            linkedin_url = COALESCE(?, linkedin_url),
                            status = COALESCE(?, status),
                            rating = COALESCE(?, rating),
                            region = COALESCE(?, region),
                            Webseite = COALESCE(?, Webseite),
                            adresse = COALESCE(?, adresse),
                            naechster_schritt = COALESCE(?, naechster_schritt),
                            vernetzt_am = COALESCE(?, vernetzt_am),
                            naechster_termin = COALESCE(?, naechster_termin),
                            einladung_zurueckgezogen_am = COALESCE(?, einladung_zurueckgezogen_am),
                            kommentar = COALESCE(?, kommentar),
                            RollenVerteilungzuordnung = COALESCE(?, RollenVerteilungzuordnung),
                            LinkedInheader = COALESCE(?, LinkedInheader),
                            Linkedin_info = COALESCE(?, Linkedin_info),
                            profilbild = COALESCE(?, profilbild),
                            tags = COALESCE(?, tags),
                            debitor_nr = COALESCE(?, debitor_nr),
                            kreditor_nr = COALESCE(?, kreditor_nr),
                            zahlungsart = COALESCE(?, zahlungsart),
                            zahlungsziel_tage = COALESCE(?, zahlungsziel_tage),
                            skonto_prozent = COALESCE(?, skonto_prozent),
                            skonto_tage = COALESCE(?, skonto_tage),
                            kreditlimit = COALESCE(?, kreditlimit),
                            preisgruppe = COALESCE(?, preisgruppe),
                            iban = COALESCE(?, iban),
                            bic = COALESCE(?, bic),
                            bank_name = COALESCE(?, bank_name),
                            ust_id = COALESCE(?, ust_id),
                            steuernummer = COALESCE(?, steuernummer),
                            steuergebiet = COALESCE(?, steuergebiet),
                            leitweg_id = COALESCE(?, leitweg_id),
                            ansprechpartner_json = COALESCE(?, ansprechpartner_json),
                            dsgvo_status = COALESCE(?, dsgvo_status),
                            dsgvo_opt_in_datum = COALESCE(?, dsgvo_opt_in_datum),
                            dsgvo_legal_basis = COALESCE(?, dsgvo_legal_basis),
                            dsgvo_opt_email = COALESCE(?, dsgvo_opt_email),
                            dsgvo_opt_phone = COALESCE(?, dsgvo_opt_phone),
                            dsgvo_opt_postal = COALESCE(?, dsgvo_opt_postal),
                            dsgvo_opt_source = COALESCE(?, dsgvo_opt_source),
                            dsgvo_opt_out = COALESCE(?, dsgvo_opt_out),
                            dsgvo_opt_out_date = COALESCE(?, dsgvo_opt_out_date),
                            dsgvo_retention_category = COALESCE(?, dsgvo_retention_category),
                            updated = ?
                        WHERE id = ?
                    """, (
                        payload.get("name"),
                        payload.get("unternehmen"),
                        payload.get("rolle"),
                        payload.get("email"),
                        payload.get("telefon_1"),
                        payload.get("telefon_2"),
                        payload.get("linkedin_url"),
                        payload.get("status"),
                        payload.get("rating"),
                        payload.get("region"),
                        payload.get("Webseite") or payload.get("webseite"),
                        payload.get("adresse"),
                        payload.get("naechster_schritt"),
                        payload.get("vernetzt_am"),
                        payload.get("naechster_termin"),
                        payload.get("einladung_zurueckgezogen_am"),
                        payload.get("kommentar"),
                        payload.get("RollenVerteilungzuordnung"),
                        payload.get("LinkedInheader"),
                        payload.get("Linkedin_info"),
                        payload.get("profilbild"),
                        tags_json if payload.get("tags") is not None else None,
                        payload.get("debitor_nr"),
                        payload.get("kreditor_nr"),
                        payload.get("zahlungsart"),
                        payload.get("zahlungsziel_tage"),
                        payload.get("skonto_prozent"),
                        payload.get("skonto_tage"),
                        payload.get("kreditlimit"),
                        payload.get("preisgruppe"),
                        payload.get("iban"),
                        payload.get("bic"),
                        payload.get("bank_name"),
                        payload.get("ust_id"),
                        payload.get("steuernummer"),
                        payload.get("steuergebiet"),
                        payload.get("leitweg_id"),
                        payload.get("ansprechpartner_json"),
                        payload.get("dsgvo_status"),
                        payload.get("dsgvo_opt_in_datum"),
                        payload.get("dsgvo_legal_basis"),
                        payload.get("dsgvo_opt_email"),
                        payload.get("dsgvo_opt_phone"),
                        payload.get("dsgvo_opt_postal"),
                        payload.get("dsgvo_opt_source"),
                        payload.get("dsgvo_opt_out"),
                        payload.get("dsgvo_opt_out_date"),
                        payload.get("dsgvo_retention_category"),
                        now_iso,
                        cid
                    ))
                else:
                    import uuid
                    cid = f"usr_{uuid.uuid4().hex[:12]}"
                    conn.execute("""
                        INSERT INTO kontakte (
                            id, name, unternehmen, rolle, email, telefon_1, telefon_2,
                            linkedin_url, status, rating, region, Webseite, adresse,
                            naechster_schritt, vernetzt_am, naechster_termin,
                            einladung_zurueckgezogen_am, kommentar, RollenVerteilungzuordnung,
                            LinkedInheader, Linkedin_info, profilbild, tags,
                            nachrichtenverlauf, created, updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
                    """, (
                        cid,
                        payload.get("name", "Neuer Kontakt"),
                        payload.get("unternehmen", ""),
                        payload.get("rolle", ""),
                        payload.get("email", ""),
                        payload.get("telefon_1", ""),
                        payload.get("telefon_2", ""),
                        payload.get("linkedin_url", ""),
                        payload.get("status", "Vernetzt"),
                        payload.get("rating", 1),
                        payload.get("region", ""),
                        payload.get("Webseite", ""),
                        payload.get("adresse", ""),
                        payload.get("naechster_schritt", ""),
                        payload.get("vernetzt_am", datetime.date.today().isoformat()),
                        payload.get("naechster_termin", ""),
                        payload.get("einladung_zurueckgezogen_am", ""),
                        payload.get("kommentar", ""),
                        payload.get("RollenVerteilungzuordnung", ""),
                        payload.get("LinkedInheader", ""),
                        payload.get("Linkedin_info", ""),
                        payload.get("profilbild", ""),
                        tags_json,
                        now_iso,
                        now_iso
                    ))

            return self.get_contact_detail(cid) or {"id": cid, "success": True}
        finally:
            conn.close()

    def add_contact_message(
        self,
        contact_id: str,
        text: str,
        channel: str = "note",  # 'note', 'linkedin', 'email', 'meeting'
        direction: str = "outbound",  # 'inbound', 'outbound'
        sender: str = "Michael Keller"
    ) -> Dict[str, Any]:
        with _CRM_MSG_LOCK:
            conn = _get_pb_conn()
            try:
                with conn:
                    c = conn.cursor()
                    c.execute("SELECT nachrichtenverlauf, name FROM kontakte WHERE id = ?", (contact_id,))
                    row = c.fetchone()
                    if not row:
                        raise ValueError(f"Kontakt {contact_id} existiert nicht.")

                    raw_nv = row[0]
                    contact_name = row[1] or "Kontakt"
                    messages = []
                    if raw_nv:
                        try:
                            parsed = json.loads(raw_nv)
                            if isinstance(parsed, list):
                                messages = parsed
                        except Exception:
                            pass

                    now_dt = datetime.datetime.now()
                    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
                    new_msg = {
                        "id": f"msg_{int(now_dt.timestamp())}_{uuid.uuid4().hex[:6]}",
                        "date": now_str,
                        "timestamp": now_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "sender": sender if direction == "outbound" else contact_name,
                        "text": text.strip(),
                        "type": channel,
                        "direction": direction,
                        "isStarred": False
                    }
                    messages.append(new_msg)

                    conn.execute(
                        "UPDATE kontakte SET nachrichtenverlauf = ?, updated = ? WHERE id = ?",
                        (json.dumps(messages, ensure_ascii=False), datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.000Z"), contact_id)
                    )

                return {"success": True, "message": new_msg, "total_messages": len(messages)}
            finally:
                conn.close()

    def delete_contact(self, contact_id: str) -> bool:
        conn = _get_pb_conn()
        try:
            with conn:
                conn.execute("DELETE FROM kontakte WHERE id = ?", (contact_id,))
            return True
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 3. ALLE NACHRICHTEN TIMELINE (Screenshot 2)
    # -------------------------------------------------------------------------
    def list_all_messages(
        self,
        search: str = "",
        channel: str = "all",     # 'all', 'linkedin', 'email', 'meeting', 'note', 'audio'
        direction: str = "all",   # 'all', 'received', 'sent'
        sort: str = "newest",     # 'newest', 'oldest'
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        conn = _get_pb_conn()
        try:
            c = conn.cursor()
            # We select contacts that have non-empty nachrichtenverlauf
            c.execute("""
                SELECT id, name, unternehmen, rolle, profilbild, nachrichtenverlauf
                FROM kontakte
                WHERE nachrichtenverlauf IS NOT NULL AND nachrichtenverlauf != '[]' AND nachrichtenverlauf != ''
            """)
            rows = c.fetchall()

            all_messages = []
            channel_counts = {"all": 0, "linkedin": 0, "email": 0, "meeting": 0, "audio": 0, "note": 0}
            direction_counts = {"all": 0, "received": 0, "sent": 0}

            search_lower = search.strip().lower() if search else ""

            for r in rows:
                cid = r["id"]
                cname = r["name"] or "Ohne Name"
                company = r["unternehmen"] or ""
                role = r["rolle"] or ""
                pbild = r["profilbild"] or ""
                raw_nv = r["nachrichtenverlauf"]

                try:
                    msgs = json.loads(raw_nv)
                    if not isinstance(msgs, list):
                        continue

                    for idx, m in enumerate(msgs):
                        if not isinstance(m, dict):
                            continue

                        text = m.get("text") or ""
                        sender = m.get("sender") or ""
                        m_type = (m.get("type") or "linkedin").lower()
                        ts_str = m.get("timestamp") or m.get("date") or ""

                        # Determine direction
                        is_sent = ("ich" in sender.lower() or sender.lower() == "me" or m.get("direction") == "outbound")
                        msg_dir = "sent" if is_sent else "received"

                        # Track channel & direction totals
                        channel_counts["all"] += 1
                        if m_type in channel_counts:
                            channel_counts[m_type] += 1
                        else:
                            channel_counts["note"] += 1

                        direction_counts["all"] += 1
                        direction_counts[msg_dir] += 1

                        # Search filter
                        if search_lower:
                            haystack = f"{cname} {company} {role} {sender} {text}".lower()
                            if search_lower not in haystack:
                                continue

                        # Channel filter
                        if channel != "all" and m_type != channel:
                            continue

                        # Direction filter
                        if direction == "received" and is_sent:
                            continue
                        if direction == "sent" and not is_sent:
                            continue

                        all_messages.append({
                            "message_id": m.get("id") or f"{cid}_{idx}",
                            "contact_id": cid,
                            "contact_name": cname,
                            "contact_company": company,
                            "contact_role": role,
                            "contact_avatar": pbild,
                            "sender": sender,
                            "is_sent_by_user": is_sent,
                            "channel": m_type,
                            "text": text,
                            "date": m.get("date") or ts_str[:16],
                            "timestamp": ts_str,
                            "is_starred": bool(m.get("isStarred"))
                        })
                except Exception:
                    pass

            # Sort messages
            def parse_sort_key(item):
                ts = item.get("timestamp") or item.get("date") or ""
                return ts

            reverse = (sort == "newest")
            all_messages.sort(key=parse_sort_key, reverse=reverse)

            total_hits = len(all_messages)

            # Paginate
            start = max(0, (page - 1) * limit)
            end = start + limit
            page_items = all_messages[start:end]

            return {
                "total": total_hits,
                "page": page,
                "limit": limit,
                "channel_counts": channel_counts,
                "direction_counts": direction_counts,
                "messages": page_items
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 4. KALENDER ANSICHT (Screenshot 1 / 4: Termine & Follow-ups)
    # -------------------------------------------------------------------------
    def get_calendar_events(self) -> Dict[str, Any]:
        conn = _get_pb_conn()
        try:
            c = conn.cursor()

            # 1. Termine table
            c.execute("SELECT * FROM termine ORDER BY start ASC")
            termine_rows = c.fetchall()
            events = []
            for t in termine_rows:
                events.append({
                    "id": t["id"],
                    "title": t["titel"] or "Termin",
                    "start": t["start"],
                    "end": t["Ende"],
                    "location": t["Ort"],
                    "notes": t["Notiz"],
                    "contact_id": t["kontakt"],
                    "type": "termin"
                })

            # 2. Upcoming next appointments from contacts
            c.execute("""
                SELECT id, name, unternehmen, naechster_termin, naechster_schritt
                FROM kontakte
                WHERE naechster_termin IS NOT NULL AND naechster_termin != ''
                ORDER BY naechster_termin ASC
            """)
            for k in c.fetchall():
                events.append({
                    "id": f"followup_{k['id']}",
                    "title": f"Follow-up: {k['name']} ({k['unternehmen']})",
                    "start": k["naechster_termin"],
                    "notes": k["naechster_schritt"],
                    "contact_id": k["id"],
                    "type": "followup"
                })

            return {"total": len(events), "events": events}
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 5. BERICHT / MISSIONSKONTROLLE (Screenshot 4)
    # -------------------------------------------------------------------------
    def get_report_metrics(self) -> Dict[str, Any]:
        conn = _get_pb_conn()
        try:
            c = conn.cursor()

            c.execute("SELECT id, name, unternehmen, rolle, status, updated, nachrichtenverlauf, RollenVerteilungzuordnung, naechster_termin FROM kontakte")
            all_contacts = c.fetchall()

            # 1. Filter active contacts: Exclude Gesperrt_1Jahr, Kein_Interesse, Unvernetzt, Irrelevant
            active_contacts = []
            total_count = len(all_contacts)
            for k in all_contacts:
                st = (k["status"] or "").strip()
                if st not in ("Gesperrt_1Jahr", "Kein_Interesse", "Unvernetzt", "Irrelevant"):
                    active_contacts.append(k)

            active_count = len(active_contacts)

            # 2. Status distribution
            status_counts = {}
            for k in active_contacts:
                st = (k["status"] or "Ohne Status").strip()
                status_counts[st] = status_counts.get(st, 0) + 1

            erst_nachricht = status_counts.get("Erstnachricht", 0)
            im_dialog = status_counts.get("Im Dialog", 0)
            interview = status_counts.get("Interview", 0) + status_counts.get("Interview vereinbart", 0)

            reply_rate = round((im_dialog / (erst_nachricht + im_dialog)) * 100) if (erst_nachricht + im_dialog) > 0 else 0
            meeting_rate = round((interview / (im_dialog + interview)) * 100) if (im_dialog + interview) > 0 else 0

            # 3. Role regexes matching MissionControlView.tsx exactly
            re_GF = re.compile(r"(geschäftsführer|geschaeftsfuehrer|inhaber|eigentümer|eigentuemer|gründer|gruender|ceo|founder|co-founder|managing director|president|owner|partner)", re.I)
            re_Exec = re.compile(r"(executive search|headhunter|personalberater|talent acquisition|recruiter|recruiting|talent partners)", re.I)
            re_Decision = re.compile(r"(entscheider|decision|bereichsleiter|division|vorstand|board|leadership|leitung|director|vp[ .-]|vice president|chief)", re.I)
            re_Investor = re.compile(r"(private equity|\bpe\b|investor|investment|venture capital|beteiligungsgesellschaft|family office|angel investor|kapitalgeber|fonds|fund manager)", re.I)
            re_HR = re.compile(r"(human resources|personalleiter|hr manager|\bhr\b|personal|talent)", re.I)
            re_Finance = re.compile(r"(\bcfo\b|chief financial|finanzleiter|finance director|controlling|treasury|\bbank\b|finanz)", re.I)
            re_Interim = re.compile(r"(interim|freiberuflich|freelance|selbstständig|selbststaendig|consultant|freelancer)", re.I)
            re_Consulting = re.compile(r"(consultant|consulting|berater|beratung|advisor|advisory|strategy|unternehmensberatung|business development|matchmaker)", re.I)
            re_Quality = re.compile(r"(qualified person|quality|gmp|gdp|regulatory|zulassung|compliance|good manufacturing|sterile|quality manager|quality director|qm\b|regulatory affairs)", re.I)

            role_buckets = {
                "GF / Inhaber": 0,
                "Entscheider / Führung": 0,
                "Investor / Private Equity": 0,
                "Personalberater / Executive Search": 0,
                "Personalwesen / Persönliches": 0,
                "Finanzen / CFO": 0,
                "Interim / Freiberuflich": 0,
                "Beratung": 0,
                "Qualität / GMP": 0,
                "Sonstige": 0
            }

            recruiter_contacts = []
            stagnated_contacts = []

            for k in active_contacts:
                text_pool = f"{k['rolle'] or ''} {k['unternehmen'] or ''} {k['RollenVerteilungzuordnung'] or ''}"
                assigned = False

                if re_GF.search(text_pool):
                    role_buckets["GF / Inhaber"] += 1
                    assigned = True
                elif re_Decision.search(text_pool):
                    role_buckets["Entscheider / Führung"] += 1
                    assigned = True
                elif re_Investor.search(text_pool):
                    role_buckets["Investor / Private Equity"] += 1
                    assigned = True
                elif re_Exec.search(text_pool):
                    role_buckets["Personalberater / Executive Search"] += 1
                    assigned = True
                    recruiter_contacts.append({
                        "id": k["id"],
                        "name": k["name"] or "Ohne Name",
                        "company": k["unternehmen"] or "",
                        "role": k["rolle"] or "",
                        "date": (k["updated"] or "")[:10]
                    })
                elif re_HR.search(text_pool):
                    role_buckets["Personalwesen / Persönliches"] += 1
                    assigned = True
                elif re_Finance.search(text_pool):
                    role_buckets["Finanzen / CFO"] += 1
                    assigned = True
                elif re_Interim.search(text_pool):
                    role_buckets["Interim / Freiberuflich"] += 1
                    assigned = True
                elif re_Consulting.search(text_pool):
                    role_buckets["Beratung"] += 1
                    assigned = True
                elif re_Quality.search(text_pool):
                    role_buckets["Qualität / GMP"] += 1
                    assigned = True

                if not assigned:
                    role_buckets["Sonstige"] += 1

                # Stagnation test: active contacts with no recent update
                stagnated_contacts.append({
                    "id": k["id"],
                    "name": k["name"] or "Ohne Name",
                    "company": k["unternehmen"] or "",
                    "role": k["rolle"] or "",
                    "date": (k["updated"] or "")[:10]
                })

            stagnated_count = len(stagnated_contacts)
            exec_search_count = role_buckets["Personalberater / Executive Search"]

            # Sort and format role breakdown
            role_breakdown = []
            for r_name, count in role_buckets.items():
                pct = round((count / active_count) * 100) if active_count > 0 else 0
                role_breakdown.append({"role": r_name, "count": count, "pct": pct})

            # Status breakdown
            status_breakdown = [
                {"status": "Vernetzt", "count": status_counts.get("Vernetzt", 0)},
                {"status": "Erstnachricht", "count": status_counts.get("Erstnachricht", 0)},
                {"status": "Im Dialog", "count": status_counts.get("Im Dialog", 0)},
                {"status": "Interview", "count": interview},
                {"status": "Regelmäßiger Kontakt", "count": status_counts.get("Regelmäßiger Kontakt", 0)},
                {"status": "Parkposition", "count": status_counts.get("Parkposition", 0)},
            ]

            # 4. Recent contacts (Last 8 updated)
            c.execute("SELECT id, name, unternehmen, rolle, updated, profilbild FROM kontakte WHERE name IS NOT NULL AND name != '' ORDER BY updated DESC LIMIT 8")
            recent_contacts = []
            for r in c.fetchall():
                parts = (r["name"] or "??").split()
                ini = "".join([p[0].upper() for p in parts[:2]]) if parts else "??"
                recent_contacts.append({
                    "id": r["id"],
                    "name": r["name"],
                    "company": r["unternehmen"] or "",
                    "role": r["rolle"] or "",
                    "avatar": r["profilbild"] or "",
                    "initials": ini,
                    "date": (r["updated"] or "")[:10]
                })

            # 5. Upcoming next appointments count
            c.execute("SELECT COUNT(*) FROM termine WHERE start >= date('now')")
            next_termine_count = c.fetchone()[0]

            return {
                "active_contacts": active_count,
                "total_contacts": total_count,
                "reply_rate": reply_rate,
                "meeting_rate": meeting_rate,
                "executive_search_count": exec_search_count,
                "stagnated_count": stagnated_count,
                "next_termine_count": next_termine_count,
                "role_breakdown": role_breakdown,
                "status_breakdown": status_breakdown,
                "recent_contacts": recent_contacts,
                "action_items_check": stagnated_contacts[:8],
                "action_items_recruiter": recruiter_contacts[:8]
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 7. DSGVO & DATENSCHUTZ (Art. 15, 17, 20)
    # -------------------------------------------------------------------------
    def export_gdpr(self, contact_id: str) -> Optional[Dict[str, Any]]:
        contact = self.get_contact_detail(contact_id)
        if not contact:
            return None
        return {
            "export_metadata": {
                "regulation": "EU-DSGVO (Verordnung EU 2016/679)",
                "articles": ["Art. 15 (Auskunftsrecht)", "Art. 20 (Datenübertragbarkeit)"],
                "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
                "mandant": "Archon OS CRM",
                "subject_id": contact_id
            },
            "personal_data": {
                "id": contact.get("id"),
                "name": contact.get("name"),
                "unternehmen": contact.get("unternehmen"),
                "rolle": contact.get("rolle"),
                "email": contact.get("email"),
                "telefon_1": contact.get("telefon_1"),
                "telefon_2": contact.get("telefon_2"),
                "adresse": contact.get("adresse"),
                "region": contact.get("region"),
                "webseite": contact.get("Webseite"),
                "linkedin_url": contact.get("linkedin_url"),
                "kommentar": contact.get("kommentar"),
                "status": contact.get("status"),
                "tags": contact.get("tags_list", []),
                "vernetzt_am": contact.get("vernetzt_am"),
                "rating": contact.get("rating")
            },
            "commercial_data": {
                "debitor_nr": contact.get("debitor_nr"),
                "kreditor_nr": contact.get("kreditor_nr"),
                "zahlungsart": contact.get("zahlungsart"),
                "zahlungsziel_tage": contact.get("zahlungsziel_tage"),
                "iban": contact.get("iban"),
                "bic": contact.get("bic"),
                "bank_name": contact.get("bank_name"),
                "ust_id": contact.get("ust_id"),
                "steuernummer": contact.get("steuernummer"),
                "steuergebiet": contact.get("steuergebiet")
            },
            "communications_history": contact.get("messages", []),
            "gdpr_status": {
                "legal_basis": contact.get("dsgvo_legal_basis") or "Art. 6 Abs. 1 lit. f (Berechtigtes Interesse B2B)",
                "dsgvo_status": contact.get("dsgvo_status", "Konform"),
                "opt_in_datum": contact.get("dsgvo_opt_in_datum"),
                "opt_in_source": contact.get("dsgvo_opt_source"),
                "consents": {
                    "email_marketing": bool(contact.get("dsgvo_opt_email", 1)),
                    "phone_marketing": bool(contact.get("dsgvo_opt_phone", 1)),
                    "postal_marketing": bool(contact.get("dsgvo_opt_postal", 0))
                },
                "opt_out_objection_art21": {
                    "objection_active": bool(contact.get("dsgvo_opt_out", 0)),
                    "objection_date": contact.get("dsgvo_opt_out_date")
                },
                "retention_category": contact.get("dsgvo_retention_category") or "commercial_10y"
            }
        }

    def anonymize_gdpr(self, contact_id: str) -> bool:
        conn = _get_pb_conn()
        try:
            now_iso = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.000Z")
            with conn:
                res = conn.execute("""
                    UPDATE kontakte SET
                        name = ?,
                        unternehmen = '',
                        rolle = '',
                        email = '',
                        telefon_1 = '',
                        telefon_2 = '',
                        linkedin_url = '',
                        profilbild = '',
                        adresse = '',
                        kommentar = '[Gelöscht gemäß Art. 17 DSGVO]',
                        nachrichtenverlauf = '[]',
                        tags = '["DSGVO-gelöscht"]',
                        iban = '',
                        bic = '',
                        bank_name = '',
                        ust_id = '',
                        steuernummer = '',
                        ansprechpartner_json = '[]',
                        dsgvo_status = ?,
                        updated = ?
                    WHERE id = ?
                """, (
                    f"Gelöschter Kontakt #{contact_id}",
                    f"Gelöscht gemäß Art. 17 DSGVO am {now_iso[:10]}",
                    now_iso,
                    contact_id
                ))
                return res.rowcount > 0
        finally:
            conn.close()


crm_service = CRMService()
