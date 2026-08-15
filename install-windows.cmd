@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 install.py
  goto finish
)

where python >nul 2>nul
if %errorlevel% equ 0 (
  python install.py
  goto finish
)

echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/ and run this file again.

:finish
echo.
pause
