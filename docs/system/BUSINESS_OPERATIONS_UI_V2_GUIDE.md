# Archon OS — Business Operations, Radar & UI v2 (Block C & D)

Technische Referenz der umgesetzten Operations-, ERP-, Audio- und UI-Meilensteine (**M25/M55, M32, M33, M37, M38, M39, M54, M62, M63, M64**).

---

## 1. Gateway, UI & Operations (Block C)
- **M32 — Telegram-Gateway v2 (`backend/telegram_gateway_v2.py`):** Konfliktfreies Session-Keying (`resolve_telegram_session_key`), Slash-Command-Routing (`parse_telegram_agent_route`), Inline-HITL-Buttons (`build_hitl_inline_keyboard`, `parse_hitl_callback`) und Edit-in-Place Live-Status (`format_live_task_status`).
- **M63 — Sidebar v2 (`static/js/sidebar_v2.js`):** Einklappbare Navigations-Sektionen mit `localStorage`-Persistenz, eingebunden in `static/index.html`.
- **M64 — Onboarding-Trigger (`static/views/system_settings_modal.html`):** Direkter `Setup-Wizard`-Button im Header des Settings-Modals (`#modal-header-onboarding-btn`).
- **M62 — Operations-Vorlagen (`backend/operations_templates.py`):** Einheitliche Registry (`list_operations_templates`) und Platzhalter-Vorschau (`preview_operations_template`) für Beleg-, Playbook- und Workflow-Vorlagen.
- **M55 / M25 — Enterprise-Kalender (`backend/enterprise_calendar.py`, `static/js/enterprise_calendar_ui.js`):** Tages-/Wochen-/Monatsraster (`build_calendar_grid`), Serientermin-Expansion (`expand_recurring_events`), Drag-&-Drop-Reschedule und Agenten-Ressourcenansicht (`group_events_by_agent`).

---

## 2. Business-Operations, ERP-Wächter & Audio/Radar (Block D)
- **M33 — Watchdog & Internet-Radar 2.0 (`backend/watchdog_radar_v2.py`):** Relevanz-Scoring (`score_signal_relevance`), SHA-256-Dubletten-Sperre (`register_signal_if_new` in `data/watchdog_v2.db`) und Auto-Fallback-Selbstheilung (`record_source_health`).
- **M38 — Vertrags-, Fristen- & Abo-Wächter (`backend/contract_deadline_watcher.py`):** 30/14-Tage-Fristen-Scan (`scan_upcoming_deadlines`) inkl. automatischem Kündigungsentwurf (`draft_cancellation_notice`).
- **M37 — Zeiterfassung & Time-to-Invoice (`backend/time_tracking_invoice.py`):** Timer (`start_timer`, `stop_timer` in `data/time_tracking.db`), Soll-/Ist-Budgetabgleich (`compute_project_budget_variance`) und ERP-Rechnungspositions-Export (`export_invoice_line_items`).
- **M39 — Lokaler Meeting- & Call-Copilot (`backend/meeting_copilot.py`):** Sprechergetrennte Transkript-Formatierung (`format_diarized_transcript`), Action-Item-Extraktion (`extract_action_items`) und CRM-Aktennotiz (`build_crm_meeting_note`).
- **M54 — Voice-to-Workflow (`backend/voice_to_workflow.py`):** 2-Stufen-Diktat-Analyse (`analyze_dictation_ambiguities` + `compile_playbook_from_spec`).

---

## 3. Sync, Verträge, Kundenportal, Worktrees & Connectoren (M40, M41, M42, M85, M87)
- **M41 — Kalender-Sync & Fokus-Blocker (`backend/calendar_sync_blocker.py`):** `parse_ics_events`, `export_ics_events`, `sync_calendar_bidirectional` und `schedule_focus_blocks`.
- **M40 — Vertrags-Diff & Redlining (`backend/contract_diff_redliner.py`):** `diff_contract_clauses` + `assess_clause_risks` (HTML-Redlining & Risiko-Keywords).
- **M42 — Kunden-Freigabe-Portal (`backend/client_approval_portal.py`):** `create_share_link`, `verify_share_access`, `submit_client_decision` in `data/client_portal.db`.
- **M85 — Best-of-N Coding-Worktrees (`backend/worktree_joust.py`):** `plan_joust_worktrees`, `create_joust_worktrees`, `score_joust_contenders`.
- **M87 — Externe Fach-Connectoren (`backend/external_connectors.py`):** Adapter für `inkly`, `local-business-leads`, `hermes-issue-sync` und `ghl-command`.
- **M88 — Optionale Spezial-Erweiterungen (`backend/special_extensions.py`):** SSH-/Slurm-Worker (`flota`/`own-compute`), approval-gesteuerte Kujo-Bridge (`kujo-hermes`), Medien-Swipe-Deck (`riah-swipe`) und Höflichkeits-Metrik (`manners-meter`).

---

## 4. Automatisierte Verifikation
- Testsuiten: `tests/test_milestones_block_cd.py`, `tests/test_milestones_41_40_42_85_87.py` und `tests/test_milestone_88.py`.
