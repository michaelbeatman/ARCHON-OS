# Audit D12 — Silent Tool Failures & Hallucination-Prevention

**Datum:** 24.11.2026 | **Domäne:** 12 (Silent Tool Failures & Hallucination-Prevention)
**Repo:** `C:\.Antigravity-projekte\AgenticOS-2026` (Archon OS v0.5.7.5)
**Modus:** Working-Tree-Audit (62 Dateien uncommitted), Ignore-Liste gemäß Auftrag (`.venv*`, `.ci_venv`, `node_modules`, `.git`, `__pycache__`, `dist`, `site`, `backups`, `archive`, `_archive_legacy`, `*.bak*`, Caches).

---

## 1. Scope & Methodik

### 1.1 Untersuchte Quellen (Auszug, alle mit Zeilenbezug in Abschnitt 2)

| Ebene | Dateien |
|---|---|
| Root | `api_provider.py`, `core_dispatcher.py`, `main.py`, `oracle_news_radar.py`, `research_engine.py`, `research_engine_v2.py`, `seo_execution_agent.py`, `jev_router.py`, `telegram_notify.py`, `local_security_guard.py`, `utils/safe_http.py` |
| Archon | `archon/core/provider_registry.py`, `archon/routers/llm_providers.py`, `archon/routers/gateway.py`, `archon/routers/hermes_proxy.py`, `archon/routers/mcp_gateway.py`, `archon/routers/container_ops.py`, `archon/core/delegation.py` |
| Backend | `backend/agent_router.py`, `backend/dual_llm_sanitizer.py`, `backend/mcp_gateway.py`, `backend/llm_kernel.py`, `backend/llm_egress_guard.py`, `backend/structured_output_enforcer.py`, `backend/tool_output_firewall.py`, `backend/notification_hub.py`, `backend/epistemic_hygiene.py`, `backend/crm_service.py`, `backend/erp_manager.py`, `backend/dead_letter_queue.py` |
| Frontend | `static/js/*.js` (v. a. `crm_studio.js`, `corporate_controller.js`, `mission_control_cockpit.js`, `operations_kanban.js`, `agent_profiles.js`, `command_palette.js`), `frontend/src/lib/archon-api.ts`, `frontend/src/app/api/**/route.ts` |
| MCP | `scripts/archon_mcp_server.py` (`execute_tool`, `isError`-Mapping) |

**Methode:** Echter Code gelesen, keine Doc-/Kommentar-Aussage als Beleg übernommen. Systematische RegExp-Suche über alle `.py`-Dateien (Vendor/Cache ausgeschlossen) und `.js`/`.ts`-Dateien, danach gezielte Verifikation jeder verdächtigen Stelle im Kontext (Aufrufer, Fehlerpfad, Return-Shape).

### 1.2 Quantitative Muster-Zählung

Zählung per `Select-String` über alle `.py`-Dateien außer `.venv*`, `.ci_venv`, `node_modules`, `.git`, `__pycache__`, `dist`, `site`, `backups`, `archive`, `_archive_legacy`, `.pytest_cache`, `.ruff_cache`, `.hermes`, `obsidian_vault`, `library`, `antigravity_complete_skills_package` (12.369 Dateien inkl. `scripts/`, `tests/`, `tools/`, `plugins/`):

