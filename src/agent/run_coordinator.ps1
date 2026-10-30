param(
    [ValidateRange(1, 10)]
    [int]$MaxTasks = 4,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = (Get-Command python -ErrorAction Stop).Source
Push-Location $ProjectRoot
try {
    if ($Help) {
        & $Python -m src.agent.coordinator --help
        exit $LASTEXITCODE
    }

    $StartedServer = $false
    $ServerProcess = $null
    $OllamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    }
    catch {
        if (-not (Test-Path -LiteralPath $OllamaExe)) {
            throw "Ollama is not available and the installed executable was not found: $OllamaExe"
        }
        $ServerProcess = Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WindowStyle Hidden -PassThru
        $StartedServer = $true
        $Deadline = (Get-Date).AddSeconds(45)
        $Ready = $false
        while ((Get-Date) -lt $Deadline) {
            try {
                $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
                $Ready = $true
                break
            }
            catch {
                Start-Sleep -Seconds 2
            }
        }
        if (-not $Ready) { throw 'Ollama API did not become ready within 45 seconds.' }
    }

    & $Python -m src.agent.coordinator --max-tasks $MaxTasks
    if ($LASTEXITCODE -ne 0) { throw "Coordinator exited with code $LASTEXITCODE" }
}
finally {
    if ($StartedServer -and $ServerProcess) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
