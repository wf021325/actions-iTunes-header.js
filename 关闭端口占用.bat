@echo off

echo 检查端口 9000 是否被占用...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :9000') do (
    echo 端口 9000 被占用。
    pause > nul
    exit /b 1
)
echo 端口 9000 未被占用。

REM 自定义暂停提示，自动根据系统语言显示
set /p "=按任意键继续 . . . "<nul
pause > nul
