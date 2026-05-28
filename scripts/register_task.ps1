#Requires -Version 5.1
<#
.SYNOPSIS
  Register (or refresh) the gdoc-to-medium scheduled task. Runs the publisher
  every few minutes while the PC is on (spec section 9 — no wake, no catch-up).
.PARAMETER TaskName
  Scheduled-task name. Default: gdoc-to-medium.
.PARAMETER IntervalMinutes
  How often to run, in minutes. Default: 5.
.EXAMPLE
  .\scripts\register_task.ps1
.EXAMPLE
  .\scripts\register_task.ps1 -IntervalMinutes 10
#>
[CmdletBinding()]
param(
    [string]$TaskName = "gdoc-to-medium",
    [int]$IntervalMinutes = 5
)
$ErrorActionPreference = "Stop"

# Project root is the parent of this script's folder (scripts\..).
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Could not find $python. Create the venv first: py -3.13 -m venv .venv ; .\.venv\Scripts\pip install -e ."
}

$runner = Join-Path $PSScriptRoot "run.cmd"
if (-not (Test-Path $runner)) {
    throw "Missing $runner (it should ship alongside this script)."
}

# schtasks /SC MINUTE /MO N runs every N minutes, indefinitely, and only while the
# PC is on. /TR points at run.cmd, which cd's to the project root and appends all
# output to logs\run.log. /F refreshes an existing task. /RL LIMITED = no elevation.
& schtasks.exe /Create /TN $TaskName /TR "`"$runner`"" /SC MINUTE /MO $IntervalMinutes /RL LIMITED /F
if ($LASTEXITCODE -ne 0) {
    throw "schtasks failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Registered '$TaskName' to run every $IntervalMinutes minute(s) while the PC is on."
Write-Host "  Inspect:  Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Run now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Logs:     $projectRoot\logs\run.log"
Write-Host "  Remove:   schtasks /Delete /TN '$TaskName' /F"
