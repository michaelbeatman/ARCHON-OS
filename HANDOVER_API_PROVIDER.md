---
title: "API Provider — Handover & Commit (Archon OS)"
date: 2026-08-25
tags: [archon, api-provider, hermes, handover, commit]
---

# API Provider Sektion — Handover & Commits

## Zusammenfassung

Neue **"API Provider"-Sektion** (Backend + Frontend) im echten Archon-OS-Projekt
`/projects/AgenticOS-2026`. Die Sektion ist **Hermes-nativ** gebaut: Provider &
Modelle kommen NICHT aus einer eigenen Registry, sondern direkt aus Hermes'
eigenen Quellen (Source of Truth). Konfig-Änderungen laufen über den Hermes-
Config-Mechanismus (model.default / model.provider / model.base_url).

## Kernidee

> "Hermes Agent hat bereits die Mechanik - alle relevanten Provider und Keys
> stecken in seiner eigenen Konfiguration und in seinen Caches. Eine separate
> Registry ware Redundanz."

| Aspekt | Quelle |
|---|---|
| Provider-Definitionen (~195) | models_dev_cache.json (id, name, env, api, models) |
| Live Modelllisten | provider_models_cache.json |
| Aktive Konfiguration | <Profil>/config.yaml -> model:{default,provider,base_url} |
| Keys | <Profil>/.env (Hermes-Env-Mapping) |

## Geanderte / neue Dateien

| Datei | Status | Beschreibung |
|---|---|---|
| api_provider.py | **neu** | Hermes-nativer Provider-Manager (Status, Liste, Modell-Load, Config-Set, Key-Verteiler, Verifikation). Nur Stdlib. |
| main.py | geandert | import api_provider + 5 neue Routen (siehe unten) |
| static/index.html | geandert | Sidebar-Button, View-Container, JS-Logik |

> Wichtig: Routen sind **vor dem Catch-all-Forward** registriert (siehe unten).

## API-Provider-Routen

| Methode | Pfad | Funktion |
|---|---|---|
| GET | /api/providers | Alle Provider (aus Hermes-Katalog) + gefundene Keys + aktive Config |
| GET | /api/providers/models?provider=X | Modellliste eines Providers |
| POST | /api/providers/configure | Setzt Provider (+ optional Modell) im Hermes-Config |
| GET | /api/providers/verify | Selbsttest: reproduziert den No-API-key-Check |
| POST | /api/providers/deploy | Verteilt Keys in alle .env. {"dry_run":bool} |

## Der eigentliche Nutzen (Paperclip-Fix)

Problem: isolierte Paperclip-Sub-Shells finden API-Keys nicht, weil sie nicht im
jeweiligen Profil-.env liegen ("No API key found for provider 'openrouter'").

Losung: Der **Deploy-Keys-Button** verteilt alle gefundenen Keys (idempotent,
dedupliziert) in ALLE 49 Profil-.env + zentrales .env = 50 Ziele. Keys werden
aus Hermes' Umfeld gesammelt (OpenRouter, OpenAI, Google, Groq, NVIDIA, ...).

## Kritische Falle / Lektion

Das echte main.py besitzt Catch-all-Routen (@app.api_route("/api/providers",
"/api/providers/{path}", ...), ~Z. 2826ff.) die zu einem laufenden Hermes-Dienst
(host.docker.internal:8787, Fallback :9119) weiterleiten. Ist der Dienst down,
liefert das 502 ("Name or service not known").

**Eigene Provider-Routen MUSSEN deshalb VOR diesem Catch-all registriert werden**
(fruh im Datei, nach app = FastAPI(...) + CORSMiddleware). Sonst shadowed das
Forwarding die eigenen Routen. Im Code beginnt der Block bei
class ProviderConfigRequest (~Z. 31).

## Commits

    git -c safe.directory=/projects/AgenticOS-2026 add main.py static/index.html api_provider.py
    git -c safe.directory=/projects/AgenticOS-2026 commit -m \
      "feat: API Provider-Sektion (Hermes-nativ) - Provider/Modelle aus Hermes-Katalog, Key-Verteiler fur Paperclip-Fix, Config-Set"

> Achtung: .env in /projects/AgenticOS-2026 enthalt echte Keys (OMNIROUTE, GOOGLE etc.)
> - NICHT comitten. Vor dem Commit prufen: git status.

## Getestet (real im Projekt-Code via FastAPI TestClient)
- Root / -> 200, index.html inkl. API-Provider-Sektion.
- GET /api/providers -> 195 Provider, 5 mit Key (openrouter, openai, google, groq, nvidia).
- GET /api/providers/models?provider=openrouter -> 41 Modelle.
- POST /configure -> success (idempotent, config.yaml unverandert).
- POST /deploy (dry) -> 50 Ziele.
- main.py + api_provider.py kompilieren ohne Fehler.

## Nachster Schritt (geplant): Agent-Profil > Modell-Kopplung
Pro Agent-Profil ein bestimmtes Hermes-Modell/Provider zuordnen (analog
Personalakte/SOUL.md-Manipulation). Basis: Hermes-native Config-Lese-/Schreib-
Funktionen in api_provider.py sind wiederverwendbar. Ziel: Dropdown im Frontend,
das pro Profil das Modell setzt (hermes config set model.default) und Provider
automatisch aufloest.
