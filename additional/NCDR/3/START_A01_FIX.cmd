@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -B "%~dp0fix_a01.py" %*
) else (
  python -B "%~dp0fix_a01.py" %*
)
echo.
echo Read PATCH_INSTALLED or NO_PATCH_OR_ROLLED_BACK above.
pause
