"""Fachlogik-Schicht (Services) zwischen Routern und Kern.

Ein Service kennt keine HTTP-Schicht: kein ``Request``, kein ``Body``, keinen
RBAC-Zaun. Router sind die Fassade und uebersetzen Domaenenfehler in
HTTP-Antworten. ``main.py`` darf Services direkt aufrufen.
"""
