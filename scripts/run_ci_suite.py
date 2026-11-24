"""
scripts/run_ci_suite.py
Lokaler Runner für die vollständige Archon OS CI & E2E Test-Pipeline.
Führt die CI-Stufen lokal aus (Audit D09: Alignement mit GitHub Actions):
1. Pre-Flight Config Validator
2. Secrets Management & Credential Audit
3. Gesamte Pytest-Suite (zuvor nur in GitHub Actions)
4. Security-Guard & Router Unit-Tests
5. End-to-End Governance & Lifecycle Tests
6. Frontend Production Build (zuvor nur in GitHub Actions)
7. pip-audit & bandit (zuvor nur in GitHub Actions)
8. Docker Compose Syntax- und Ressourcenprüfung

Hinweis: der Restore-Test-Gate (CI-Job 1) bleibt CI-only, da er frische
Backup-Fixtures und einen isolierten Runner braucht.
ARCHON_TEST_DB_ISOLATION=1 wird hier gesetzt, damit nie in data/ geschrieben wird.
"""

import os
import sys
import subprocess
import time

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def run_stage(name: str, cmd: list) -> bool:
    print(f"\n{BOLD}{CYAN}=== Stufe: {name} ==={RESET}")
    print(f"{CYAN}Befehl: {' '.join(cmd)}{RESET}")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
        dur = round(time.time() - t0, 2)
        if proc.stdout:
            print(proc.stdout.strip())
        if proc.stderr and proc.returncode != 0:
            print(f"{RED}{proc.stderr.strip()}{RESET}")
        
        if proc.returncode == 0:
            print(f"{GREEN}[OK] {name} erfolgreich ({dur}s){RESET}")
            return True
        else:
            print(f"{RED}[FAIL] {name} FEHLGESCHLAGEN (Code {proc.returncode}, {dur}s){RESET}")
            return False
    except Exception as e:
        print(f"{RED}[ERROR] Fehler beim Ausfuehren von {name}: {e}{RESET}")
        return False


def main():
    py = sys.executable
    # Audit D09: lokale Läufe dürfen nie in das shared data/ schreiben.
    # conftest.py:60-64 leitet bei diesem Flag ARCHON_DATA_DIR in ein tempdir um.
    os.environ["ARCHON_TEST_DB_ISOLATION"] = "1"
    print(f"{BOLD}===================================================={RESET}")
    print(f"{BOLD}   Archon OS 2026 - Lokale CI & E2E Testsuite       {RESET}")
    print(f"{BOLD}===================================================={RESET}")

    stages = [
        ("1. Pre-Flight Konfigurationsprüfung", [py, "scripts/validate_config.py"]),
        ("2. Secrets- & Zero-Leak Audit", [py, "scripts/audit_secrets.py", "--all"]),
        ("3. Gesamte Pytest-Suite", [py, "-m", "pytest", "tests/", "-q"]),
        ("4. Security-Guard Unit-Tests", [py, "-m", "unittest", "tests/test_security_and_validation.py"]),
        ("5. Router Unit-Tests", [py, "-m", "unittest", "tests/test_jev_router.py"]),
        ("6. End-to-End Lifecycle & MCP", [py, "-m", "unittest", "tests/test_e2e_lifecycle.py"]),
        ("7. Frontend Build (Next.js)", ["npm", "--prefix", "frontend", "run", "build"]),
        ("8. pip-audit (bekannte CVEs)", [py, "-m", "pip_audit", "-r", "requirements.lock.txt"]),
        ("9. bandit (SAST, HIGH)", ["bandit", "-q", "-lll", "-r", "main.py", "core_dispatcher.py", "backend", "archon", "-x", "tests,scripts"]),
        ("10. Docker-Compose Validierung", ["docker", "compose", "config", "--quiet"])
    ]

    results = []
    overall_start = time.time()

    for name, cmd in stages:
        ok = run_stage(name, cmd)
        results.append((name, ok))
        if not ok and "--fail-fast" in sys.argv:
            print(f"\n{RED}Abbruch wegen --fail-fast{RESET}")
            break

    total_time = round(time.time() - overall_start, 2)
    print(f"\n{BOLD}===================================================={RESET}")
    print(f"{BOLD}   ZUSAMMENFASSUNG CI PIPELINE ({total_time}s)               {RESET}")
    print(f"{BOLD}===================================================={RESET}")

    all_passed = True
    for name, ok in results:
        status_str = f"{GREEN}BESTANDEN{RESET}" if ok else f"{RED}FEHLGESCHLAGEN{RESET}"
        print(f"  - {name:<38} : {status_str}")
        if not ok:
            all_passed = False

    print(f"{BOLD}===================================================={RESET}")
    if all_passed:
        print(f"{GREEN}{BOLD}[OK] Alle 10 Qualitaetstore erfolgreich bestanden. Bereit zum Deployment/Push.{RESET}\n")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}[FAIL] Mindestens ein Qualitaetstor ist fehlgeschlagen. Bitte Fehler beheben.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
