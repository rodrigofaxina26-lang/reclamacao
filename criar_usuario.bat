@echo off
REM Cria um usuario do sistema (ou redefine a senha de um existente).
REM Basta dar dois cliques e responder as perguntas.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Rode o executar.bat uma vez antes, para instalar o sistema.
  pause & exit /b 1
)
echo === Criar usuario - Reclamacoes 8D ===
echo (Se o login ja existir, a senha dele sera redefinida.)
echo.
set /p LOGIN=Login (sem espacos, ex: rodrigo): 
set /p NOME=Nome completo: 
if "%LOGIN%"=="" (echo Login vazio. & pause & exit /b 1)
if "%NOME%"=="" set NOME=%LOGIN%
".venv\Scripts\python.exe" -m flask --app app criar-usuario "%LOGIN%" "%NOME%"
echo.
pause
endlocal
