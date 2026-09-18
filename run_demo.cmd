@echo off
setlocal
set "DEMO_PYTHON=%~dp0..\.python311\python.exe"
if not exist "%DEMO_PYTHON%" set "DEMO_PYTHON=python"
"%DEMO_PYTHON%" "%~dp0main.py" %*
exit /b %errorlevel%
