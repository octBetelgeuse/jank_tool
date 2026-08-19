@echo off
chcp 65001 >nul
title Download Load APKs
echo ========================================
echo   Download Load APKs from mirrorapk.com
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found, please install Python 3.8+
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

set /p INSTALL=Auto adb install after download? [y/N]: 

if /i "%INSTALL%"=="y" (
    set INSTALL_FLAG=--install
) else (
    set INSTALL_FLAG=
)

echo.
echo Region: %REGION%
python "%~dp0download_apks.py" --region %REGION% %INSTALL_FLAG%

echo.
pause
