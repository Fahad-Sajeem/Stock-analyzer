# Observational-run wrapper for the daily EOD pipeline.
# Invoked by the "StockAnalyzerDaily" scheduled task (weekdays 19:00 IST) and
# safe to run by hand. Writes a timestamped, clean UTF-8 log per run to logs/.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
New-Item -ItemType Directory -Force -Path (Join-Path $root 'logs') | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = Join-Path $root "logs\daily_$stamp.log"
$analyzer = Join-Path $root '.venv\Scripts\analyzer.exe'

# Force Python to emit clean UTF-8; redirect via cmd so bytes pass through
# unchanged (PowerShell's native-command capture re-encodes and mangles UTF-8).
$env:PYTHONUTF8 = '1'
"=== analyzer daily START $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8
& cmd /c "`"$analyzer`" daily >> `"$log`" 2>&1"
$code = $LASTEXITCODE
"=== analyzer daily END exit=$code $(Get-Date -Format o) ===" | Out-File -FilePath $log -Append -Encoding utf8

# Prune logs older than 120 days so the observational run doesn't accumulate forever.
Get-ChildItem (Join-Path $root 'logs') -Filter 'daily_*.log' |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-120) } |
  Remove-Item -Force -ErrorAction SilentlyContinue

exit $code
