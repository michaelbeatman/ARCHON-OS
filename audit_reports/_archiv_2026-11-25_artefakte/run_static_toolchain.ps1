# Statische Analyse-Toolchain — read-only Scans, Ausgaben nach audit_reports/tool_scans/
# Kein Code wird veraendert. Produktiv-DBs werden nicht beruehrt.
$ErrorActionPreference = 'Continue'
$out = 'audit_reports/tool_scans'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$env:ARCHON_DATA_DIR = 'C:\Users\micha\AppData\Local\Temp\opencode\archon-toolchain-scan'

function Run-Scan($name, $exe, $args) {
    Write-Host "=== $name ==="
    $log = Join-Path $out "$name.txt"
    try {
        & $exe @args 2>&1 | Tee-Object -FilePath $log
        $code = $LASTEXITCODE
    } catch {
        "EXCEPTION: $_" | Tee-Object -FilePath $log
        $code = -1
    }
    "EXIT=$code" | Tee-Object -FilePath $log -Append
    Write-Host "--- $name exit=$code`n"
}

Run-Scan 'ruff' '.venv\Scripts\ruff.exe' @('check','.','--statistics','--output-format','concise')
Run-Scan 'vulture' '.venv\Scripts\vulture.exe' @('.','--min-confidence','80')
Run-Scan 'radon' '.venv\Scripts\radon.exe' @('cc','-a','-s','archon','backend','scripts','utils')
Run-Scan 'import-linter' '.venv\Scripts\lint-imports.exe' @()
Run-Scan 'detect-secrets' '.venv\Scripts\detect-secrets.exe' @('scan','--all-files')
Run-Scan 'bandit' '.venv\Scripts\bandit.exe' @('-q','-lll','-r','archon','backend','scripts','utils')
Run-Scan 'pip-audit' '.venv\Scripts\pip-audit.exe' @('-r','requirements.lock.txt')
Run-Scan 'semgrep' '.venv\Scripts\semgrep.exe' @('scan','--config','p/ci','--quiet','--metrics','off','archon','backend')
Run-Scan 'coverage' '.venv\Scripts\coverage.exe' @('run','--source=archon,backend','-m','pytest','tests/','-q','--tb=no')
Run-Scan 'coverage-report' '.venv\Scripts\coverage.exe' @('report','--skip-covered')

Write-Host 'TOOLCHAIN_SCANS_DONE'
