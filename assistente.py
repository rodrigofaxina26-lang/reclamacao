"""Fase 3: assistente de análise com o Claude.

Fluxo: anexar e-mail do cliente -> coletar histórico nos outros sistemas -> mostrar EXATAMENTE o
que será enviado -> usuário confirma -> Claude devolve SUGESTÕES -> usuário aceita uma a uma.
Nada é gravado no 8D sem clique do usuário; tudo que é aceito vai para o Historico.
Arquivos da análise ficam em instance/analises/<id>/ (fora do banco: são rascunho, não 8D).
"""
import base64
import email
import email.policy
import json
import os
from datetime import datetime

from flask import (Blueprint, current_app, flash, redirect, render_template, request, session,
                   url_for)
from werkzeug.utils import secure_filename

import fontes
from analise import TIPOS_ACAO, TIPOS_PORQUE, _rec_editavel
from models import CATEGORIAS_6M, Acao, CausaIshikawa, Reclamacao, db
from servicos import registrar, write_lock

bp = Blueprint("ia", __name__)

MODELO = "claude-opus-5-5"
EXT_EMAIL = {".eml", ".pdf", ".txt", ".png", ".jpg", ".jpeg"}
MIDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

INSTRUCOES = """Você é um engenheiro de qualidade sênior de uma estamparia automotiva (Pro-Metal),
ajudando a montar um 8D para uma reclamação de cliente. Responda em português do Brasil.

Você recebe: a reclamação cadastrada, o e-mail/anexo do cliente e o histórico interno da peça
(cartões amarelo/vermelho, refugo por modo de falha e turno, alertas de qualidade, reclamações
anteriores e ações já tomadas).

Regras:
- Baseie cada causa e ação nos dados recebidos e diga em "base" qual dado a sustenta. Se uma
  hipótese não tiver dado que a apoie, diga que é hipótese a verificar.
- Nunca invente números, datas, lotes ou registros que não estejam nos dados.
- Considere sempre as duas pernas: por que OCORREU e por que NÃO FOI DETECTADO.
- Se uma ação parecida já foi tomada antes para a mesma peça/modo de falha e o problema voltou,
  aponte isso: a ação anterior não foi eficaz.
- As fontes marcadas com erro não foram lidas; não tire conclusões sobre elas.
- Categorias 6M aceitas: """ + ", ".join(CATEGORIAS_6M) + "."

_txt = {"type": "string"}
ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resumo_email", "leitura_historico", "causas", "porques_ocorrencia",
                 "porques_nao_deteccao", "acoes", "dados_faltando"],
    "properties": {
        "resumo_email": _txt,
        "leitura_historico": _txt,
        "causas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["categoria", "descricao", "base"],
            "properties": {"categoria": {"type": "string", "enum": CATEGORIAS_6M},
                           "descricao": _txt, "base": _txt}}},
        "porques_ocorrencia": {"type": "array", "items": _txt},
        "porques_nao_deteccao": {"type": "array", "items": _txt},
        "acoes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["tipo", "foco", "descricao", "base"],
            "properties": {"tipo": {"type": "string", "enum": TIPOS_ACAO},
                           "foco": {"type": "string", "enum": list(TIPOS_PORQUE)},
                           "descricao": _txt, "base": _txt}}},
        "dados_faltando": {"type": "array", "items": _txt},
    },
}


@bp.before_request
def _exigir_login():
    if "usuario" not in session:
        return redirect(url_for("auth.login", next=request.full_path))


# ---------------- arquivos da análise ----------------
def _pasta(rid):
    p = os.path.join(current_app.instance_path, "analises", str(rid))
    os.makedirs(p, exist_ok=True)
    return p


def _ler(rid, nome):
    caminho = os.path.join(_pasta(rid), nome)
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _gravar(rid, nome, dados):
    with open(os.path.join(_pasta(rid), nome), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1, default=str)


def _chave_api():
    caminho = os.path.join(current_app.instance_path, "anthropic_key.txt")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return f.read().strip() or None
    return os.environ.get("ANTHROPIC_API_KEY")


