@echo off
chcp 65001 >nul
title Install Load APKs
echo ========================================
echo   Install Load APKs to Device
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

adb devices >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] adb not found, please add platform-tools to PATH
    pause
    exit /b 1
)

echo Select region:
echo   1. CN (China)
echo   2. OS (Oversea)
echo   3. ALL
echo.
set /p choice=Enter option [1/2/3]: 

if "%choice%"=="1" set REGION=CN
if "%choice%"=="2" set REGION=OS
if "%choice%"=="3" set REGION=ALL
if not defined REGION (
    echo [ERROR] Invalid option
    pause
    exit /b 1
)

echo.
echo Region: %REGION%
python "%~dp0install_apks.py" --region %REGION%

echo.
pause
