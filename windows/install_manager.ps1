param([switch]$Uninstall, [switch]$Launch)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TaskName = 'NCDR Autonomous Research Manager'
$WeeklyReviewTaskName = 'NCDR Autonomous Weekly Codex Review'
$Pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $Pythonw) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
    $Pythonw = Join-Path (Split-Path $Python) 'pythonw.exe'
}
if (-not (Test-Path -LiteralPath $Pythonw)) { throw "Python with Tk is required; pythonw.exe not found at $Pythonw" }
$GuiPath = Join-Path $ProjectRoot 'NCDR_Manager.pyw'
$WorkerModule = 'src.agent.autonomous_manager'
$ShortcutPath = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NCDR Autonomous Research Manager.lnk'
$StartupWorkerShortcutPath = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\NCDR Autonomous Research Worker.lnk'
$WatchdogPath = Join-Path $PSScriptRoot 'worker_watchdog.py'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $WeeklyReviewTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ShortcutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StartupWorkerShortcutPath -Force -ErrorAction SilentlyContinue
    Write-Host 'Startup task and shortcuts removed. SQLite checkpoints and results were kept.'
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'project_state.sqlite'))) {
    throw "Existing NCDR checkpoint not found: $(Join-Path $ProjectRoot 'project_state.sqlite')"
}

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument ('-B "' + $WatchdogPath + '"') -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$TaskSchedulerInstalled = $false
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Principal $Principal -Description 'Resume the saved NCDR research queue after Windows sign-in.' -Force | Out-Null
    $TaskSchedulerInstalled = $true
}
catch {
    Write-Warning "Task Scheduler registration was unavailable: $($_.Exception.Message)"
}

$WeeklyReviewAction = New-ScheduledTaskAction -Execute $Pythonw `
    -Argument '-B -m src.agent.weekly_review run' -WorkingDirectory $ProjectRoot
$WeeklyReviewTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '6:00PM'
$WeeklyReviewInstalled = $false
try {
    Register-ScheduledTask -TaskName $WeeklyReviewTaskName -Action $WeeklyReviewAction `
        -Trigger $WeeklyReviewTrigger -Settings $Settings -Principal $Principal `
        -Description 'Run one read-only weekly architecture review under the daily Codex quota gate.' -Force | Out-Null
    $WeeklyReviewInstalled = $true
}
catch {
    Write-Warning "Weekly Codex review registration was unavailable: $($_.Exception.Message)"
}

# The per-user watchdog stays enabled even when Task Scheduler succeeds. Its
# file lock prevents duplicate workers, and it restarts the worker if a process
# exits while the durable control state remains RUNNING.
$null = New-Item -ItemType Directory -Force -Path (Split-Path $StartupWorkerShortcutPath)
$Shell = New-Object -ComObject WScript.Shell
$WorkerShortcut = $Shell.CreateShortcut($StartupWorkerShortcutPath)
$WorkerShortcut.TargetPath = $Pythonw
$WorkerShortcut.Arguments = "`"$WatchdogPath`""
$WorkerShortcut.WorkingDirectory = $ProjectRoot
$WorkerShortcut.Description = 'Resume and watch the saved NCDR research worker after sign-in.'
$WorkerShortcut.Save()

$null = New-Item -ItemType Directory -Force -Path (Split-Path $ShortcutPath)
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = "`"$GuiPath`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = 'NCDR Autonomous Research Manager'
$Shortcut.Save()

Write-Host "Installed: $ShortcutPath"
if ($TaskSchedulerInstalled) {
    Write-Host "Worker autostart: Task Scheduler ONLOGON ($TaskName)"
}
if ($WeeklyReviewInstalled) {
    Write-Host "Codex review: weekly Sunday at 6:00 PM ($WeeklyReviewTaskName); read-only, quota-gated, one request per ISO week."
}
else {
    Write-Host "Worker autostart: per-user Startup watchdog ($StartupWorkerShortcutPath)"
}
Write-Host 'The worker resumes a saved RUNNING checkpoint after sign-in; administrator rights are not required.'
if ($Launch) { Start-Process -FilePath $Pythonw -ArgumentList "`"$GuiPath`"" -WorkingDirectory $ProjectRoot }
