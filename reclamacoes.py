import os
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   session, current_app, send_from_directory, abort, jsonify)
from werkzeug.utils import secure_filename

from auth import _validar_usuario
from models import db, Reclamacao, Cliente, MembroEquipe, Evidencia, Historico, Usuario, STATUS
from servicos import (write_lock, registrar, gerar_codigo, normalizar_pn, normalizar_modo,
                      buscar_recorrencias, aplicar_campos, converter, ABAS, CAMPOS,
                      STATUS_EDITAVEIS)

bp = Blueprint("rec", __name__)

EXTENSOES = {"pdf", "jpg", "jpeg", "png", "gif", "bmp", "xlsx", "xls", "docx", "doc",
             "csv", "txt", "msg", "eml", "zip", "mp4"}
ABAS_IDS = [a for a, _ in ABAS]


@bp.before_request
def _exigir_login():
    if "usuario" not in session:
        return redirect(url_for("auth.login", next=request.full_path))


def _obter(rid):
    return db.get_or_404(Reclamacao, rid)


def _voltar(rec, aba):
    return redirect(url_for("rec.detalhe", rid=rec.id, aba=aba))


def _bloqueada(rec, aba):
    if rec.status == "FECHADA":
        flash("Reclamação fechada: não pode ser alterada.", "erro")
        return _voltar(rec, aba)
    return None


# ---------------- lista ----------------
@bp.route("/")
def lista():
    q = Reclamacao.query.join(Cliente)
    cliente_id = request.args.get("cliente", type=int)
    status = request.args.get("status", "")
    pn = request.args.get("pn", "").strip()
    if cliente_id:
        q = q.filter(Reclamacao.cliente_id == cliente_id)
    if status == "ABERTAS":
        q = q.filter(Reclamacao.status != "FECHADA")
    elif status in STATUS:
        q = q.filter(Reclamacao.status == status)
    if pn:
        q = q.filter(Reclamacao.part_number.ilike(f"%{pn}%"))
    recs = q.order_by(Reclamacao.data_recebimento.desc()).all()
    return render_template("lista.html", recs=recs, clientes=Cliente.query.order_by(Cliente.nome).all(),
                           status_lista=STATUS, filtro={"cliente": cliente_id, "status": status, "pn": pn})


# ---------------- abertura ----------------
@bp.route("/nova", methods=["GET", "POST"])
def nova():
    clientes = Cliente.query.order_by(Cliente.nome).all()
    if request.method == "POST":
        f = request.form
        cliente = db.session.get(Cliente, f.get("cliente_id", type=int) or 0)
        pn, modo = normalizar_pn(f.get("part_number")), normalizar_modo(f.get("modo_falha"))
        try:
            qtd = converter("int", f.get("qtd_suspeita"))
            recebida = converter("datetime", f.get("data_recebimento")) or datetime.now()
        except ValueError:
            qtd = recebida = None
        if not cliente or not pn or not modo or recebida is None:
            flash("Preencha cliente, part number e modo de falha (e números/datas válidos).", "erro")
            return render_template("nova.html", clientes=clientes, f=f)

        with write_lock:
            rec = Reclamacao(codigo=gerar_codigo(), cliente_id=cliente.id,
                             num_reclamacao_cliente=f.get("num_reclamacao_cliente", "").strip() or None,
                             part_number=pn, lote=f.get("lote", "").strip() or None,
                             qtd_suspeita=qtd, modo_falha=modo, data_recebimento=recebida)
            db.session.add(rec)
            db.session.flush()
            registrar(rec.id, f"Reclamação aberta ({cliente.nome}, PN {pn}, {modo})")
            db.session.commit()

        recs = buscar_recorrencias(pn, modo, excluir_id=rec.id)
        if recs:
            flash("RECORRÊNCIA: mesmo PN e modo de falha já reclamados em "
                  + ", ".join(r.codigo for r in recs), "alerta")
        flash(f"Reclamação {rec.codigo} aberta.", "ok")
        return _voltar(rec, "DADOS")
    return render_template("nova.html", clientes=clientes, f={})


@bp.route("/api/recorrencias")
def api_recorrencias():
    recs = buscar_recorrencias(request.args.get("pn"), request.args.get("modo"))
    return jsonify([{"codigo": r.codigo, "cliente": r.cliente.nome, "status": r.status,
                     "data": r.data_recebimento.strftime("%d/%m/%Y")} for r in recs])


# ---------------- detalhe ----------------
@bp.route("/<int:rid>")
def detalhe(rid):
    rec = _obter(rid)
    aba = request.args.get("aba", "DADOS")
    if aba not in ABAS_IDS:
        aba = "DADOS"
    evidencias = Evidencia.query.filter_by(reclamacao_id=rec.id, etapa=aba).all()
    historico = (Historico.query.filter_by(reclamacao_id=rec.id)
                 .order_by(Historico.momento.desc(), Historico.id.desc()).all()) if aba == "HIST" else []
    return render_template("detalhe.html", rec=rec, aba=aba, abas=ABAS, campos=CAMPOS.get(aba, []),
                           evidencias=evidencias, historico=historico,
                           recorrencias=buscar_recorrencias(rec.part_number, rec.modo_falha, rec.id),
                           status_editaveis=STATUS_EDITAVEIS)


