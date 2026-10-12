@echo off
cd /d %~dp0\..
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-App.ps1"
