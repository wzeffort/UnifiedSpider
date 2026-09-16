@echo off
title UnifiedSpider Setup
cd /d "%~dp0"
set PYTHONUTF8=1
set "SPIDER_PYTHON=D:\Anaconda\envs\spider-crawl4ai\python.exe"
if not exist "%SPIDER_PYTHON%" goto missing
"%SPIDER_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
"%SPIDER_PYTHON%" -m playwright install chromium
if errorlevel 1 goto failed
echo Installation complete. Double-click start.bat to launch.
pause
exit /b 0
:missing
echo Create the Conda environment first: conda env create -f environment.yml
:failed
echo Installation failed. See the message above.
pause
exit /b 1
