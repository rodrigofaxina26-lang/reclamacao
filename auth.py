from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from models import db, Usuario
from servicos import write_lock

bp = Blueprint("auth", __name__)


def _validar_usuario(login, nome, senha, confirmacao):
    if not login or " " in login:
        return "Login obrigatório e sem espaços."
    if not nome:
        return "Nome obrigatório."
    if len(senha) < 6:
        return "A senha precisa ter pelo menos 6 caracteres."
    if senha != confirmacao:
        return "As senhas não conferem."
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not Usuario.query.first():
        return redirect(url_for("auth.primeiro_acesso"))
    if request.method == "POST":
        u = Usuario.query.filter_by(login=request.form.get("login", "").strip()).first()
        if u and not u.ativo and u.conferir_senha(request.form.get("senha", "")):
            flash("Conta desativada. Peça a um usuário do sistema para ativá-la na tela Usuários.", "erro")
        elif u and u.conferir_senha(request.form.get("senha", "")):
            session.clear()
            session["usuario"] = u.login
            session["nome"] = u.nome
            destino = request.args.get("next", "")
            # só aceita caminho local, evita redirecionamento para fora
            if not destino.startswith("/") or destino.startswith("//"):
                destino = url_for("rec.lista")
            return redirect(destino)
        else:
            flash("Usuário ou senha inválidos.", "erro")
    return render_template("login.html")


@bp.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Só funciona enquanto o banco não tem nenhum usuário."""
    if Usuario.query.first():
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        f = request.form
        login_, nome = f.get("login", "").strip(), f.get("nome", "").strip()
        erro = _validar_usuario(login_, nome, f.get("senha", ""), f.get("confirmacao", ""))
        if erro:
            flash(erro, "erro")
        else:
            with write_lock:
                if not Usuario.query.first():
                    u = Usuario(login=login_, nome=nome, admin=True)
                    u.definir_senha(f["senha"])
                    db.session.add(u)
                    db.session.commit()
            flash("Usuário criado. Entre com o login e a senha.", "ok")
            return redirect(url_for("auth.login"))
    return render_template("usuario_form.html", titulo="Primeiro acesso",
                           aviso="Nenhum usuário cadastrado ainda. Crie o primeiro usuário do sistema.")


@bp.route("/criar-conta", methods=["GET", "POST"])
def criar_conta():
    """Cadastro pela tela de login. A conta já nasce ativa."""
    if request.method == "POST":
        f = request.form
        login_, nome = f.get("login", "").strip(), f.get("nome", "").strip()
        erro = _validar_usuario(login_, nome, f.get("senha", ""), f.get("confirmacao", ""))
        if not erro and Usuario.query.filter_by(login=login_).first():
            erro = f"O login '{login_}' já existe."
        if erro:
            flash(erro, "erro")
        else:
            with write_lock:
                u = Usuario(login=login_, nome=nome)
                u.definir_senha(f["senha"])
                db.session.add(u)
                db.session.commit()
            flash("Conta criada. Entre com o login e a senha.", "ok")
            return redirect(url_for("auth.login"))
    return render_template("usuario_form.html", titulo="Criar conta")


@bp.route("/minha-senha", methods=["GET", "POST"])
def minha_senha():
    if "usuario" not in session:
        return redirect(url_for("auth.login"))
    u = Usuario.query.filter_by(login=session["usuario"]).first_or_404()
    if request.method == "POST":
        f = request.form
        if not u.conferir_senha(f.get("atual", "")):
            flash("Senha atual incorreta.", "erro")
        elif (erro := _validar_usuario(u.login, u.nome, f.get("senha", ""), f.get("confirmacao", ""))):
            flash(erro, "erro")
        else:
            with write_lock:
                u.definir_senha(f["senha"])
                db.session.commit()
            flash("Senha alterada.", "ok")
            return redirect(url_for("rec.lista"))
    return render_template("minha_senha.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
