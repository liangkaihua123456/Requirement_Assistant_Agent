@echo off
chcp 65001 >nul
cd /d "%~dp0"

if "%1"=="" goto :help
if "%1"=="backend" goto :backend
if "%1"=="frontend" goto :frontend
if "%1"=="docker" goto :docker
if "%1"=="docker-down" goto :docker_down
if "%1"=="test" goto :test
if "%1"=="health" goto :health
if "%1"=="all" goto :all
goto :help

:help
echo Usage: start.bat [backend / frontend / docker / docker-down / test / health / all]
echo.
echo Commands:
echo   backend  - Start FastAPI backend (http://127.0.0.1:8000)
echo   frontend - Start Vue frontend (http://localhost:5173)
echo   docker   - Start Vue + API with Docker Compose (http://127.0.0.1:8080)
echo   docker-down - Stop Docker Compose services
echo   test     - Run pytest
echo   health   - Check backend health
echo   all      - Show startup instructions
goto :eof

:backend
echo Starting FastAPI backend at http://127.0.0.1:8000
call :pick_python
echo Using Python: %PY%
"%PY%" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
goto :eof

:frontend
echo Starting Vue frontend at http://127.0.0.1:5173
cd /d "%~dp0frontend-vue"
if not exist node_modules (
  echo Frontend dependencies are missing. Run: npm ci
  goto :eof
)
call :pick_npm
if not defined NPM goto :eof
echo Using npm: %NPM%
call "%NPM%" run dev -- --host 0.0.0.0
goto :eof

:docker
echo Starting Vue + API with Docker Compose at http://127.0.0.1:8080
docker compose up --build
goto :eof

:docker_down
echo Stopping Docker Compose services...
docker compose down
goto :eof

:test
echo Running tests...
call :pick_python
echo Using Python: %PY%
"%PY%" -m pytest tests\ -v
goto :eof

:pick_python
set "PY=%PYTHON_EXE%"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined PY set "PY=python"
goto :eof

:pick_npm
set "NPM="
if exist "%NODE_HOME%\npm.cmd" set "NPM=%NODE_HOME%\npm.cmd"
if not defined NPM for /f "delims=" %%i in ('where npm.cmd 2^>nul') do if not defined NPM set "NPM=%%i"
if not defined NPM for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do if exist "%%d\npm.cmd" set "NPM=%%d\npm.cmd"
if not defined NPM if exist "%ProgramFiles%\nodejs\npm.cmd" set "NPM=%ProgramFiles%\nodejs\npm.cmd"
if defined NPM for %%i in ("%NPM%") do set "PATH=%%~dpi;%PATH%"
if not defined NPM (
  echo Node.js / npm not found.
  echo Install Node.js 18+ or set NODE_HOME to the folder containing npm.cmd.
)
goto :eof

:health
curl -s http://127.0.0.1:8000/health 2>nul || echo Backend not running
goto :eof

:all
echo Local development mode:
echo 1. Run in window 1: start.bat backend
echo 2. Run in window 2: start.bat frontend
echo 3. Open http://127.0.0.1:5173
echo.
echo Docker mode:
echo 1. Run: start.bat docker
echo 2. Open http://127.0.0.1:8080
goto :eof
