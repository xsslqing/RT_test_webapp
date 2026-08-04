@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动辐射安全考试练习系统...
echo 浏览器将自动打开 http://localhost:8502
echo 按 Ctrl+C 可停止服务
echo.
start http://localhost:8502
streamlit run app.py --server.port 8502
pause
