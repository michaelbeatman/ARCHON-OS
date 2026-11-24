#!/usr/bin/env python3
"""
Archon OS Watchdog Daemon
Autonomous background supervisor for profile-level loop prevention and resource governance.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WATCHDOG] %(message)s"
)
logger = logging.getLogger("watchdog_daemon")

# 1. Harte Konfigurations-Schwellenwerte (Config-Dict)
CONFIG = {
    "MAX_TOKENS_PER_MIN": 10000,          # Verhindert Kostenexplosion
    "MAX_API_REQUESTS_PER_MIN": 50,       # Verhindert Rate-Limits
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


class WatchdogDaemon:
    def __init__(self):
        self.file_tracker: Dict[str, int] = {}
        self.request_tracker: Dict[str, int] = {}
        self.token_tracker: Dict[str, int] = {}
        self.last_oracle_run = 0
        self.is_running = True
        import threading as _threading
        self._stop_event = _threading.Event()
        self._thread = None
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

                # Suche nach Token-Counts in Outputs
                import re
                token_matches = re.findall(r'\"?total_tokens\"?:\s*(\d+)', chunk)
                if token_matches:
                    last_tokens = int(token_matches[-1])
                    if last_tokens >= CONFIG["MAX_TOKENS_PER_MIN"]:
                        self.abort_agent_thread(
                            profile_handle=profile_handle,
                            reason=f"Token Usage Limit Exceeded ({last_tokens} tokens/turn >= {CONFIG['MAX_TOKENS_PER_MIN']})",
                            details={"tokens": last_tokens, "file": file_path}
                        )
        except Exception as _exc:
            logger.debug("[watchdog_daemon] Ignorierte Ausnahme (Z.255): %s", _exc)

    def stop(self, timeout: float = 5.0) -> None:
        """Sofortiger, joinbarer Stopp (statt Flag + 30 s sleep)."""
        self.is_running = False
        self._stop_event.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=timeout)

    def run_forever(self):
        logger.info("Watchdog supervisor loop started.")
        while self.is_running:
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


def start_background_watchdog():
    import threading
    daemon = WatchdogDaemon()
    t = threading.Thread(target=daemon.run_forever, daemon=True, name="ArchonWatchdogThread")
    daemon._thread = t
    t.start()
    return daemon


if __name__ == "__main__":
    daemon = WatchdogDaemon()
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        logger.info("Watchdog terminated by user.")
