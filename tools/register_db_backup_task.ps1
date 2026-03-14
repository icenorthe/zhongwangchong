param(
    [string]$TaskName = "ZWC-PythonAnywhere-DB-Backup",
    [int]$IntervalHours = 2
)

$ErrorActionPreference = "Stop"

if ($IntervalHours -lt 1) {
    throw "IntervalHours must be at least 1."
}

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$script = Join-Path $root "tools\backup_pythonanywhere_db.py"

if (-not (Test-Path $script)) {
    throw "Missing backup script: $script"
}

$startTime = (Get-Date).AddMinutes(1).ToString("HH:mm")
$taskCommand = "`"$python`" `"$script`""
schtasks /Create `
    /TN $TaskName `
    /SC HOURLY `
    /MO $IntervalHours `
    /ST $startTime `
    /TR $taskCommand `
    /F | Out-Null

Write-Host "Scheduled task registered: $TaskName"
Write-Host "Runs every $IntervalHours hour(s)."
