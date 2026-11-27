#!/usr/bin/env python3
"""
Archon OS Chaos & Resilience Testing Suite
Simulates container disruptions, database concurrency spikes, and watchdog supervisor recovery.
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))

# D10-H1 / D08-M6: harter Restart-Recovery-SLA. Gemessen wird jetzt die
# End-to-End-Zeit vom simulierten Ausfall (t_fail) bis zum ersten wieder
# HTTP-200-antwortenden /livez (t_recovered) — nicht mehr nur die Dauer des
# Docker-API-Aufrufs. Die Suite darf nicht "passed" melden, wenn diese Zeit
# laenger als 15 s dauert oder wenn ein Pfad nur "skipped" ist.
RESTART_SLA_S = 15.0
LIVEZ_URL = os.getenv("CHAOS_LIVEZ_URL", "http://archon-os:8501/livez").strip()
LIVEZ_POLL_INTERVAL_S = max(0.05, float(os.getenv("CHAOS_LIVEZ_POLL_INTERVAL_S", "0.5")))
LIVEZ_WAIT_TIMEOUT_S = max(RESTART_SLA_S, float(os.getenv("CHAOS_LIVEZ_WAIT_TIMEOUT_S", str(RESTART_SLA_S))))
# Kurzes SIGTERM-Fenster fuer stop+start — sonst kostet der Docker-Default
# (~10 s) allein fast das gesamte SLA-Budget. Der Proxy erlaubt `?t=<n>`.
RESTART_STOP_GRACE_S = max(1, int(os.getenv("CHAOS_RESTART_STOP_GRACE_S", "2")))

# D10-M1: der Watchdog schreibt keine Logdatei, sondern die atomare
# Liveness-Datei (watchdog_daemon.py:76-110,459-511). Evidenz ist ausschliesslich
# diese Datei; zwei Proben im Abstand > CHECK_INTERVAL_SEC (30 s) muessen einen
# erhoehten loop_count und ein frisches last_seen zeigen.
WATCHDOG_SAMPLE_INTERVAL_S = max(30.0, float(os.getenv("CHAOS_WATCHDOG_SAMPLE_INTERVAL_S", "31")))
WATCHDOG_MAX_LIVENESS_AGE_S = max(30.0, float(os.getenv("CHAOS_WATCHDOG_MAX_LIVENESS_AGE_S", "60")))
WATCHDOG_LIVENESS_CANDIDATES = (
    os.path.join(DATA_DIR, "watchdog_liveness.json"),
    os.path.join(WORKSPACE_DIR, "data", "watchdog_liveness.json"),
    "/app/data/watchdog_liveness.json",
    os.path.join(WORKSPACE_DIR, "watchdog_liveness.json"),
)

RESULTS_FILE = os.path.join(WORKSPACE_DIR, "data", "chaos_test_results.json")
os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

# Der Probe-Timeout gilt nur fuer EINEN HTTP-Poll, nicht das Gesamtfenster
# (LIVEZ_WAIT_TIMEOUT_S).
PROBE_TIMEOUT = max(1.0, float(os.getenv("CHAOS_LIVEZ_PROBE_TIMEOUT_S", "2")))


def livez_ok(url: str = LIVEZ_URL) -> bool:
    """Ein einziger /livez-Probe. Nur HTTP 200 zaehlt als 'wieder gesund'.

    503 (Event-Loop- oder Watchdog-Tot), Timeouts und ConnectionRefused sind
    bewusst ``False`` — der Aufrufer pollt weiter, bis das SLA-Fenster abgelaufen
    ist. Das ist der Produktivkonsument derselben Probe, die auch
    ``scripts/archon_autoheal.py`` verwendet.
    """
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:
            return int(response.status) == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def trigger_restart(client, container_name: str) -> None:
    """stop+start ueber den Proxy, mit kurzem SIGTERM-Fenster.

    ``DockerAdminClient.restart_container()`` ruft ``stop`` ohne ``?t`` auf;
    Docker wartet dann bis zu ~10 s. Das sprengt das 15-s-SLA-Budget. Der
    direkte Proxy-Aufruf mit ``?t=2`` ist der echte, freigegebene Pfad
    (utils/docker_client.py:_ADMIN_ALLOWED erlaubt ``stop(\\?.*)?``).
    Fuer gemockte/aeltere Clients ohne ``request()`` bleibt der Helper
    ``restart_container()`` als kompatibler Fallback erhalten.
    """
    if hasattr(client, "request"):
        client.request("POST", f"/containers/{container_name}/stop?t={RESTART_STOP_GRACE_S}", timeout=20.0)
        client.request("POST", f"/containers/{container_name}/start", timeout=20.0)
        return
    client.restart_container(container_name)


def wait_for_livez(
    clock: Callable[[], float],
    probe: Callable[[], bool],
    timeout_s: float = LIVEZ_WAIT_TIMEOUT_S,
    interval_s: float = LIVEZ_POLL_INTERVAL_S,
) -> Optional[float]:
    """Pollt bis zum ersten HTTP-200 und liefert die Uhrzeit t_recovered.

    ``None`` bedeutet: innerhalb des Fensters nie gesund geworden. Der erste
    Probe findet sofort statt (kein unnoetiges Warten bei bereits gesundem Ziel).
    """
    deadline = clock() + timeout_s
    while True:
        if probe():
            return clock()
        if clock() >= deadline:
            return None
        time.sleep(interval_s)


def find_watchdog_liveness() -> Optional[str]:
    """Findet die atomare Liveness-Datei des externen Watchdog-Prozesses."""
    for candidate in WATCHDOG_LIVENESS_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def read_watchdog_liveness(path: str, clock: Callable[[], float]) -> Dict[str, Any]:
    """Liest loop_count/last_seen/alive aus der Liveness-Datei (fail-closed)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("no dict")
        last_seen = float(data.get("last_seen", 0.0))
        loop_count = int(data.get("loop_count", 0))
    except Exception as exc:
        return {"usable": False, "error": f"unreadable: {type(exc).__name__}",
                "last_seen": 0.0, "loop_count": -1, "alive": False, "age_s": None}
    age_s = max(0.0, clock() - last_seen) if last_seen > 0 else None
    return {
        "usable": True,
        "last_seen": last_seen,
        "loop_count": loop_count,
        "alive": bool(data.get("alive", True)),
        "age_s": age_s,
        "path": path,
    }


