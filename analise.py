"""Fase 2: Ishikawa (6M), 5 Porquês, ações D5/D6, fechamento do 8D e dashboard."""
from collections import Counter
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort

from models import db, Reclamacao, Cliente, CausaIshikawa, Porque, Acao, CATEGORIAS_6M
from servicos import write_lock, registrar, converter

bp = Blueprint("ana", __name__)

SITUACOES = ["EM_ANALISE", "PROVAVEL", "DESCARTADA"]
TIPOS_PORQUE = {"OCORRENCIA": "Ocorrência", "NAO_DETECCAO": "Não detecção"}
TIPOS_ACAO = ["CORRETIVA", "PREVENTIVA"]
STATUS_ACAO = ["ABERTA", "EM_ANDAMENTO", "CONCLUIDA"]


@bp.before_request
def _exigir_login():
    if "usuario" not in session:
        return redirect(url_for("auth.login", next=request.full_path))


def _rec_editavel(rid, aba):
    rec = db.get_or_404(Reclamacao, rid)
    if rec.status == "FECHADA":
        flash("Reclamação fechada: não pode ser alterada.", "erro")
        return rec, redirect(url_for("rec.detalhe", rid=rec.id, aba=aba))
    return rec, None


def _filho(modelo, oid, rec):
    obj = db.get_or_404(modelo, oid)
    if obj.reclamacao_id != rec.id:
        abort(404)
    return obj


def _voltar(rec, aba, ancora=""):
    return redirect(url_for("rec.detalhe", rid=rec.id, aba=aba) + ancora)


# ---------------- Ishikawa ----------------
@bp.route("/<int:rid>/causas", methods=["POST"])
def causa_add(rid):
    rec, bloqueio = _rec_editavel(rid, "D4")
    if bloqueio:
        return bloqueio
    cat = request.form.get("categoria")
    desc = request.form.get("descricao", "").strip()
    if cat not in CATEGORIAS_6M or not desc:
        flash("Escolha a categoria 6M e descreva a causa.", "erro")
        return _voltar(rec, "D4", "#ishikawa")
    with write_lock:
        db.session.add(CausaIshikawa(reclamacao_id=rec.id, categoria=cat, descricao=desc))
        registrar(rec.id, f"D4 · Causa incluída [{cat}]: {desc}")
        db.session.commit()
    return _voltar(rec, "D4", "#ishikawa")


@bp.route("/<int:rid>/causas/<int:cid>", methods=["POST"])
def causa_salvar(rid, cid):
    rec, bloqueio = _rec_editavel(rid, "D4")
    if bloqueio:
        return bloqueio
    c = _filho(CausaIshikawa, cid, rec)
    situacao = request.form.get("situacao")
    evidencia = request.form.get("evidencia", "").strip() or None
    if situacao not in SITUACOES:
        abort(400)
    if situacao == "DESCARTADA" and not evidencia:
        flash("Para DESCARTAR uma causa é obrigatório informar a evidência.", "erro")
        return _voltar(rec, "D4", f"#causa-{c.id}")
    with write_lock:
        if c.situacao != situacao:
            registrar(rec.id, f"D4 · Causa '{c.descricao[:60]}': {c.situacao} → {situacao}")
            c.situacao = situacao
        if c.evidencia != evidencia:
            registrar(rec.id, f"D4 · Evidência da causa '{c.descricao[:60]}': {evidencia or '(vazio)'}")
            c.evidencia = evidencia
        db.session.commit()
    return _voltar(rec, "D4", f"#causa-{c.id}")


# ---------------- 5 Porquês ----------------
@bp.route("/<int:rid>/causas/<int:cid>/excluir", methods=["POST"])
def causa_excluir(rid, cid):
    rec, bloqueio = _rec_editavel(rid, "D4")
    if bloqueio:
        return bloqueio
    c = _filho(CausaIshikawa, cid, rec)
    with write_lock:
        Porque.query.filter_by(causa_id=c.id).delete()   # a cadeia de porquês sai junto
        registrar(rec.id, f"D4 · Causa excluída [{c.categoria}]: {c.descricao}")
        db.session.delete(c)
        db.session.commit()
    return _voltar(rec, "D4", "#ishikawa")


