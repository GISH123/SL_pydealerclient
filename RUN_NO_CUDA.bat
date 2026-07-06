@echo off
setlocal EnableExtensions

REM =========================================================
REM  Run the latest ImageDetector build in **CPU-only** mode
REM  - Hides GPUs from TF using CUDA_VISIBLE_DEVICES
REM  - Signals our runtime hook via NO_CUDA=1 to skip CUDA DLLs
REM  - Does NOT modify system/user environment permanently
REM =========================================================

set "PROJ=%~dp0"
set "DIST=%PROJ%dist"

if not exist "%DIST%" (
  echo [NO-CUDA] ERROR: dist\ not found. Build first.
  exit /b 1
)

REM --- pick newest app folder under dist ---
set "EXE_PATH="
for /f "delims=" %%D in ('dir /ad /b /o-d "%DIST%\ImageDetector_PH_Gish_*" 2^>nul') do (
  for /f "delims=" %%E in ('dir /b /a:-d "%DIST%\%%D\ImageDetector_PH_Gish_*.exe" 2^>nul') do (
    set "EXE_PATH=%DIST%\%%D\%%E"
    goto :found
  )
)

echo [NO-CUDA] ERROR: Could not locate ImageDetector_PH_Gish_*.exe in dist.
exit /b 1

:found
for %%# in ("%EXE_PATH%") do set "EXE_DIR=%%~dp#"

REM --- no-GPU flags (effective only for this process tree) ---
set "NO_CUDA=1"
set "CUDA_VISIBLE_DEVICES="
set "TF_CPP_MIN_LOG_LEVEL=2"

echo [NO-CUDA] Launching CPU-only run:
echo   EXE = "%EXE_PATH%"
echo   NO_CUDA=%NO_CUDA%  CUDA_VISIBLE_DEVICES="%CUDA_VISIBLE_DEVICES%"
echo.

pushd "%EXE_DIR%"
"%EXE_PATH%"
set "RC=%ERRORLEVEL%"
popd

echo.
echo [NO-CUDA] App exited with code %RC%
endlocal & exit /b %RC%
