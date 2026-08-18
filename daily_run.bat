@echo off
rem Daily 7:30AM briefing run: collect live data, then render briefings.
rem Portable: run from any Windows PC with Python installed.
setlocal
cd /d "%~dp0"
set LOGDIR=%CD%\logs
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

rem One-time setup: build project-local engine config + yt-dlp.
call setup.bat

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set D=%%b-%%c-%%d
set LOGFILE=%LOGDIR%\daily_run_%D%.log

echo [%date% %time%] Starting daily collect... >> "%LOGFILE%"
"%PYTHON%" collect_today.py >> "%LOGFILE%" 2>&1
if errorlevel 1 echo [%date% %time%] WARNING: collect_today.py reported failures >> "%LOGFILE%"

echo [%date% %time%] Rendering briefings... >> "%LOGFILE%"
"%PYTHON%" daily_briefing.py >> "%LOGFILE%" 2>&1
if errorlevel 1 echo [%date% %time%] WARNING: daily_briefing.py reported failures >> "%LOGFILE%"

echo [%date% %time%] Done. >> "%LOGFILE%"
endlocal