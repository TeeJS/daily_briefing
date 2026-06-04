#Requires -RunAsAdministrator
# create_outlook_task.ps1
# Creates (or replaces) the Daily Briefing Prefetch Outlook scheduled task.
# Runs scripts/prefetch_outlook.py at 5:45 AM daily -- 15 min before the
# Unraid briefing container fires at 6:00 AM.
#
# Interactive-only mode: task runs in the logged-on desktop session so it can
# reach Outlook via COM. No password needed -- machine is on 24/7 anyway.
#
# Usage (elevated PowerShell):
#   cd D:\Github\daily_briefing
#   .\scripts\create_outlook_task.ps1

$ErrorActionPreference = 'Stop'

$taskName  = 'Daily Briefing - Prefetch Outlook'
$taskDesc  = 'Pre-fetches unread Outlook inbox items for the daily briefing. Runs at 5:45 AM so the Unraid container (6:00 AM) has fresh data.'
$python    = 'D:\Github\daily_briefing\.venv\Scripts\python.exe'
$scriptArg = 'D:\Github\daily_briefing\scripts\prefetch_outlook.py'
$workDir   = 'D:\Github\daily_briefing'

Write-Host ''
Write-Host '=== Create Task: Daily Briefing - Prefetch Outlook ===' -ForegroundColor Cyan
Write-Host ''

# Pre-flight: confirm the venv and script exist before touching Task Scheduler
foreach ($path in @($python, $scriptArg)) {
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "[STOP] Not found: $path" -ForegroundColor Red
        Write-Host '       Confirm the venv exists and pip install pywin32 has been run.' -ForegroundColor Yellow
        exit 1
    }
}
Write-Host '  Pre-flight: python and script found.' -ForegroundColor Green

$logFile = 'D:\Github\daily_briefing\logs\prefetch_outlook.log'

# Run via powershell.exe so Out-File -Append captures stdout+stderr to a log.
# This matches the pattern used by other working Python scheduled tasks on this machine.
$psCmd  = "& '$python' '$scriptArg' 2>&1 | Out-File -Append '$logFile'"
$action = New-ScheduledTaskAction `
    -Execute          'powershell.exe' `
    -Argument         "-NonInteractive -Command `"$psCmd`"" `
    -WorkingDirectory $workDir

# Trigger: daily at 5:45 AM
$trigger = New-ScheduledTaskTrigger -Daily -At '05:45'

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances  IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries     = $false

# Register -- no -Password means interactive-only (runs in the logged-on session).
# This is required for COM access to Outlook.exe which lives on the desktop.
Write-Host '  Registering task...' -ForegroundColor Cyan
Register-ScheduledTask `
    -TaskName    $taskName `
    -Description $taskDesc `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -User        "$env:USERDOMAIN\$env:USERNAME" `
    -Force | Out-Null
Write-Host '  Registered.' -ForegroundColor Green

# Smoke test: run it now and wait up to 90 seconds for completion
Write-Host ''
Write-Host '  Running task once to verify...' -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName

$timeout = 90
$elapsed = 0
do {
    Start-Sleep -Seconds 2
    $elapsed += 2
    $state = (Get-ScheduledTask -TaskName $taskName).State
} while ($state -eq 'Running' -and $elapsed -lt $timeout)

$info = Get-ScheduledTaskInfo -TaskName $taskName
$rc   = $info.LastTaskResult

Write-Host ''
if ($rc -eq 0) {
    Write-Host '=== Success ===' -ForegroundColor Green
    Write-Host '  Task completed (exit 0).'
    Write-Host "  Next run: $($info.NextRunTime)"
} else {
    Write-Host "=== Warning - exit code $rc ===" -ForegroundColor Yellow
    Write-Host '  Check Task Scheduler History tab for details.'
}
Write-Host ''
