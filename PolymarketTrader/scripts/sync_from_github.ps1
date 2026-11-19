# Bring this folder up to date with the project as it stands on GitHub (branch claude/friendly-clarke-tf5rm4,
# folder PolymarketTrader), without touching what only exists here: data\, .venv\ and .env.
#
#     Set-ExecutionPolicy -Scope Process Bypass; .\scripts\sync_from_github.ps1
#
# It downloads the branch into a temporary folder, copies the project files over this folder, and removes the
# temporary folder. Files you changed here and that also changed on GitHub are overwritten: commit or copy your
# own edits elsewhere first. Needs git on the PATH.
param(
    [string]$Repo = "https://github.com/NoMansion/StockTrader.git",
    [string]$Branch = "claude/friendly-clarke-tf5rm4"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSScriptRoot
$tmp = Join-Path $env:TEMP ("pmt_sync_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
try {
    git clone --quiet --depth 1 --branch $Branch --single-branch $Repo $tmp
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
    $src = Join-Path $tmp "PolymarketTrader"
    if (-not (Test-Path $src)) { throw "the branch has no PolymarketTrader folder" }
    # /E all subfolders; /XD and /XF keep local-only things out of the way; robocopy exit codes under 8 are success
    robocopy $src $here /E /XD data .venv __pycache__ .pytest_cache /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }
    Write-Host "Updated $here from $Branch." -ForegroundColor Green
    Write-Host "Run .\setup.ps1 again if requirements changed, then: .venv\Scripts\python -m pytest -q"
}
finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}
