param(
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = (Get-Command python.exe -ErrorAction Stop).Source
$MapPath = Join-Path $ProjectRoot 'data\osm\kryvyi_rih.sqlite'
$MetadataPath = Join-Path $ProjectRoot 'data\osm\source.json'
$EntryPoint = Join-Path $ProjectRoot 'src\cid\virtual_cid.py'
$PyInstallerModules = Join-Path $ProjectRoot 'build\pyinstaller_runtime'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Split-Path (Split-Path $ProjectRoot -Parent) -Parent) 'outputs\NCDR_Ukraine_Windows'
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$BuildDirectory = Join-Path $ProjectRoot 'build\pyinstaller_work'
$SpecDirectory = Join-Path $ProjectRoot 'build\pyinstaller_spec'

if (-not (Test-Path -LiteralPath $MapPath)) { throw "Map database is missing: $MapPath" }
if (-not (Test-Path -LiteralPath $MetadataPath)) { throw "Map provenance is missing: $MetadataPath" }
if (-not (Test-Path -LiteralPath $PyInstallerModules)) { throw 'Build-only PyInstaller installation is missing.' }
$metadata = Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
if ($metadata.license -ne 'Open Database License (ODbL)' -or -not $metadata.dataset_content_timestamp) {
    throw 'OSM attribution, license, or source timestamp is missing.'
}
$integrity = & $Python -c "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(c.execute('pragma integrity_check').fetchone()[0]); c.close()" $MapPath
if ($LASTEXITCODE -ne 0 -or $integrity.Trim() -ne 'ok') { throw "Map database integrity check failed: $integrity" }
if (Test-Path -LiteralPath $OutputDirectory) {
    throw "Output folder already exists; choose another OutputDirectory to preserve existing files: $OutputDirectory"
}
$null = New-Item -ItemType Directory -Force -Path $OutputDirectory,$BuildDirectory,$SpecDirectory

$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$PyInstallerModules;$ProjectRoot"
    $mapData = "$MapPath;data\osm"
    $metadataData = "$MetadataPath;data\osm"
    & $Python -m PyInstaller --clean --noconfirm --onedir --windowed `
        --name NCDR_Ukraine --paths $ProjectRoot `
        --add-data $mapData --add-data $metadataData `
        --distpath $OutputDirectory --workpath $BuildDirectory --specpath $SpecDirectory `
        $EntryPoint
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE" }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}

$Executable = Join-Path $OutputDirectory 'NCDR_Ukraine\NCDR_Ukraine.exe'
if (-not (Test-Path -LiteralPath $Executable)) { throw "Expected Windows application was not produced: $Executable" }
$PackagedMap = Join-Path $OutputDirectory 'NCDR_Ukraine\_internal\data\osm\kryvyi_rih.sqlite'
if (-not (Test-Path -LiteralPath $PackagedMap)) { throw "Packaged map database is missing: $PackagedMap" }
$packagedIntegrity = & $Python -c "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(c.execute('pragma integrity_check').fetchone()[0]); c.close()" $PackagedMap
if ($LASTEXITCODE -ne 0 -or $packagedIntegrity.Trim() -ne 'ok') { throw "Packaged map failed integrity check: $packagedIntegrity" }

Write-Output (ConvertTo-Json -Compress -InputObject @{
    status='BUILT'; executable=$Executable; packaged_map=$PackagedMap
    packaged_map_integrity=$packagedIntegrity.Trim(); map_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $PackagedMap).Hash
})
