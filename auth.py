from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from models import Usuario

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = Usuario.query.filter_by(login=request.form.get("login", "").strip(), ativo=True).first()
        if u and u.conferir_senha(request.form.get("senha", "")):
            session.clear()
            session["usuario"] = u.login
            session["nome"] = u.nome
            destino = request.args.get("next", "")
            # só aceita caminho local, evita redirecionamento para fora
            if not destino.startswith("/") or destino.startswith("//"):
                destino = url_for("rec.lista")
            return redirect(destino)
        flash("Usuário ou senha inválidos.", "erro")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
