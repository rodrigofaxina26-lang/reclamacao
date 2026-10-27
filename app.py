"""Reclamações de Cliente 8D - Pro-Metal. Factory da aplicação."""
import os
import secrets
from datetime import datetime

import click
from flask import Flask
from sqlalchemy import text

from models import db, Cliente, Usuario

CLIENTES_INICIAIS = ["FORVIA", "HWASHIN", "MARELLI", "BOSCH", "CONTINENTAL", "VOLVO"]


def _secret_key(instance_path):
    caminho = os.path.join(instance_path, "secret_key")
    if not os.path.exists(caminho):
        with open(caminho, "w") as f:
            f.write(secrets.token_hex(32))
    with open(caminho) as f:
        return f.read().strip()


def _criar_triggers():
    # Historico é só INSERT: o próprio banco recusa UPDATE/DELETE
    for evento in ("UPDATE", "DELETE"):
        db.session.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS historico_sem_{evento.lower()} "
            f"BEFORE {evento} ON historico "
            "BEGIN SELECT RAISE(ABORT, 'Historico e imutavel'); END;"))
    db.session.commit()


def _seed_clientes():
    existentes = {c.nome for c in Cliente.query.all()}
    for nome in CLIENTES_INICIAIS:
        if nome not in existentes:
            db.session.add(Cliente(nome=nome))
    db.session.commit()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    uploads = os.path.join(app.instance_path, "uploads")
    os.makedirs(uploads, exist_ok=True)

    banco = os.environ.get("RECLAMACAO_DB") or os.path.join(app.instance_path, "reclamacao.db")
    app.config.update(
        SECRET_KEY=_secret_key(app.instance_path),
        SQLALCHEMY_DATABASE_URI="sqlite:///" + banco,
        UPLOAD_FOLDER=uploads,
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        _criar_triggers()
        _seed_clientes()

    from auth import bp as auth_bp
    from reclamacoes import bp as rec_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(rec_bp)

    @app.template_filter("dt")
    def _fmt_dt(v):
        return v.strftime("%d/%m/%Y %H:%M") if v else ""

    @app.template_filter("dtinput")
    def _fmt_dtinput(v):
        return v.strftime("%Y-%m-%dT%H:%M") if v else ""

    @app.context_processor
    def _agora():
        return {"agora": datetime.now()}

    @app.cli.command("criar-usuario")
    @click.argument("login")
    @click.argument("nome")
    def criar_usuario(login, nome):
        """Cria (ou redefine a senha de) um usuário."""
        senha = click.prompt("Senha", hide_input=True, confirmation_prompt=True)
        u = Usuario.query.filter_by(login=login).first() or Usuario(login=login, nome=nome)
        u.nome = nome
        u.ativo = True
        u.definir_senha(senha)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Usuário '{login}' salvo.")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5007, debug=True)
