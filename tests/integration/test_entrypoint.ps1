$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Launcher = Join-Path $ProjectRoot 'src\agent\run_ncdqwen.ps1'
Push-Location $env:TEMP
try {
    $output = & $Launcher -Help 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Launcher returned exit code $LASTEXITCODE" }
    $text = $output -join "`n"
    if ($text -notmatch 'usage: runner.py') { throw 'Runner help text did not appear from the unrelated working directory.' }
    'PASS: launcher imports and starts ncdqwen.runner --help from an unrelated working directory.'
} finally {
    Pop-Location
}
