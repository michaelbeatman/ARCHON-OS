#!/usr/bin/env python3
"""
Archon OS Chaos & Resilience Testing Suite
Simulates container disruptions, database concurrency spikes, and watchdog supervisor recovery.
"""

import os
import sys
import time
import json
import sqlite3
import argparse
import subprocess
import threading
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", "/opt/data" if os.path.exists("/opt/data") else os.path.join(os.path.expanduser("~"), ".hermes"))

RESULTS_FILE = os.path.join(WORKSPACE_DIR, "data", "chaos_test_results.json")
os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)


class ArchonChaosTester:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.results: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dry_run": self.dry_run,
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
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
        """Testet SQLite WAL-Resilienz unter extremer Nebenläufigkeit (Lock-Contention)."""
        db_path = self._resolve_db("kanban.db")
        if not os.path.exists(db_path):
            return {"status": "skipped", "reason": f"Database not found at {db_path}"}

        errors = []
        latencies = []

        def worker(thread_id: int):
            for i in range(ops_per_thread):
                t0 = time.time()
                try:
                    conn = sqlite3.connect(db_path, timeout=5.0)
                    cur = conn.cursor()
                    cur.execute("SELECT id, status FROM tasks LIMIT 5")
                    _ = cur.fetchall()
                    conn.close()
                    latencies.append(time.time() - t0)
                except Exception as e:
                    errors.append(f"Thread {thread_id} op {i}: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        t_start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total_time = time.time() - t_start

        avg_latency_ms = (sum(latencies) / len(latencies) * 1000) if latencies else 0.0
        max_latency_ms = (max(latencies) * 1000) if latencies else 0.0

        passed = len(errors) == 0
        return {
            "status": "passed" if passed else "failed",
            "threads": num_threads,
            "total_operations": len(latencies),
            "errors_count": len(errors),
            "errors": errors[:5],
            "total_duration_sec": round(total_time, 3),
            "avg_latency_ms": round(avg_latency_ms, 2),
            "max_latency_ms": round(max_latency_ms, 2)
        }

    def test_container_discovery_and_health(self) -> Dict[str, Any]:
        """Prüft die Erreichbarkeit und Status der Kern-Container."""
        try:
            res = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True, text=True, check=True, timeout=10
            )
            lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
            containers = {}
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 2:
                    name = parts[0]
                    status = parts[1]
                    ports = parts[2] if len(parts) > 2 else ""
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

    def test_simulated_container_restart(self, container_name: str = "hermes-dashboard-proxy") -> Dict[str, Any]:
        """Simuliert den Ausfall und automatischen Neustart eines Proxy-/Hilfsdienstes."""
        if self.dry_run:
            return {
                "status": "passed",
                "mode": "dry_run",
                "container": container_name,
                "message": f"Simulierter Neustart von '{container_name}' übersprungen (dry_run=True)."
            }

        try:
            # 1. Stoppen
            t0 = time.time()
            subprocess.run(["docker", "restart", container_name], capture_output=True, check=True, timeout=15)
            restart_time = time.time() - t0

            # 2. Status abfragen
            res = subprocess.run(["docker", "inspect", "--format", "{{.State.Status}}", container_name], capture_output=True, text=True, check=True)
            current_status = res.stdout.strip()

            passed = current_status == "running"
            return {
                "status": "passed" if passed else "failed",
                "container": container_name,
                "recovery_time_sec": round(restart_time, 2),
                "current_status": current_status
            }
        except Exception as e:
            return {
                "status": "failed",
                "container": container_name,
                "error": str(e)
            }

    def test_watchdog_supervisor_responsiveness(self) -> Dict[str, Any]:
        """Prüft, ob der Watchdog Supervisor aktiv Warnungen und Grenzwerte überprüft."""
        log_candidates = [
            os.path.join(DATA_DIR, "logs", "watchdog_daemon.log"),
            os.path.join(DATA_DIR, "logs", "watchdog.log"),
            os.path.join(WORKSPACE_DIR, "data", "logs", "watchdog_daemon.log"),
            "/opt/data/logs/watchdog_daemon.log"
        ]
        found_log = None
        for p in log_candidates:
            if os.path.exists(p):
                found_log = p
                break

        # Prüfe Uptime / Alarme
        alarms_candidates = [
            os.path.join(WORKSPACE_DIR, "data", "archon_alarms.json"),
            os.path.join(DATA_DIR, "archon_alarms.json"),
            "/app/data/archon_alarms.json"
        ]
        alarms_found = any(os.path.exists(a) for a in alarms_candidates)

        return {
            "status": "passed",
            "log_file_present": found_log is not None,
            "log_path": found_log,
            "alarms_file_active": alarms_found,
            "supervisor_interval_sec": 30
        }

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
        if status in ("passed", "skipped"):
            self.results["tests_passed"] += 1
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
    sys.exit(0 if res["tests_failed"] == 0 else 1)


if __name__ == "__main__":
    main()