# ---------------- leitura do e-mail ----------------
def _ler_email(nome, conteudo):
    """Devolve (texto, anexos) onde anexos = [(nome, media_type, bytes)] para PDF/imagem."""
    ext = os.path.splitext(nome)[1].lower()
    if ext == ".txt":
        return conteudo.decode("utf-8", errors="replace"), []
    if ext in MIDIA:
        return "", [(nome, MIDIA[ext], conteudo)]
    msg = email.message_from_bytes(conteudo, policy=email.policy.default)
    corpo = msg.get_body(preferencelist=("plain", "html"))
    texto = (f"De: {msg['from']}\nPara: {msg['to']}\nData: {msg['date']}\nAssunto: {msg['subject']}\n\n"
             + (corpo.get_content() if corpo else ""))
    anexos = []
    for parte in msg.iter_attachments():
        n = parte.get_filename() or "anexo"
        e = os.path.splitext(n)[1].lower()
        if e in MIDIA:
            anexos.append((n, MIDIA[e], parte.get_payload(decode=True)))
    return texto, anexos


def _dados_reclamacao(rec):
    campos = [("Código interno", rec.codigo), ("Cliente", rec.cliente.nome),
              ("Nº reclamação do cliente", rec.num_reclamacao_cliente), ("Part number", rec.part_number),
              ("Lote", rec.lote), ("Qtd. suspeita", rec.qtd_suspeita), ("Modo de falha", rec.modo_falha),
              ("D2 O quê", rec.d2_o_que), ("D2 Onde", rec.d2_onde), ("D2 Quando", rec.d2_quando),
              ("D2 Como", rec.d2_como), ("D2 Quanto", rec.d2_quanto)]
    return "\n".join(f"{k}: {v}" for k, v in campos if v not in (None, ""))


def _montar_texto(rec, pacote):
    partes = ["## Reclamação cadastrada", _dados_reclamacao(rec)]
    if pacote.get("email_texto"):
        partes += ["## E-mail do cliente", pacote["email_texto"]]
    if pacote.get("observacao"):
        partes += ["## Observações do analista", pacote["observacao"]]
    partes.append("## Histórico interno da peça " + (rec.part_number or ""))
    for f in pacote["fontes"]:
        if not f["ok"]:
            partes.append(f"### {f['fonte']}: NÃO LIDA (erro: {f['erro']})")
            continue
        extra = f" (mostrando {len(f['registros'])} de {f['total']})" if f["total"] > len(f["registros"]) else ""
        partes.append(f"### {f['fonte']}: {f['total']} registro(s){extra}")
        partes += [json.dumps(r, ensure_ascii=False) for r in f["registros"]]
    return "\n".join(partes)


# ---------------- rotas ----------------
@bp.route("/<int:rid>/assistente")
def tela(rid):
    rec = db.get_or_404(Reclamacao, rid)
    pacote, resultado = _ler(rid, "pacote.json"), _ler(rid, "resultado.json")
    texto = _montar_texto(rec, pacote) if pacote else ""
    return render_template("assistente.html", rec=rec, pacote=pacote, texto=texto, resultado=resultado,
                           tem_chave=bool(_chave_api()), ext=", ".join(sorted(EXT_EMAIL)),
                           tipos_porque=TIPOS_PORQUE, hoje=datetime.now().date())


