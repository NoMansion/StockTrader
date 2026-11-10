# Heartbeat for an external uptime monitor (e.g. healthchecks.io). Run every 10 min from Task Scheduler:
#   schtasks /create /tn "StockTrader Heartbeat" /sc minute /mo 10 /f /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File E:\Coding\StockTrader\scripts\heartbeat.ps1"
# Put the check's ping URL in .env as HEALTHCHECK_URL=https://hc-ping.com/<uuid>  (never commit .env).
# If the PC goes offline, sleeps, or the task stops, the monitor stops receiving pings and emails/pushes you.
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { exit 0 }
$url = $null
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*HEALTHCHECK_URL\s*=\s*(.+?)\s*$') { $url = $Matches[1].Trim('"').Trim("'") }
}
if (-not $url) { exit 0 }

# Short status body (shown in the monitor's log): sweep queue depth, worker count, last daily-job line.
$sweep = "C:\Users\farmp\AppData\Local\Temp\claude\958ad0923145ce5e\d9f51536-0ead-4c48-b142-bfe57c399e1f\scratchpad\sweep"
$status = @()
if (Test-Path $sweep) {
    $q = (Get-ChildItem "$sweep\queue" -Filter *.json -ErrorAction SilentlyContinue).Count
    $r = (Get-ChildItem "$sweep\running" -Filter *.json -ErrorAction SilentlyContinue).Count
    $d = (Get-ChildItem "$sweep\results" -Filter *.json -ErrorAction SilentlyContinue).Count
    $status += "sweep queue=$q running=$r results=$d"
}
$workers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'sweep_worker' }).Count
$status += "workers=$workers"
$log = Join-Path $root "data\run_daily.log"
if (Test-Path $log) { $status += ("daily: " + ((Get-Content $log -Tail 1) -join '')) }
$body = ($status -join " | ")
try {
    Invoke-RestMethod -Method Post -Uri $url -Body $body -TimeoutSec 20 -ErrorAction Stop | Out-Null
} catch {
    # offline or monitor unreachable: nothing to do locally; the monitor notices the missing ping
}
