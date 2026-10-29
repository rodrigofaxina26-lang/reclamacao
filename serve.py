"""Ponto de entrada do serviço Windows (waitress, porta 5007, acesso pela LAN)."""
from waitress import serve

from app import create_app
from backup import iniciar_rotina

app = create_app()

if __name__ == "__main__":
    iniciar_rotina(app)   # backup diário (só no servidor de produção)
    serve(app, host="0.0.0.0", port=5007, threads=8)
