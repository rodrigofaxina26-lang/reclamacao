@echo off
REM Executa o sistema de Reclamacoes 8D (porta 5007).
REM Na primeira vez cria o ambiente virtual e instala as dependencias.
REM Uso:  executar.bat         -> banco de producao (instance\reclamacao.db)
REM       executar.bat teste   -> banco de teste (instance\teste.db)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual...
  python -m venv .venv || (echo Python nao encontrado no PATH. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)

if /i "%1"=="teste" (
  if not exist "instance\teste.db" ".venv\Scripts\python.exe" seed_teste.py
  echo Sistema ^(TESTE^) em http://localhost:5007  -  login teste / teste
  ".venv\Scripts\python.exe" serve_teste.py
) else (
  echo Sistema em http://localhost:5007  ^(na rede: http://IP-DESTA-MAQUINA:5007^)
  ".venv\Scripts\python.exe" serve.py
)
pause
endlocal
