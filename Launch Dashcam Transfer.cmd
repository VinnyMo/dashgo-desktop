@echo off
cd /d "%~dp0"
python -B dashcam_qt.py
if errorlevel 1 pause
