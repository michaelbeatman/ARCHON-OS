# Passkey / WebAuthn HITL-Verifizierung (Meilenstein 101)

> Status: Implementiert (Basis) · Backend: `backend/passkey_hitl.py`, `archon/routers/auth.py` · UI: `Einstellungen → Benutzer`

## Zweck

Die Passkey-Verifizierung stellt kryptographisch sicher, dass sensible **Human-in-the-Loop (HITL)**-Freigaben (z. B. Zahlungen, Budget-Überschreitungen, Projektstarts oder destruktive Systemaktionen) ausschließlich durch den berechtigten Menschen mit seinem Gerät (Google Passkey, Windows Hello, Apple Touch ID/Face ID oder Hardware-Key) bestätigt werden können. Ein KI-Modell hat keinen Zugriff auf den privaten Schlüssel und kann keine Signatur vortäuschen.

## Einrichtung pro Benutzer (`Einstellungen → Benutzer`)

1. **System Control Center → Benutzer** öffnen und den gewünschten Benutzer im Abschnitt **Passkey / WebAuthn HITL-Verifizierung (M101)** auswählen.
2. Auf **+ Passkey registrieren** klicken und den Browser-Dialog (z. B. Google Passkey oder Windows Hello) bestätigen.
3. Über **Testen** lässt sich die Challenge-Response-Signaturprüfung direkt verifizieren.

## Zweistufige Konfiguration

- **Stufe 1 — Master-Schalter (`Aktivieren`):** Schaltet die Passkey-Pflicht für diesen Benutzer grundsätzlich ein oder aus (Standard: aus, rein optional).
- **Stufe 2 — Geltungsbereich:**
  - **Für alle HITL-Freigaben erzwingen:** Jede HITL-Freigabe erfordert eine gültige WebAuthn-Signatur.
  - **Nur für ausgewählte Kategorien:** Granulare Auswahl zwischen `Zahlungen & Finanzen` (`payments`), `Projektstart` (`project_start`), `Budget-Überschreitung` (`budget_overrun`) und `System-Aktionen` (`destructive_actions`).

## Technische Hinweise

- **Voraussetzung:** WebAuthn funktioniert direkt auf `http://localhost` bzw. `127.0.0.1` sowie auf entfernten Servern über **HTTPS**.
- **Speicherort:** Benutzer-Konfigurationen und öffentliche SPKI-Schlüssel liegen in `config/passkey_hitl.json` (private Schlüssel verlassen niemals das Endgerät).
- **API-Endpunkte:**
  - `GET / POST /api/auth/passkey/config`
  - `POST /api/auth/passkey/register/options` & `/verify`
  - `DELETE /api/auth/passkey/credentials/{cred_id}`
  - `POST /api/auth/passkey/hitl/options` & `/verify`
