# Install (or refresh) the hidden Windows Scheduled Task that keeps the TCE
# subscription worker supervisor running.
#
#   powershell -NoProfile -File scripts\install_tce_worker_task.ps1 `
#       -SshTarget user@host -Workers 2
#
# What it registers, for the CURRENT user only (the Claude Code subscription
# login is per user, so the worker must run in this user's session):
#   - trigger 1: at logon
#   - trigger 2: every 5 minutes, forever. The supervisor holds a lock, so a
#     relaunch while it is healthy exits immediately; after a crash it recovers.
#   - action: pythonw.exe (no console window) running tce_worker_supervisor.py
#
# The private access key is NOT an argument. Put it in
# %USERPROFILE%\.tce-worker\private_access_key before running this (the
# supervisor reads it at start and passes it to workers through their
# environment only).
#
# Kill switch:  New-Item "$env:USERPROFILE\.tce-worker\state\STOP" -ItemType File
#               (then Disable-ScheduledTask, or the next 5-minute relaunch
#               sees STOP and exits again; delete STOP to resume)
# Remove:       Unregister-ScheduledTask -TaskName "TCE Subscription Worker" -Confirm:$false
# Status:       Get-Content "$env:USERPROFILE\.tce-worker\state\status.json"
param(
    [Parameter(Mandatory = $true)][string]$SshTarget,
    [int]$Workers = 1,
    [string]$SshBin = "",
    [string]$TaskName = "TCE Subscription Worker"
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
$script = Join-Path $repo "scripts\tce_worker_supervisor.py"
if (-not (Test-Path $pythonw)) { throw "pythonw not found at $pythonw (create the .venv first)" }
if (-not $SshBin) { $SshBin = (Get-Command ssh -ErrorAction Stop).Source }

$keyFile = Join-Path $env:USERPROFILE ".tce-worker\private_access_key"
if (-not (Test-Path $keyFile)) { throw "missing $keyFile - the workers cannot lease without it" }

$taskArgs = "`"$script`" --ssh-target $SshTarget --ssh-bin `"$SshBin`" --workers $Workers"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $taskArgs -WorkingDirectory $repo

$user = "$env:USERDOMAIN\$env:USERNAME"
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($atLogon, $every5) -Settings $settings -Principal $principal `
    -Description "Team Content Engine: keeps the Claude subscription LLM worker and its SSH tunnel running. Kill switch: create %USERPROFILE%\.tce-worker\state\STOP." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Output "registered and started: $TaskName (workers=$Workers)"
