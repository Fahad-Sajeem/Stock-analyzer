# Weekly backup wrapper (Windows). Invoked by "StockAnalyzerBackup" (Sun 10:00).
# Verified local snapshot; on Oracle use scripts/run_backup.sh instead (adds the
# Object Storage offsite push).
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
New-Item -ItemType Directory -Force -Path (Join-Path $root 'logs') | Out-Null
$log = Join-Path $root ("logs\backup_" + (Get-Date -Format 'yyyyMMdd') + ".log")
$env:PYTHONUTF8 = '1'

"=== backup START $(Get-Date -Format o) ===" | Out-File -FilePath $log -Append -Encoding utf8
& cmd /c "`"$(Join-Path $root '.venv\Scripts\analyzer.exe')`" backup --keep 4 >> `"$log`" 2>&1"
$code = $LASTEXITCODE
"=== backup END exit=$code $(Get-Date -Format o) ===" | Out-File -FilePath $log -Append -Encoding utf8
exit $code
