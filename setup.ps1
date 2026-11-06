# quant-starter first-session setup for Windows.
# Run from the project folder in PowerShell:
#     Set-ExecutionPolicy -Scope Process Bypass; .\setup.ps1
# Steps: venv -> install -> tests -> free yfinance smoke backtest.
# Then (with Norgate Data Updater running): .\.venv\Scripts\python scripts\norgate_smoke.py

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "`n[1/4] Python virtual environment" -ForegroundColor Cyan
# Pin a supported interpreter: the bare "python" on this PC resolves to 3.7,
# which cannot install pandas>=2 / streamlit>=1.35. Use the py launcher.
$pyVersion = "3.12"
if (-not (Test-Path ".venv")) { py -$pyVersion -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip

Write-Host "`n[2/4] Installing requirements (a few minutes the first time)" -ForegroundColor Cyan
& $py -m pip install --quiet -r requirements.txt

Write-Host "`n[3/4] Running tests (39 should pass)" -ForegroundColor Cyan
& $py -m pytest -q

Write-Host "`n[4/4] Free smoke backtest on yfinance data (no Norgate needed)" -ForegroundColor Cyan
& $py scripts\fetch_data.py --provider yfinance --universe static
& $py scripts\run_backtest.py --provider yfinance --universe static --no-tune

Write-Host "`nDone. Next:" -ForegroundColor Green
Write-Host "  - Start Norgate Data Updater, then:  $py scripts\norgate_smoke.py"
Write-Host "  - Real data + backtest:               $py scripts\fetch_data.py ; $py scripts\run_backtest.py"
Write-Host "  - First ML run:                       $py scripts\run_backtest.py --model lgbm"
Write-Host "  - Dashboard:                          $py -m streamlit run dashboard\app.py"
