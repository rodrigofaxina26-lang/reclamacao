"""Backup diário: banco (cópia consistente pela API de backup do SQLite) + anexos + análises da IA,
num .zip por dia. Guarda os últimos DIAS_GUARDAR. A pasta de destino fica em instance/backup.json
({"pasta": "P:\\\\...\\\\Backup 8D"}); sem o arquivo, usa instance/backups."""
import json
import os
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime

DIAS_GUARDAR = 30
PREFIXO = "backup_8d_"


def pasta_destino(instance_path):
    arq = os.path.join(instance_path, "backup.json")
    if os.path.isfile(arq):
        with open(arq, encoding="utf-8") as f:
            pasta = (json.load(f).get("pasta") or "").strip()
        if pasta:
            return pasta
    return os.path.join(instance_path, "backups")


def listar(instance_path):
    """Backups existentes, do mais novo para o mais antigo: [(nome, datetime, tamanho_mb)]."""
    pasta = pasta_destino(instance_path)
    if not os.path.isdir(pasta):
        return []
    itens = []
    for nome in os.listdir(pasta):
        if nome.startswith(PREFIXO) and nome.endswith(".zip"):
            caminho = os.path.join(pasta, nome)
            itens.append((nome, datetime.fromtimestamp(os.path.getmtime(caminho)),
                          round(os.path.getsize(caminho) / 1024 / 1024, 1)))
    return sorted(itens, key=lambda x: x[1], reverse=True)


def fazer(instance_path, banco):
    """Cria o zip de hoje (substitui o do mesmo dia) e apaga os excedentes. Devolve o caminho."""
    pasta = pasta_destino(instance_path)
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"{PREFIXO}{datetime.now():%Y-%m-%d}.zip")
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, os.path.basename(banco))
        origem, alvo = sqlite3.connect(banco), sqlite3.connect(copia)
        with alvo:
            origem.backup(alvo)          # cópia consistente mesmo com o sistema em uso
        origem.close(); alvo.close()
        provisorio = destino + ".tmp"
        with zipfile.ZipFile(provisorio, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copia, os.path.basename(banco))
            for sub in ("uploads", "analises", "fontes.json", "backup.json"):
                p = os.path.join(instance_path, sub)
                if os.path.isfile(p):
                    z.write(p, sub)
                for raiz, _, arquivos in os.walk(p):
                    for a in arquivos:
                        cam = os.path.join(raiz, a)
                        z.write(cam, os.path.relpath(cam, instance_path))
        os.replace(provisorio, destino)
    for nome, _, _ in listar(instance_path)[DIAS_GUARDAR:]:
        os.remove(os.path.join(pasta, nome))
    return destino


def iniciar_rotina(app):
    """Thread que faz o backup do dia ao subir o servidor e depois a cada hora confere se já tem o de hoje."""
    banco = app.config["SQLALCHEMY_DATABASE_URI"].removeprefix("sqlite:///")

    def laco():
        while True:
            try:
                hoje = f"{PREFIXO}{datetime.now():%Y-%m-%d}.zip"
                if not any(n == hoje for n, _, _ in listar(app.instance_path)):
                    app.logger.warning("Backup criado: %s", fazer(app.instance_path, banco))
            except Exception:
                app.logger.exception("Falha no backup automático")
            time.sleep(3600)

    threading.Thread(target=laco, daemon=True, name="backup").start()
