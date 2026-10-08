@echo off
chcp 65001 > nul
title 경기북부 기상·재난 상황판
cd /d "%~dp0"
echo.
echo ====================================================
echo    경기북부 기상·재난 상황판
echo ====================================================
echo.
echo [1/2] 최신 데이터 가져오는 중...
python tools\update_data.py
if errorlevel 1 (
    echo.
    echo [경고] 데이터 갱신 실패. 이전 데이터로 표시됩니다.
    timeout /t 2 > nul
)
echo.
echo [2/2] 상황판 여는 중...
start "" "%~dp0index.html"
echo.
echo ====================================================
echo    상황판이 브라우저에 열렸습니다.
echo    이 창은 3초 후 자동으로 닫힙니다.
echo ====================================================
timeout /t 3 > nul
