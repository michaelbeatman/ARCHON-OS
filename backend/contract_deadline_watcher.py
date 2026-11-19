# -*- coding: utf-8 -*-
"""
backend/contract_deadline_watcher.py
====================================
Meilenstein 38: Automatischer Vertrags-, Fristen- & Abo-Waechter.

Erkennt auslaufende Vertraege, Leasing- und SaaS-Abos (30/14-Tage-Vorwarnung)
und generiert direkt einen fertigen Kuendigungsentwurf.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple


def draft_cancellation_notice(contract: Dict[str, Any]) -> str:
    vendor = contract.get("vendor") or "Vertragspartner"
    cnum = contract.get("contract_number") or contract.get("id") or "N/A"
    end_date = contract.get("end_date") or "zum naechstmoeglichen Zeitpunkt"
    return (
        f"Betreff: Fristgerechte Kuendigung Vertrag {cnum}\n\n"
        f"Sehr geehrte Damen und Herren ({vendor}),\n\n"
        f"hiermit kuendigen wir den oben genannten Vertrag (Nr. {cnum}) "
        f"fristgerecht zum {end_date}.\n"
        f"Bitte bestaetigen Sie uns den Erhalt dieser Kuendigung sowie das Vertragsende schriftlich.\n\n"
        f"Mit freundlichen Gruessen"
    )


def scan_upcoming_deadlines(
    contracts: List[Dict[str, Any]],
    today: Optional[datetime.date] = None,
    warn_days: Tuple[int, ...] = (30, 14),
) -> List[Dict[str, Any]]:
    ref = today or datetime.date.today()
    max_warn = max(warn_days) if warn_days else 30
    alerts: List[Dict[str, Any]] = []

    for c in contracts:
        cancel_by_str = str(c.get("cancel_by_date") or c.get("end_date") or "").strip()
        if not cancel_by_str:
            continue
        try:
            cancel_dt = datetime.date.fromisoformat(cancel_by_str[:10])
        except Exception:
            continue
        days_left = (cancel_dt - ref).days
        if 0 <= days_left <= max_warn:
            urgency = "critical" if days_left <= min(warn_days) else "warning"
            alerts.append({
                "contract_id": c.get("id"),
                "vendor": c.get("vendor"),
                "days_left": days_left,
                "cancel_by_date": cancel_dt.isoformat(),
                "urgency": urgency,
                "cancellation_draft": draft_cancellation_notice(c),
            })

    alerts.sort(key=lambda x: x["days_left"])
    return alerts
