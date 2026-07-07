# Intraday position-watch wrapper. Invoked by the "StockAnalyzerWatch" scheduled
# task every 15 minutes during market hours; exits instantly outside them.
# Appends to one log per day: logs/watch_YYYYMMDD.log
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
New-Item -ItemType Directory -Force -Path (Join-Path $root 'logs') | Out-Null

$log = Join-Path $root ("logs\watch_" + (Get-Date -Format 'yyyyMMdd') + ".log")
$analyzer = Join-Path $root '.venv\Scripts\analyzer.exe'
$env:PYTHONUTF8 = '1'

"--- watch $(Get-Date -Format 'HH:mm:ss') ---" | Out-File -FilePath $log -Append -Encoding utf8
& cmd /c "`"$analyzer`" watch >> `"$log`" 2>&1"

# Prune watch logs older than 60 days.
Get-ChildItem (Join-Path $root 'logs') -Filter 'watch_*.log' |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-60) } |
  Remove-Item -Force -ErrorAction SilentlyContinue
exit $LASTEXITCODE
