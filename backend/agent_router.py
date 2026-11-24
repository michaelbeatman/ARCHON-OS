import os
import re
import time
import uuid
import logging
import asyncio
import threading
import random
import weakref
import json
import httpx
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime

logger = logging.getLogger("agent_router")

from backend.llm_kernel import AUTO_MODEL_MAP, finalize_llm_output

OPENROUTER_FALLBACK_CHAIN = [
    "deepseek/deepseek-chat",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openai/gpt-4o-mini"
]

BUDGET_WARN_MARKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", ".budget_warn.json")


async def _router_provider_backoff(status_code: int = 0, headers: Optional[Dict[str, str]] = None) -> None:
    """H1: Jitter-Backoff nach fehlgeschlagenem Provider-Hop im Agent-Router."""
    delay = 0.2
    if status_code == 429:
        try:
            delay = max(delay, float(dict(headers or {}).get("Retry-After", "0")))
        except (TypeError, ValueError):
            pass
    await asyncio.sleep(min(3.0, delay) * (0.75 + random.random() * 0.5))


class BudgetExceededError(RuntimeError):
    """Wird geworfen, wenn das Tagesbudget zu 100% ausgeschöpft ist und kein Override aktiv ist."""


class SilentFailureBlockedError(BudgetExceededError):
    """Agent E: Flightlog-Flags -> status=blocked, needs_human, kein Erfolg."""

    def __init__(self, run_id: str, flags: List[str]):
        self.status = "blocked"
        self.needs_human = True
        self.failure_reason = "SILENT_FAILURE"
        self.run_id = run_id
        self.flags = list(flags or [])
        super().__init__(
            f"[SILENT_FAILURE] run={run_id} flags={','.join(self.flags)} — HITL erforderlich"
        )


def _audit_silent_failure(run_id: str, flags: List[str]) -> None:
    msg = f"SILENT_FAILURE im Agent-Router: run={run_id} flags={','.join(flags)}"
    logger.error("[AgentRouter] %s", msg)
    try:
        from archon.core.mission_control import mc_append_audit_sqlite
        mc_append_audit_sqlite("agent_router", msg, run_id or "_system")
    except Exception as exc:
        logger.debug("[AgentRouter] Silent-Failure-Audit fehlgeschlagen: %s", exc)
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("hitl_required", {
            "run_id": run_id, "status": "blocked",
            "failure_reason": "SILENT_FAILURE", "flags": list(flags or []),
        })
    except Exception:
        pass


def _detect_chat_silent_failure(run_id: str, final_output: str) -> List[str]:
    """Agent E: detect_silent_failures() im Chat-/Stream-Abschluss."""
    if not run_id:
        return []
    try:
        from backend.flightlog_backtester import detect_silent_failures
        report = detect_silent_failures(
            run_id, final_status="success", final_output=str(final_output or "")
        )
        flags = [str(x) for x in (report.get("flags") or [])]
        if flags:
            _audit_silent_failure(run_id, flags)
        return flags
    except Exception as exc:
        # Fail-closed: Detektor nicht auswertbar -> kein Erfolg quittieren.
        logger.error("[AgentRouter] Silent-Failure-Detektor nicht verfuegbar: %s", exc)
        flags = ["detector_unavailable"]
        _audit_silent_failure(run_id, flags)
        return flags


class RoutePolicy:
    def __init__(self, requires_high_reasoning: bool = False, max_cost_per_1k: float = 1.0, data_residency_local_only: bool = False):
        self.requires_high_reasoning = requires_high_reasoning
        self.max_cost_per_1k = max_cost_per_1k
        self.data_residency_local_only = data_residency_local_only

