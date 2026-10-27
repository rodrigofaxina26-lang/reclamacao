@echo off
REM Instala o sistema de Reclamacoes 8D como servico Windows via NSSM.
REM Executar como Administrador. Requer nssm.exe no PATH e venv em .venv
setlocal
set SERVICO=Reclamacao8D
set PASTA=%~dp0
set PASTA=%PASTA:~0,-1%
set PYTHON=%PASTA%\.venv\Scripts\python.exe

where nssm >nul 2>nul
if errorlevel 1 (
  echo nssm.exe nao encontrado no PATH.
  exit /b 1
)
if not exist "%PYTHON%" (
  echo Ambiente virtual nao encontrado. Rode antes:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)
if not exist "%PASTA%\instance" mkdir "%PASTA%\instance"

nssm install %SERVICO% "%PYTHON%" "%PASTA%\serve.py"
nssm set %SERVICO% AppDirectory "%PASTA%"
nssm set %SERVICO% DisplayName "Pro-Metal - Reclamacoes 8D"
nssm set %SERVICO% Description "Sistema de resposta a reclamacoes de cliente (8D) - porta 5007"
nssm set %SERVICO% Start SERVICE_AUTO_START
nssm set %SERVICO% AppStdout "%PASTA%\instance\servico.log"
nssm set %SERVICO% AppStderr "%PASTA%\instance\servico.log"
nssm set %SERVICO% AppRotateFiles 1
nssm set %SERVICO% AppRotateBytes 5000000

netsh advfirewall firewall add rule name="Reclamacao8D porta 5007" dir=in action=allow protocol=TCP localport=5007

nssm start %SERVICO%
echo Servico %SERVICO% instalado. Acesse http://IP-DO-SERVIDOR:5007
echo Para remover: nssm stop %SERVICO% ^& nssm remove %SERVICO% confirm
endlocal
