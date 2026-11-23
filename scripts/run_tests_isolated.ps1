# W6: pytest mit isoliertem Datenverzeichnis starten.
# Der ARCHON-OS-Container kann dabei WEITERLAUFEN — pytest schreibt nicht mehr
# auf ./data/*.db, sondern in ein temporäres Verzeichnis (siehe tests/conftest.py).
#
# Aufruf: powershell -ExecutionPolicy Bypass -File .\scripts\run_tests_isolated.ps1

$ErrorActionPreference = "Stop"
$env:ARCHON_TEST_DB_ISOLATION = "1"

Write-Host "[run_tests_isolated] Starte pytest mit ARCHON_TEST_DB_ISOLATION=1 ..." -ForegroundColor Cyan
python -m pytest tests/ -q
$rc = $LASTEXITCODE
Write-Host "[run_tests_isolated] pytest exit code: $rc" -ForegroundColor $(if ($rc -eq 0) { "Green" } else { "Red" })
exit $rc
