@echo off
REM Atualiza o sistema de Reclamacoes 8D no servidor com um clique:
REM   1) backup do banco e anexos   2) baixa a versao nova (git pull)
REM   3) instala dependencias novas 4) reinicia o sistema (porta 5007)
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
  echo Ambiente nao encontrado. Rode o executar.bat uma vez antes.
  pause & exit /b 1
)

echo [1/4] Backup antes de atualizar...
"%PY%" -c "import os, backup; from app import create_app; a = create_app(); print('   ', backup.fazer(a.instance_path, a.config['SQLALCHEMY_DATABASE_URI'].removeprefix('sqlite:///')))"
if errorlevel 1 (
  echo Falha no backup. Atualizacao cancelada, nada foi alterado.
  pause & exit /b 1
)

echo [2/4] Baixando a versao nova...
git pull
if errorlevel 1 (
  echo Falha no git pull. O sistema continua na versao anterior.
  pause & exit /b 1
)

echo [3/4] Conferindo dependencias...
"%PY%" -m pip install -q -r requirements.txt

echo [4/4] Reiniciando o sistema...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5007 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
timeout /t 2 /nobreak >nul
start "Reclamacoes 8D" cmd /c executar.bat

echo.
echo Pronto. O sistema foi reiniciado numa janela nova.
timeout /t 5
endlocal
