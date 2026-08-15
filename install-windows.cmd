@echo off
setlocal
cd /d "%~dp0"

if not "%BHKA_FORCE_UV_BOOTSTRAP%"=="1" (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 install.py %*
    goto finish
  )

  where python >nul 2>nul
  if not errorlevel 1 (
    python install.py %*
    goto finish
  )
)

echo Python was not found. Preparing the private runtime automatically...
set "BHKA_UV_DIR=%LOCALAPPDATA%\bilibili-tech-resource-discovery\tools\uv-0.11.32"
set "BHKA_UV_EXE=%BHKA_UV_DIR%\uv.exe"
if not exist "%BHKA_UV_EXE%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_UNMANAGED_INSTALL=$env:BHKA_UV_DIR; $env:UV_NO_MODIFY_PATH='1'; irm 'https://astral.sh/uv/0.11.32/install.ps1' | iex"
  if errorlevel 1 goto runtime_failed
)
if not exist "%BHKA_UV_EXE%" goto runtime_failed

"%BHKA_UV_EXE%" run --no-project --python 3.13 "%~dp0install.py" %*
goto finish

:runtime_failed
echo The private runtime could not be prepared automatically.
echo Check the network connection and run this file again.
set "BHKA_EXIT_CODE=1"
goto done

:finish
set "BHKA_EXIT_CODE=%errorlevel%"

:done
echo.
if not "%BHKA_NO_PAUSE%"=="1" pause
exit /b %BHKA_EXIT_CODE%
