@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% EQU 0 (
    py -3 "%~dp0decode_geography.py"
) else (
    python "%~dp0decode_geography.py"
)
echo.
echo Check the output folder next to this CMD file.
pause