@bp.route("/<int:rid>/causas/<int:cid>/porques/<tipo>", methods=["POST"])
def porques_salvar(rid, cid, tipo):
    if tipo not in TIPOS_PORQUE:
        abort(404)
    rec, bloqueio = _rec_editavel(rid, "D4")
    if bloqueio:
        return bloqueio
    c = _filho(CausaIshikawa, cid, rec)
    if c.situacao != "PROVAVEL":
        flash("5 Porquês só pode ser feito em causa PROVÁVEL.", "erro")
        return _voltar(rec, "D4", f"#causa-{c.id}")
    novas = []
    for n in range(1, 6):
        p = request.form.get(f"pergunta{n}", "").strip()
        r = request.form.get(f"resposta{n}", "").strip()
        if p or r:
            novas.append((p or f"Por que? ({n})", r))
    with write_lock:
        antigas = Porque.query.filter_by(reclamacao_id=rec.id, causa_id=c.id, tipo=tipo).all()
        for a in antigas:
            db.session.delete(a)
        for ordem, (p, r) in enumerate(novas, 1):
            db.session.add(Porque(reclamacao_id=rec.id, causa_id=c.id, tipo=tipo, ordem=ordem,
                                  pergunta=p, resposta=r or None))
        resumo = " | ".join(f"{i}. {r or '?'}" for i, (_, r) in enumerate(novas, 1)) or "(removida)"
        registrar(rec.id, f"D4 · 5 Porquês {TIPOS_PORQUE[tipo]} da causa '{c.descricao[:50]}': {resumo}")
        db.session.commit()
    flash(f"5 Porquês de {TIPOS_PORQUE[tipo].lower()} salvo.", "ok")
    return _voltar(rec, "D4", f"#causa-{c.id}")


# ---------------- Ações D5/D6 ----------------
@bp.route("/<int:rid>/acoes", methods=["POST"])
def acao_add(rid):
    rec, bloqueio = _rec_editavel(rid, "D5")
    if bloqueio:
        return bloqueio
    f = request.form
    try:
        prazo = datetime.strptime(f.get("prazo", ""), "%Y-%m-%d").date()
    except ValueError:
        prazo = None
    desc, resp = f.get("descricao", "").strip(), f.get("responsavel", "").strip()
    if (f.get("tipo") not in TIPOS_ACAO or f.get("foco") not in TIPOS_PORQUE
            or not desc or not resp or not prazo):
        flash("Preencha tipo, foco, descrição, responsável e prazo.", "erro")
        return _voltar(rec, "D5")
    with write_lock:
        db.session.add(Acao(reclamacao_id=rec.id, tipo=f["tipo"], foco=f["foco"], descricao=desc,
                            responsavel=resp, prazo=prazo))
        registrar(rec.id, f"D5 · Ação incluída [{f['tipo']}/{f['foco']}] {desc} - {resp} até {prazo:%d/%m/%Y}")
        db.session.commit()
    return _voltar(rec, "D5")


@bp.route("/<int:rid>/acoes/<int:aid>", methods=["POST"])
def acao_status(rid, aid):
    rec, bloqueio = _rec_editavel(rid, "D6")
    if bloqueio:
        return bloqueio
    a = _filho(Acao, aid, rec)
    novo = request.form.get("status")
    if novo not in STATUS_ACAO:
        abort(400)
    try:
        concluida = converter("datetime", request.form.get("concluida_em"))
    except ValueError:
        concluida = None
    if novo == "CONCLUIDA":
        concluida = concluida or datetime.now()
    else:
        concluida = None
    with write_lock:
        if a.status != novo or a.concluida_em != concluida:
            registrar(rec.id, f"D6 · Ação '{a.descricao[:60]}': {a.status} → {novo}"
                      + (f" em {concluida:%d/%m/%Y %H:%M}" if concluida else ""))
            a.status, a.concluida_em = novo, concluida
            db.session.commit()
    return _voltar(rec, "D6")


@bp.route("/<int:rid>/acoes/<int:aid>/excluir", methods=["POST"])
def acao_excluir(rid, aid):
    rec, bloqueio = _rec_editavel(rid, "D5")
    if bloqueio:
        return bloqueio
    a = _filho(Acao, aid, rec)
    with write_lock:
        registrar(rec.id, f"D5 · Ação excluída [{a.tipo}/{a.foco}]: {a.descricao}")
        db.session.delete(a)
        db.session.commit()
    return _voltar(rec, request.form.get("aba") if request.form.get("aba") in ("D5", "D6") else "D5")


