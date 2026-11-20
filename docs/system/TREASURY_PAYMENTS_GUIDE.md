# Treasury, Wallets & Passkey-gesichertes Zahlungs-Cockpit (M103)

Das **Treasury-Cockpit** unter **Rechnungswesen & Finanzen → Treasury** bündelt alle Finanzschienen, Liquiditätsstände, Ausgabenkategorien und Zahlungsfreigaben an einem Ort.

## 1. Sicherheitsmodell (Schutz vor autonomen Agenten-Fehlern)

- **Hauptkonten & Main-Wallets (`watch_only` / `passkey_hitl`):** Agenten erhalten niemals direkten Schreib- oder Signaturzugriff auf Bankkonten, PayPal, Stripe oder Haupt-Krypto-Wallets.
- **Passkey-Zwang (Handy / FIDO2):** Sobald unter **Settings → Benutzer** die Passkey-Pflicht für Zahlungen (`payments`) aktiv ist, wird jede Zahlungsanfrage (auch von Agenten oder Workflows) serverseitig gestoppt (`pending_approval`) und erst nach erfolgreicher WebAuthn-Signatur (`requirePasskeyForHitl("payments")`) gebucht.
- **Gedeckelte Agent-Allowance (`crypto_agent_allowance` / x402):** Optionales Sub-Budget für kleine API-/Micro-Payments mit hartem Einzel- und Tageslimit sowie Empfänger-Allowlist (nur aktiv, wenn Passkey-Zwang für `payments` nicht global erzwungen wird).
- **Idempotenz & SHA-256 Audit-Chain:** Jede Transaktion trägt einen eindeutigen `idempotency_key` gegen Doppelbuchungen sowie eine verkettete SHA-256-Signatur (`entry_hash`) in `data/treasury.db`.

## 2. Funktionen im UI

- **Liquiditäts-Karten:** Gesamtliquidität nach Währung (`EUR`, `USD`, `USDC`), Fiat vs. Krypto und Anzahl offener Freigaben.
- **Offene Zahlungsfreigaben:** Direkte Freigabe mit Passkey (`Mit Passkey freigeben`) oder Ablehnung mit Begründung. Freigaben feuern automatisch ein `approval.payment_approved`-Event auf dem Event-Bus.
- **Konten & Wallets verwalten:** Anlegen und Entfernen von Bankkonten, PayPal, Stripe, Watch-Only-Wallets und Agent-Allowances.
- **Ausgaben-Ledger:** Aufschlüsselung nach Kategorien (*LLM / API*, *Ads & Marketing*, *Lieferanten / E-Commerce*, *Software & Abos*, *Steuern & Gebühren*, *Honorar / Service*) inklusive Filter.

## 3. API-Endpunkte

- `GET /api/v2/treasury/overview`
- `POST /api/v2/treasury/accounts` / `DELETE /api/v2/treasury/accounts/{acc_id}`
- `POST /api/v2/treasury/payments/request`
- `POST /api/v2/treasury/payments/{tx_id}/approve`
- `POST /api/v2/treasury/payments/{tx_id}/reject`
