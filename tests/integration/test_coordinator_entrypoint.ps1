$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Launcher = Join-Path $ProjectRoot 'src\agent\run_coordinator.ps1'
$Original = Get-Location
try {
    Set-Location $env:TEMP
    $Output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Launcher -Help 2>&1
    if ($LASTEXITCODE -ne 0 -or ($Output -join "`n") -notmatch '--max-tasks') {
        throw "Coordinator launcher failed from an unrelated working directory: $($Output -join "`n")"
    }
    Write-Output 'PASS: coordinator help runs from an unrelated working directory without starting Ollama.'
}
finally {
    Set-Location $Original
}