class ArchonChaosTester:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.results: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dry_run": self.dry_run,
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_skipped": 0,
            "details": {}
        }

    def _resolve_db(self, name: str) -> str:
        candidates = [
            os.path.join(DATA_DIR, name),
            os.path.join(WORKSPACE_DIR, "data", name),
            os.path.join(os.path.expanduser("~"), ".hermes", name),
            os.path.join("/opt/data", name)
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return candidates[0]

    def test_database_concurrency(self, num_threads: int = 8, ops_per_thread: int = 50) -> Dict[str, Any]:
        """Echte WAL-Schreiblast: 8 Threads × 50 ``BEGIN IMMEDIATE``-Transaktionen.

        D10/MED: frueher wurden nur reine SELECTs auf ``./data/kanban.db``
        ausgefuehrt — kein Effekt, keine Lock-Contention, kein Nachweis.
        Jetzt: dedizierte Temp-DB (nie ``./data``), WAL + busy_timeout, echte
        INSERTs mit BEGIN IMMEDIATE/COMMIT und ``PRAGMA integrity_check``.
        """
        tmp_dir = tempfile.mkdtemp(prefix="archon_chaos_db_")
        db_path = os.path.join(tmp_dir, "chaos_concurrency.db")
        try:
            init_conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                journal_mode = str(init_conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                init_conn.execute("PRAGMA busy_timeout=5000")
                init_conn.execute(
                    "CREATE TABLE chaos_writes ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, thread INTEGER, seq INTEGER, payload TEXT)"
                )
                init_conn.commit()
            finally:
                init_conn.close()

            errors: List[str] = []
            latencies: List[float] = []
            committed = 0
            lock = threading.Lock()

            def worker(thread_id: int):
                nonlocal committed
                for i in range(ops_per_thread):
                    t0 = time.time()
                    conn = None
                    try:
                        conn = sqlite3.connect(db_path, timeout=5.0)
                        conn.execute("PRAGMA busy_timeout=5000")
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute(
                            "INSERT INTO chaos_writes (thread, seq, payload) VALUES (?, ?, ?)",
                            (thread_id, i, f"chaos-{thread_id}-{i}"),
                        )
                        conn.commit()
                        with lock:
                            committed += 1
                            latencies.append(time.time() - t0)
                    except Exception as e:
                        with lock:
                            errors.append(f"Thread {thread_id} op {i}: {e}")
                    finally:
                        if conn is not None:
                            conn.close()

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
            t_start = time.time()
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            total_time = time.time() - t_start

            integrity = "unknown"
            row_count = -1
            try:
                check_conn = sqlite3.connect(db_path, timeout=5.0)
                try:
                    integrity = str(check_conn.execute("PRAGMA integrity_check").fetchone()[0])
                    row_count = int(check_conn.execute("SELECT COUNT(*) FROM chaos_writes").fetchone()[0])
                finally:
                    check_conn.close()
            except Exception as e:
                integrity = f"error: {e}"

            expected = num_threads * ops_per_thread
            avg_latency_ms = (sum(latencies) / len(latencies) * 1000) if latencies else 0.0
            max_latency_ms = (max(latencies) * 1000) if latencies else 0.0
            passed = (
                not errors
                and committed == expected
                and row_count == expected
                and integrity == "ok"
                and journal_mode == "wal"
            )
            return {
                "status": "passed" if passed else "failed",
                "threads": num_threads,
                "ops_per_thread": ops_per_thread,
                "expected_commits": expected,
                "successful_commits": committed,
                "row_count": row_count,
                "journal_mode": journal_mode,
                "integrity_check": integrity,
                "errors_count": len(errors),
                "errors": errors[:5],
                "total_duration_sec": round(total_time, 3),
                "avg_latency_ms": round(avg_latency_ms, 2),
                "max_latency_ms": round(max_latency_ms, 2),
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_container_discovery_and_health(self) -> Dict[str, Any]:
        """Prüft die Erreichbarkeit und Status der Kern-Container über den Docker-Proxy."""
        try:
            from utils.docker_client import DockerAdminClient
            client = DockerAdminClient()
            raw = client.request("GET", "/containers/json")
            items = json.loads(raw.decode("utf-8"))
            containers = {}
            for item in items:
                names = item.get("Names") or []
                name = str(names[0]).lstrip("/") if names else str(item.get("Id", ""))[:12]
                status = str(item.get("Status") or item.get("State") or "")
                ports = item.get("Ports") or []
                containers[name] = {"status": status, "ports": ports}

            essential = ["ARCHON-OS", "hermes", "docker-socket-proxy"]
            missing = [e for e in essential if e not in containers]

            return {
                "status": "passed" if not missing else "failed",
                "running_containers_count": len(containers),
                "containers": containers,
                "missing_essential": missing
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def test_simulated_container_restart(
        self,
        container_name: str = "hermes-dashboard-proxy",
        clock: Optional[Callable[[], float]] = None,
        probe: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """Misst die echte Restart-Recovery-SLA vom Ausfall bis `/livez` 200.

        D10-H1: frueher startete die Uhr erst beim Docker-Call und ein Dry-Run
        meldete ``passed``, ohne die SLA ueberhaupt zu messen. Jetzt:

        * ``t_fail`` = Zeitpunkt unmittelbar vor dem ausgeloesten Ausfall,
        * ``t_recovered`` = erster erfolgreicher ``/livez``-200 nach dem Neustart,
        * ``passed`` nur bei ``(t_recovered - t_fail) < 15 s`` **und**
          ``running``-Status,
        * ein Dry-Run ist ``skipped`` (nie ``passed``) und macht die Suite rot.

        ``clock``/``probe`` sind Injektionspunkte fuer Regressionstests; im
        Produktivpfad sind es ``time.time`` und ``livez_ok``.
        """
        if self.dry_run:
            return {
                "status": "skipped",
                "mode": "dry_run",
                "container": container_name,
                "restart_sla_s": RESTART_SLA_S,
                "reason": "dry_run_sla_not_measurable",
                "message": (
                    f"Simulierter Neustart von '{container_name}' nicht ausgefuehrt "
                    "(dry_run=True); SLA ist nicht messbar und wird nicht als Erfolg "
                    "gewertet."
                ),
            }

        now = clock or time.time
        check = probe or (lambda: livez_ok(LIVEZ_URL))
        try:
            from utils.docker_client import DockerAdminClient
            client = DockerAdminClient()

            # t_fail ist der Ausfall — nicht der Beginn der Docker-Antwortzeit.
            t_fail = now()
            trigger_restart(client, container_name)

            info = json.loads(client.container_json(container_name).decode("utf-8"))
            current_status = str((info.get("State") or {}).get("Status") or "")

            t_recovered = wait_for_livez(now, check)
            elapsed = (t_recovered - t_fail) if t_recovered is not None else (now() - t_fail)
            sla_violation = t_recovered is None or elapsed >= RESTART_SLA_S
            passed = current_status == "running" and not sla_violation
            result = {
                "status": "passed" if passed else "failed",
                "container": container_name,
                "t_fail": round(t_fail, 3),
                "t_recovered": round(t_recovered, 3) if t_recovered is not None else None,
                "recovery_time_sec": round(elapsed, 2),
                "restart_sla_s": RESTART_SLA_S,
                "sla_violation": bool(sla_violation),
                "current_status": current_status,
                "livez_url": LIVEZ_URL,
                "measured_from": "simulated_failure_to_livez_200",
            }
            if t_recovered is None:
                result["reason"] = (
                    f"livez_not_recovered_within_{LIVEZ_WAIT_TIMEOUT_S:.0f}s "
                    f"(mindestens {elapsed:.2f}s >= {RESTART_SLA_S:.1f}s)"
                )
            elif sla_violation:
                result["reason"] = (
                    f"restart_sla_exceeded: {elapsed:.2f}s >= {RESTART_SLA_S:.1f}s"
                )
            elif current_status != "running":
                result["reason"] = f"container_not_running: {current_status!r}"
            return result
        except Exception as e:
            return {
                "status": "failed",
                "container": container_name,
                "restart_sla_s": RESTART_SLA_S,
                "error": str(e)
            }

    def test_watchdog_supervisor_responsiveness(
        self,
        sample_interval_s: Optional[float] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> Dict[str, Any]:
        """Prueft die echte Watchdog-Liveness ueber zwei Proben.

        D10-M1: der Watchdog schreibt **keine** Logdatei (logging.basicConfig
        ohne ``filename=`` in watchdog_daemon.py:22-26), sondern die atomare
        ``watchdog_liveness.json``. Der fruehere Test las eine nie entstehende
        Logdatei und war im Produktivpfad immer ``skipped`` — die Suite blieb
        trotzdem gruen. Jetzt: ``loop_count`` muss steigen, ``last_seen`` darf
        nicht zurueckgehen und darf hoechstens 60 s alt sein. Fehlende Evidenz
        ist ``failed`` (Exit 1), niemals ``skipped``.
        """
        now = clock or time.time
        interval = (
            WATCHDOG_SAMPLE_INTERVAL_S
            if sample_interval_s is None else max(0.0, float(sample_interval_s))
        )
        path = find_watchdog_liveness()
        base: Dict[str, Any] = {
            "evidence_file": "watchdog_liveness.json",
            "evidence_path": path,
            "supervisor_interval_sec": 30,
            "sample_interval_sec": interval,
            "max_age_s": WATCHDOG_MAX_LIVENESS_AGE_S,
            "alarms_file_active": any(
                os.path.exists(a) for a in (
                    os.path.join(WORKSPACE_DIR, "data", "archon_alarms.json"),
                    os.path.join(DATA_DIR, "archon_alarms.json"),
                    "/app/data/archon_alarms.json",
                )
            ),
        }
        if path is None:
            base.update({
                "status": "failed",
                "reason": "watchdog_liveness_evidence_missing",
                "first": None, "second": None,
            })
            return base

        first = read_watchdog_liveness(path, now)
        time.sleep(interval)
        second = read_watchdog_liveness(path, now)
        base["first"] = first
        base["second"] = second

        if not first.get("usable") or not second.get("usable"):
            base.update({"status": "failed", "reason": "watchdog_liveness_unreadable"})
            return base

        loop_advanced = second["loop_count"] > first["loop_count"]
        last_seen_advanced = second["last_seen"] >= first["last_seen"]
        age_s = second["age_s"]
        fresh = age_s is not None and age_s <= WATCHDOG_MAX_LIVENESS_AGE_S
        alive = bool(second["alive"])
        passed = loop_advanced and last_seen_advanced and fresh and alive
        base.update({
            "status": "passed" if passed else "failed",
            "reason": None if passed else (
                "watchdog_loop_stalled_or_stale: "
                f"loop_count {first['loop_count']}->{second['loop_count']}, "
                f"last_seen_age={age_s}s, alive={alive}"
            ),
            "loop_advanced": loop_advanced,
            "last_seen_advanced": last_seen_advanced,
            "last_seen_age_s": age_s,
        })
        return base

    def run_all(self) -> Dict[str, Any]:
        """Führt die gesamte Chaos- & Resilienz-Testsuite aus."""
        print(f"=== Starte Archon OS Chaos & Resilience Suite (dry_run={self.dry_run}) ===")

        # 1. DB Concurrency
        print("[1/4] Teste SQLite Concurrency & Lock Resilience...")
        db_res = self.test_database_concurrency(num_threads=8, ops_per_thread=50)
        self.results["details"]["db_concurrency"] = db_res
        self._record_result(db_res["status"])

        # 2. Container Health
        print("[2/4] Teste Container Discovery & Status...")
        c_res = self.test_container_discovery_and_health()
        self.results["details"]["container_health"] = c_res
        self._record_result(c_res["status"])

        # 3. Simulated Restart
        print("[3/4] Teste Container Recovery & Resilience...")
        r_res = self.test_simulated_container_restart("hermes-dashboard-proxy")
        self.results["details"]["container_restart"] = r_res
        self._record_result(r_res["status"])

        # 4. Watchdog Supervisor
        print("[4/4] Teste Watchdog Supervisor Responsiveness...")
        w_res = self.test_watchdog_supervisor_responsiveness()
        self.results["details"]["watchdog_supervisor"] = w_res
        self._record_result(w_res["status"])

        # Persist results
        try:
            with open(RESULTS_FILE, "w", encoding="utf-8") as fh:
                json.dump(self.results, fh, indent=2)
        except Exception as e:
            print(f"Warnung: Konnte {RESULTS_FILE} nicht schreiben: {e}", file=sys.stderr)

        print("\n=== Chaos Suite Ergebnis ===")
        print(f"Tests ausgeführt: {self.results['tests_run']}")
        print(f"Bestanden:        {self.results['tests_passed']}")
        print(f"Fehlgeschlagen:   {self.results['tests_failed']}")

        return self.results

    def _record_result(self, status: str):
        self.results["tests_run"] += 1
        if status == "passed":
            self.results["tests_passed"] += 1
        elif status == "skipped":
            # Audit 23.11.2026: "nicht pruefbar" darf nicht als Erfolg zaehlen.
            self.results["tests_skipped"] += 1
        else:
            self.results["tests_failed"] += 1


def main():
    parser = argparse.ArgumentParser(description="Archon OS Chaos & Resilience Tester")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Führt zerstörungsfreie Simulationen durch")
    parser.add_argument("--live", action="store_true", help="Führt echte Container-Restarts durch")
    args = parser.parse_args()

    dry_run = not args.live
    tester = ArchonChaosTester(dry_run=dry_run)
    res = tester.run_all()
    # D10-H1 / D08-M6: "nicht pruefbar" ist kein Erfolg. Ein Dry-Run und ein
    # fehlender Watchdog-Beweis muessen den CI-Gate (Exit 1) ausloesen.
    sys.exit(0 if (res["tests_failed"] == 0 and res["tests_skipped"] == 0) else 1)


if __name__ == "__main__":
    main()