@bp.route("/<int:rid>/assistente/coletar", methods=["POST"])
def coletar(rid):
    rec = db.get_or_404(Reclamacao, rid)
    if not rec.part_number:
        flash("Cadastre o part number antes de usar o assistente.", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    pasta = _pasta(rid)
    pacote = {"coletado_em": datetime.now(), "por": session.get("usuario"),
              "observacao": request.form.get("observacao", "").strip(), "email_texto": "", "anexos": []}
    arq = request.files.get("email")
    if arq and arq.filename:
        nome = secure_filename(arq.filename) or "email"
        if os.path.splitext(nome)[1].lower() not in EXT_EMAIL:
            flash("Formato não aceito. Use .eml (salvar e-mail no Outlook como .eml), .pdf, .txt ou imagem. "
                  "Arquivos .msg do Outlook ainda não são lidos.", "erro")
            return redirect(url_for("ia.tela", rid=rid))
        texto, anexos = _ler_email(nome, arq.read())
        pacote["email_texto"] = texto
        for n, tipo, dados in anexos:
            n = secure_filename(n) or "anexo"
            with open(os.path.join(pasta, n), "wb") as f:
                f.write(dados)
            pacote["anexos"].append({"nome": n, "tipo": tipo})
    colado = request.form.get("email_colado", "").strip()
    if colado:
        pacote["email_texto"] = (pacote["email_texto"] + "\n\n" + colado).strip()
    pacote["fontes"] = fontes.coletar(rec.part_number, current_app.instance_path)
    _gravar(rid, "pacote.json", pacote)
    with write_lock:
        registrar(rid, "Assistente · Histórico coletado nos sistemas (ainda não enviado ao Claude)")
        db.session.commit()
    return redirect(url_for("ia.tela", rid=rid) + "#envio")


@bp.route("/<int:rid>/assistente/enviar", methods=["POST"])
def enviar(rid):
    import anthropic

    rec = db.get_or_404(Reclamacao, rid)
    pacote = _ler(rid, "pacote.json")
    chave = _chave_api()
    if not pacote or not chave:
        flash("Colete os dados primeiro e confira se a chave da API está instalada.", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    conteudo = []
    for a in pacote["anexos"]:
        with open(os.path.join(_pasta(rid), a["nome"]), "rb") as f:
            dados = base64.standard_b64encode(f.read()).decode()
        tipo_bloco = "document" if a["tipo"] == "application/pdf" else "image"
        conteudo.append({"type": tipo_bloco, "source": {"type": "base64", "media_type": a["tipo"], "data": dados}})
    conteudo.append({"type": "text", "text": _montar_texto(rec, pacote)})
    try:
        resp = anthropic.Anthropic(api_key=chave).beta.messages.create(
            model=MODELO, max_tokens=16000, system=INSTRUCOES,
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": conteudo}])
    except anthropic.AuthenticationError:
        flash("Chave da API inválida. Confira instance/anthropic_key.txt.", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    except anthropic.APIConnectionError:
        flash("Sem conexão com a API do Claude (internet/proxy).", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    except anthropic.APIStatusError as e:
        flash(f"Erro da API do Claude ({e.status_code}): {e.message}", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    if resp.stop_reason != "end_turn":
        flash(f"O Claude não concluiu a resposta (motivo: {resp.stop_reason}). Tente de novo.", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    texto = next(b.text for b in resp.content if b.type == "text")
    resultado = json.loads(texto)
    resultado.update(gerado_em=datetime.now(), por=session.get("usuario"), modelo=resp.model,
                     aceitas={"causas": [], "acoes": []},
                     tokens={"entrada": resp.usage.input_tokens, "saida": resp.usage.output_tokens})
    _gravar(rid, "resultado.json", resultado)
    with write_lock:
        registrar(rid, f"Assistente · Dados enviados ao Claude ({resp.model}); sugestões recebidas para revisão")
        db.session.commit()
    return redirect(url_for("ia.tela", rid=rid) + "#sugestoes")


@bp.route("/<int:rid>/assistente/aceitar/<tipo>/<int:i>", methods=["POST"])
def aceitar(rid, tipo, i):
    aba = "D4" if tipo == "causas" else "D5"
    rec, bloqueio = _rec_editavel(rid, aba)
    if bloqueio:
        return bloqueio
    resultado = _ler(rid, "resultado.json")
    if not resultado or tipo not in ("causas", "acoes") or not 0 <= i < len(resultado[tipo]):
        flash("Sugestão não encontrada.", "erro")
        return redirect(url_for("ia.tela", rid=rid))
    if i in resultado["aceitas"][tipo]:
        flash("Essa sugestão já foi aceita.", "erro")
        return redirect(url_for("ia.tela", rid=rid) + "#sugestoes")
    s = resultado[tipo][i]
    with write_lock:
        if tipo == "causas":
            db.session.add(CausaIshikawa(reclamacao_id=rid, categoria=s["categoria"], descricao=s["descricao"]))
            registrar(rid, f"D4 · Causa incluída a partir de sugestão do assistente [{s['categoria']}]: {s['descricao']}")
        else:
            resp = request.form.get("responsavel", "").strip()
            try:
                prazo = datetime.strptime(request.form.get("prazo", ""), "%Y-%m-%d").date()
            except ValueError:
                prazo = None
            if not resp or not prazo:
                flash("Para aceitar uma ação informe responsável e prazo.", "erro")
                return redirect(url_for("ia.tela", rid=rid) + f"#acao{i}")
            db.session.add(Acao(reclamacao_id=rid, tipo=s["tipo"], foco=s["foco"], descricao=s["descricao"],
                                responsavel=resp, prazo=prazo))
            registrar(rid, f"D5 · Ação incluída a partir de sugestão do assistente [{s['tipo']}/{s['foco']}] "
                           f"{s['descricao']} - {resp} até {prazo:%d/%m/%Y}")
        db.session.commit()
        resultado["aceitas"][tipo].append(i)
        _gravar(rid, "resultado.json", resultado)
    flash("Sugestão incluída no 8D. Revise e ajuste na aba " + aba + ".", "ok")
    return redirect(url_for("ia.tela", rid=rid) + "#sugestoes")
