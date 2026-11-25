#!/usr/bin/env python3
# mypy: ignore-errors
"""
Archon OS Watchdog Daemon
Autonomous background supervisor for profile-level loop prevention and resource governance.
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    import urllib.error
    import urllib.request
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WATCHDOG] %(message)s"
)
logger = logging.getLogger("watchdog_daemon")

# 1. Harte Konfigurations-Schwellenwerte (Config-Dict)
CONFIG = {
    "MAX_TOKENS_PER_MIN": 10000,          # Verhindert Kostenexplosion
    # Audit D10: MAX_API_REQUESTS_PER_MIN war toter Code (nur Definition,
    # kein Konsument) und wurde entfernt. Harte API-/Rate-Limits erzwingt
    # role_budget_engine.check_budget_gate() im Dispatch-Hotpath — nicht
    # dieser Datei-Scan.
    "MAX_LOG_SIZE_MB": 5,                 # Indikator für schnelle Endlosschleifen
    "CHECK_INTERVAL_SEC": 30,             # Prüf-Intervall 30 Sekunden (Pillar 1)
    "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/archon-alarm"),
    "HERMES_API_BASE": os.getenv("HERMES_API_BASE", "http://localhost:8644"),
    "HERMES_DASHBOARD_BASE": os.getenv("HERMES_DASHBOARD_BASE", "http://localhost:9119"),
    "LOCAL_ARCHON_API": os.getenv("LOCAL_ARCHON_API", "http://localhost:8501")
}

# Finde aktives Log-Verzeichnis
CANDIDATE_LOG_DIRS = [
    "/opt/hermes_agent/archon_logs",
    "/opt/data/logs",
    "/app/data/logs",
    os.path.join(os.path.expanduser("~"), ".hermes", "logs"),
    os.path.join(os.getcwd(), "data", "logs"),
    os.path.join(os.getcwd(), "archon_logs")
]

LOG_DIR = None
for c_dir in CANDIDATE_LOG_DIRS:
    if os.path.exists(c_dir):
        LOG_DIR = c_dir
        break
if not LOG_DIR:
    LOG_DIR = os.path.join(os.getcwd(), "data", "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

# Alarms Storage
ALARM_FILE_CANDIDATES = [
    "/app/data/archon_alarms.json",
    os.path.join(os.getcwd(), "data", "archon_alarms.json"),
    os.path.join(os.getcwd(), "archon_alarms.json")
]
ALARMS_FILE = ALARM_FILE_CANDIDATES[0] if os.path.exists("/app/data") else ALARM_FILE_CANDIDATES[1]
os.makedirs(os.path.dirname(ALARMS_FILE), exist_ok=True)

# Audit D10: gemeinsamer Liveness-Punkt. Der Watchdog schreibt am
# Schleifenanfang einen Timestamp; main.py liest ihn fuer /livez
# (`loops.watchdog`), der externe Supervisor (archon_autoheal.py) wertet die
# Staleness. Atomar schreiben — ein Abbruch mitten in json.dump darf die
# Datei nicht korumpieren.
WATCHDOG_LIVENESS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(ALARMS_FILE)), "watchdog_liveness.json"
)
WATCHDOG_MAX_LAST_SEEN_AGE_S = max(
    60.0, float(os.environ.get("ARCHON_WATCHDOG_MAX_LAST_SEEN_AGE_S", "120"))
)


def _write_watchdog_liveness(loop_count: int, *, dead: bool = False) -> None:
    payload = {
        "last_seen": 0.0 if dead else time.time(),
        "loop_count": int(loop_count),
        "pid": os.getpid(),
        "alive": not dead,
    }
    try:
        import tempfile

        directory = os.path.dirname(os.path.abspath(WATCHDOG_LIVENESS_FILE))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, WATCHDOG_LIVENESS_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.warning("[Watchdog] Liveness-Datei nicht schreibbar: %s", exc)


def watchdog_liveness() -> Dict[str, Any]:
    """Von main.py (/livez -> loops.watchdog) und Tests gelesen.

    `last_seen=0.0` bzw. `alive=False` heisst: der Supervisor-Thread laeuft
    nicht (mehr). Fehlt die Datei vollstaendig, gilt der Watchdog als unbekannt
    (`last_seen=0.0`, `alive=False`) — fail-closed statt still gruen.
    """
    try:
        with open(WATCHDOG_LIVENESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("no dict")
        last_seen = float(data.get("last_seen", 0.0))
    except Exception:
        last_seen = 0.0
        data = {}
    age_s = round(max(0.0, time.time() - last_seen), 3) if last_seen > 0 else None
    alive = bool(last_seen > 0 and (age_s or 0) <= WATCHDOG_MAX_LAST_SEEN_AGE_S
                 and bool(data.get("alive", True)))
    return {
        "alive": alive,
        "last_seen": last_seen,
        "age_s": age_s,
        "loop_count": int(data.get("loop_count", 0)),
        "max_age_s": WATCHDOG_MAX_LAST_SEEN_AGE_S,
        "timestamp": time.time(),
    }


def watchdog_last_seen() -> float:
    """Schlanke Variante fuer /livez: epoch-Sekunden des letzten Ticks (0 = tot)."""
    return float(watchdog_liveness()["last_seen"])


class WatchdogDaemon:
    def __init__(self):
        self.file_tracker: Dict[str, int] = {}
        self.request_tracker: Dict[str, int] = {}
        self.token_tracker: Dict[str, int] = {}
        self.last_oracle_run = 0
        self.is_running = True
        self._shutdown_requested = False
        import threading as _threading
        self._stop_event = _threading.Event()
        self._thread = None
        # D10/HIGH: gemeinsames Stop-Signal fuer den spawn-Prozess. Der Child
        # bekommt dieselbe multiprocessing.Event-Instanz uebergeben; ein
        # threading.Event oder ein Flag im Parentobjekt wirkt dort NICHT.
        self._process = None
        self._mp_stop_event = None
        logger.info(f"Initialized Watchdog Daemon. Monitoring logs at: {LOG_DIR}")
        logger.info(f"Alarms file: {ALARMS_FILE}")

    def load_alarms(self) -> list:
        if os.path.exists(ALARMS_FILE):
            try:
                with open(ALARMS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except Exception:
                return []
        return []

    def save_alarm(self, profile_handle: str, reason: str, details: dict,
                   aborted_successfully: bool = True):
        alarms = self.load_alarms()
        new_alarm = {
            "id": f"alarm_{int(time.time())}_{profile_handle}",
            "timestamp": datetime.now().isoformat(),
            "agent": profile_handle,
            "profile_handle": profile_handle,
            "reason": reason,
            "details": details,
            # A: Nie "aborted" melden, wenn kein Abort-Endpunkt den Abbruch
            # bestaetigt hat — sonst luegt der Kill-Switch im Alarm-File.
            "status": "triggered_and_aborted" if aborted_successfully else "abort_failed"
        }
        alarms.insert(0, new_alarm)
        alarms = alarms[:50]  # Keep last 50 alarms
        try:
            # Atomar schreiben: ein Abbruch mitten in json.dump wuerde die
            # Alarmdatei korumpieren (frueher direkt open("w")).
            import tempfile
            os.makedirs(os.path.dirname(os.path.abspath(ALARMS_FILE)), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(ALARMS_FILE)), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(alarms, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, ALARMS_FILE)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            logger.info(f"Saved alarm record for '{profile_handle}' to {ALARMS_FILE}")
        except Exception as e:
            logger.error(f"Failed to save alarm to {ALARMS_FILE}: {e}")

    def trigger_n8n_webhook(self, profile_handle: str, reason: str, details: dict):
        webhook_url = CONFIG["N8N_WEBHOOK_URL"]
        payload = {
            "event": "archon_watchdog_alarm",
            "agent": profile_handle,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "details": details,
            "message": f"🚨 [ARCHON WATCHDOG] Agent '{profile_handle}' wurde isoliert gestoppt. Grund: {reason}"
        }
        
        logger.info(f"Sending alarm webhook to n8n ({webhook_url}) for agent '{profile_handle}'...")
        try:
            from utils.safe_http import webhook_signature_headers
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            headers.update(webhook_signature_headers(body))
            if requests:
                resp = requests.post(webhook_url, data=body, headers=headers, timeout=4)
                logger.info(f"n8n webhook response: HTTP {resp.status_code}")
            else:
                req = urllib.request.Request(
                    webhook_url,
                    data=body,
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    logger.info(f"n8n webhook response: HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"n8n Webhook unreachable ({webhook_url}): {e} (Signal registered locally in alarms.json)")

    def abort_agent_thread(self, profile_handle: str, reason: str, details: dict):
        """
        Der Profil-Level Kill-Switch:
        Bricht gezielt den Thread / Task des betroffenen Profils ab, OHNE den Container zu stoppen.
        """
        logger.warning(f"⚠️ TRIGGERING PROFILE-LEVEL KILL-SWITCH FOR AGENT: '{profile_handle}'! Reason: {reason}")
        
        # 1. Hermes Thread Abort API aufrufen
        abort_endpoints = [
            f"{CONFIG['HERMES_API_BASE']}/api/threads/abort",
            f"{CONFIG['HERMES_DASHBOARD_BASE']}/api/threads/abort",
            f"{CONFIG['HERMES_API_BASE']}/api/profiles/{profile_handle}/abort"
        ]
        
        abort_payload = {
            "profile": profile_handle,
            "profile_handle": profile_handle,
            "agent_id": profile_handle,
            "reason": reason,
            "force": True
        }
        
        from utils.safe_http import webhook_signature_headers
        abort_body = json.dumps(abort_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        abort_headers = {"Content-Type": "application/json"}
        abort_headers.update(webhook_signature_headers(abort_body))
        aborted_successfully = False
        failed_endpoints = []
        for ep in abort_endpoints:
            try:
                if requests:
                    res = requests.post(ep, data=abort_body, headers=abort_headers, timeout=3)
                    if res.status_code in [200, 204]:
                        logger.info(f"Successfully aborted thread via {ep}")
                        aborted_successfully = True
                        break
                    failed_endpoints.append(f"{ep}: HTTP {res.status_code}")
                    logger.error(f"[WATCHDOG] Abort-Endpunkt {ep} für '{profile_handle}' lehnte ab: HTTP {res.status_code}")
                else:
                    req = urllib.request.Request(
                        ep,
                        data=abort_body,
                        headers=abort_headers
                    )
                    with urllib.request.urlopen(req, timeout=3) as res:
                        if res.status in [200, 204]:
                            logger.info(f"Successfully aborted thread via {ep}")
                            aborted_successfully = True
                            break
                        failed_endpoints.append(f"{ep}: HTTP {res.status}")
                        logger.error(f"[WATCHDOG] Abort-Endpunkt {ep} für '{profile_handle}' lehnte ab: HTTP {res.status}")
            except Exception as exc:
                # A: Fehler nicht mehr still verschlucken — jeder Endpunkt
                # einzeln loggen, damit ein wirkungsloser Kill-Switch sichtbar ist.
                failed_endpoints.append(f"{ep}: {exc}")
                logger.error(f"[WATCHDOG] Abort-Endpunkt {ep} für '{profile_handle}' fehlgeschlagen: {exc}")
                continue

        alarm_details = dict(details or {})
        if failed_endpoints:
            alarm_details["failed_abort_endpoints"] = failed_endpoints
        if not aborted_successfully:
            logger.critical(
                f"🚨 [WATCHDOG] KILL-SWITCH FEHLGESCHLAGEN für Agent '{profile_handle}': "
                f"keiner der {len(abort_endpoints)} Abort-Endpunkte hat einen Abbruch bestätigt. "
                f"Fehler: {'; '.join(failed_endpoints) or 'keine Details'}"
            )

        # 2. Local State Alarm dokumentieren
        self.save_alarm(
            profile_handle, reason, alarm_details,
            aborted_successfully=aborted_successfully,
        )

        # 3. Asynchrone n8n Benachrichtigung
        self.trigger_n8n_webhook(profile_handle, reason, alarm_details)

    def scan_logs_and_metrics(self):
        """
        Analysiert Dateigrößen-Deltas und Metriken der Profile.
        """
        if not os.path.exists(LOG_DIR):
            return

        for root, _, files in os.walk(LOG_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    current_size = os.path.getsize(file_path)
                    prev_size = self.file_tracker.get(file_path, current_size)
                    self.file_tracker[file_path] = current_size

                    delta_bytes = max(0, current_size - prev_size)
                    delta_mb = delta_bytes / (1024 * 1024)

                    # Profil-Handle aus Dateiname oder Ordnerstruktur ableiten (ohne Unterstriche abzuschneiden)
                    if file in ("agent.log", "gateway.log") and os.path.basename(os.path.dirname(root)):
                        parent_name = os.path.basename(root)
                        profile_handle = (
                            os.path.basename(os.path.dirname(root))
                            if parent_name == "logs"
                            else parent_name
                        )
                    else:
                        stem = file
                        if stem.endswith(".log"):
                            stem = stem[:-4]
                        if stem.startswith("agent_"):
                            stem = stem[len("agent_"):]
                        elif stem.startswith("gateway-"):
                            stem = stem[len("gateway-"):]
                        profile_handle = stem or "unknown"

                    # 1. Prüfe Log-Wachstum (Endlosschleifen-Indikator)
                    if delta_mb >= CONFIG["MAX_LOG_SIZE_MB"]:
                        self.abort_agent_thread(
                            profile_handle=profile_handle,
                            reason=f"Log Growth Limit Exceeded ({delta_mb:.2f} MB in 60s > {CONFIG['MAX_LOG_SIZE_MB']} MB)",
                            details={"delta_mb": delta_mb, "file": file_path}
                        )

                    # 2. Prüfe Token- & API-Metriken im Logfile falls vorhanden
                    if delta_bytes > 0 and file.endswith(".log"):
                        self._inspect_recent_log_lines(file_path, profile_handle, delta_bytes)

                except Exception as e:
                    logger.debug(f"Error scanning file {file_path}: {e}")

    def _inspect_recent_log_lines(self, file_path: str, profile_handle: str, read_bytes: int):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(max(0, os.path.getsize(file_path) - read_bytes))
                chunk = f.read()

                # Audit D10: SUMME ueber alle Treffer des 60-s-Fensters —
                # der alte Blick auf [-1] liess 50 Calls a 9000 Tokens unerkannt.
                import re
                token_matches = re.findall(r'\"?total_tokens\"?:\s*(\d+)', chunk)
                if token_matches:
                    total_tokens = sum(int(x) for x in token_matches)
                    if total_tokens >= CONFIG["MAX_TOKENS_PER_MIN"]:
                        self.abort_agent_thread(
                            profile_handle=profile_handle,
                            reason=(f"Token Usage Limit Exceeded ({total_tokens} tokens "
                                    f"im Fenster >= {CONFIG['MAX_TOKENS_PER_MIN']})"),
                            details={"tokens": total_tokens, "file": file_path}
                        )
        except Exception as _exc:
            logger.debug("[watchdog_daemon] Ignorierte Ausnahme (Z.255): %s", _exc)

    def stop(self, timeout: float = 5.0) -> bool:
        """Sofortiger, joinbarer Stopp des Threads ODER des Supervisor-Prozesses.

        D10/HIGH: frueher wurden nur Flag/Event im Parent gesetzt. Der per
        ``spawn`` gestartete Supervisor lief mit einer eigenen Event-Kopie
        weiter, schrieb Liveness und konnte Alarme ausloesen. Jetzt wird das
        gemeinsame ``multiprocessing.Event`` gesetzt, gejoint und bei Bedarf
        terminate()/kill() angewendet. Rueckgabe = verifizierter Erfolg.
        """
        self._shutdown_requested = True
        self.is_running = False
        self._stop_event.set()
        if self._mp_stop_event is not None:
            try:
                self._mp_stop_event.set()
            except Exception as exc:
                logger.error("[Shutdown] Watchdog-Stop-Event nicht setzbar: %s", exc)
        ok = True

        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=timeout)
            if t.is_alive():
                ok = False
                logger.error(
                    "[Shutdown] Watchdog-Thread %s konnte nach %.1f s nicht beendet werden.",
                    t.name, timeout,
                )

        proc = self._process
        if proc is not None:
            try:
                proc.join(timeout=timeout)
                if proc.is_alive():
                    logger.warning("[Shutdown] Watchdog-Prozess reagiert nicht — terminate().")
                    proc.terminate()
                    proc.join(timeout=max(1.0, timeout / 2.0))
                if proc.is_alive():
                    logger.error("[Shutdown] Watchdog-Prozess bleibt nach terminate() aktiv — kill().")
                    proc.kill()
                    proc.join(timeout=max(1.0, timeout / 2.0))
                ok = ok and not proc.is_alive()
                if proc.is_alive():
                    logger.error(
                        "[Shutdown] Watchdog-Prozess (pid=%s) konnte NICHT beendet werden.",
                        getattr(proc, "pid", "?"),
                    )
            except Exception as exc:
                ok = False
                logger.error("[Shutdown] Watchdog-Prozess-Stopp fehlgeschlagen: %s", exc)

        # Liveness im Parent auf dead setzen, damit /livez und der externe
        # Autoheal den Supervisor sofort als beendet sehen (auch wenn der
        # Child sein eigenes finally nicht mehr ausfuehren konnte).
        try:
            loop_count = int(watchdog_liveness().get("loop_count", 0))
        except Exception:
            loop_count = 0
        _write_watchdog_liveness(loop_count, dead=True)

        if ok:
            logger.info("[Shutdown] Watchdog-Daemon gestoppt (Prozess/Thread verifiziert).")
        return ok

    def run_forever(self):
        logger.info("Watchdog supervisor loop started.")
        loop_count = 0
        try:
            while self.is_running:
                loop_count += 1
                # Audit D10: Heartbeat AM ANFANG der Schleife — auch wenn ein
                # Scan laenger dauert, bleibt der Thread als lebend sichtbar.
                _write_watchdog_liveness(loop_count)
                try:
                    self.scan_logs_and_metrics()
                except Exception as e:
                    logger.error(f"Exception during watchdog scan: {e}")

                # Oracle News Radar alle 4 Stunden autonom im separaten Daemon-Thread ausführen,
                # damit Netzwerk-I/O niemals den 30s-Watchdog-Loop blockiert (Pillar 1)
                if time.time() - self.last_oracle_run > 14400:
                    self.last_oracle_run = time.time()
                    import threading

                    def _run_oracle_bg():
                        try:
                            import oracle_news_radar
                            radar = oracle_news_radar.OracleNewsRadar()
                            radar.run_radar_cycle()
                            logger.info("Autonomous Oracle News Radar cycle executed.")
                        except Exception as oe:
                            logger.warning(f"Oracle News Radar background run failed: {oe}")

                    threading.Thread(target=_run_oracle_bg, daemon=True, name="OracleRadarBg").start()

                # Event.wait statt sleep: der Stopp wirkt sofort, nicht erst nach 30 s.
                if self._stop_event.wait(CONFIG["CHECK_INTERVAL_SEC"]):
                    break
        finally:
            # Audit D10: der Tod des Supervisors darf nicht still passieren.
            # last_seen auf 0 setzen -> /livez (loops.watchdog) und der externe
            # Autoheal sehen den Ausfall sofort als stale.
            _write_watchdog_liveness(loop_count, dead=True)
            if not self._shutdown_requested:
                logger.critical("Watchdog supervisor loop EXITED unerwartet — Supervision ist nicht mehr aktiv.")
                try:
                    from backend.metrics_collector import report_external_alert

                    report_external_alert(
                        "watchdog_thread_dead", "CRITICAL", "archon-os",
                        "Der Watchdog-Supervisor-Thread hat die Schleife unerwartet verlassen; "
                        "Loop-/Hang-Ueberwachung ist nicht mehr aktiv.",
                        active=True, title="Watchdog-Thread tot",
                    )
                except Exception as exc:
                    logger.error("[Watchdog] Alarm 'watchdog_thread_dead' konnte nicht gemeldet werden: %s", exc)


def _watchdog_process_main(stop_event=None) -> None:
    """Entry-Point für den externen Supervisor-Prozess (spawn-fähig).

    ``stop_event`` ist die vom Parent geteilte ``multiprocessing.Event``; sie
    ersetzt das lokale ``threading.Event`` des Childs, damit stop() sofort
    wirkt statt erst nach 30 Sekunden.
    """
    try:
        daemon = WatchdogDaemon()
        if stop_event is not None:
            daemon._mp_stop_event = stop_event
            daemon._stop_event = stop_event
        daemon.run_forever()
    except Exception as exc:  # pragma: no cover
        logger.error("[Watchdog] Supervisor-Prozess beendet: %s", exc)


def start_background_watchdog():
    """D10/HIGH: Supervisor als EIGENER PROZESS mit eigenem Interpreter.

    Vorher lief der 30-s-Watchdog als `daemon=True`-Thread im selben Prozess
    wie die überwachte Anwendung — bei Event-Loop-Hang/Freeze konnte er nicht
    eingreifen. Die Liveness wird über eine atomare Datei cross-process
    geteilt; der externe `archon-autoheal`-Container liest sie jetzt via
    `/livez` und restartet bei `watchdog_stale` (siehe D10-Fund 1).
    """
    import multiprocessing
    daemon = WatchdogDaemon()
    try:
        ctx = multiprocessing.get_context("spawn")
        # Gemeinsames Stop-Signal: beim spawn bekommt der Child eine eigene
        # Kopie aller Objekte — nur eine multiprocessing.Event uebersteht das.
        stop_event = ctx.Event()
        proc = ctx.Process(
            target=_watchdog_process_main,
            args=(stop_event,),
            name="ArchonWatchdogProcess",
            daemon=True,
        )
        daemon._mp_stop_event = stop_event
        daemon._process = proc
        _write_watchdog_liveness(0, dead=False)
        proc.start()
        logger.info("[Watchdog] Supervisor-Prozess gestartet (pid=%s)", getattr(proc, "pid", "?"))
        return daemon
    except Exception as exc:
        # Fallback nur, wenn die Plattform keinen Process-Spawn erlaubt.
        logger.error("[Watchdog] Prozess-Start fehlgeschlagen, Fallback Thread: %s", exc)
        import threading
        t = threading.Thread(
            target=daemon.run_forever, daemon=True, name="ArchonWatchdogThread"
        )
        daemon._thread = t
        _write_watchdog_liveness(0, dead=False)
        t.start()
        return daemon


if __name__ == "__main__":
    daemon = WatchdogDaemon()
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        logger.info("Watchdog terminated by user.")