class AgentRouter:
    """
    Hardware Abstraction Layer (HAL) for LLM routing.
    Routes tasks dynamically, enforces Token Guard budgets, and provides automatic provider fallback.
    """
    
    def __init__(self):
        self.active_tasks: Dict[str, Any] = {}
        self._guardian_cache: Dict[str, Any] = {"ts": 0.0, "daily_budget": 2.0, "max_context_tokens": 32000}
        self._spend_cache: Dict[str, Any] = {"ts": 0.0, "spend": 0.0, "ok": False}
        # F-056/F-059: der Guard laeuft jetzt im Worker-Thread; die Caches
        # brauchen eine Sperre gegen parallele Rebuilds.
        self._guard_cache_lock = threading.Lock()
        # H12: id()-basierte Caches veralten nach GC eines Loops und halten
        # Connection-Pools ewig fest. WeakKeyDictionary wie in
        # core_dispatcher.py:321 — der Loop ist der richtige Schlüssel.
        self._http_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()

    def _enforce_token_guard(self, messages: List[Dict], provider: str, model: str, reasoning_level: str) -> tuple:
        """F-056: gesperrter Einstieg — kein paralleler Cache-Rebuild.

        D13/HIGH: Guard-Ausfall ist fail-closed `blocked`, nie Debug-Log.
        """
        with self._guard_cache_lock:
            try:
                return self._enforce_token_guard_unlocked(messages, provider, model, reasoning_level)
            except BudgetExceededError:
                raise
            except Exception as exc:
                logger.error("[AgentRouter] Token-Guard nicht auswertbar — fail-closed: %s", exc)
                raise BudgetExceededError(f"[GUARD_UNAVAILABLE]: {exc}") from exc

    # --- Token Guard: Verbrauchsmessung -------------------------------------
    # Bewusst NICHT über /api/guardian/stats: dieser Endpunkt blockiert bei
    # 24h-Abfragen den Worker. Hier wird direkt und mit hartem Zeitlimit gelesen.
    def _daily_spend_usd(self) -> tuple:
        """Summe der LLM-Kosten der letzten 24h aus allen state.db (max. 2s, read-only)."""
        now = time.time()
        if self._spend_cache.get("ok") and (now - self._spend_cache.get("ts", 0.0)) < 60.0:
            return float(self._spend_cache["spend"]), True

        import glob
        import sqlite3

        total = 0.0
        ok = False
        db_errors = 0
        deadline = now + 2.0
        dbs = []
        try:
            from archon.core.paths import HERMES_PROFILES_BASE, STATE_DB_PATH
            dbs.extend(glob.glob(os.path.join(HERMES_PROFILES_BASE, "*", "state.db")))
            dbs.append(STATE_DB_PATH)
        except Exception as exc:
            logger.debug(f"[AgentRouter] Konnte Hermes-State-DB-Pfade nicht aufloesen: {exc}")
        dbs.extend(glob.glob("/opt/data/profiles/*/state.db"))
        dbs.append("/opt/data/state.db")
        dbs.append(os.path.expanduser("~/.hermes/state.db"))
        dbs = sorted({os.path.abspath(p) for p in dbs if p and os.path.exists(p)})
        for db in dbs:
            if time.time() > deadline:
                db_errors += 1
                break
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.4)
                try:
                    row = con.execute(
                        "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM session_model_usage "
                        "WHERE COALESCE(last_seen, first_seen, 0) >= ?",
                        (now - 86400,),
                    ).fetchone()
                    if row:
                        total += float(row[0] or 0.0)
                        ok = True
                finally:
                    con.close()
            except Exception:
                db_errors += 1
                continue

        # P0-9: Frueher galt Fail-Closed nur, wenn DBs vorhanden, aber unlesbar
        # waren. Ohnestate.db (frische Installation / falscher Pfad) blieb
        # ``ok=False`` und der Budget-Check wurde komplett uebersprungen.
        if not ok and not self._budget_override():
            logger.error("[TokenGuard] Verbrauch nicht verifizierbar — Budget-Check fail-closed (Block).")
            total = float("inf")
            ok = True

        self._spend_cache = {"ts": now, "spend": total, "ok": ok}
        return total, ok

    def _budget_override(self) -> bool:
        """Notausstieg: Umgebungsvariable oder cost-budget.json -> "override": true."""
        if str(os.environ.get("ARCHON_BUDGET_OVERRIDE", "")).lower() in ("1", "true", "yes", "on"):
            return True
        cost_file = os.path.expanduser("~/.hermes/cost-budget.json")
        if not os.path.exists(cost_file):
            cost_file = "/opt/data/cost-budget.json"
        try:
            if os.path.exists(cost_file):
                with open(cost_file, "r", encoding="utf-8") as f:
                    return bool(json.load(f).get("override", False))
        except (OSError, ValueError) as exc:
            logger.warning(f"[AgentRouter] cost-budget.json Override nicht lesbar: {exc}")
        return False

    def _warn_budget_once(self, spend: float, budget: float) -> None:
        """Einmal pro Kalendertag Telegram-Warnung bei >= 80% Budget."""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            state = {}
            if os.path.exists(BUDGET_WARN_MARKER):
                with open(BUDGET_WARN_MARKER, "r", encoding="utf-8") as f:
                    state = json.load(f) or {}
            if state.get("date") == today:
                return
            import telegram_notify
            telegram_notify.send_telegram_message(
                f"⚠️ *Token Guard*: Tagesbudget zu {spend / budget * 100:.0f}% verbraucht.\n"
                f"Verbrauch: *${spend:.2f}* von *${budget:.2f}*.\n"
                f"Bei 100% werden LLM-Aufrufe blockiert."
            )
            os.makedirs(os.path.dirname(BUDGET_WARN_MARKER), exist_ok=True)
            with open(BUDGET_WARN_MARKER, "w", encoding="utf-8") as f:
                json.dump({"date": today, "spend": round(spend, 4)}, f)
        except Exception as e:
            logger.warning(f"[TokenGuard] Budget-Warnung nicht gesendet: {e}")

    def _get_shared_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._http_clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                timeout=90.0,
                limits=httpx.Limits(max_keepalive_connections=25, max_connections=100)
            )
            self._http_clients[loop] = client
        return client

    def _get_guardian_policy(self) -> Dict[str, Any]:
        now = time.time()
        if now - self._guardian_cache.get("ts", 0.0) < 15.0:
            return self._guardian_cache

        daily_budget = 2.0
        max_context_tokens = 32000
        try:
            cost_file = os.path.expanduser("~/.hermes/cost-budget.json")
            if not os.path.exists(cost_file):
                cost_file = "/opt/data/cost-budget.json"
            if os.path.exists(cost_file):
                with open(cost_file, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                    daily_budget = float(bdata.get("daily_budget", 2.0))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(f"[AgentRouter] cost-budget.json nicht lesbar, nutze Default-Budget: {exc}")

        try:
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            limits_file = os.path.join(workspace_dir, "memory", "guardian_limits.json")
            if os.path.exists(limits_file):
                with open(limits_file, "r", encoding="utf-8") as f:
                    ldata = json.load(f)
                    max_context_tokens = int(ldata.get("max_context_tokens", 32000))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(f"[AgentRouter] guardian_limits.json nicht lesbar, nutze Default: {exc}")

        current_spend, spend_ok = self._daily_spend_usd()

        cb_cfg = {}
        try:
            from backend.autonomy_settings import get_module_config
            cb_cfg = get_module_config("circuit_breaker")
        except Exception as exc:
            logger.debug(f"[AgentRouter] Circuit-Breaker-Config Fallback auf Defaults: {exc}")

        # D13/HIGH: harte Code-Invarianten — Config darf den Guard nicht
        # abschalten oder die Schwellen ueber/clampen.
        def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
            try:
                return max(low, min(high, int(value)))
            except (TypeError, ValueError):
                return default

        def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
            try:
                return max(low, min(high, float(value)))
            except (TypeError, ValueError):
                return default

        _disable_requested = not bool(cb_cfg.get("loop_detection_enabled", True))
        _disable_allowed = os.environ.get("ARCHON_ALLOW_LOOP_DETECTION_OFF", "").strip() == "1"
        _loop_enabled = True
        if _disable_requested:
            if _disable_allowed:
                _loop_enabled = False
                logger.error(
                    "[AgentRouter] LOOP_DETECTION_OFF explizit erlaubt via "
                    "ARCHON_ALLOW_LOOP_DETECTION_OFF — Audit-Event."
                )
                try:
                    from archon.core.mission_control import mc_append_audit_sqlite
                    mc_append_audit_sqlite(
                        "agent_router", "LOOP_DETECTION_OFF via ENV-Override erlaubt",
                        "_system",
                    )
                except Exception:
                    pass
            else:
                logger.error(
                    "[AgentRouter] loop_detection_enabled=False ohne ARCHON_ALLOW_LOOP_DETECTION_OFF "
                    "ignoriert — Guard bleibt fail-closed aktiv."
                )

        self._guardian_cache = {
            "ts": now,
            "daily_budget": daily_budget,
            "current_spend": current_spend,
            "spend_ok": spend_ok,
            "max_context_tokens": max_context_tokens,
            "loop_detection_enabled": _loop_enabled,
            "max_identical_turns": _clamp_int(cb_cfg.get("max_identical_turns"), 2, 10, 3),
            "jaccard_similarity_threshold": _clamp_float(
                cb_cfg.get("jaccard_similarity_threshold"), 0.5, 0.99, 0.90),
            "max_steps_per_task": _clamp_int(cb_cfg.get("max_steps_per_task"), 5, 30, 15),
            "budget_downgrade_threshold_pct": _clamp_int(
                cb_cfg.get("budget_downgrade_threshold_pct"), 50, 95, 80),
            "token_clipper_enabled": bool(cb_cfg.get("token_clipper_enabled", True))
        }
        return self._guardian_cache

    @staticmethod
    def guard_window_size(policy: Optional[Dict[str, Any]] = None) -> int:
        """HANDOFF an core_dispatcher.py: Boardroom-Slice >= max_steps+1."""
        from backend.trajectory_budget import guard_window_size as _gws
        return _gws(policy or None)

    def _compress_conversation_window(self, messages: List[Dict], max_ctx_chars: int) -> List[Dict]:
        """
        Sliding Window Memory Compression (Pillar 4 / Transient Context Compression):
        Verhindert Datenverlust bei langen Sessions (> max_context_tokens).
        Extrahiert Beschlüsse, Rollen-Aussagen und Kontext aus überlaufenden Nachrichten
        und bindet sie als kompakte Zusammenfassung dauerhaft oben im Prompt ein.
        """
        if len(messages) <= 3:
            return messages

        sys_msg = messages[0]
        recent_count = max(3, min(8, len(messages) // 3))
        recent_msgs = messages[-recent_count:]
        older_msgs = messages[1:-recent_count]

        if not older_msgs:
            return messages

        summary_lines = []
        for m in older_msgs:
            role = str(m.get("role", "unknown")).upper()
            content = str(m.get("content", "")).strip()
            if not content:
                continue
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            preview = lines[0] if lines else content[:120]
            if len(preview) > 160:
                # Audit D11: Kürzung explizit markieren — sonst verschwinden
                # Safety-/Negativ-Regeln unerkannt aus dem Kontext.
                preview = preview[:160] + f" … [GEKÜRZT: {len(preview) - 160} Zeichen]"
            summary_lines.append(f"- [{role}]: {preview}")

        # Kopf (Aufgabenstellung, frühe Regeln) + Schwanz (letzte Entscheidungen)
        if len(summary_lines) > 18:
            omitted = len(summary_lines) - 15
            kept_lines = summary_lines[:3] + [f"- [... {omitted} weitere Einträge ausgelassen ...]"] + summary_lines[-12:]
        else:
            kept_lines = summary_lines
        compact_text = (
            "### [KONSOLIDIERTER GESPRÄCHS- & ENTSCHEIDUNGSKONTEXT (AUTOMATISCH KOMPRIMIERT)]:\n"
            + "\n".join(kept_lines)
        )

        compact_msg = {
            "role": "system",
            "content": compact_text
        }

        # Erste Nutzernachricht unverändert voranstellen (Aufgabenanker), ohne aufeinanderfolgende user-Nachrichten zu erzeugen
        anchor = None
        for m in older_msgs:
            if m.get("role") == "user":
                original = str(m.get("content", ""))
                anchor_text = original[:1500]
                if len(original) > 1500:
                    anchor_text += f"\n[GEKÜRZT: {len(original) - 1500} Zeichen des ursprünglichen Aufgabenankers]"
                anchor = {"role": "user", "content": anchor_text}
                break
        if anchor and recent_msgs and recent_msgs[0].get("role") == "user":
            compact_msg["content"] = f"{compact_text}\n\n### [URSPRÜNGLICHER AUFGABENANKER]:\n{anchor['content']}"
            anchor = None
        compressed = ([sys_msg, compact_msg] + ([anchor] if anchor else []) + recent_msgs)
        total_len = sum(len(str(m.get("content", ""))) for m in compressed)
        if total_len > max_ctx_chars:
            trimmed = [sys_msg, compact_msg] + ([anchor] if anchor else [])
            insert_idx = 3 if anchor else 2
            acc = len(str(sys_msg.get("content", ""))) + len(compact_text)
            if anchor:
                acc += len(str(anchor.get("content", "")))
            dropped = 0
            stopped = False
            for m in reversed(recent_msgs):
                m_len = len(str(m.get("content", "")))
                if not stopped and (acc + m_len <= max_ctx_chars or len(trimmed) < 3):
                    trimmed.insert(insert_idx, m)
                    acc += m_len
                else:
                    # D11: keine stille Kompression — verworfene Nachrichten
                    # werden als System-Streifen sichtbar gemacht.
                    stopped = True
                    dropped += 1
            if dropped:
                trimmed.insert(insert_idx, {
                    "role": "system",
                    "content": (
                        f"[KONTEXT GEKÜRZT: {dropped} ältere Nachricht(en) entfernt — "
                        f"Vollversion bleibt im Session-Store]"
                    ),
                })
            compressed = trimmed

        return compressed


    def check_loop_or_circuit_breaker(self, messages: List[Dict], max_identical_turns: int = 3) -> Dict[str, Any]:
        """
        Pillar 1 & 6: Loop-Detection & Runaway Circuit-Breaker
        Verhindert unendliche Argumentations- oder Tool-Schleifen.
        Prüft:
        1. Identische/wiederholte Modell-Antworten oder Tool-Aufrufe
        2. Ping-Pong-Muster zwischen Agenten
        3. Überschreitung des max_steps Limits
        """
        policy = self._get_guardian_policy()
        loop_enabled = policy.get("loop_detection_enabled", True)
        if not loop_enabled:
            return {"loop_detected": False, "tripped": False}

        max_identical_turns = int(policy.get("max_identical_turns", max_identical_turns))
        jaccard_thresh = float(policy.get("jaccard_similarity_threshold", 0.90))

        if len(messages) < max_identical_turns * 2:
            return {"loop_detected": False, "tripped": False}

        # 1. Prüfe die letzten N Antworten der Assistenz/Agenten
        assistant_contents = []
        for m in reversed(messages):
            if m.get("role") in ("assistant", "agent"):
                c = str(m.get("content", "")).strip()
                if c:
                    assistant_contents.append(c)
                if len(assistant_contents) >= max_identical_turns + 1:
                    break

        if len(assistant_contents) >= max_identical_turns:
            # Exakte Wiederholung der letzten N Turns
            first = assistant_contents[0]
            if all(first == other for other in assistant_contents[1:max_identical_turns]):
                logger.error(f"[CircuitBreaker] Endlosschleife erkannt! {max_identical_turns} identische Ausgaben.")
                return {
                    "loop_detected": True,
                    "tripped": True,
                    "reason": f"Endlosschleife: Agent wiederholt exakt dieselbe Ausgabe ({max_identical_turns}-mal)."
                }

            # Semantische Wiederholung / Ping-Pong (Token-Jaccard-Ähnlichkeit > 90%)
            def _tokens(txt):
                return set(re.findall(r'\w+', txt.lower()))

            t0 = _tokens(assistant_contents[0])
            t1 = _tokens(assistant_contents[1])
            if t0 and t1:
                overlap = len(t0 & t1) / len(t0 | t1)
                if overlap > jaccard_thresh and len(t0) > 10:
                    logger.warning(f"[CircuitBreaker] Hohe semantische Redundanz ({overlap*100:.1f}%) zwischen den letzten Runden.")
                    if len(assistant_contents) > 2:
                        t2 = _tokens(assistant_contents[2])
                        if t2 and (len(t0 & t2) / len(t0 | t2) >= jaccard_thresh):
                            logger.error("[CircuitBreaker] Zirkulärer Argumentations-Kreis erkannt. Circuit Breaker ausgelöst.")
                            return {
                                "loop_detected": True,
                                "tripped": True,
                                "reason": f"Zirkuläre Konversation erkannt (Ähnlichkeit > 90% über {max_identical_turns} Runden)."
                            }

        # 2. Schrittgrenzen-Prüfung (max_steps_per_task):
        # Nur bei autonomen Agenten-Ketten (viele aufeinanderfolgende Assistant-/Tool-Schritte ohne neue User-Nachricht)
        # oder extrem langen Runs ausloesen — normale interaktive Nutzer-Chats duerfen > 15 Runden haben.
        max_steps = int(policy.get("max_steps_per_task", 15))
        trailing_agent_steps = 0
        for m in reversed(messages):
            role = (m.get("role") or "").lower()
            if role in ("assistant", "tool"):
                trailing_agent_steps += 1
            elif role == "user":
                break
        if trailing_agent_steps > max_steps:
            logger.error(f"[CircuitBreaker] Maximale autonome Schrittanzahl ({max_steps}) überschritten ({trailing_agent_steps}).")
            return {
                "loop_detected": True,
                "tripped": True,
                "reason": f"Task-Limit erreicht: {trailing_agent_steps} autonome Folgeschritte überschreiten max_steps ({max_steps})."
            }

        return {"loop_detected": False, "tripped": False}

    def _enforce_token_guard_unlocked(self, messages: List[Dict], provider: str, model: str, reasoning_level: str) -> tuple:
        policy = self._get_guardian_policy()
        # 0. Loop-Detection & Circuit-Breaker Prüfung
        cb_res = self.check_loop_or_circuit_breaker(messages)
        if cb_res.get("tripped"):
            logger.critical(f"[AgentRouter] CIRCUIT BREAKER AUSGELÖST: {cb_res.get('reason')}")
            raise BudgetExceededError(f"[CIRCUIT BREAKER]: {cb_res.get('reason')}")

        daily_budget = float(policy.get("daily_budget", 2.0) or 0.0)
        current_spend = float(policy.get("current_spend", 0.0) or 0.0)
        max_ctx_chars = max(8000, int(policy.get("max_context_tokens", 32000)) * 4)

        # 1. Context-Window Cap mit intelligenter Rolling Summarization (Sliding Window Memory Compression)
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        if total_chars > max_ctx_chars and len(messages) > 3:
            messages = self._compress_conversation_window(messages, max_ctx_chars)
        elif total_chars > max_ctx_chars and len(messages) > 2:
            trimmed = [messages[0]]
            acc = len(str(messages[0].get("content", "")))
            for m in reversed(messages[1:]):
                m_len = len(str(m.get("content", "")))
                if acc + m_len <= max_ctx_chars or len(trimmed) < 2:
                    trimmed.insert(1, m)
                    acc += m_len
                else:
                    break
            messages = trimmed

        # 1b. Dynamischer Token-Clipper (schützt kleine/lokale Modelle, Pillar 5)
        if policy.get("token_clipper_enabled", True):
            try:
                from backend.token_clipper import clip_messages_to_limit
                messages, was_clipped, tok_before, tok_after = clip_messages_to_limit(
                    messages, max_tokens=max(1000, int(policy.get("max_context_tokens", 32000)))
                )
                if was_clipped:
                    logger.info(f"[TokenClipper] {tok_before} -> {tok_after} Tokens (Limit {policy.get('max_context_tokens')})")
            except Exception as clip_err:
                logger.warning(f"[TokenClipper] nicht angewendet: {clip_err}")

        # 2. Budget-Stufenprüfung: 80% drosseln + warnen, 100% hart blockieren
        # P0-9: frueher `and spend_ok` — damit wurde bei nicht verifizierbarem
        # Verbrauch (keine state.db) der Budget-Check KOMPLETT uebersprungen.
        # Jetzt gilt: nur der explizite Override darf den Check abschalten.
        if daily_budget > 0 and not self._budget_override():
            ratio = current_spend / daily_budget
            if ratio >= 1.0:
                if self._budget_override():
                    logger.warning(
                        f"[TokenGuard] Budget überschritten (${current_spend:.2f}/${daily_budget:.2f}), "
                        f"Override aktiv — Aufruf wird zugelassen."
                    )
                else:
                    logger.error(
                        f"[TokenGuard] BLOCKIERT: ${current_spend:.2f} von ${daily_budget:.2f} verbraucht."
                    )
                    raise BudgetExceededError(
                        f"Tagesbudget ausgeschöpft: ${current_spend:.2f} von ${daily_budget:.2f} "
                        f"in den letzten 24 h. LLM-Aufrufe sind blockiert. "
                        f"Freigabe: in cost-budget.json \"override\": true setzen oder "
                        f"\"daily_budget\" erhöhen."
                    )
            else:
                downgrade_thresh = max(0.1, min(0.99, float(policy.get("budget_downgrade_threshold_pct", 80)) / 100.0))
                if ratio >= downgrade_thresh:
                    self._warn_budget_once(current_spend, daily_budget)
                    if reasoning_level in ("max", "deep", "high", "medium"):
                        logger.info(f"[TokenGuard] Budget bei {ratio*100:.0f}% (Schwelle {downgrade_thresh*100:.0f}%): Drossele Reasoning von '{reasoning_level}' auf 'low'.")
                        reasoning_level = "low"

        return messages, model, reasoning_level

    def _build_request_payload(self, messages: List[Dict], provider: str, model: str, api_keys: Dict[str, str], stream: bool = False, max_tokens: int = 4096, reasoning_level: str = "medium") -> tuple:
        target_url = "http://omniroute:20128/v1/chat/completions"
        request_headers = {"Content-Type": "application/json"}
        
        provider = provider.lower().strip()
        lvl = (reasoning_level or "medium").lower().strip()
        effort_map = {
            "off": "none",
            "none": "none",
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "max": "high",
            "deep": "high"
        }
        tokens_map = {
            "off": 0,
            "none": 0,
            "minimal": 1024,
            "low": 2048,
            "medium": 4096,
            "high": 8192,
            "max": 16384,
            "deep": 16384
        }
        or_effort = effort_map.get(lvl, "medium")
        or_tokens = tokens_map.get(lvl, 4096)
        
        if provider == "google":
            target_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            g_key = api_keys.get("GEMINI_API_KEY") or api_keys.get("GOOGLE_API_KEY") or ""
            if not g_key:
                raise ValueError("Kein Google / Gemini API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {g_key}"

        elif provider == "openrouter":
            target_url = "https://openrouter.ai/api/v1/chat/completions"
            or_key = api_keys.get("OPENROUTER_API_KEY") or ""
            if not or_key:
                raise ValueError("Kein OpenRouter API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {or_key}"
            request_headers["HTTP-Referer"] = "http://localhost:8501"
            request_headers["X-Title"] = "Archon OS"

        elif provider == "groq":
            target_url = "https://api.groq.com/openai/v1/chat/completions"
            groq_key = api_keys.get("GROQ_API_KEY") or ""
            if not groq_key:
                raise ValueError("Kein Groq API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {groq_key}"

        elif provider == "openai":
            target_url = "https://api.openai.com/v1/chat/completions"
            oa_key = api_keys.get("OPENAI_API_KEY") or ""
            if not oa_key:
                raise ValueError("Kein OpenAI API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {oa_key}"

        elif provider == "nvidia":
            target_url = "https://integrate.api.nvidia.com/v1/chat/completions"
            nv_key = api_keys.get("NVIDIA_API_KEY") or ""
            if not nv_key:
                raise ValueError("Kein NVIDIA NIM API-Key gefunden.")
            request_headers["Authorization"] = f"Bearer {nv_key}"

        elif provider == "anthropic":
            target_url = "https://api.anthropic.com/v1/messages"
            ant_key = api_keys.get("ANTHROPIC_API_KEY") or ""
            if not ant_key:
                raise ValueError("Kein Anthropic API-Key gefunden.")
            request_headers["x-api-key"] = ant_key
            request_headers["anthropic-version"] = "2023-06-01"

        elif provider == "local":
            try:
                from backend.privacy_router import get_privacy_config
                cfg = get_privacy_config()
                raw_url = cfg.get("local_llm_url", "http://127.0.0.1:11434/v1").rstrip("/")
            except Exception:
                raw_url = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:11434/v1").rstrip("/")
            target_url = f"{raw_url}/chat/completions"
            omni_key = api_keys.get("LOCAL_LLM_KEY") or ""
            if omni_key:
                request_headers["Authorization"] = f"Bearer {omni_key}"

        elif provider == "mistral":
            target_url = "https://api.mistral.ai/v1/chat/completions"
            m_key = api_keys.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY", "")
            if not m_key:
                try:
                    from backend.privacy_router import get_privacy_config
                    m_key = get_privacy_config().get("mistral_api_key", "")
                except Exception as exc:
                    logger.debug(f"[AgentRouter] Mistral-Key aus Privacy-Config nicht lesbar: {exc}")
            if not m_key:
                raise ValueError("Kein Mistral API-Key hinterlegt.")
            request_headers["Authorization"] = f"Bearer {m_key}"

        else:
            target_url = "http://omniroute:20128/v1/chat/completions"
            omni_key = api_keys.get("OMNIROUTE_API_KEY") or ""
            if omni_key:
                request_headers["Authorization"] = f"Bearer {omni_key}"

        client_payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": 0.6,
            "max_tokens": max_tokens
        }

        # Reasoning-Konfiguration
        if provider == "openrouter":
            if or_effort == "none" or or_tokens == 0:
                client_payload["reasoning"] = {"effort": "none"}
            elif model.lower().startswith("openai/o") or "/o1" in model.lower() or "/o3" in model.lower():
                client_payload["reasoning"] = {"effort": or_effort}
            else:
                client_payload["reasoning"] = {"max_tokens": or_tokens}
                if max_tokens <= or_tokens:
                    client_payload["max_tokens"] = or_tokens + 4096

        elif provider == "google":
            if lvl in ("off", "none"):
                client_payload["thinking_config"] = {"thinking_budget": 0}
            else:
                client_payload["thinking_config"] = {"thinking_budget": or_tokens}

        elif provider == "openai":
            m_low = model.lower().split("/")[-1]
            is_openai_reasoning = (
                m_low.startswith(("o1", "o3", "o4", "gpt-5"))
                and not m_low.startswith("gpt-4")
            )
            if is_openai_reasoning and lvl not in ("off", "none"):
                if lvl in ("minimal", "low"):
                    client_payload["reasoning_effort"] = "low"
                elif lvl == "medium":
                    client_payload["reasoning_effort"] = "medium"
                else:
                    client_payload["reasoning_effort"] = "high"

        if provider == "anthropic":
            sys_msg = [m["content"] for m in messages if m["role"] == "system"]
            user_msgs = [m for m in messages if m["role"] != "system"]
            client_payload = {
                "model": model,
                "messages": user_msgs,
                "stream": stream,
                "max_tokens": max_tokens
            }
            if sys_msg:
                client_payload["system"] = "\n\n".join(str(s) for s in sys_msg if s)
            m_low = model.lower()
            supports_thinking = any(tok in m_low for tok in ("claude-3-7", "claude-3.7", "claude-4", "sonnet-4", "opus-4", "haiku-4"))
            if supports_thinking and lvl not in ("off", "none"):
                ant_budget = max(1024, or_tokens)
                client_payload["thinking"] = {"type": "enabled", "budget_tokens": ant_budget}
                if max_tokens <= ant_budget:
                    client_payload["max_tokens"] = ant_budget + 4096
                
        return target_url, request_headers, client_payload

    @staticmethod
    def _run_compliance_and_classify(agent_id: str, messages: List[Dict], category: str) -> str:
        """Single Execution Gate Teil 1: EU AI Act Aktivierung + DataClassifier-Eskalation."""
        from backend.llm_egress_guard import ZeroEgressBlockedError
        sys_prompt = next(
            (str(m.get("content", "")) for m in (messages or []) if m.get("role") == "system"),
            "",
        )
        try:
            from backend.compliance_engine import compliance_engine
            chk = compliance_engine.check_activation_allowed(agent_id, system_prompt=sys_prompt)
            if not chk.get("allowed", True):
                raise ZeroEgressBlockedError(
                    chk.get("reason") or f"EU AI Act Guardrail blockiert '{agent_id}'.",
                    error_code=chk.get("error_code") or "COMPLIANCE_BLOCKED",
                )
        except ZeroEgressBlockedError:
            raise
        except Exception as exc:
            # F-041: Ein nicht auswertbarer EU-AI-Act-Gate darf NIE fall-through
            # in den LLM-Dispatch erlauben (fail-closed, analog DataClassifier).
            logger.error(f"[AgentRouter] Compliance-Check fuer '{agent_id}' fehlgeschlagen — blockiert: {exc}")
            raise ZeroEgressBlockedError(
                f"Compliance-Gate nicht verfuegbar: {exc}",
                error_code="COMPLIANCE_GATE_UNAVAILABLE",
            ) from exc

        # KRITISCH: der Aufrufer darf die Kategorie NIE abschwächen. Vorher
        # wurde der DataClassifier nur laufen gelassen, wenn `category` leer
        # war — mit category="general" ging vertraulicher Inhalt unerkannt
        # an die Cloud. Jetzt IMMER klassifizieren und die sensiblere Wahl
        # nehmen (fail-closed bei Klassifikationsfehler).
        eff_cat = (category or "").strip().lower() or "general"
        try:
            from backend.data_classifier import DataClassifier
            user_text = "\n".join(
                str(m.get("content", ""))
                for m in (messages or [])[-3:]
                if m.get("role") in ("user", "tool")
            )
            if user_text.strip():
                cls_res = DataClassifier.classify(user_text)
                if not cls_res.get("cloud_llm_allowed", True):
                    eff_cat = "confidential"
        except Exception as exc:
            logger.error(f"[AgentRouter] DataClassifier fehlgeschlagen — fail-closed: {exc}")
            eff_cat = "confidential"
        return eff_cat

    @staticmethod
    def _finalize_output_guard(raw_text: str, session_id: str, is_local_hop: bool) -> str:
        """Single Execution Gate Teil 2: PII Re-Hydration (Cloud) + Secret Masking + Output Policy Linter."""
        text = raw_text or ""
        if not text:
            return text
        if not is_local_hop:
            try:
                from backend.pii_scrubber import pii_scrubber
                rehyd = pii_scrubber.rehydrate_text(text, session_id=session_id)
                if isinstance(rehyd, dict) and "text" in rehyd:
                    text = rehyd["text"]
            except Exception as exc:
                logger.warning(f"[AgentRouter] PII-Rehydrierung fehlgeschlagen: {exc}")
        try:
            from backend.secret_masker import mask_sensitive_text
            masked, _ = mask_sensitive_text(text)
            if isinstance(masked, str):
                text = masked
        except Exception as exc:
            logger.warning(f"[AgentRouter] Secret-Masking fehlgeschlagen: {exc}")
        try:
            from backend.output_policy_linter import output_policy_linter
            linted = output_policy_linter.lint_and_clean(text)
            if isinstance(linted, dict) and linted.get("cleaned_text") is not None:
                text = linted["cleaned_text"]
        except Exception as exc:
            logger.warning(f"[AgentRouter] Output-Policy-Linter fehlgeschlagen: {exc}")
        return text

    async def _reserve_task_budget(
        self, agent_id: str, task_id: str, messages: List[Dict], model: str,
        provider: str, max_tokens: int = 4096,
    ) -> tuple:
        """D13/HIGH: taskbezogenes Budget-Gate auch im Chat-/Stream-Pfad."""
        est_in = max(100, sum(
            max(1, len(str(m.get("content") or "")) // 4) for m in (messages or [])
        ))
        est_out = max(64, min(2048, int(max_tokens or 1024) // 2))
        est_eur = 0.0
        try:
            from backend.role_budget_engine import USD_TO_EUR_RATE, budget_bank
            from backend.llm_kernel import estimate_model_cost_usd
            est_eur = round(
                float(estimate_model_cost_usd(model, est_in, est_out, provider=provider))
                * USD_TO_EUR_RATE, 6,
            )
            check = await asyncio.to_thread(
                budget_bank.reserve,
                agent_id=agent_id or "default",
                task_id=task_id or None,
                estimated_tokens=est_in + est_out,
                estimated_cost_eur=est_eur,
                node_id=f"agent-router:{agent_id}",
            )
        except Exception as exc:
            logger.error("[AgentRouter] Budget-Bank nicht verfuegbar — fail-closed: %s", exc)
            raise BudgetExceededError(f"[BUDGET_GATE_UNAVAILABLE]: {exc}") from exc
        if not check.get("allowed", False):
            raise BudgetExceededError(
                f"[TASK_BUDGET]: {check.get('error_code') or check.get('reason') or 'blocked'}"
            )
        # Trajectory-Hop zhlen, wenn der Aufrufer eine echte trajectory_id liefert.
        if str(task_id or "").startswith("traj-"):
            try:
                from backend.trajectory_budget import reserve_hop
                hop = await asyncio.to_thread(
                    reserve_hop, task_id, agent_id or "default", "llm_call"
                )
                if not hop.get("allowed", False):
                    await asyncio.to_thread(
                        budget_bank.release, check.get("reservation_id"), "trajectory_hop_blocked"
                    )
                    raise BudgetExceededError(f"[{hop.get('reason')}]: Trajectory-Cap erreicht")
            except BudgetExceededError:
                raise
            except Exception as exc:
                logger.error("[AgentRouter] Trajectory-Hop nicht reservierbar — fail-closed: %s", exc)
                raise BudgetExceededError(f"[TRAJECTORY_GATE_UNAVAILABLE]: {exc}") from exc
        return str(check.get("reservation_id") or ""), est_in + est_out, est_eur

    async def _settle_task_budget(
        self, reservation_id: str, tokens: int, eur: float,
    ) -> None:
        if not reservation_id:
            return
        try:
            from backend.role_budget_engine import budget_bank
            await asyncio.to_thread(
                budget_bank.settle, reservation_id,
                actual_tokens=int(tokens or 0), cost_eur=float(eur or 0.0),
            )
        except Exception as exc:
            logger.warning("[AgentRouter] Budget-Settle fehlgeschlagen: %s", exc)

    async def _release_task_budget(self, reservation_id: str) -> None:
        if not reservation_id:
            return
        try:
            from backend.role_budget_engine import budget_bank
            await asyncio.to_thread(budget_bank.release, reservation_id, "agent_router_final")
        except Exception as exc:
            logger.warning("[AgentRouter] Budget-Release fehlgeschlagen: %s", exc)

    async def chat_completion(
        self,
        messages: List[Dict],
        provider: str,
        model: str,
        api_keys: Dict[str, str],
        max_tokens: int = 4096,
        reasoning_level: str = "medium",
        agent_id: str = "master_chat",
        role: str = "",
        category: str = "",
        task_id: str = "",
    ) -> str:
        """D13: Budget-Gate + Flightlog-Guard + finally-release."""
        tid = str(task_id or f"agent-router:{agent_id}")
        reservation, tokens, eur = await self._reserve_task_budget(
            agent_id, tid, messages, model, provider, max_tokens
        )
        try:
            text = await self._chat_completion_unreserved(
                messages, provider, model, api_keys,
                max_tokens=max_tokens, reasoning_level=reasoning_level,
                agent_id=agent_id, role=role, category=category,
                flightlog_run_id=tid,
            )
            flags = _detect_chat_silent_failure(tid, text)
            if flags:
                raise SilentFailureBlockedError(tid, flags)
            await self._settle_task_budget(reservation, tokens, eur)
            return text
        finally:
            await self._release_task_budget(reservation)

    async def _chat_completion_unreserved(
        self,
        messages: List[Dict],
        provider: str,
        model: str,
        api_keys: Dict[str, str],
        max_tokens: int = 4096,
        reasoning_level: str = "medium",
        agent_id: str = "master_chat",
        role: str = "",
        category: str = "",
        flightlog_run_id: str = "",
    ) -> str:
        """
        Synchronous-style asynchronous chat completion via the HAL with Token Guard,
        Zero-Egress / Privacy-Router Hard-Block & SHA-256 Dispatch Audit.
        """
        from backend.llm_egress_guard import (
            ZeroEgressBlockedError,
            evaluate_and_gate_llm_dispatch,
            log_completed_llm_dispatch,
        )

        # F-056: bis zu 2 s SQLite/Glob-I/O im Worker-Thread, nicht im Loop.
        messages, model, reasoning_level = await asyncio.to_thread(
            self._enforce_token_guard, messages, provider, model, reasoning_level
        )
        category = self._run_compliance_and_classify(agent_id, messages, category)
        gate = evaluate_and_gate_llm_dispatch(
            agent_id=agent_id,
            provider=provider,
            model=model,
            messages=messages,
            role=role,
            explicit_category=category,
        )
        if gate.get("routed_to_local"):
            provider = "local"
            model = str(gate.get("model") or model)
        elif gate.get("provider"):
            provider = str(gate.get("provider"))
            model = str(gate.get("model") or model)

        prov_low = provider.lower().strip()
        if prov_low == "openrouter" and model in AUTO_MODEL_MAP:
            model = AUTO_MODEL_MAP[model]
        candidate_models = [model]
        if prov_low == "openrouter" and not gate.get("zero_egress_active"):
            for fb in OPENROUTER_FALLBACK_CHAIN:
                if fb != model and fb not in candidate_models:
                    candidate_models.append(fb)

        last_err = None
        client = self._get_shared_client()
        if True:
            for idx, m_try in enumerate(candidate_models):
                try:
                    from backend.llm_egress_guard import enforce_egress_firewall_for_url, sanitize_llm_endpoint, sanitize_outbound_llm_payload
                    hop_gate = evaluate_and_gate_llm_dispatch(
                        agent_id=agent_id,
                        provider=provider,
                        model=m_try,
                        messages=messages,
                        role=role,
                        explicit_category=category,
                    )
                    eff_provider = "local" if hop_gate.get("routed_to_local") and prov_low not in ("local", "ollama", "lmstudio", "vllm") else provider
                    eff_model = (hop_gate.get("model") or hop_gate.get("routed_model") or m_try) if hop_gate.get("routed_to_local") else m_try
                    target_url, request_headers, client_payload = self._build_request_payload(
                        messages, eff_provider, eff_model, api_keys, stream=False, max_tokens=max_tokens, reasoning_level=reasoning_level
                    )
                    enforce_egress_firewall_for_url(target_url, agent_id=agent_id)
                    _, _, ep_zone = sanitize_llm_endpoint(target_url)
                    is_local_hop = (
                        bool(hop_gate.get("routed_to_local"))
                        or ep_zone == "LOCAL_ON_PREM"
                        or (eff_provider or "").strip().lower() in ("local", "ollama", "lmstudio", "vllm")
                    )
                    hop_sid = str(flightlog_run_id or f"router-{agent_id}-{uuid.uuid4().hex[:8]}")
                    safe_payload = sanitize_outbound_llm_payload(
                        client_payload,
                        agent_id=agent_id,
                        session_id=hop_sid,
                        is_local=is_local_hop,
                    )
                    from backend.provider_circuit_breaker import provider_breaker
                    if not provider_breaker.allow(provider):
                        # A: auch der Circuit-Breaker-Skip ist ein Fehlerfall —
                        # ohne last_err wuerde die Kette still None zurueckgeben.
                        last_err = RuntimeError(f"Provider '{provider}' circuit-open")
                        logger.warning(f"[AgentRouter] Provider '{provider}' circuit-open — Fallback")
                        continue
                    active_trace_id = ""
                    try:
                        from backend.trace_context import child_span, current_trace_id, inject_headers
                        with child_span():
                            # D16/H2: NEUE Span-ID im traceparent — kein
                            # Self-Parenting. active_trace_id bleibt dieselbe
                            # Trace-ID (child_span() aendert nur die Span-ID).
                            request_headers = inject_headers(request_headers)
                            active_trace_id = current_trace_id()
                    except Exception as tr_exc:
                        logger.warning("[AgentRouter] Trace-Injektion am Provider-Hop fehlgeschlagen: %s", tr_exc)
                    try:
                        resp = await client.post(target_url, headers=request_headers, json=safe_payload)
                    except Exception:
                        provider_breaker.record_failure(provider)
                        await _router_provider_backoff()
                        raise
                    if resp.status_code in (401, 403, 404):
                        # C: Auth-/Routing-Fehler sind kein Provider-Ausfall und
                        # kein Provider-Erfolg — den Breaker-Zustand nicht antasten.
                        logger.debug(
                            "[AgentRouter] Provider '%s' antwortete %s (kein Breaker-Event)",
                            provider, resp.status_code,
                        )
                    elif resp.status_code >= 500 or resp.status_code == 429:
                        provider_breaker.record_failure(eff_provider)
                    elif 200 <= resp.status_code < 300:
                        provider_breaker.record_success(eff_provider)
                    log_completed_llm_dispatch(
                        agent_id=agent_id,
                        provider=eff_provider,
                        model=m_try,
                        target_endpoint=target_url,
                        http_status=resp.status_code,
                        data_category=hop_gate["data_category"],
                        zero_egress_active=hop_gate["zero_egress_active"],
                        trace_id=active_trace_id,
                    )
                    if resp.status_code in (429, 500, 502, 503, 504, 404) and idx < len(candidate_models) - 1:
                        logger.warning(f"[AgentRouter] Model '{m_try}' returned {resp.status_code}, falling back to '{candidate_models[idx+1]}'...")
                        await _router_provider_backoff(resp.status_code, dict(resp.headers))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if not isinstance(data, dict):
                        raise RuntimeError(f"Ungueltige LLM-Antwortstruktur von {eff_provider}/{m_try} (kein JSON-Objekt).")
                    if eff_provider == "anthropic":
                        blocks = data.get("content") or []
                        if not isinstance(blocks, list) or not blocks:
                            raise RuntimeError(f"Leere Anthropic-Antwort ohne content-Bloecke von {m_try}.")
                        raw_text = "".join(
                            b.get("text", "")
                            for b in blocks
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    else:
                        choices = data.get("choices")
                        if not isinstance(choices, list) or not choices:
                            raise RuntimeError(f"Leere LLM-Antwort ohne choices von {eff_provider}/{m_try}.")
                        msg_obj = choices[0].get("message") if isinstance(choices[0], dict) else None
                        raw_text = msg_obj.get("content") if isinstance(msg_obj, dict) else None
                    if not isinstance(raw_text, str) or not raw_text.strip():
                        raise RuntimeError(f"Leerer LLM-Antworttext von {eff_provider}/{m_try} (HTTP 200 ohne Inhalt).")
                    raw_text = self._finalize_output_guard(raw_text, hop_sid, is_local_hop)
                    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                    p_toks = int(usage.get("prompt_tokens") or usage.get("input_tokens") or max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4))
                    c_toks = int(usage.get("completion_tokens") or usage.get("output_tokens") or max(1, len(raw_text) // 4))
                    est_cost_unverified = True
                    est_cost = 0.0
                    try:
                        # R-B2 (Re-Audit D12): `estimate_cost_usd` existiert nicht —
                        # der Import schlug fehl und die Receipt enthielt dauerhaft 0.0.
                        from backend.llm_kernel import estimate_model_cost_usd
                        est_cost = float(estimate_model_cost_usd(m_try, p_toks, c_toks, provider=eff_provider))
                        est_cost_unverified = False
                    except Exception as cost_exc:
                        logger.error("[AgentRouter] Kostenberechnung fehlgeschlagen: %s", cost_exc)
                    try:
                        from backend.execution_receipt_ledger import execution_receipt_ledger
                        execution_receipt_ledger.issue_receipt(
                            task_id=hop_sid,
                            agent_role=agent_id or "router",
                            model_used=m_try,
                            prompt_tokens=p_toks,
                            completion_tokens=c_toks,
                            cost_usd=est_cost,
                            tools_invoked=["agent_router.chat_completion"],
                        )
                    except Exception as log_exc:
                        logger.warning(f"[AgentRouter] Audit-Logging (chat_completion) fehlgeschlagen: {log_exc}")
                    return raw_text
                except ZeroEgressBlockedError:
                    raise
                except Exception as e:
                    last_err = e
                    if idx < len(candidate_models) - 1:
                        logger.warning(f"[AgentRouter] Call to '{m_try}' failed ({e}), trying fallback '{candidate_models[idx+1]}'...")
                        continue
                    raise last_err
            # A: wenn jeder Kandidat per Circuit-Breaker uebersprungen wurde,
            # endet die Schleife ohne return/raise. Ein stilles None wird von
            # Konsumenten (z. B. context_help.py) als leerer Treffer gewertet.
            raise last_err or RuntimeError("all candidates circuit-open / unavailable")

    async def stream_chat_completion(
        self,
        messages: List[Dict],
        provider: str,
        model: str,
        api_keys: Dict[str, str],
        reasoning_level: str = "medium",
        agent_id: str = "master_chat",
        role: str = "",
        category: str = "",
        task_id: str = "",
    ) -> AsyncGenerator[str, None]:
        """D13: Budget-Gate + Flightlog-Guard + finally-release (Stream)."""
        tid = str(task_id or f"agent-router:{agent_id}")
        try:
            reservation, tokens, eur = await self._reserve_task_budget(
                agent_id, tid, messages, model, provider, 4096
            )
        except BudgetExceededError as budget_err:
            yield f"ERROR: [Task Budget] {budget_err}"
            return
        stream_buf: List[str] = []
        try:
            async for piece in self._stream_chat_completion_unreserved(
                messages, provider, model, api_keys,
                reasoning_level=reasoning_level, agent_id=agent_id,
                role=role, category=category, flightlog_run_id=tid,
            ):
                stream_buf.append(piece)
                yield piece
            flags = _detect_chat_silent_failure(tid, "".join(stream_buf))
            if flags:
                yield f"ERROR: [SILENT_FAILURE] status=blocked needs_human=true flags={','.join(flags)}"
                return
            await self._settle_task_budget(reservation, tokens, eur)
        finally:
            await self._release_task_budget(reservation)

    async def _stream_chat_completion_unreserved(
        self,
        messages: List[Dict],
        provider: str,
        model: str,
        api_keys: Dict[str, str],
        reasoning_level: str = "medium",
        agent_id: str = "master_chat",
        role: str = "",
        category: str = "",
        flightlog_run_id: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion via the HAL with Token Guard,
        Zero-Egress / Privacy-Router Hard-Block & SHA-256 Dispatch Audit.
        """
        from backend.llm_egress_guard import (
            ZeroEgressBlockedError,
            evaluate_and_gate_llm_dispatch,
            log_completed_llm_dispatch,
        )

        try:
            messages, model, reasoning_level = await asyncio.to_thread(
                self._enforce_token_guard, messages, provider, model, reasoning_level
            )
        except BudgetExceededError as budget_err:
            yield f"ERROR: [Token Guard] {budget_err}"
            return

        try:
            category = self._run_compliance_and_classify(agent_id, messages, category)
            gate = evaluate_and_gate_llm_dispatch(
                agent_id=agent_id,
                provider=provider,
                model=model,
                messages=messages,
                role=role,
                explicit_category=category,
            )
        except ZeroEgressBlockedError as ze_err:
            yield f"ERROR: [Zero-Egress Hard-Block] {ze_err}"
            return

        if gate.get("routed_to_local"):
            provider = "local"
            model = str(gate.get("model") or model)
        elif gate.get("provider"):
            provider = str(gate.get("provider"))
            model = str(gate.get("model") or model)

        prov_low = provider.lower().strip()
        if prov_low == "openrouter" and model in AUTO_MODEL_MAP:
            model = AUTO_MODEL_MAP[model]
        candidate_models = [model]
        if prov_low == "openrouter" and not gate.get("zero_egress_active"):
            for fb in OPENROUTER_FALLBACK_CHAIN:
                if fb != model and fb not in candidate_models:
                    candidate_models.append(fb)

        last_err = None
        for idx, m_try in enumerate(candidate_models):
            try:
                from backend.llm_egress_guard import enforce_egress_firewall_for_url, sanitize_llm_endpoint, sanitize_outbound_llm_payload
                hop_gate = evaluate_and_gate_llm_dispatch(
                    agent_id=agent_id,
                    provider=provider,
                    model=m_try,
                    messages=messages,
                    role=role,
                    explicit_category=category,
                )
                eff_provider = "local" if hop_gate.get("routed_to_local") and prov_low not in ("local", "ollama", "lmstudio", "vllm") else provider
                eff_model = (hop_gate.get("model") or hop_gate.get("routed_model") or m_try) if hop_gate.get("routed_to_local") else m_try
                target_url, request_headers, client_payload = self._build_request_payload(
                    messages, eff_provider, eff_model, api_keys, stream=True, reasoning_level=reasoning_level
                )
                enforce_egress_firewall_for_url(target_url, agent_id=agent_id)
                _, _, ep_zone = sanitize_llm_endpoint(target_url)
                is_local_hop = (
                    bool(hop_gate.get("routed_to_local"))
                    or ep_zone == "LOCAL_ON_PREM"
                    or (eff_provider or "").strip().lower() in ("local", "ollama", "lmstudio", "vllm")
                )
                hop_sid = str(flightlog_run_id or f"router-stream-{agent_id}-{uuid.uuid4().hex[:8]}")
                safe_payload = sanitize_outbound_llm_payload(
                    client_payload,
                    agent_id=agent_id,
                    session_id=hop_sid,
                    is_local=is_local_hop,
                )
            except ZeroEgressBlockedError as ze_err:
                yield f"ERROR: [Zero-Egress Hard-Block] {ze_err}"
                return
            except ValueError as ve:
                yield f"ERROR: {ve}"
                return

            try:
                client = self._get_shared_client()
                if True:
                    from backend.provider_circuit_breaker import provider_breaker
                    if not provider_breaker.allow(provider):
                        last_err = RuntimeError(f"Provider '{provider}' circuit-open")
                        logger.warning(f"[AgentRouter Stream] Provider '{provider}' circuit-open — Fallback")
                        continue
                    async with client.stream("POST", target_url, headers=request_headers, json=safe_payload) as response:
                        log_completed_llm_dispatch(
                            agent_id=agent_id,
                            provider=provider,
                            model=m_try,
                            target_endpoint=target_url,
                            http_status=response.status_code,
                            data_category=hop_gate["data_category"],
                            zero_egress_active=hop_gate["zero_egress_active"],
                        )
                        if response.status_code in (401, 403, 404):
                            # C: Auth-/Routing-Fehler zaehlen weder als Success
                            # noch als Failure (sonst wird ein downer Provider
                            # durch 404-Fallbacks kuenstlich "gesund" gemeldet).
                            logger.debug(
                                "[AgentRouter Stream] Provider '%s' antwortete %s (kein Breaker-Event)",
                                provider, response.status_code,
                            )
                        elif response.status_code >= 500 or response.status_code == 429:
                            provider_breaker.record_failure(provider)
                        else:
                            provider_breaker.record_success(provider)
                        if response.status_code != 200:
                            err_body = await response.aread()
                            if response.status_code in (429, 500, 502, 503, 504, 404) and idx < len(candidate_models) - 1:
                                logger.warning(f"[AgentRouter Stream] Model '{m_try}' returned {response.status_code}, falling back to '{candidate_models[idx+1]}'...")
                                await _router_provider_backoff(response.status_code, dict(response.headers))
                                continue
                            yield f"ERROR: {provider.capitalize()} Fehler (Status {response.status_code}): {err_body.decode('utf-8', errors='ignore')[:300]}"
                            return
                        else:
                            stream_buf = ""
                            total_chars = 0
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(data_str)
                                        piece = ""
                                        if eff_provider == "anthropic":
                                            if chunk.get("type") == "content_block_delta":
                                                delta = chunk.get("delta", {})
                                                if delta.get("type") == "text_delta":
                                                    piece = delta.get("text", "")
                                        else:
                                            choices = chunk.get("choices") or []
                                            if not choices:
                                                continue
                                            choice = choices[0] or {}
                                            delta = choice.get("delta") or {}
                                            piece = delta.get("content", "")
                                        if piece:
                                            stream_buf += piece
                                            total_chars += len(piece)
                                            # Unvollständigen [EMAIL_N] / [GESCHÜTZT...]-Tag am Pufferende zurückhalten
                                            open_idx = stream_buf.rfind("[")
                                            if open_idx != -1 and "]" not in stream_buf[open_idx:] and (len(stream_buf) - open_idx) < 32:
                                                ready = stream_buf[:open_idx]
                                                stream_buf = stream_buf[open_idx:]
                                            else:
                                                ready = stream_buf
                                                stream_buf = ""
                                            if ready:
                                                cleaned = self._finalize_output_guard(ready, hop_sid, is_local_hop)
                                                if cleaned:
                                                    yield cleaned
                                    except json.JSONDecodeError as dec_err:
                                        logger.debug(f"[AgentRouter] Ungueltiger SSE-Chunk uebersprungen: {dec_err}")
                            if stream_buf:
                                cleaned_tail = self._finalize_output_guard(stream_buf, hop_sid, is_local_hop)
                                if cleaned_tail:
                                    yield cleaned_tail
                            try:
                                from backend.execution_receipt_ledger import execution_receipt_ledger
                                execution_receipt_ledger.issue_receipt(
                                    task_id=hop_sid,
                                    agent_role=agent_id or "router",
                                    model_used=m_try,
                                    prompt_tokens=max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4),
                                    completion_tokens=max(1, total_chars // 4),
                                    cost_usd=0.0,
                                    tools_invoked=["agent_router.stream_chat_completion"],
                                )
                            except Exception as log_exc:
                                logger.debug(f"[AgentRouter] Audit-Logging (stream) fehlgeschlagen: {log_exc}")
                            return
            except Exception as e:
                last_err = e
                # B: der Half-Open-Probe muss bei Verbindungsfehlern als Failure
                # verbucht werden, sonst bleibt `probing=True` gesetzt und
                # allow() verweigert den Provider dauerhaft (gleiches Muster wie
                # im Non-Stream-Pfad bei client.post).
                try:
                    from backend.provider_circuit_breaker import provider_breaker as _stream_breaker
                    _stream_breaker.record_failure(provider)
                except Exception as _pb_err:
                    logger.debug(f"[AgentRouter Stream] Breaker-Failure-Record fehlgeschlagen: {_pb_err}")
                if idx < len(candidate_models) - 1:
                    logger.warning(f"[AgentRouter Stream] Error with '{m_try}' ({e}), falling back to '{candidate_models[idx+1]}'...")
                    continue
                logger.error(f"[AgentRouter] Stream error: {e}")
                yield f"ERROR: Verbindungsfehler zum LLM-Provider ({e})"
                return

        # A: alle Kandidaten circuit-open/uebersprungen -> nie mit einem leeren
        # Stream enden. "ERROR: " wird von chat.py als Provider-Fehler erkannt.
        logger.error(f"[AgentRouter Stream]Alle Kandidaten nicht verfuegbar: {last_err}")
        yield f"ERROR: Alle LLM-Provider nicht verfuegbar ({last_err or 'circuit-open'})"
        return

    def suspend_task(self, task_id: str) -> bool:
        if task_id in self.active_tasks and self.active_tasks[task_id]["status"] == "in_progress":
            self.active_tasks[task_id]["status"] = "suspended"
            return True
        return False

# Global Singleton Router
router_instance = AgentRouter()


def check_task_budget(task_id: str, cost_usd: float, budget_usd: float = 0.25, task_title: str = "") -> dict:
    """
    Pillar 5 / TokenGuard: Prüft das Budget eines Tasks.
    Bei 100% Überschreitung wird der Task pausiert und eine Benachrichtigung per Telegram gesendet.
    """
    cost = float(cost_usd or 0.0)
    budget = float(budget_usd or 0.25)
    title = task_title or f"Task #{task_id}"

    if cost >= budget:
        try:
            import telegram_notify
            tg_text = (
                f"⚠️ *Archon OS Task-Budget Limit erreicht*\n"
                f"Aufgabe: *{title}*\n"
                f"Verbraucht: *${cost:.3f}* von *${budget:.3f}*\n\n"
                f"Der Task wurde pausiert. Bitte Budget im Dashboard freigeben oder erhöhen."
            )
            telegram_notify.send_telegram_message(tg_text)
        except Exception as e:
            print(f"[BudgetCheck] Telegram notice error: {e}")

        return {
            "status": "budget_exhausted",
            "task_id": task_id,
            "cost_usd": cost,
            "budget_usd": budget,
            "paused": True,
            "message": "Task-Budget erschöpft. Benachrichtigung an Telegram gesendet."
        }
    elif cost >= budget * 0.8:
        return {
            "status": "budget_warning",
            "task_id": task_id,
            "cost_usd": cost,
            "budget_usd": budget,
            "paused": False,
            "recommend_model": "deepseek/deepseek-chat"
        }
    return {"status": "ok", "task_id": task_id, "cost_usd": cost, "budget_usd": budget, "paused": False}


# --- M86: Quota-, Verification- & Quality-Escalation-Fallback ---
def select_quota_and_escalation_route(
    primary_model: str,
    remaining_quota_pct: float = 100.0,
    quota_threshold_pct: float = 51.0,
    cheap_model: str = "deepseek/deepseek-chat",
    frontier_model: str = "anthropic/claude-sonnet-4",
    verification_passed: bool = True,
) -> Dict[str, Any]:
    """
    Waehlt das Zielmodell anhand von Rest-Quota (vibe-relay) und
    Verifikationsergebnis (nvidia-switchyard / calling-mom).
    """
    if not verification_passed:
        return {"model": frontier_model, "reason": "verification_escalation", "escalated": True}
    if remaining_quota_pct < quota_threshold_pct:
        return {"model": cheap_model, "reason": "quota_threshold_fallback", "escalated": False}
    return {"model": primary_model, "reason": "primary", "escalated": False}


async def chat_with_verification_escalation(
    router_instance: "AgentRouter",
    messages: List[Dict],
    provider: str,
    primary_model: str,
    api_keys: Dict[str, str],
    verifier_fn: Optional[Any] = None,
    remaining_quota_pct: float = 100.0,
    quota_threshold_pct: float = 51.0,
    cheap_model: str = "deepseek/deepseek-chat",
    frontier_model: str = "anthropic/claude-sonnet-4",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Fuehrt zuerst das ausgewaehlte (ggf. guenstige/lokale) Modell aus und
    eskaliert nur dann auf `frontier_model`, wenn `verifier_fn` False liefert.
    """
    first_pick = select_quota_and_escalation_route(
        primary_model=primary_model,
        remaining_quota_pct=remaining_quota_pct,
        quota_threshold_pct=quota_threshold_pct,
        cheap_model=cheap_model,
        frontier_model=frontier_model,
        verification_passed=True,
    )
    first_out = await router_instance.chat_completion(
        messages=messages,
        provider=provider,
        model=first_pick["model"],
        api_keys=api_keys,
        **kwargs,
    )
    passed = bool(verifier_fn(first_out)) if callable(verifier_fn) else bool((first_out or "").strip())
    if passed or first_pick["model"] == frontier_model:
        return {
            "content": first_out,
            "model_used": first_pick["model"],
            "escalated": False,
            "route_reason": first_pick["reason"],
        }

    esc_pick = select_quota_and_escalation_route(
        primary_model=primary_model,
        remaining_quota_pct=remaining_quota_pct,
        quota_threshold_pct=quota_threshold_pct,
        cheap_model=cheap_model,
        frontier_model=frontier_model,
        verification_passed=False,
    )
    esc_out = await router_instance.chat_completion(
        messages=messages,
        provider=provider,
        model=esc_pick["model"],
        api_keys=api_keys,
        **kwargs,
    )
    return {
        "content": esc_out,
        "model_used": esc_pick["model"],
        "escalated": True,
        "route_reason": esc_pick["reason"],
    }
