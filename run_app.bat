@echo off
setlocal

set PROJECT_ROOT=%~dp0
set VENV_DIR=%PROJECT_ROOT%\.venv

if not exist "%VENV_DIR%" (
    echo [1/4] 建立專案虛擬環境...
    py -3 -m venv "%VENV_DIR%"
)

if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
) else (
    echo 找不到虛擬環境啟動腳本，請確認 Python 是否安裝完整。
    exit /B 1
)

echo [2/4] 升級 pip 並安裝必要套件...
python -m pip install --upgrade pip
if exist "%PROJECT_ROOT%requirements.txt" (
    python -m pip install -r "%PROJECT_ROOT%requirements.txt"
) else (
    echo 找不到 requirements.txt，請確認專案根目錄。
    exit /B 1
)

echo [3/4] 檢查預設環境變數...
if "%BACKEND_HOST%"=="" (
    if not "%APP_HOST%"=="" (
        set BACKEND_HOST=%APP_HOST%
    )
)
if "%BACKEND_PORT%"=="" (
    if not "%APP_PORT%"=="" (
        set BACKEND_PORT=%APP_PORT%
    )
)
if not "%BACKEND_HOST%"=="" set APP_HOST=%BACKEND_HOST%
if not "%BACKEND_PORT%"=="" set APP_PORT=%BACKEND_PORT%

echo [4/4] 啟動應用服務 (CTRL+C 可結束)...
pushd "%PROJECT_ROOT%"
python -m app
set EXIT_CODE=%ERRORLEVEL%
popd

endlocal & exit /B %EXIT_CODE%
