@echo off
REM Double-click this file to launch the Fantasy Football Draft Assistant locally.
cd /d "%~dp0"
echo.
echo   Starting your draft assistant...
echo   A browser tab will open at http://localhost:8501
echo.
echo   Keep this black window open during your draft.
echo   To stop: close this window or press Ctrl+C.
echo.
python -m streamlit run app.py
pause
