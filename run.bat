@echo off
chcp 65001 >nul
rem AeroPulse: подготовка окружения (при первом запуске), обновление данных и запуск дашборда.
rem Первый запуск загружает 24 месяца истории BTS — около 35 минут.
rem Параметр skip — не обновлять данные, сразу открыть дашборд:  run.bat skip
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist .venv\Scripts\python.exe (
    echo Создаю виртуальное окружение...
    py -3 -m venv .venv || goto :nopython
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt || exit /b 1
)

if /i not "%1"=="skip" .venv\Scripts\python.exe pipeline.py

rem браузер откроется через 6 секунд, когда сервер дашборда успеет стартовать
start "" cmd /c "timeout /t 6 >nul & start http://localhost:8501"
.venv\Scripts\python.exe -m streamlit run app.py
exit /b

:nopython
echo Не найден Python. Установите Python 3.12+ с python.org (галочка "Add python.exe to PATH") и запустите снова.
pause
exit /b 1