| Muster | Treffer | Dateien | Bewertung |
|---|---:|---:|---|
| `except Exception:` (bare, ohne Typ-Differenzierung) | **4.584** | 1.296 | flächendeckend; davon 643 in Backend, 108 in `archon/`, ~90 in Root-Modulen |
| `return ""` | **536** | 340 | systematische Leerwert-Rückgabe inkl. Fehlerpfaden |
| `or {}` | **1.073** | 548 | Fallback-Ketten, oft auf parse-/DB-Fehler angewandt |
| `or []` | **721** | 344 | Fallback-Ketten, oft auf parse-/HTTP-Fehler angewandt |
| `.json()` / `resp.json()` / `response.json()` | **563** | 135 | nur ein Teil mit `.ok` / Status- / Shape-Prüfung |
| `return {}` | **316** | 211 | —— |
| `return []` | **877** | 440 | —— |
| `return None` | **6.950** | 1.728 | überwiegend harmlose Optional-Returns; in Tool-Wrappern aber relevant (siehe Befunde #14/#18/#26) |
| `raise_for_status()` | **427** | 116 | zeigt: Status-Prüfung ist verfügbar, wird aber an den kritischen Stellen (#9/#10/#14) nicht genutzt |
| `temperature=0` | **41** | 25 | nur vereinzelt (z. B. LLM-Judge `local_security_guard.py:215`), nicht für Extraktions-Tasks im Router |
| `\|\| []` in `static/js/*.js` (ohne Vendor) | **292** | 28+ | Frontend: Fehler → leere Tabelle/Liste |

Schwerpunkt im Kern-Dispatch: `core_dispatcher.py` allein hat **59** `except Exception`-Blöcke (davon 13 mit nacktem `except Exception:`); `backend/agent_router.py` hat 3 nackte Handler im heißen Pfad; `api_provider.py` hat **21** `except Exception`-Blöcke (davon 12 nackt).

**Interpretation:** Die Dichte an „leeren Erfolgen" ist sehr hoch. Entscheidend ist nicht die Anzahl an sich, sondern dass an zentralen Chokepoints (LLM-Response, Tool-Output, Webhook, Frontend) Fehler mit gültigen, aber inhaltlosen Werten vermischt werden. Genau diese Stellen sind in Abschnitt 2 mit Befund-IDs belegt.

### 1.3 Bewertungsskala Kritikalität

- **Kritisch** — Agent/UI erhält erfundene oder leere Fakten als gültiges Ergebnis; direkter Halluzinations-/Fehlentscheidungs-Pfad.
- **Hoch** — Fehler wird als Erfolg/„keine Daten" gemeldet; Retry/DLQ fehlt; Grounding-Guard ist wirkungslos.
- **Mittel** — Fehler ist sichtbar, aber unpräzise (stale Daten, Platzhalter, fehlende Quellenangabe).
- **Niedrig** — Code-Smell mit potenzieller Auswirkung, aber kein direkter Halluzinationspfad.

---

## 2. Befundtabelle

| # | Dateipfad | Zeile(n) | Kritikalität | Kategorie | Technischer Nachweis | Impact | Empfehlung |
|---|---|---|---|---|---|---|---|
| 1 | `api_provider.py` | 121–145, 148–155 | Hoch | Leere Erfolge | `_load_json()` gibt bei `not exists`, `OSError` und `except Exception` dreimal `{}` zurück; `load_provider_catalog()/load_provider_models()` liefern leere Dicts ohne Fehler-Flag. | Katalog-Lesefehler ist von „leerer Katalog" nicht unterscheidbar; nachgelagerte Modell-/Key-Erkennung arbeitet auf leerer Basis und greift auf Static-Fallbacks zu. | `Result[dict, ReadError]` mit `path`, `errno`, `mtime`; leerer Katalog nur bei verifiziert gültiger leerer Datei. |
| 2 | `api_provider.py` | 213–250 | **Kritisch** | Fallback-Fabrik | Alle drei OmniRoute-URLs scheitern → `print(... stderr)` (239–240), dann harte Liste mit plausiblen Modellnamen (`auto/best-coding`, `deepseek-ai/DeepSeek-V4-Pro`, …) zurückgegeben (246–250). Aufrufer `llm_providers.py:56–70` meldet `status: ok`. | Agent/UI sieht eine vollständige, plausibel klingende Modellliste, obwohl keine Live-Abfrage stattfand; nicht existierende Modelle werden dispatcht. | Fallback-Liste nur mit `degraded: true`, `source: "static"`, `error` + Alter; UI muss „veraltet/live nicht erreichbar" anzeigen. |
| 3 | `api_provider.py` | 536–574 | **Kritisch** | Silent Failure/State | Beim Lesen der Config in `_set_model_block` (`except Exception: lines = []`, 541–542) wird die Datei anschließend mit `out.extend(block)` komplett überschrieben und `True` zurückgegeben. | Config-Verlust (alle anderen Keys) wird als Erfolg gemeldet; falsche Provider-Konfiguration führt zu still umgeleiteten LLM-Calls. | Bei Read-Fehler `return False, error` und **kein** Schreiben; Schreiben nur nach erfolgreichem Parse + Backup. |
| 4 | `api_provider.py` | 872–904 | Hoch | Fallback-Fabrik | Beim Parse-Fehler der `profile.yaml` (`tools`, 877–897) wird `prof_tools = []` und danach `if not prof_tools: prof_tools = ["web_search"]` (903–904). Kommentar behauptet „fail-closed: kein Profil-Tool-Set" — tatsächlich wird ein Tool gewährt. | Agent erhält still eine Fähigkeit, die das Profil nicht vorgesehen hat; „fail-closed"-Doku ist falsch. | Bei Parse-Fehler `tools: None` + `capability_error`; leeres Set = `[]`, nicht `["web_search"]`. |
| 5 | `api_provider.py` | 978–988 | Mittel | Provider-Substitution | `if not prov: prov = "openrouter"  # Fallback` (982–983) bei unbekanntem Modell. | Falscher Provider/Endpoint ohne Signal; Rechnung/Privacy-Routing kann falsch werden. | `Result` mit `provider_inferred: false`, kein stiller Default. |
| 6 | `archon/routers/llm_providers.py` | 56–70, 73–140 | **Kritisch** | 200 OK ohne Nutzlast | Preis- und Modell-Abfragen scheitern still (`logger.debug`, 63–64/71–72), danach wird statischer Katalog zurückgegeben und `status: "ok"`/`"success"` geliefert; unbekannter Provider erhält `catalog["openrouter"]` (134). | UI und Agenten glauben an echte, aktuelle Modellverfügbarkeit; `IndexError`/`KeyError` beim Dispatch ist die Folge. | Bei Fehler HTTP 502 + `status: error`; nur bei erfolgreichem Live-Fetch `status: ok` + `source`. |
| 7 | `archon/routers/llm_providers.py` | 199–218 | Mittel | Irreführender Erfolg | `"has_key": bool(found_val) or (pid == "omniroute")` (212). | OmniRoute wird immer als „Key vorhanden" angezeigt, auch wenn kein Key existiert; Login/Dispatch-Fehler überrascht. | Key-Status aus `keys_for_provider()` + explizitem `key_source`; niemals `or pid == …`. |
| 8 | `archon/routers/llm_providers.py` | 295–308 | Hoch | Fallback-Fabrik | `_get_llm_provider_models_impl()` ersetzt leere OmniRoute-Modelle durch hartcodierte Liste und gibt `status: ok` (304–306). | Wie #2, auf internem Helfer-Pfad (SSE/Chat). | `status: degraded` + Fehlergrund; leere Liste nur bei verifiziert leerer API-Antwort. |
| 9 | `archon/routers/llm_providers.py` | 244–283 | Hoch | Antwort-Parsing | `_get_llm_prices_locked` gibt bei Fehler `{"status":"error", "prices": _openrouter_price_cache or {}}` (277–278) zurück; interne Aufrufer (`backend.llm_kernel`, `chat.py`) müssen `status` selbst prüfen. | Ein Aufrufer ohne Status-Check sieht `prices: {}` als „keine Modelle" statt „Preis-API down". | Fehler-Result ohne `prices`-Feld oder mit `prices: None`; `status` zwingend auswerten. |
| 10 | `utils/safe_http.py` | 50–104 | **Kritisch** | Antwort-Parsing | `safe_http_json()` verwirft HTTP-Status (`_, _, raw`, 95) und parst `raw` direkt; kein `resp.raise_for_status()`, keine `None`/`{}`/`{"error":…}`-Prüfung. | 200 mit `{"error":…}` oder leerer/HTML-Body wird als Datenobjekt an Agenten weitergegeben. | Status + Content-Type prüfen; `Result[Any, HttpError]`; `{"error"}`-Body als Fehler markieren. |
| 11 | `oracle_news_radar.py` | 69–82, 176–213 | **Kritisch** | Leere Erfolge | `_fetch_url()` fängt jede Exception → `print(stderr)` → `None` (71–75); alle Fetcher geben `[]`; `run_radar_cycle()` meldet `status: success, new_signals_count: 0` (207–213). | Totaler Netzwerkausfall ist von „keine News" nicht unterscheidbar; Agent berichtet „keine neuen Signale" als Fakt. | `status: degraded/error`, `failed_sources`, `fetch_errors`; Erfolg nur bei ≥1 erfolgreichem Source. |
| 12 | `oracle_news_radar.py` | 93–107, 125–139, 152–172 | **Kritisch** | Fallback-Fabrik | `story.get("url", f"https://news.ycombinator.com/item?id=…")`, `fromtimestamp(story.get("time", time.time()))`, `f"…{score} Punkten und {descendants} Kommentaren"`, `pipeline = m.get("pipeline_tag", "llm / weights")`, `desc = repo.get("description", "Keine Beschreibung vorhanden.")`, `lang = repo.get("language", "Code")`. | Erfundene URLs, Timestamps, Metriken und Modellklassen werden als echte Fakten in Obsidian-Infos und Agenten-Kontext geschrieben. | Fehlende Felder → `None` + `missing_fields`; niemals plausibel klingende Defaults. |
| 13 | `oracle_news_radar.py` | 239–241, 248–256 | Hoch | Leere Erfolge | Ohne Signale wird „*Bislang keine neuen ungesehenen Signale im aktuellen Zeitfenster.*" notiert (241); `get_feed()` gibt bei JSON-Fehler still `[]` (254–255). | „Keine Daten" vs. „Datei korrupt/Fetch fehlgeschlagen" nicht trennbar. | `no_data` vs. `read_error` unterscheiden; Obsidian-Notiz mit `fetch_status`. |
| 14 | `backend/agent_router.py` | 824–849, 673–678 | **Kritisch** | Antwort-Parsing | `data = resp.json()` ohne `None`/`{}`-Prüfung; `data["choices"][0]["message"]["content"]` ohne Längenprüfung (834); Anthropic `data.get("content") or []` (827); `raw_text` kann `""`/`None` sein; `_finalize_output_guard` gibt bei `""` sofort `""` zurück (676–678) und `chat_completion` returned das als Erfolg (849). | 200 OK ohne Nutzlast → leerer String als „Antwort" an Agenten;halluzinierte Fortsetzung des Kontexts möglich. | Nach Parse: `if not text or not text.strip(): raise EmptyResponseError(provider, model, status)`; Fallback oder `ERROR`. |
| 15 | `backend/agent_router.py` | 1001–1043 | Hoch | Antwort-Parsing | SSE: `choices = chunk.get("choices") or []; if not choices: continue` (1017–1019); `JSONDecodeError` still übersprungen (1038–1039); bei 0 Text-Deltas endet der Generator ohne `yield` und ohne Fehler (1057). | Stream-Antwort bleibt leer; Consumer zeigt „keine Antwort" statt Provider-Fehler. | `received_chars == 0` → `yield "ERROR: empty stream"` nach gleichem Muster wie 1076–1079. |
| 16 | `backend/agent_router.py` | 564–570 | Mittel | Hallucination-Guard | `client_payload["temperature"] = 0.6` für **alle** Tasks; kein `response_format`/JSON-Schema im Router. | Extraktive Aufgaben (z. B. Tool-Argumente) werden mit Sampling betrieben; erhöhte Varianz/Faktenerfindung. | `temperature=0` für Extraktion, `response_format={"type":"json_object"}` + Schema validieren. |
| 17 | `core_dispatcher.py` | 100–145 | **Kritisch** | Webhook | `trigger_n8n_execution()` meldet bei Nicht-200 `status: warning, "n8n returned HTTP … - stored locally"` (136–140) und bei Exception `status: error, "… - stored locally"` (142–145) — tatsächlich wird hier **nichts** persistiert, kein Retry, keine DLQ. | Falsche Zusicherung „stored locally"; Webhook-Payload geht verloren, Agent glaubt an Zustellung. | Fehler in Outbox/DLQ schreiben und `dlq_id` zurückgeben; Meldung „geplant/fehlgeschlagen" statt „stored". |
| 18 | `core_dispatcher.py` | 308–349 | Hoch | Antwort-Parsing | `parse_omniroute_response()` gibt bei JSON-/SSE-Fehler oder leerer Antwort immer `""` zurück (313–349); Aufrufer prüfen teils `len(content.strip()) > 5` (1292/1317), teils nur `if content` (1363/1480/1533). | Parse-Fehler, leere LLM-Antwort und gültige Kurzantwort sind nicht trennbar; inkonsistente Mindestlänge. | `Result[str, ParseError]`; einheitlicher `min_chars`-Gate; leere Antwort → nächster Fallback/Fehler. |
| 19 | `archon/routers/gateway.py` | 54–74, 368–386 | Hoch | Webhook/Lifecycle | `stop-all` fängt jede `docker_exec`-Exception (382–383) und gibt trotzdem `{"ok": True, "stopped": [pid]}` (385–386); `_run_docker_exec` verschluckt alle Exceptions (69–72) und liefert generische Fehlermeldung. | Fehlgeschlagene Gateway-Stopps werden als Erfolg gemeldet; Agenten glauben an korrekten Systemzustand. | `results: [{pid, ok, error}]`; HTTP 207/502 bei Teilfehlern. |
| 20 | `archon/routers/gateway.py` | 77–119 | **Kritisch** | Hallucination | `_parse_gateway_list()`: Wenn JSON-Parsing scheitert (88–90) oder Dict unbekannte Keys hat, wird jede beliebige zweitokenige Textzeile als Profil mit `status` interpretiert (100–118). | Parse-Fehler erzeugt **erfundene** Profile/Statusse; Orchestrator trifft Entscheidungen auf Phantom-Daten. | Bei Parse-Fehler `[]` + `parse_error`; kein Text-Heuristic-Fallback auf fremde Ausgaben. |
| 21 | `archon/routers/hermes_proxy.py` | 131–155 | Hoch | 200 OK ohne Nutzlast | Jede Upstream-Antwort wird mit `status_code=resp.status_code` und `content=resp.content` durchgereicht (142–146); 200 mit leerem Body wird nicht erkannt; `_HERMES_TARGET_CACHE` wird bei jeder Antwort gesetzt (140–141), auch bei leerer/Fehler-Antwort. | Agent/UI sieht erfolgreichen leeren HTTP-Call; fehlerhaftes Ziel wird 30 s gecacht. | Nur bei 2xx + validem Body cachen; leerer Body → 502 `proxy_empty_response`. |
| 22 | `backend/mcp_gateway.py` | 537–565, 711–737 | **Kritisch** | Leere Erfolge | `_tool_search_vault()` gibt bei fehlendem Vault-Root oder Exception pro Datei `{"status":"success","count":0,"matches":[]}` (563–565). JSON-RPC setzt `is_error` **nur** bei `result["status"] == "error"` (729), alle anderen Fehler-Shape werden als Erfolg an den LLM geliefert. | „Keine Treffer" vs. „Vault nicht lesbar" nicht unterscheidbar → Agent behauptet faktenbasiert „nichts gefunden". | Einheitlicher Tool-Vertrag (siehe Abschnitt 6); `is_error` aus `result.ok == false`. |
| 23 | `backend/mcp_gateway.py` | 320–325 | Mittel | Fallback-Fabrik | Fehlt `config/boardroom_frameworks.json`, gibt `read_resource()` `{"frameworks": []}` mit `ok=True` (325). | Agent sieht „keine Frameworks" statt „Datei fehlt". | `ok=False` + `error=FILE_NOT_FOUND`; Ressource leer nur bei gültiger leerer Datei. |
| 24 | `backend/mcp_gateway.py` | 518–535 | Hoch | Irreführender Erfolg | `_tool_ask_specialist()` gibt ohne Prüfung von `task_res` immer `status: success` + „Aufgabe an Spezialist übergeben" (530–535). | Delegationsfehler (`_create_task` liefert `status: error`) wird als Erfolg berichtet; Agent glaubt an erledigte Übergabe. | `task_res.status` prüfen; bei Fehler `status: error` + Originalfehler weitergeben. |
| 25 | `backend/mcp_gateway.py` | 588–595 | Hoch | Fail-open | Demo-Mode-Guard: `except Exception → logger.debug("Guard wird übergangen")` (593–594), danach wird das Tool ausgeführt. | Sicherheits-/Demo-Gate ist bei internem Fehler wirkungslos; widerspricht fail-closed-Doku. | Bei Guard-Fehler `-32003` zurückgeben, niemals `continue`. |
| 26 | `backend/tool_output_firewall.py` | 20–27, 100–114 | Hoch | Hallucination | `guard_tool_output()` macht `text = raw_output if isinstance(str) else str(raw_output)` (27): `None` wird zum Literal `"None"`; dieser String wird mit `--- BEGIN UNTRUSTED TOOL OUTPUT ---` in den LLM-Kontext eingespeist. | Ein fehlgeschlagenes Tool (`None`) wird als Inhalt `"None"` ausgegeben; Agent kann daraus „Ergebnis: None" ableiten. | `None` → `{"status":"error","error":"EMPTY_TOOL_RESULT"}`; leerer Output nie in Kontext. |
| 27 | `backend/structured_output_enforcer.py` | 26–39, 112–139 | **Kritisch** | Fallback-Fabrik | Fehlende/`None`-Felder werden mit `TYPE_DEFAULTS` (`""`, `0`, `False`, `[]`, `{}`) gefüllt (115–117), coercions featlschläge ebenfalls (130–132), Ergebnis ist `valid: True` (135). | Modell halluziniert strukturierte Werte: `amount: 0.0`, `name: ""` erscheinen als „validierte" Fakten in Rechnungs-/Vertrags-Workflows. | Fehlende Pflichtfelder → `valid: False` + `missing_fields`; Defaults nur mit explizitem `fill_policy` und `synthesized: true`. |
| 28 | `local_security_guard.py` | 175–263 | **Kritisch** | Hallucination-Guard | `validate_ai_output()` nutzt standardmäßig `use_llm=False` (180), nur  regex-Heuristik `HALLUCINATION_PATTERNS`; `base_score = 10 - flags*2` (192). Ein sachlich klingender, aber unbelegter Claim hat 0 Flags → Score 10 → `TRUST`. | Hallucination-Guard erkennt nur „weasel words", keine Quellen-/Belegprüfung; schützt nicht vor erfundenen Fakten. | Grounding-Pflicht: jeder Claim muss `source_id` + `quote` haben; LLM-Judge mit `temperature=0` und `SCORE` validieren; `use_llm=True` als Default. |
| 29 | `research_engine.py` | 430–468 | Hoch | Fallback-Fabrik | Bei OmniRoute-Synthesefehler wird ein „Heuristische Zusammenfassung"-Dossier aus Snippets gebaut (457–467) und mit `model_used: "local-fallback"` zurückgegeben; `status` bleibt Erfolg. | LLM-Ausfall wird durch plausibel klingende, aber nicht modellvalidierte Prosa ersetzt. | `status: degraded`, `synthesis_source: heuristic`, niemals als reguläres Dossier ausgeben. |
| 30 | `research_engine.py` | 587–597, 637, 678–696 | **Kritisch** | Hallucination-Guard | `val_gate = validate_ai_output(..., min_score=6)` wird nur als Metadaten ins Dossier geschrieben (637/690) und das Dossier mit `status: success` gespeichert (679). Auch `recommendation: REJECT` blockiert nichts. | Quality-Gate ist rein dekorativ; abgelehnte Halluzinationen landen in Obsidian und im Agenten-Kontext. | `if not val_gate["passed"]: return status: rejected` + kein Persistieren/Weiterleiten. |
| 31 | `research_engine.py` | 93–107, 148–184, 187–223, 226–289, 292–347 | Hoch | Leere Erfolge | Alle Such-Wrapper (`search_wikipedia`, `search_arxiv`, `search_duckduckgo`, `search_searxng`, `search_tavily`, `search_grokipedia`) fangen Exceptions mit `print(...)` und `return []`. | Netzwerk-/API-Fehler sehen aus wie „keine Suchergebnisse"; Triangulation und Dossier behaupten Evidenzbasis. | `SearchResult[T]` mit `engine`, `error`, `http_status`; `no_results` nur bei 2xx + gültigem leeren Body. |
| 32 | `research_engine.py` | 650–653 | Mittel | Zitatvalidierung | Quellenzeile nutzt `s.get('domain','-')` und `[…]({s.get('url','#')})` — fehlende URL wird zu `href="#"`. | Pseudogültige Zitate ohne erreichbare Quelle; Zitatvalidierung fehlt. | URL fehlt → `⚠ fehlende Quelle` statt Link; Zitat nur mit verifizierter URL. |
| 33 | `research_engine_v2.py` | 190–242, 386–419 | Hoch | Leere Erfolge | `scrape_local()`, `scrape_jina()` geben bei Fehler `""` (193/200/201/219/221); `scrape_page()` liefert `("", "none")` (242); `_enrich()` überspringt still (394–396). | Kein Fehlerkanal für Scraping; Gesamt-Evidenz kann als „no_evidence" enden, obwohl nur HTTP-Fehler vorlagen. | `ScrapeResult` mit `status`, `http_status`, `error`, `provider`; in `rounds_log` aufnehmen. |
| 34 | `telegram_notify.py` + `backend/notification_hub.py` | `telegram_notify.py:143–171`; `notification_hub.py:158–170, 184–192` | Hoch | Webhook/DLQ | `send_telegram_message()` prüft korrekt `200 and data.ok`, gibt aber bei Fehler nur `False` zurück — kein Retry, keine DLQ. `dispatch_notification()` ignoriert den Return (167) und fügt `"telegram"` zu `dispatched_channels` hinzu, meldet `status: success` (185). | Zustellfehler wird im Audit-Log als zugestellt dokumentiert; kritische HITL-Nachrichten gehen verloren. | Return auswerten; `channels` nur bei bestätigter Zustellung; Fehler in `dead_letter_queue` mit `retry_after`. |
| 35 | `backend/epistemic_hygiene.py` | 65–78, 118–129 | Mittel | Hallucination-Guard | `scanned += 1` (73) **vor** dem Datei-Read; `except Exception: continue` (77–78) überspringt die Datei still; `hygiene_score` wird aus unvollständiger Stichprobe berechnet. | Scores suggerieren vollständigen Vault-Scan, obwohl Dateien nicht gelesen wurden. | `scanned_ok` vs. `skipped` + `errors` ausgeben; Score nur bei 0 Skip-Fehlern. |
| 36 | `backend/crm_service.py` | 245–264 | Mittel | Antwort-Parsing | `nachrichtenverlauf` JSON-Parse-Fehler → `print(stderr)` und leere Nachrichtenliste (263–264). | Korruptes CRM-Feld wird als „keine Nachrichten" interpretiert; Agent schließt auf fehlende Kommunikation. | `{"messages": [], "parse_error": …}`; UI/LLM zeigt „Daten beschädigt". |
| 37 | `jev_router.py` + `archon/routers/container_ops.py` | `jev_router.py:37–41, 76–90`; `container_ops.py:241–253` | **Kritisch** | Fallback-Fabrik | Fast-Path `system_status` führt `python -c "print('System Status: Online')"` aus; `container_ops` gibt das als echten Befehls-Output zurück (249–253). | Auf „Status prüfen" wird **immer** „System Status: Online" behauptet, ohne jeden Service-Check — klassische Hallucination-as-a-Service. | Hardcoded Status-Eintrag entfernen oder als `demo_only: true` markieren und nie als `stdout` ausgeben. |
| 38 | `static/js/crm_studio.js` | 1339–1355 | Hoch | Frontend | `.then(r => r.json())` ohne `.ok`-Prüfung; Fehler-Body wird als Erfolg interpretiert und `res.message` (evtl. `undefined`) in die Nachrichtenliste eingefügt. | Fehlgeschlagene Nachricht wird als gesendet/erscheint als leere Nachricht; User glaubt an Erfolg. | `if (!r.ok) throw …`; Erfolg nur bei gültigem `res.message`. |
| 39 | `static/js/agent_profiles.js:1243`, `static/js/command_palette.js:150`, `static/js/operations_kanban.js:450,571`, `static/js/corporate_controller.js:598` | je 1 Zeile | Mittel | Frontend | Fire-and-forget `.then(r => r.json()).then(() => …)` ohne `.ok` und ohne Fehler-Anzeige. | Schreibfehler bleiben unsichtbar, nachfolgende UI-Aktion läuft auf veraltetem State. | `.ok` prüfen, Fehler toasten, State erst nach Bestätigung ändern. |
| 40 | `static/js/corporate_controller.js:31–33`, `static/js/mission_control_cockpit.js:316–319` | je 3 Zeilen | Mittel | Frontend | Bei `!res.ok` wird still `return`; vorhandener Cache/alte Tabelle bleibt stehen und wird nicht als „veraltet" markiert. | User sieht alte Daten als aktuell; Fehlerstatus fehlt. | `error` in den Store schreiben und Banner/Placeholder „Daten nicht aktualisierbar" zeigen. |

**Summe:** 40 belastbare Befunde — **14 kritisch, 17 hoch, 9 mittel**. Alle Angaben wurden durch Lesen des echten Codes verifiziert; keine Docs/Kommentare als Beleg verwendet (Kommentar-Widersprüche sind vielmehr selbst Befund #4).

---

## 3. Domänen-Urteil

**Note 2 (von 5)** — mit klarer Tendenz zu 1.

**Begründung:**
- Positiv: Es existieren echte, gut platzierte Chokepoints (`evaluate_and_gate_llm_dispatch`, `sanitize_outbound_llm_payload`, `log_completed_llm_dispatch`, `ZeroEgressBlockedError`, `guard_tool_output`, `provider_breaker`, explizite `status: error`-Returns in `core_dispatcher` und `AgentRouter.chat_completion`). Der grobe Fall „stilles `except: pass` → Dummy-Bereitschaftsmeldung" ist an zentralen Dispatch-Pfaden weitgehend behoben (z. B. `core_dispatcher.py:1578–1585`, `agent_router.py:858–861/1076–1079`).
- Negativ: Die **halluzinationsrelevanten** Fehlerpfade sind systematisch fail-open: leere/parsefehlerhafte LLM-Antworten werden als Erfolg zurückgegeben (#14/#15), Fallback-Fabriken liefern plausibel klingende Modell-/News-/Status-/Strukturwerte (#2/#6/#12/#27/#37), Grounding-Guards sind dekorativ (#28/#30), Webhook-Zustellung wird falsch dokumentiert (#17/#34), und das Frontend zeigt Fehler als „keine Daten" (#38/#40).
- Die Quantität (4.584 bare `except Exception`, 1.073 `or {}`, 721 `or []`, 292 `|| []` im Frontend) zusammen mit der Qualität der oben belegten Chokepoint-Fehler rechtfertigt keine Note 3.

**Für Note 1 spricht:** #3 (Config-Überschreibung), #14 (leere LLM-Antwort), #17 („stored locally"-Lüge), #27 (synthetisierte Pflichtfelder), #30 (REJECT ohne Wirkung), #37 (halluzinierter Systemstatus) — sechs Pfade, bei denen ein Agent oder ein Owner aktiv falsche Fakten erhält.

---

## 4. Top-5-Risiken

1. **Leere LLM-Antwort als Erfolg** (`backend/agent_router.py:824–849`): HTTP 200 ohne `choices`/Text wird als gültige Antwort an den Agenten zurückgegeben; der Agent füllt die Lücke aus dem Kontext → direkte Halluzination.
2. **Quality-Gate ohne Wirkung** (`research_engine.py:587–597, 637, 679` + `local_security_guard.py:175–263`): `REJECT` wird ins Dossier geschrieben, speichert es aber trotzdem; der Heuristik-Score erkennt keine unbelegten Fakten.
3. **Strukturierte Fallback-Werte als „valid"** (`backend/structured_output_enforcer.py:112–139`): fehlende Pflichtfelder werden mit `0`/`""`/`[]` gefüllt und als validiert markiert — in Rechnungs-/Vertrags-Workflows ein direktes Risiko für falsche Fakten und Entscheidungen.
4. **Webhook-/Zustellungs-Lüge** (`core_dispatcher.py:100–145`, `notification_hub.py:158–192`): „stored locally" bzw. `dispatched_channels: ["telegram"]` ohne Persistenz/DLQ — kritische HITL-Nachrichten und n8n-Trigger gehen verloren, während Audit-Log Erfolg behauptet.
5. **Plausible Daten aus toten Quellen** (`api_provider.py:213–250`, `oracle_news_radar.py:69–172`, `jev_router.py:37–41`): bei Totalausfall werden statische Modelllisten, erfundene News-Metriken und „System Status: Online" als echte Daten ausgegeben.

---

## 5. Geprüfte Doc-Behauptungen

| Behauptung | Status | Beleg / Begründung |
|---|---|---|
| OmniRoute-Multi-Provider (OpenAI/Anthropic/Gemini/Groq/DeepSeek) | ⚠️ | Provider-Pfade existieren in `backend/agent_router.py:488–562` und `core_dispatcher.py:1276–1540`; **aber** Modellkataloge sind statische Fallbacks (`api_provider.py:246–250`, `llm_providers.py:73–140`) → „verfügbar" ≠ „live abgefragt". |
| LLM-Dispatch-Protokollierung mit Provider/Modell/Host/Endpunkt | ✅ | `backend/agent_router.py:811–819`, `969–977` (`log_completed_llm_dispatch` mit `provider`, `model`, `target_endpoint`, `http_status`, `data_category`, `zero_egress_active`); `core_dispatcher.py:_audited_post`. |
| Strikt fail-closed bei blockiertem/zero-egress-Dispatch | ⚠️ | LLM-Pfad tatsächlich fail-closed (`agent_router.py:627–649, 850–851, 902–904`; `core_dispatcher.py:1245–1274, 1296–1297`). **Aber** `backend/mcp_gateway.py:593–594` (Demo-Guard übergangen) und `api_provider.py:903–904` (Tool-Fallback) sind fail-open. |
| Idempotenz + Outbox mit Retry/DLQ | ⚠️ | `backend/dead_letter_queue.py` (Retry/Backoff/Claim/Idempotency-Key), `backend/idempotency_guard.py` vorhanden; **nicht** angewandt auf n8n-Webhook (`core_dispatcher.py:100–145`) und Telegram (`telegram_notify.py:143–171`) — beides ohne Retry/DLQ. |
| 407 stille `except: pass` ersetzt | ❌ | 4.584 bare `except Exception:` (1.296 Dateien), 643 allein in `backend/`, 108 in `archon/`, 21 in `api_provider.py`; viele mit `pass`, `continue`, `return ""`/`{}`/`[]`. Ein Teil ist geloggt (nicht mehr „still"), aber die Halluzinationspfade #1–#40 bleiben. |
| Dual-LLM-Prompt-Injection-Guard | ⚠️ | `backend/dual_llm_sanitizer.py:135–229` ist **einstufig heuristisch** (NFKC + 25+9 Signaturen); `local_security_guard.validate_ai_output` hat optionalen LLM-Judge mit `temperature=0.0` (215) und Egress-Gate (217–225), aber `use_llm=False` als Default (180). Kein durchgängiger Dual-LLM-Durchlauf für jeden Input. |
| `evaluate_and_gate_llm_dispatch` | ✅ | Import + Aufruf in `agent_router.py:719–737` und `:760–767`, `:878–901`, `:925–933`; `core_dispatcher.py:154–186`; Fail-closed bei `ZeroEgressBlockedError`. |
| `sanitize_outbound_llm_payload` | ✅ | `agent_router.py:781–786` (Non-Stream) und `:947–952` (Stream), jeweils vor `client.post`/`client.stream`; zusätzlich `enforce_egress_firewall_for_url` (773/939). |

---

## 6. Empfehlung: einheitliches `Result[T, Error]`-Tool-Vertragsmuster

### 6.1 Kernidee

Jeder Tool-Wrapper, Webhook-Client und LLM-Response-Parser liefert **ein** Typergebnis — niemals `None`, `""`, `{}`, `[]` als Erfolg:

```python
@dataclass(frozen=True)
class ToolError:
    code: str                 # z. B. HTTP_EMPTY_BODY, PARSE_ERROR, SOURCE_UNAVAILABLE
    message: str              # technisch, für Logs
    source: str               # tool/url/provider
    http_status: int | None
    retryable: bool
    payload_excerpt: str = "" # max. 200 Zeichen, redacted

@dataclass(frozen=True)
class ToolResult(Generic[T]):
    ok: bool
    value: T | None           # nur bei ok=True gesetzt
    error: ToolError | None   # nur bei ok=False gesetzt
    evidence: list[Evidence]  # source_id, url, retrieved_at, quote
    degraded: bool = False    # true = Fallback/_cache, kein Live-Ergebnis
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def success(cls, value: T, evidence=..., degraded=False): ...
    @classmethod
    def failure(cls, error: ToolError): ...
```

### 6.2 Obligatorische Regeln (aus den Befunden abgeleitet)

1. **Kein leerer Erfolg.** `value is None`, `value == ""`, `value == {}`, `value == []` → nur erlaubt, wenn die Quelle explizit und verifiziert „leer" gemeldet hat (Status + `content-length` + gültiger Body). Sonst `failure(EMPTY_RESPONSE)`.
2. **HTTP-Status vor Parsing.** `resp.raise_for_status()` (oder `Result.failure(HTTP_x)`) **bevor** `.json()`; Body mit `{"error": …}` ist ein Fehler, auch bei 200.
3. **Antwort-Shapes zwingend prüfen.** OpenAI `choices[0].message.content` nur nach `len(choices) >= 1` und `isinstance(content, str)`; Anthropic `content[].type == "text"` nur nach `isinstance(list)`; `None`/fehlend → `EMPTY_RESPONSE`.
4. **Keine plausiblen Defaults.** Fehlende Felder → `missing_fields`, nicht `0`/`""`/`"Code"`/`"llm / weights"`/`"System Status: Online"`. Ein Default darf nur mit `degraded=True` + `synthesis_source` gesetzt werden.
5. **Grounding-Pflicht für LLM-Output.** Jeder in den Kontext zurückfließende Tool-Result braucht `evidence` mit `source_id`; `validate_ai_output` prüft Zitat-vorhandensein statt nur Weasel-Words; `REJECT` **blockiert** Persistenz und Weitergabe (#30).
6. **Fehler → Outbox/DLQ.** Jeder fehlgeschlagene Webhook liefert `dlq_id`/`retry_after`; `dispatched_channels` darf nur bestätigte Zustellungen enthalten (#17/#34).
7. **Frontend-Vertrag.** `archonFetch` wirft bei `!res.ok`; `status: error`/`degraded` wird als Fehler-Banner gerendert, nicht als leere Tabelle. `|| []` nur für **optional** Felder eines bereits validierten Erfolgsobjekts, nie für den Whole-Body.
8. **MCP/tool_call_id.** `isError` aus `result.ok`, nicht aus `result.status == "error"`; unbekannte Tool-Namen und nicht übereinstimmende `tool_call_id` → JSON-RPC `-32602`/-32601; `None`-Outputs nie in den Kontext (#22/#26).
9. **Zentrale Metrik.** `degraded=True` und `failure()`-Raten pro Tool in Telemetrie; Ziel: 0 „leere Erfolge" im LLM-/Tool-Pfad.

### 6.3 Migrationsreihenfolge (pragmatisch)

1. `utils/safe_http.py`, `backend/agent_router.py`, `core_dispatcher.py:parse_omniroute_response` (höchster Hebel, #10/#14/#18).
2. `backend/structured_output_enforcer.py`, `backend/tool_output_firewall.py`, `backend/mcp_gateway.py` (#22/#26/#27).
3. `api_provider.py`, `archon/routers/llm_providers.py`, `oracle_news_radar.py` (#1/#2/#6/#11/#12).
4. Webhooks/Notify + Frontend (#17/#34/#38/#40).
5. Alte bare `except Exception:`-Blöcke mit `ruff`/AST-Regel erfassen und nach Priorität abarbeiten (4.584 Treffer — nicht in einem Schritt).

---

*Ende des Berichts. Keine Dateien außer `audit_reports/2026-11-24_d12_silent_failures.md` wurden im Rahmen dieses Audits verändert.*
