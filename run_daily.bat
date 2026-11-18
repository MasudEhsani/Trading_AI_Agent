@echo off
rem run_daily.bat - edit the path below to your project folder
cd /d C:\Users\you\trading-agent
if not exist reports mkdir reports
.venv\Scripts\python.exe trading_agent.py --daily >> reports\log.txt 2>&1
