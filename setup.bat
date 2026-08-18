@echo off
rem One-time setup for the Scraper Intelligence project.
rem - builds the project-local engine config (.config\last30days\.env)
rem   from data\.scrapecreators_key if present
rem - installs yt-dlp (free, required for YouTube)
rem - verifies the vendored last30days engine exists
setlocal
cd /d "%~dp0"
echo === Scraper Intelligence setup ===

set PYTHON=
for %%P in (python py python3) do (
  if not defined PYTHON (
    %%P --version >nul 2>&1 && set PYTHON=%%P
  )
)
if not defined PYTHON (
  echo ERROR: Python not found. Install Python 3.13 from https://www.python.org/downloads/
  exit /b 1
)
echo [1/4] Python found: %PYTHON%

rem --- project-local engine config ---
set CFGDIR=%CD%\.config\last30days
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
if not exist "%CFGDIR%\.env" (
  if exist "data\.scrapecreators_key" (
    for /f "usebackq delims=" %%K in ("data\.scrapecreators_key") do (
      > "%CFGDIR%\.env" echo SCRAPECREATORS_API_KEY=%%K
    )
    >> "%CFGDIR%\.env" echo SETUP_COMPLETE=true
    echo [2/4] Engine config created from data\.scrapecreators_key
  ) else (
    > "%CFGDIR%\.env" echo SETUP_COMPLETE=true
    echo [2/4] Engine config created (no API key found; free sources only)
  )
) else (
  echo [2/4] Engine config already exists
)

rem --- yt-dlp ---
echo [3/4] Ensuring yt-dlp is installed...
"%PYTHON%" -m pip show yt-dlp >nul 2>&1
if errorlevel 1 "%PYTHON%" -m pip install yt-dlp

rem --- engine check ---
if exist ".opencode\skills\last30days\scripts\last30days.py" (
  echo [4/4] Engine OK: .opencode\skills\last30days\scripts\last30days.py
) else (
  echo [4/4] WARNING: engine missing - re-copy the .opencode\skills\last30days folder
)

echo.
echo Setup complete. Run daily_run.bat (or register the scheduled task).
endlocal