@bp.route("/<int:rid>/salvar/<aba>", methods=["POST"])
def salvar(rid, aba):
    if aba not in CAMPOS:
        abort(404)
    rec = _obter(rid)
    if (r := _bloqueada(rec, aba)):
        return r
    with write_lock:
        try:
            mudancas = aplicar_campos(rec, aba, request.form)
        except ValueError as e:
            db.session.rollback()
            flash(f"Valor inválido em: {e}", "erro")
            return _voltar(rec, aba)
        for m in mudancas:
            registrar(rec.id, m)
        db.session.commit()
    flash(f"{len(mudancas)} alteração(ões) salva(s)." if mudancas else "Nada foi alterado.", "ok")
    return _voltar(rec, aba)


# ---------------- D1 equipe ----------------
@bp.route("/<int:rid>/equipe", methods=["POST"])
def equipe_add(rid):
    rec = _obter(rid)
    if (r := _bloqueada(rec, "D1")):
        return r
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome do membro.", "erro")
        return _voltar(rec, "D1")
    lider = request.form.get("lider") == "on"
    with write_lock:
        db.session.add(MembroEquipe(reclamacao_id=rec.id, nome=nome,
                                    funcao=request.form.get("funcao", "").strip() or None, lider=lider))
        registrar(rec.id, f"D1 · Membro incluído: {nome}{' (líder)' if lider else ''}")
        db.session.commit()
    return _voltar(rec, "D1")


@bp.route("/<int:rid>/equipe/<int:mid>/remover", methods=["POST"])
def equipe_remover(rid, mid):
    rec = _obter(rid)
    if (r := _bloqueada(rec, "D1")):
        return r
    m = db.get_or_404(MembroEquipe, mid)
    if m.reclamacao_id != rec.id:
        abort(404)
    with write_lock:
        registrar(rec.id, f"D1 · Membro removido: {m.nome}")
        db.session.delete(m)
        db.session.commit()
    return _voltar(rec, "D1")


# ---------------- evidências ----------------
@bp.route("/<int:rid>/evidencia/<aba>", methods=["POST"])
def evidencia_upload(rid, aba):
    if aba not in ABAS_IDS or aba == "HIST":
        abort(404)
    rec = _obter(rid)
    if (r := _bloqueada(rec, aba)):
        return r
    arq = request.files.get("arquivo")
    nome = secure_filename(arq.filename) if arq and arq.filename else ""
    if not nome or nome.rsplit(".", 1)[-1].lower() not in EXTENSOES or "." not in nome:
        flash("Arquivo ausente ou tipo não permitido.", "erro")
        return _voltar(rec, aba)
    salvo = Evidencia.nome_seguro(nome)
    with write_lock:
        arq.save(os.path.join(current_app.config["UPLOAD_FOLDER"], salvo))
        db.session.add(Evidencia(reclamacao_id=rec.id, etapa=aba, arquivo=salvo,
                                 descricao=request.form.get("descricao", "").strip()[:200] or None))
        registrar(rec.id, f"{aba} · Evidência anexada: {nome}")
        db.session.commit()
    flash("Evidência anexada.", "ok")
    return _voltar(rec, aba)


@bp.route("/evidencia/<int:eid>")
def evidencia_baixar(eid):
    ev = db.get_or_404(Evidencia, eid)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], ev.arquivo,
                               as_attachment=True, download_name=ev.arquivo.split("_", 1)[-1])


@bp.errorhandler(413)
def _grande_demais(_):
    flash("Arquivo maior que 20 MB.", "erro")
    return redirect(request.referrer or url_for("rec.lista"))


# ---------------- usuários ----------------
@bp.route("/usuarios", methods=["GET", "POST"])
def usuarios():
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
            flash(f"Usuário '{login_}' criado.", "ok")
        return redirect(url_for("rec.usuarios"))
    return render_template("usuarios.html", usuarios=Usuario.query.order_by(Usuario.nome).all())


@bp.route("/usuarios/<int:uid>/ativo", methods=["POST"])
def usuario_ativo(uid):
    u = db.get_or_404(Usuario, uid)
    if u.login == session["usuario"]:
        flash("Você não pode desativar o próprio usuário.", "erro")
    else:
        with write_lock:
            u.ativo = not u.ativo
            db.session.commit()
        flash(f"Usuário '{u.login}' {'ativado' if u.ativo else 'desativado'}.", "ok")
    return redirect(url_for("rec.usuarios"))


@bp.route("/usuarios/<int:uid>/senha", methods=["POST"])
def usuario_senha(uid):
    u = db.get_or_404(Usuario, uid)
    erro = _validar_usuario(u.login, u.nome, request.form.get("senha", ""), request.form.get("confirmacao", ""))
    if erro:
        flash(erro, "erro")
    else:
        with write_lock:
            u.definir_senha(request.form["senha"])
            db.session.commit()
        flash(f"Senha de '{u.login}' redefinida.", "ok")
    return redirect(url_for("rec.usuarios"))
