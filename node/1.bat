@echo off
title NodeJS Shell
set NODE_HOME=%~dp0
set NODE_PATH=%~dp0
set PATH=%~dp0;%NODE_HOME%;%NODE_PATH%;%PATH%;
cd /d %~dp0
cmd.exe
pause
