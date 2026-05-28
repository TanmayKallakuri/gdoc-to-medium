@echo off
REM Scheduled-task runner for gdoc-to-medium. Runs from the project root and
REM appends all output (stdout + stderr) to logs\run.log, which is gitignored.
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" -m gdoc_to_medium >> "logs\run.log" 2>&1
