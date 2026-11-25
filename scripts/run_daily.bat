@echo off
rem run_daily.bat - unattended daily review (Windows Task Scheduler).
rem Edit the path below to your repository folder.
cd /d C:\Users\you\Trading_AI_Agent
if not exist data\live\reports mkdir data\live\reports
.venv\Scripts\python.exe -m trading_agent --daily >> data\live\reports\log.txt 2>&1
