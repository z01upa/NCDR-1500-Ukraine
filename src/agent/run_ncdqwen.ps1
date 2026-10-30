param(
    [string]$SourceRoot = '%USERPROFILE%\Desktop\crz\NCDR',
    [string]$Model = 'qwen3.5:4b',
    [ValidateRange(1, 200)][int]$MaxRounds = 3,
    [switch]$Status,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Db0 = Join-Path $SourceRoot 'NCDR_MAP_RESEARCH\DB_0'
$Python = Get-Command python -ErrorAction Stop
$PreviousPythonPath = $env:PYTHONPATH
$PathEntries = @($ProjectRoot)
if ($PreviousPythonPath) { $PathEntries += $PreviousPythonPath }
$env:PYTHONPATH = $PathEntries -join [IO.Path]::PathSeparator

$Arguments = @('-m', 'ncdqwen.runner', '--db0', $Db0, '--model', $Model, '--max-rounds', "$MaxRounds")
if ($Status) { $Arguments += '--status' }
if ($Help) { $Arguments += '--help' }

try {
    & $Python.Source @Arguments
    $ExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $PreviousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $PreviousPythonPath }
}

if (-not $Help) {
    try {
        $Unload = @{ model = $Model; prompt = ''; stream = $false; keep_alive = 0; options = @{ num_predict = 1 } } | ConvertTo-Json -Depth 4 -Compress
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body $Unload -TimeoutSec 10 | Out-Null
    } catch { Write-Warning "Local model unload was not confirmed: $($_.Exception.Message)" }
}

exit $ExitCode
