@echo off
setlocal
cd /d "%~dp0"
echo NCDR1500 read-only RL/IOF/IL structural verification.
echo Select folder containing EUZ.RL.logical.bin, EUZ.IOF.logical.bin, EUZ.IL.logical.bin.
set "INPUT="
for /f "delims=" %%A in ('powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $f=New-Object System.Windows.Forms.FolderBrowserDialog; if($f.ShowDialog() -eq 'OK'){$f.SelectedPath}"') do set "INPUT=%%A"
if not defined INPUT (
 echo No input chosen. Nothing changed.
 pause
 exit /b 1
)
set "OUT=%~dp0OUTPUT_RUN_%RANDOM%"
py -3 verify_road_links.py "%INPUT%" --out "%OUT%"
if errorlevel 1 echo Verification failed. Original files not modified.
pause
