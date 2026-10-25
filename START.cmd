@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "RT=runtime"
if not exist "%RT%\pythonw.exe" (
  set "RT=runtime-x64"
  if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "RT=runtime-x86"
)
if not exist "%RT%\pythonw.exe" (
  echo Λείπει ο φάκελος runtime. Αποσυμπιέστε ΟΛΟ το ZIP σε φάκελο και ξαναδοκιμάστε.
  pause
  exit /b 1
)
rem Ανοίγει την εφαρμογή σε δικό της παράθυρο, χωρίς κονσόλα.
start "" "%RT%\pythonw.exe" -X utf8 "src\server.py"
exit /b 0
