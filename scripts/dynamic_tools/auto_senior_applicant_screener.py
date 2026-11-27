# -*- coding: utf-8 -*-
"""Demo-Aufzeichnung fuer Skill: auto_senior_applicant_screener — NICHT ausfuehrbar.
Synthetisiert aus Demonstration: Bewerbungen Prüfen und Senior Coder Selektieren
Erstellt am: 2026-11-05T14:06:05.936541
demo_only: True | simulated: True | executable: False

Es ist keine CUA-Runtime angebunden. Dieses Artefakt dokumentiert nur
die aufgezeichneten Schritte; es fuehrt keine Klicks, Tastatureingaben
oder Navigationen aus. execute_*() wirft daher RuntimeError.
"""

from backend.computer_use_pbd import CUA_RUNTIME_UNAVAILABLE_MESSAGE

DEMO_ONLY = True
SIMULATED = True
EXECUTABLE = False

RECORDED_STEPS = [{'step': 1, 'type': 'navigate', 'details': {'url': 'https://karriere.portal.internal'}, 'commentary': 'Navigiere zum Karriereportal'}, {'step': 2, 'type': 'click', 'details': {'selector': '#btn-filter-senior', 'x': 65, 'y': 42}, 'commentary': 'Klicke auf Filter für Senior-Profile'}, {'step': 3, 'type': 'type', 'details': {'field': 'Suche', 'text': 'Python Fullstack'}, 'commentary': 'Tippe Suchbegriff mit natürlicher Kadenz'}, {'step': 4, 'type': 'click', 'details': {'selector': '#btn-submit-review', 'x': 80, 'y': 70}, 'commentary': 'Bewerbungen freigeben'}]

def execute_auto_senior_applicant_screener(target_url: str = 'https://karriere.portal.internal'):
    """Fail-closed: ohne echte CUA-Runtime nie Erfolg melden."""
    raise RuntimeError(CUA_RUNTIME_UNAVAILABLE_MESSAGE)

if __name__ == '__main__':
    execute_auto_senior_applicant_screener()
