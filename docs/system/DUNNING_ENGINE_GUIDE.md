# Mahnwesen & Forderungsmanagement (Dunning Engine) in Archon OS

Dieses Handbuch beschreibt die Funktionsweise und Bedienung des dreistufigen Mahnwesens (`backend/dunning_engine.py`) in Archon OS.

---

## 1. 3-Stufen-Modell (BGB § 286 konform)

Die Dunning Engine überwacht Ausgangsrechnungen auf Fälligkeit und automatisiert die Erstellung von Mahnentwürfen:

| Stufe | Verzugstage | Mahngebühr | Frist | Charakter & Rechtsfolge |
| :--- | :--- | :--- | :--- | :--- |
| **Stufe 1 (Erinnerung)** | ab 5–10 Tagen | 0,00 EUR | 7 Tage | Freundlicher Hinweis auf Zahlungseingangs-Fehlen. Höflicher Tonfall, Annahme eines Versehens. |
| **Stufe 2 (1. Mahnung)** | ab 15–20 Tagen | 5,00 EUR Pauschale | 5 Tage | Förmliche Aufforderung unter Verzugshinweis. Fristsetzung mit konkretem Datum. |
| **Stufe 3 (Letzte Mahnung)** | ab 30 Tagen | 10,00 EUR + 3% Verzugsschaden | 3 Tage | Letzte außergerichtliche Frist mit ausdrücklicher Androhung des gerichtlichen Mahnverfahrens / Inkasso. |

---

## 2. Human-in-the-Loop (HITL) Freigabeschranke

Keine Mahnung verlässt das System ohne explizite Freigabe:
1. **Entwurf:** Das System generiert automatisch einen formellen Mahnentwurf und legt ihn in `dunning_history` (`status='draft'`) ab.
2. **Aufgabe in Kanban:** Im Operations-Kanban (`finance_lead`) wird ein Prüftask angelegt:
   `[Mahnung Stufe X] Kunde: Betrag EUR - Freigabe erforderlich`.
3. **Prüfung & Versand:** Im Web-UI unter **Infrastruktur & Governance → Rechnungswesen → Mahnwesen** kann der Entwurfstext angepasst und mit einem Klick verbindlich freigegeben werden.

---

## 3. REST-API-Schnittstellen

Unter `/api/operations/dunning` stehen folgende Endpunkte zur Verfügung:

- `GET /api/operations/dunning/invoices`: Liefert alle Ausgangsrechnungen mit automatischer Verzugsberechnung (`overdue_days`, `recommended_level`).
- `POST /api/operations/dunning/invoices`: Erstellt eine neue Ausgangsrechnung.
- `POST /api/operations/dunning/draft`: Generiert den formellen Mahnungstext je nach gewählter Stufe (1–3).
- `POST /api/operations/dunning/approve`: Verbindliche Freigabe und Status-Update der Rechnung (`dunning_1`, `dunning_2`, `dunning_3`).
- `POST /api/operations/dunning/mark-paid`: Setzt den Rechnungsstatus auf `paid` und schließt das Verfahren ab.
