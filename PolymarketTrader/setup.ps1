# First-session setup for Windows. Run from the project folder (whatever it is called) in PowerShell:
#     Set-ExecutionPolicy -Scope Process Bypass; .\setup.ps1
# Steps: venv -> install -> tests -> offline demo. Nothing here touches the network beyond pip, and no money.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "`n[1/4] Python virtual environment" -ForegroundColor Cyan
# The bare "python" on this PC is 3.7; the SDK needs 3.10+. Use the py launcher, as the stock trader does.
$pyVersion = "3.12"
if (-not (Test-Path ".venv")) { py -$pyVersion -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip

Write-Host "`n[2/4] Installing requirements" -ForegroundColor Cyan
& $py -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
# numpy and pandas, for the backtests in research\. If they fail to install the bot still works: the research
# tests are skipped.
& $py -m pip install --quiet -r requirements-research.txt
if ($LASTEXITCODE -ne 0) { Write-Host "  (research packages not installed: backtests unavailable, the bot is unaffected)" -ForegroundColor Yellow }

Write-Host "`n[3/4] Running tests (all should pass)" -ForegroundColor Cyan
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed: do not go further until they pass" }

Write-Host "`n[4/4] Offline demo (made-up exchange, made-up forecasts)" -ForegroundColor Cyan
& $py scripts\demo_offline.py
if ($LASTEXITCODE -ne 0) { throw "offline demo failed" }

Write-Host "`nDone. Next:" -ForegroundColor Green
Write-Host "  - See which real markets pass the filters:  $py scripts\run_cycle.py --scan"
Write-Host "  - One real paper cycle (asks Claude):       $py scripts\run_cycle.py"
Write-Host "  - Where things stand:                       $py scripts\status.py"
