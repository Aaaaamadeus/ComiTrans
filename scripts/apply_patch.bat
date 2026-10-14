@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply-Update.ps1" %* & pause
