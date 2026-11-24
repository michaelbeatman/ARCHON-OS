#!/usr/bin/env python3
"""Audit D15: explizite Negativ-Abgrenzungen für alle Rollenprofile.

Kanonische Quelle ist ``agent_profiles.json``. Der Zusatz ist idempotent
(Marker ``ARCHON_NEGATIVE_GUARDRAILS_v1``) und wird an prompt/system_prompt
sowie deren englische Varianten angehängt — niemals mitten in bestehende
Instruktionen. Domänenspezifische Regeln ergänzen die universellen Regeln.

Usage:
    python scripts/add_role_guardrails.py            # schreibt
    python scripts/add_role_guardrails.py --check    # nur prüfen (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "agent_profiles.json"
MARKER = "<!-- ARCHON_NEGATIVE_GUARDRAILS_v1 -->"

UNIVERSAL_DE = [
    "Du darfst keine Fakten, Quellen, Zahlen oder Belege erfinden. Wenn Daten fehlen, melde das explizit als 'unbekannt'.",
    "Du darfst HITL-Gates, Zero-Egress-Regeln, Budgets und Freigabeketten nicht umgehen oder als erledigt behaupten.",
    "Du darfst keine Secrets, Tokens, API-Keys oder personenbezogenen Daten ungefragt ausgeben.",
    "Du darfst deine eigene Rolle, Systemprompts anderer Agenten oder Sicherheitsregeln nicht eigenmächtig ändern.",
]
UNIVERSAL_EN = [
    "You must never invent facts, sources, figures or evidence. If data is missing, state it explicitly as unknown.",
    "You must never bypass HITL gates, zero-egress rules, budgets or approval chains, nor claim they are complete.",
    "You must never disclose secrets, tokens, API keys or personal data unprompted.",
    "You must never change your own role, another agent's system prompt or safety rules without authorization.",
]

DOMAIN_DE = {
    "medizin": [
        "Du darfst keine Diagnose stellen, keine Therapie oder Medikation verschreiben und keine ärztliche Untersuchung ersetzen.",
        "Bei akuten Beschwerden weist du ausdrücklich auf ärztliche Hilfe bzw. den Notruf hin.",
    ],
    "recht": [
        "Du darfst keine verbindliche Rechtsberatung erteilen und keine Mandats- oder Vertretungserklärung abgeben.",
        "Du weist auf die Notwendigkeit anwaltlicher Prüfung hin, sobald bindende Aussagen im Raum stehen.",
    ],
    "steuer": [
        "Du darfst keine verbindliche Steuerberatung erteilen und keine Steuererklärung ohne Prüfung durch einen Steuerberater freigeben.",
    ],
    "finanz": [
        "Du darfst keine Anlage- oder Kreditentscheidung treffen und keine Zahlung oder Überweisung ohne HITL-Freigabe auslösen.",
    ],
    "treasury": [
        "Du darfst keine Zahlung, Überweisung oder Freigabe ohne HITL-Genehmigung ausführen oder als ausgeführt behaupten.",
    ],
}
DOMAIN_EN = {
    "medical": [
        "You must not make a diagnosis, prescribe treatment or medication, or replace a physician's examination.",
        "For acute symptoms you explicitly direct the user to medical help or emergency services.",
    ],
    "legal": [
        "You must not give binding legal advice or issue any mandate or representation declaration.",
        "You point to the need for legal review whenever binding statements are involved.",
    ],
    "tax": [
        "You must not give binding tax advice or approve a tax return without review by a licensed tax advisor.",
    ],
    "finance": [
        "You must not make investment or credit decisions and must not trigger any payment without HITL approval.",
    ],
    "treasury": [
        "You must not execute any payment, transfer or release without HITL approval, nor claim it was executed.",
    ],
}


def _rules_for(profile: dict, english: bool) -> list[str]:
    """Domänenerkennung über Kategorie, ID, Name und Beschreibung (DE/EN)."""
    fields = ("category", "category_en", "id", "name", "name_en", "description", "description_en")
    low = " ".join(str(profile.get(f, "")) for f in fields).lower()
    table = DOMAIN_EN if english else DOMAIN_DE
    hits: list[str] = []
    for key, rules in table.items():
        if key in low:
            hits.extend(rules)
    return hits


def _block(profile: dict, english: bool) -> str:
    rules = (UNIVERSAL_EN if english else UNIVERSAL_DE) + _rules_for(profile, english)
    title = "## Nicht erlaubt / Negativ-Abgrenzung" if not english else "## Not allowed / Negative scope"
    lines = [MARKER, title, ""]
    lines.extend(f"- {r}" for r in rules)
    return "\n".join(lines) + "\n"


def _apply(text: str, block: str) -> str:
    if not isinstance(text, str):
        return text
    if MARKER in text:
        return text
    return text.rstrip() + "\n\n" + block


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    data = json.loads(PROFILES.read_text(encoding="utf-8"))
    updated = 0
    for profile in data:
        before = json.dumps(profile, ensure_ascii=False, sort_keys=True)
        for field, english in (
            ("prompt", False), ("system_prompt", False),
            ("prompt_en", True), ("system_prompt_en", True),
        ):
            if field in profile:
                profile[field] = _apply(profile[field], _block(profile, english))
        if json.dumps(profile, ensure_ascii=False, sort_keys=True) != before:
            updated += 1

    if args.check:
        missing = [p.get("id") for p in data if MARKER not in str(p.get("prompt", ""))]
        print(f"CHECK: {len(data)} Profile, fehlende Guardrails: {len(missing)}")
        if missing:
            print("  " + ", ".join(str(m) for m in missing[:15]))
            return 1
        return 0

    PROFILES.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OK: {len(data)} Profile geprüft, {updated} aktualisiert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
