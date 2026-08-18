@echo off
rem Register the daily 7:30AM scheduled task on THIS Windows machine.
rem The task runs daily_run.bat in the project folder.
setlocal
cd /d "%~dp0"
echo Registering ScraperIntelligence_DailyBriefing (daily at 7:30AM)...

powershell -NoProfile -Command ^
  "$dir = '%CD%';" ^
  "$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"\"%CD%\daily_run.bat\"\"' -WorkingDirectory $dir;" ^
  "$trigger = New-ScheduledTaskTrigger -Daily -At 07:30AM;" ^
  "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4);" ^
  "Register-ScheduledTask -TaskName 'ScraperIntelligence_DailyBriefing' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null;" ^
  "Write-Host 'Registered. Next run: ' (Get-ScheduledTaskInfo -TaskName 'ScraperIntelligence_DailyBriefing').NextRunTime"

if errorlevel 1 (
  echo ERROR: could not register the task. Run this as Administrator if needed.
  exit /b 1
)
endlocal