@echo off
cd /d "%~dp0"
python -B dashcam_gui.py
if errorlevel 1 pause
