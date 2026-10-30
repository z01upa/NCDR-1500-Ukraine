param([switch]$Background)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Db0 = Join-Path $Root 'DB_0'
$Work = Join-Path $Root 'work'
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$StartupError = Join-Path $Work 'startup_error.log'
Remove-Item -LiteralPath $StartupError -Force -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $Db0 -PathType Leaf)) {
    throw "DB_0 was not found in the transfer folder: $Db0"
}
$RunnerPath = Join-Path $Root 'ncdqwen\runner.py'
$RequiredFiles = @(
    $RunnerPath,
    (Join-Path $Root 'ncdqwen\__init__.py'),
    (Join-Path $Root 'ncdqwen\db0.py'),
    (Join-Path $Root 'ncdqwen\ollama_client.py'),
    (Join-Path $Root 'schema.sql'),
    (Join-Path $Root 'prompts\system_prompt.txt'),
    (Join-Path $Root 'research\roads\build_authoritative_corpus.py')
)
$MissingFiles = @($RequiredFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($MissingFiles.Count -gt 0) {
    $StartupDetail = "Research preflight failed. Missing required file(s): $($MissingFiles -join ', ')"
    $StartupDetail | Set-Content -LiteralPath $StartupError -Encoding Unicode
    throw $StartupDetail
}

function Refresh-ProcessPath {
    $MachinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$MachinePath;$UserPath"
}

function Find-Python {
    Refresh-ProcessPath
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        $Candidate = & $Launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $Candidate -and (Test-PythonVersion $Candidate)) { return $Candidate.Trim() }
    }
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command -and $Command.Source -notmatch '\\WindowsApps\\') {
        $Candidate = $Command.Source
        if (Test-PythonVersion $Candidate) { return $Candidate }
    }
    return $null
}

function Test-PythonVersion([string]$Executable) {
    try {
        & $Executable -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

$Python = Find-Python
if (-not $Python) {
    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $Winget) { throw 'Python 3.10+ is missing and winget is unavailable. Install Python 3.12, then run this file again.' }
    Write-Host 'Installing Python 3.12 for this Windows account...'
    & $Winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed with exit code $LASTEXITCODE" }
    Start-Sleep -Seconds 3
    $Python = Find-Python
    if (-not $Python) { throw 'Python installation finished but Python could not be located. Reopen PowerShell and run this file again.' }
}

$PreviousPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) { $env:PYTHONPATH = $Root }
else { $env:PYTHONPATH = "$Root;$PreviousPythonPath" }
$PreflightCode = "import importlib,sys; assert sys.version_info >= (3,10), f'Python 3.10+ required; found {sys.version}'; [importlib.import_module(name) for name in ('sqlite3','ctypes','mmap','hashlib','statistics','bz2','gzip','lzma','zlib','tkinter','ncdqwen.db0','ncdqwen.ollama_client','ncdqwen.runner')]; print(sys.executable)"
$PreflightOutput = & $Python -c $PreflightCode 2>&1
$PreflightExit = $LASTEXITCODE
if ($PreflightExit -ne 0) {
    $PreflightDetail = ($PreflightOutput | ForEach-Object { $_.ToString() }) -join "`n"
    $StartupDetail = "Python dependency preflight failed using '$Python'. Research was not started.`n$PreflightDetail"
    $StartupDetail | Set-Content -LiteralPath $StartupError -Encoding Unicode
    throw $StartupDetail
}

$System = Get-CimInstance Win32_ComputerSystem
$RamGb = [math]::Floor($System.TotalPhysicalMemory / 1GB)
if ($RamGb -ge 24) { $PreferredModel = 'qwen3.5:9b' }
elseif ($RamGb -ge 12) { $PreferredModel = 'qwen3.5:4b' }
elseif ($RamGb -ge 8) { $PreferredModel = 'qwen3.5:2b' }
else { $PreferredModel = 'qwen3.5:0.8b' }

function Find-Ollama {
    Refresh-ProcessPath
    $Command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    $Paths = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'),
        (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')
    )
    foreach ($Path in $Paths) { if (Test-Path -LiteralPath $Path) { return $Path } }
    return $null
}

$Ollama = Find-Ollama
if (-not $Ollama) {
    Write-Host 'Installing Ollama for Windows...'
    Invoke-Expression (Invoke-RestMethod -Uri 'https://ollama.com/install.ps1')
    Start-Sleep -Seconds 3
    $Ollama = Find-Ollama
    if (-not $Ollama) { throw 'Ollama installer finished but ollama.exe could not be located. Install it from https://ollama.com/download/windows, then run this file again.' }
}

function Test-OllamaApi {
    try {
        $null = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3
        return $true
    } catch { return $false }
}

if (-not (Test-OllamaApi)) {
    Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden -WorkingDirectory $Root | Out-Null
    $Ready = $false
    for ($Try = 0; $Try -lt 60; $Try++) {
        Start-Sleep -Seconds 2
        if (Test-OllamaApi) { $Ready = $true; break }
    }
    if (-not $Ready) { throw 'Ollama did not start its local API. Restart Windows and run this file again.' }
}

