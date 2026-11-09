@echo off
setlocal
cd /d "%~dp0"
title Web Collector
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
if errorlevel 1 pause
endlocal
