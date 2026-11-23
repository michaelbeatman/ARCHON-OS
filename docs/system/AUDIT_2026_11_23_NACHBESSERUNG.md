# Audit & Nachbesserung — 23.11.2026 (zweite Welle nach UI-Korrektur)

Frischer 6-Domänen-Audit auf dem Stand NACH Entfernung der separaten Content-UI.
Alle Funde mit Datei:Zeile in den Audit-Berichten, hier die umgesetzten Fixes.

## Kritisch / Hoch — behoben

| Fund | Fix |
|---|---|
| SidebarNav required Props, aber ohne Props gemountet → Buildfehler | `SidebarNav` auf routenbasierte Navigation ohne Props umgestellt (`useRouter`/`usePathname`, echte Agentenliste via API) |
| Theme-Proxy verlor Auth bei POST/DELETE | Header (Authorization/Cookie) gespiegelt, GET/DELETE mit echtem Request |
| SSRF in `/api/calendar/ics` (?)url=) | Host-Allowlist `ARCHON_ICS_ALLOWED_HOSTS`, Block privater IPs, `redirect:'error'`, keine Fehlerdetails |
| Mistral-`test-connection`: Key-Exfiltration über Client-URL | Nur noch `api.mistral.ai` erlaubt |
| Media-Proxy Schein-Auth (beliebiger Header/Cookie) | Echte Session-Verifikation über Backend `/api/auth/me` + PB-Refresh |
| Audit-Logs/Verify ohne RBAC | `require_admin` + Mandantenfilter |
| Audit-HMAC defaultmäßig inaktiv | Startup-Check `_assert_audit_hmac` (Produktion/HMAC-Blöcke → Abbruch) |
| Egress-Downgrade bei unbekanntem Provider | Default-Deny: ohne erkanntes Lokalmodell blockiert |
| Rate-Limit-Bypass durch Token-Rotation | Principal nur aus verifizierter Session, sonst anon-Bucket |
| Passkey-Proof nicht an Aktion gebunden | Alle `consume_hitl_proof_token`-Aufrufer übergeben action/resource (Binding existierte, war aber ungenutzt) |
| Boardroom-Fan-Out verwaiste Tasks bei Cancel | task_registry.spawn + try/finally mit cancel+gather |
| Boardroom-Killswitch existierte nicht | `POST /api/boardroom/cancel` → `cancel_scope("boardroom")` |
| Abgebrochene Debatte als `success` archiviert | `status="cancelled"` bei cancelled-Event |
| Synthesis-Recovery ohne Retry-Cap | Max. 3 Versuche, dann `blocked` + HITL |
| Kanban-CAS-Lease ohne Heartbeat-Abbruch | Lease + 30-s-Heartbeat + finally-Release |
| HITL-Gate client-steuerbar (`gate_approvals: true`) | Boolean-Vollfreigabe entfernt |
| PATCH machte Fact-Check/Plagiat-Reports stale | Alle textabhängigen Reports bei Patch neu berechnet |
| Leerer Plagiats-Korpus galt als bestanden | `corpus=[]` → `checked=False, passed=False` |
| `approved` ohne `scheduled_at` → Publish-Sackgasse | scheduled_at beim Freigeben setzen |
| Feedback-Loop Memory-Suche mit falscher agent_id | Suchfilter entfernt |
| Voice-Block im System-Prompt wurde von Registry überschrieben | Registry als Basis, Addons angehängt |
| Prompt-Patches Write-Only | Echter Prompt + `save_version` bei auto_apply |
| Eigene Tokenformate nicht maskiert | Regex für `archon_live_*`, `tok_*` + Datei-Secrets |
| Tool-Output-Firewall fail-open | Fail-closed Platzhalter + rekursive Härtung aller String-Blätter |
| Warrant-Pfad-Aliase unvollständig | Alle pfadartigen Argument-Keys geprüft |
| Service-Token CWD-Fallback | Nur absolute, repo-relative Pfade |
| Auth-Default aus bei `--host 0.0.0.0` ohne ARCHON_BIND_IP | HOST/UVICORN_HOST in `_must_force_auth` geprüft |
| Audit-Schreibfehler bei erlaubten Tools | `_emit(allowed=True)` schreibt Nachweis, bei Fehler deny |
| Klartext-Session-Tokens in DB akzeptiert | Nur noch Hash-Abfrage |
| ICS-SSRF, Mistral-SSRF, Media-Auth, Port-8092-Browser, Status-Map, Watchdog-Fehler | siehe obige Tabelle / Frontend-Dateien |

## Weitere behobene Funde (zweite Audit-Welle)

**Persistenz:** Nummernkreis-Migration renamt `.json` erst nach Commit + Zaehler-Verifikation;
Settings-Loader nutzt strict `.bak`-Recovery; Vault-Keys pro Mandant im Backup;
WAL-Sidecars vor Restore entfernt; einheitlicher DB-Resolver (tenant_context als Autoritaet);
Idempotency- explizite Keys tenant-gescoped; DSGVO-Anonymisierung umfasst VARCHAR/JSON/CLOB;
Learning-Dedup + Eviction gescoped (learnings GoBD-geschuetzt); Vault-DDL nur einmal pro DB;
Restore-Test ohne `immutable=1` und mit hartem Fehler bei fehlender Pflichttabelle;
Obsidian-Frontmatter gequotet + Dateiname gejailt.

**Sicherheit:** Audit-Logs/Verify RBAC + Mandantenfilter; Audit-HMAC-Startup-Check;
Egress Default-Deny; Rate-Limit-Principal aus verifizierter Session; Boardroom-Killswitch;
Passkey-Proof action/resource; eigene Tokenformate maskiert; Tool-Guard fail-closed +
rekursive Härtung; Warrant-Pfad-Aliase; Service-Token ohne CWD-Fallback; Auth-Default bei
0.0.0.0-Bind; Audit-Pflicht auch bei erlaubten Tools; nur Hash-Session-Tokens;
ICS-/Mistral-SSRF; Media-Proxy echte Auth; Watchdog-Thread joinbar + atomare Alarmdatei;
Shutdown-Reihenfolge (Drain vor Cancel).

## Verifikation
- `compileall` über alle Produktivdateien: grün
- Body-Inventur: 0 rohe Body-Dicts
- `node --check` auf geänderten JS-Dateien: grün

## Verbleibend (bewusst, kein Code-Fehler)
- Kein echter Gesamt-Testlauf lokal (pytest/Frontend-Deps fehlen) → CI muss grün werden
- Supply-Chain-Härtung (Hash-Lockfiles, Image-Digests, SAST/SBOM) ist Infrastruktur-Aufwand, nicht Code-Logik
