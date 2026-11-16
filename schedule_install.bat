@echo off
chcp 65001 >nul
rem Регистрирует задание «AeroPulse update» в Планировщике Windows: update.bat каждый час.
rem Удалить задание:   schtasks /Delete /TN "AeroPulse update" /F
rem Запустить вручную: schtasks /Run /TN "AeroPulse update"
cd /d "%~dp0"
schtasks /Create /TN "AeroPulse update" /TR "\"%~dp0update.bat\"" /SC HOURLY /MO 1 /F
