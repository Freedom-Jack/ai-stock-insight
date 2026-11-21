@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    where uv >nul 2>nul || (
        echo Install uv for Windows, then run this launcher again.
        exit /b 1
    )
    uv sync --locked || exit /b 1
)
".venv\Scripts\python.exe" -m stockinsight.launcher %*
set "trial_exit=%ERRORLEVEL%"
popd
exit /b %trial_exit%