$Tags = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags'
$InstalledNames = @($Tags.models | ForEach-Object {
    if ($_.name) { $_.name } elseif ($_.model) { $_.model }
})
if ($InstalledNames -contains $PreferredModel) {
    $Model = $PreferredModel
    $ModelSource = 'reused exact installed model'
} else {
    $LocalQwen = @($InstalledNames | Where-Object { $_ -match '(^|/)qwen' -and $_ -notmatch ':cloud' })
    $Qwen35 = @($LocalQwen | Where-Object { $_ -match '(^|/)qwen3\.5:' })
    $FallbackOrder = switch ($PreferredModel) {
        'qwen3.5:9b' { @('qwen3.5:9b','qwen3.5:4b','qwen3.5:2b','qwen3.5:0.8b') }
        'qwen3.5:4b' { @('qwen3.5:4b','qwen3.5:2b','qwen3.5:0.8b','qwen3.5:9b') }
        'qwen3.5:2b' { @('qwen3.5:2b','qwen3.5:0.8b','qwen3.5:4b','qwen3.5:9b') }
        default { @('qwen3.5:0.8b','qwen3.5:2b','qwen3.5:4b','qwen3.5:9b') }
    }
    $Model = $null
    foreach ($BaseModel in $FallbackOrder) {
        $Match = $Qwen35 | Where-Object { $_ -eq $BaseModel -or $_.StartsWith($BaseModel + '-') } | Select-Object -First 1
        if ($Match) { $Model = $Match; break }
    }
    if (-not $Model -and $Qwen35.Count -gt 0) { $Model = ($Qwen35 | Sort-Object)[0] }
    if (-not $Model -and $LocalQwen.Count -gt 0) { $Model = ($LocalQwen | Sort-Object)[0] }
    if (-not $Model) { $Model = $PreferredModel }
    $ModelSource = if ($LocalQwen.Count -gt 0) { 'reused installed local Qwen' } else { 'selected by RAM; download required' }
}

@{
    selected_model = $Model
    model_source = $ModelSource
    physical_ram_gb = $RamGb
    python = $Python
    ollama = $Ollama
    selected_utc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Work 'machine_setup.json')

$Stdout = Join-Path $Work 'python_stdout.log'
$Stderr = Join-Path $Work 'python_stderr.log'
$TaskArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '" -Background'

$TaskName = 'NCDR_DB0_Qwen_Resume'
$PowerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$TaskAction = New-ScheduledTaskAction -Execute $PowerShellExe `
    -Argument $TaskArguments
$TaskTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew
try {
    Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger $TaskTrigger `
        -Principal $TaskPrincipal -Settings $TaskSettings -Force | Out-Null
} catch {
    Write-Warning "Could not register automatic resume at sign-in: $_"
}

$DashboardVbs = Join-Path $PSScriptRoot 'Open_Dashboard.vbs'
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NCDR DB_0 Dashboard.lnk'
if ((Test-Path -LiteralPath $DashboardVbs) -and -not (Test-Path -LiteralPath $DesktopShortcut)) {
    try {
        $Shell = New-Object -ComObject WScript.Shell
        $Shortcut = $Shell.CreateShortcut($DesktopShortcut)
        $Shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
        $Shortcut.Arguments = '"' + $DashboardVbs + '"'
        $Shortcut.WorkingDirectory = $Root
        $Shortcut.Description = 'Open the local NCDR DB_0 research dashboard'
        $Shortcut.Save()
    } catch {
        Write-Warning "Could not create a desktop shortcut: $_"
    }
}

if ($Background) {
    $ExistingPid = 0
    if (Test-Path -LiteralPath (Join-Path $Work 'runner.lock')) {
        try {
            $ExistingPid = [int]((Get-Content (Join-Path $Work 'runner.lock') -Raw | ConvertFrom-Json).pid)
        } catch { $ExistingPid = 0 }
    }
    $ExistingProcess = if ($ExistingPid -gt 0) { Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue } else { $null }
    if ($ExistingProcess -and $ExistingProcess.ProcessName -match '^python(w)?$') {
        Write-Host "Runner already active (PID $ExistingPid); leaving it in place."
        exit 0
    }
    $Arguments = '"' + $RunnerPath + '" --db0 "' + $Db0 + '" --model "' + $Model + '" --max-rounds 200'
    $Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $Root `
        -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -PassThru
    Write-Host "Resumed local analysis in the background (PID $($Process.Id))."
} else {
    $GuiScript = Join-Path $Root 'ncdqwen\desktop_app.py'
    $Arguments = '"' + $GuiScript + '"'
    $PythonGui = Join-Path (Split-Path $Python -Parent) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $PythonGui)) { $PythonGui = $Python }
    $Process = Start-Process -FilePath $PythonGui -ArgumentList $Arguments -WorkingDirectory $Root `
        -PassThru
    Write-Host "Opened the NCDR dashboard (PID $($Process.Id))."
}

Write-Host "Automatic background resume at the next Windows sign-in is enabled ($TaskName)."
Write-Host "Model: $Model; detected RAM: ${RamGb} GB."
Write-Host "Progress: $Work\status.json"
Write-Host "Final report: $Root\reports\FINAL_REPORT.md"
