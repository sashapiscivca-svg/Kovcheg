@echo off
rem Kovcheg launcher for a portable kit: runs Kovcheg with this folder as its home.
rem Usage: kovcheg.bat            -^> web interface
rem        kovcheg.bat ^<command^>  -^> any kovcheg command (doctor, ask, build, ...)
set "KOVCHEG_HOME=%~dp0"
set "BIN=%~dp0.venv\Scripts\kovcheg.exe"
if not exist "%BIN%" set "BIN=kovcheg"
if "%~1"=="" ("%BIN%" ui) else ("%BIN%" %*)
