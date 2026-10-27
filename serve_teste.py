"""Sobe a aplicação usando o banco de TESTE (instance/teste.db). Só para testes."""
import os

os.environ["RECLAMACAO_DB"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "teste.db")

from waitress import serve  # noqa: E402
from app import create_app  # noqa: E402

if __name__ == "__main__":
    serve(create_app(), host="127.0.0.1", port=int(os.environ.get("PORT", 5007)), threads=8)
