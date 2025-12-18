@echo off
setlocal

set SCRIPT_DIR=%~dp0
set TARGET_BAT=%SCRIPT_DIR%run_app.bat

if not exist "%TARGET_BAT%" (
    echo 找不到 run_app.bat，請確認檔案是否位於專案根目錄。
    endlocal & exit /B 1
)

call "%TARGET_BAT%"
set EXIT_CODE=%ERRORLEVEL%

endlocal & exit /B %EXIT_CODE%
