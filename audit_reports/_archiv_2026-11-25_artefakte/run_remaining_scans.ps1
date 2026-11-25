$ErrorActionPreference = 'Continue'
$out = 'audit_reports/tool_scans'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$env:ARCHON_DATA_DIR = 'C:\Users\micha\AppData\Local\Temp\opencode\archon-toolchain-remaining'

function Scan($name, $exe, $scanArgs) {
    $log = Join-Path $out "$name.txt"
    try { & $exe @scanArgs 2>&1 | Tee-Object -FilePath $log; $code = $LASTEXITCODE }
    catch { "EXCEPTION: $_" | Tee-Object -FilePath $log; $code = -1 }
    "EXIT=$code" | Tee-Object -FilePath $log -Append
    Write-Host "$name exit=$code"
}

Scan 'radon' '.venv\Scripts\radon.exe' @('cc','-a','-s','archon','backend','scripts','utils')
Scan 'import_linter' '.venv\Scripts\lint-imports.exe' @()
Scan 'detect_secrets' '.venv\Scripts\detect-secrets.exe' @('scan','--all-files')
Scan 'pip_audit' '.venv\Scripts\pip-audit.exe' @('-r','requirements.lock.txt')
Scan 'semgrep' '.venv\Scripts\semgrep.exe' @('scan','--config','p/ci','--quiet','--metrics','off','archon','backend')
Scan 'vulture' '.venv\Scripts\vulture.exe' @('archon','backend','--min-confidence','100')
Scan 'pyright' 'npx' @('--yes','pyright','--outputjson','archon','backend')
Write-Host 'REMAINING_SCANS_DONE'