# ---------------- Fechar 8D ----------------
@bp.route("/<int:rid>/fechar", methods=["POST"])
def fechar(rid):
    rec, bloqueio = _rec_editavel(rid, "D8")
    if bloqueio:
        return bloqueio
    with write_lock:
        pend = rec.pendencias_para_fechar()
        if pend:
            flash("Não é possível fechar: há pendências.", "erro")
            return _voltar(rec, "D8")
        rec.status = "FECHADA"
        rec.fechada_em = datetime.now()
        registrar(rec.id, "8D FECHADO")
        db.session.commit()
    flash(f"{rec.codigo} fechada.", "ok")
    return _voltar(rec, "D8")


# ---------------- Dashboard ----------------
@bp.route("/dashboard")
def dashboard():
    cliente_id = request.args.get("cliente", type=int)
    ano = request.args.get("ano", type=int)
    q = Reclamacao.query
    if cliente_id:
        q = q.filter(Reclamacao.cliente_id == cliente_id)
    recs = [r for r in q.all() if not ano or r.data_recebimento.year == ano]

    por_cliente = Counter(r.cliente.nome for r in recs)
    abertas_cliente = Counter(r.cliente.nome for r in recs if r.status != "FECHADA")
    clientes = [(n, por_cliente[n], abertas_cliente[n]) for n, _ in por_cliente.most_common()]

    pareto, acumulado = [], 0
    modos = Counter(r.modo_falha for r in recs)
    for modo, n in modos.most_common():
        acumulado += n
        pareto.append((modo, n, round(100 * acumulado / len(recs))))

    prazo = []
    for etapa, nome in (("D3", "Contenção (D3)"), ("D4", "Causa raiz (D4)"), ("D8", "Fechamento (D8)")):
        sem = Counter(r.semaforo(etapa) for r in recs)
        concl = [r for r in recs if {"D3": r.d3_concluida_em, "D4": r.d4_concluida_em, "D8": r.fechada_em}[etapa]]
        no_prazo = sum(1 for r in concl if r.semaforo(etapa) == "verde")
        prazo.append({"nome": nome, "concluidas": len(concl), "no_prazo": no_prazo,
                      "pct": round(100 * no_prazo / len(concl)) if concl else None,
                      "vencidas_abertas": sem["vermelho"]})

    # indicadores gerais
    fechadas = [r for r in recs if r.fechada_em]
    dias_fechar = [(r.fechada_em - r.data_recebimento).days for r in fechadas]
    hoje = datetime.now().date()
    acoes = [a for r in recs for a in r.acoes]
    concl = [a for a in acoes if a.status == "CONCLUIDA" and a.concluida_em]
    indicadores = {
        "abertas": len(recs) - len(fechadas), "fechadas": len(fechadas),
        "media_fechar": round(sum(dias_fechar) / len(dias_fechar)) if dias_fechar else None,
        "reincidentes": sum(1 for r in recs if r.recorrencias()),
        "acoes": len(acoes), "acoes_vencidas": sum(1 for a in acoes if a.status != "CONCLUIDA" and a.prazo < hoje),
        "acoes_no_prazo": round(100 * sum(1 for a in concl if a.concluida_em.date() <= a.prazo) / len(concl)) if concl else None,
    }

    # por mês: o ano filtrado, ou os últimos 12 meses
    if ano:
        meses = [(ano, m) for m in range(1, 13)]
    else:
        y, m = hoje.year, hoje.month
        meses = []
        for _ in range(12):
            meses.insert(0, (y, m))
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    cont_mes = Counter((r.data_recebimento.year, r.data_recebimento.month) for r in recs)
    por_mes = [(f"{m:02d}/{str(y)[2:]}", cont_mes[(y, m)]) for y, m in meses]

    pecas = Counter(r.part_number for r in recs).most_common(10)

    custo_cliente, custo_tipo = Counter(), Counter()
    for r in recs:
        for c in r.custos:
            custo_cliente[r.cliente.nome] += c.valor
            custo_tipo[c.tipo] += c.valor
    custos = {"total": sum(custo_cliente.values()), "cliente": custo_cliente.most_common(),
              "tipo": custo_tipo.most_common(),
              "top": sorted((r for r in recs if r.custos), key=lambda r: r.custo_total, reverse=True)[:5]}

    anos = sorted({r.data_recebimento.year for r in Reclamacao.query.all()}, reverse=True)
    return render_template("dashboard.html", total=len(recs), ind=indicadores, por_mes=por_mes,
                           maior_mes=max((n for _, n in por_mes), default=0) or 1, pecas=pecas, custos=custos, clientes=clientes, pareto=pareto,
                           maior=max(modos.values(), default=1), prazo=prazo, anos=anos,
                           lista_clientes=Cliente.query.order_by(Cliente.nome).all(),
                           filtro={"cliente": cliente_id, "ano": ano})
