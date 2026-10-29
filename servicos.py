"""Regras de escrita compartilhadas: lock, histórico, código, recorrência e campos por aba."""
import threading
from datetime import datetime

from flask import session
from sqlalchemy import func

from models import db, Reclamacao, Historico, Usuario

write_lock = threading.Lock()

ABAS = [
    ("DADOS", "Dados"), ("D1", "D1 Equipe"), ("D2", "D2 Problema"),
    ("D3", "D3 Contenção"), ("D4", "D4 Causa raiz"), ("D5", "D5 Ações corretivas"),
    ("D6", "D6 Implementação"), ("D7", "D7 Prevenção"), ("D8", "D8 Encerramento"),
    ("HIST", "Histórico"),
]

# (campo do modelo, rótulo, tipo) - tipos: text, textarea, int, int0, datetime, bool, tri, status
CAMPOS = {
    "DADOS": [
        ("num_reclamacao_cliente", "Nº da reclamação no cliente", "text"),
        ("part_number", "Part number", "text"),
        ("lote", "Lote", "text"),
        ("qtd_suspeita", "Qtd. suspeita", "int"),
        ("modo_falha", "Modo de falha", "text"),
        ("data_recebimento", "Data de recebimento", "datetime"),
        ("status", "Status", "status"),
    ],
    "D2": [
        ("d2_o_que", "O quê?", "textarea"),
        ("d2_onde", "Onde?", "textarea"),
        ("d2_quando", "Quando?", "textarea"),
        ("d2_quem", "Quem?", "textarea"),
        ("d2_como", "Como?", "textarea"),
        ("d2_quanto", "Quanto?", "textarea"),
        ("d2_por_que_problema", "Por que é um problema?", "textarea"),
    ],
    "D3": [
        ("d3_estoque_qtd", "Estoque Pro-Metal - qtd. verificada", "int"),
        ("d3_estoque_nok", "Estoque Pro-Metal - NOK", "int"),
        ("d3_transito_qtd", "Em trânsito - qtd. verificada", "int"),
        ("d3_transito_nok", "Em trânsito - NOK", "int"),
        ("d3_cliente_qtd", "No cliente - qtd. verificada", "int"),
        ("d3_cliente_nok", "No cliente - NOK", "int"),
        ("d3_concluida_em", "Contenção concluída em", "datetime"),
    ],
    "D4": [
        ("d4_causa_ocorrencia", "Causa raiz de OCORRÊNCIA", "textarea"),
        ("d4_causa_nao_deteccao", "Causa raiz de NÃO DETECÇÃO", "textarea"),
        ("d4_como_comprovada", "Como a causa foi comprovada", "textarea"),
        ("d4_concluida_em", "Análise concluída em", "datetime"),
    ],
    "D7": [
        ("d7_pfmea", "PFMEA atualizado", "bool"),
        ("d7_plano_controle", "Plano de controle atualizado", "bool"),
        ("d7_instrucao_trabalho", "Instrução de trabalho atualizada", "bool"),
        ("d7_poka_yoke", "Poka-yoke implantado", "bool"),
        ("d7_licoes", "Lições aprendidas", "textarea"),
    ],
    "D8": [
        ("d8_lotes_verificados", "Lotes verificados após ações", "int0"),
        ("d8_eficaz", "Ações eficazes?", "tri"),
    ],
}
OBRIGATORIOS = {"part_number", "modo_falha", "data_recebimento"}


def usuario_atual():
    return session.get("usuario", "?")


def registrar(reclamacao_id, acao):
    db.session.add(Historico(reclamacao_id=reclamacao_id, usuario=usuario_atual(), acao=acao))


def normalizar_pn(pn):
    return (pn or "").strip().upper() or None


def normalizar_modo(modo):
    # recorrência compara texto exato: tira espaços duplicados e caixa
    return " ".join((modo or "").split()).upper() or None


def eh_admin():
    """Consulta o banco a cada vez: tirar o perfil de alguém vale na hora, sem novo login."""
    login = session.get("usuario")
    return bool(login and Usuario.query.filter_by(login=login, ativo=True, admin=True).first())


def gerar_codigo():
    """RC-AAAA-NNNN. Chamar dentro do write_lock."""
    prefixo = f"RC-{datetime.now().year}-"
    ultimo = db.session.query(func.max(Reclamacao.codigo)).filter(
        Reclamacao.codigo.like(prefixo + "%")).scalar()
    n = int(ultimo.rsplit("-", 1)[1]) + 1 if ultimo else 1
    # códigos de reclamações excluídas não voltam a ser usados (o histórico delas continua no banco)
    for (acao,) in db.session.query(Historico.acao).filter(Historico.acao.like(f"Reclamação {prefixo}% excluída%")):
        n = max(n, int(acao.split()[1].rsplit("-", 1)[1]) + 1)
    return f"{prefixo}{n:04d}"


def proximo_id_reclamacao():
    """O SQLite reaproveita o id da última linha apagada; o histórico de uma reclamação excluída
    ficaria grudado na nova. Chamar dentro do write_lock."""
    return max(db.session.query(func.max(Reclamacao.id)).scalar() or 0,
               db.session.query(func.max(Historico.reclamacao_id)).scalar() or 0) + 1


def buscar_recorrencias(pn, modo, excluir_id=None):
    pn, modo = normalizar_pn(pn), normalizar_modo(modo)
    if not pn or not modo:
        return []
    q = Reclamacao.query.filter(Reclamacao.part_number == pn, Reclamacao.modo_falha == modo)
    if excluir_id:
        q = q.filter(Reclamacao.id != excluir_id)
    return q.order_by(Reclamacao.data_recebimento.desc()).all()


def converter(tipo, bruto):
    bruto = (bruto or "").strip()
    if tipo == "bool":
        return bruto == "on"
    if tipo == "int0":
        return int(bruto) if bruto else 0
    if not bruto:
        return None
    if tipo == "int":
        v = int(bruto)
        if v < 0:
            raise ValueError
        return v
    if tipo == "datetime":
        return datetime.strptime(bruto, "%Y-%m-%dT%H:%M")
    if tipo == "tri":
        return {"sim": True, "nao": False}.get(bruto)
    return bruto


def _mostrar(v):
    if v is None or v == "":
        return "(vazio)"
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    return str(v)


def aplicar_campos(obj, aba, form):
    """Aplica o formulário da aba em obj. Retorna lista de textos para o histórico.
    Lança ValueError(rótulo) em valor inválido."""
    mudancas = []
    for nome, rotulo, tipo in CAMPOS[aba]:
        try:
            novo = converter(tipo, form.get(nome))
        except ValueError:
            raise ValueError(rotulo)
        if nome == "part_number":
            novo = normalizar_pn(novo)
        elif nome == "modo_falha":
            novo = normalizar_modo(novo)
        elif tipo == "status" and novo not in STATUS_EDITAVEIS:
            raise ValueError(rotulo)
        if nome in OBRIGATORIOS and novo is None:
            raise ValueError(rotulo + " (obrigatório)")
        antigo = getattr(obj, nome)
        if antigo != novo:
            setattr(obj, nome, novo)
            mudancas.append(f"{aba} · {rotulo}: {_mostrar(antigo)} → {_mostrar(novo)}")
    return mudancas


# FECHADA só pelo botão "Fechar 8D" (Fase 2), que passa por pendencias_para_fechar()
STATUS_EDITAVEIS = ["ABERTA", "CONTENCAO", "ANALISE", "ACOES", "VERIFICACAO"]
