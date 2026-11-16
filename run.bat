@echo off
chcp 65001 >nul
rem AeroPulse: подготовка окружения (при первом запуске), обновление данных и запуск дашборда.
rem Первый запуск загружает 24 месяца истории BTS — около 35 минут.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist .venv\Scripts\python.exe (
    echo Создаю виртуальное окружение...
    py -3 -m venv .venv || exit /b 1
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt || exit /b 1
)

.venv\Scripts\python.exe pipeline.py
.venv\Scripts\python.exe -m streamlit run app.py
