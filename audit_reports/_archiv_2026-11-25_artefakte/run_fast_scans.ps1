$ErrorActionPreference = 'Continue'
$out = 'audit_reports/tool_scans'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$env:ARCHON_DATA_DIR = 'C:\Users\micha\AppData\Local\Temp\opencode\archon-toolchain-fast'

function Scan($name, $exe, $scanArgs) {
    $log = Join-Path $out "$name.txt"
    try { & $exe @scanArgs > $log 2>&1; $code = $LASTEXITCODE }
    catch { "EXCEPTION: $_" > $log; $code = -1 }
    "EXIT=$code" >> $log
    Write-Host "$name exit=$code"
}

Scan 'detect_secrets' '.venv\Scripts\detect-secrets.exe' @('scan','--all-files')
Scan 'pip_audit' '.venv\Scripts\pip-audit.exe' @('-r','requirements.lock.txt')
Scan 'semgrep' '.venv\Scripts\semgrep.exe' @('scan','--config','p/ci','--quiet','--metrics','off','archon','backend')
Scan 'vulture' '.venv\Scripts\vulture.exe' @('archon','backend','--min-confidence','100')
Scan 'pyright' 'npx' @('--yes','pyright','--outputjson','archon','backend')
Write-Host 'FAST_SCANS_DONE'
