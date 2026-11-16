@echo off
chcp 65001 >nul
rem Обновление данных по расписанию (вызывается Планировщиком заданий Windows). Вывод — в data\scheduler.log.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist data mkdir data
.venv\Scripts\python.exe pipeline.py --trigger schedule >> data\scheduler.log 2>&1
