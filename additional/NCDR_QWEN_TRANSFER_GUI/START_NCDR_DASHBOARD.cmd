@echo off
setlocal
set "ROOT=%~dp0"

if not exist "%ROOT%DB_0" (
    echo This update must be extracted into the existing NCDR_QWEN_TRANSFER_GUI folder.
    echo DB_0 was not found next to this launcher.
    pause
    exit /b 1
)

if not exist "%ROOT%windows\Open_Dashboard.vbs" (
    echo The original dashboard launcher was not found.
    echo Expected: windows\Open_Dashboard.vbs
    pause
    exit /b 1
)

start "" "%SystemRoot%\System32\wscript.exe" "%ROOT%windows\Open_Dashboard.vbs"
exit /b 0
