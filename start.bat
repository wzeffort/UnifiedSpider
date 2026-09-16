@echo off
title UnifiedSpider
cd /d "%~dp0"
set PYTHONUTF8=1
set "SPIDER_PYTHON=D:\Anaconda\envs\spider-crawl4ai\python.exe"
if not exist "%SPIDER_PYTHON%" goto missing
echo Starting UnifiedSpider at http://127.0.0.1:18765
"%SPIDER_PYTHON%" launcher.py
if errorlevel 1 pause
exit /b
:missing
echo Python environment missing: spider-crawl4ai
pause
exit /b 1
