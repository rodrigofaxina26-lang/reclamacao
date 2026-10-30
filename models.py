"""Modelo 8D neutro - Sistema de Reclamações de Cliente Pro-Metal.
Layout de saída fica nos exportadores por cliente, nunca aqui."""
import uuid
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

STATUS = ["ABERTA", "CONTENCAO", "ANALISE", "ACOES", "VERIFICACAO", "FECHADA"]
CATEGORIAS_6M = ["Mão de obra", "Método", "Máquina", "Material", "Medição", "Meio ambiente"]


class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)       # FORVIA, BOSCH...
    template_8d = db.Column(db.String(200))                              # arquivo do template do cliente
    mapa_export = db.Column(db.String(200))                              # json: campo -> célula/marcador
    prazo_contencao_h = db.Column(db.Integer, default=24)
    prazo_causa_dias = db.Column(db.Integer, default=10)
    prazo_fechamento_dias = db.Column(db.Integer, default=60)


class Reclamacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True)                       # RC-2026-0001
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    num_reclamacao_cliente = db.Column(db.String(60))
    part_number = db.Column(db.String(60), index=True)
    lote = db.Column(db.String(60))
    qtd_suspeita = db.Column(db.Integer)
    modo_falha = db.Column(db.String(120), index=True)                   # p/ detectar recorrência
    data_recebimento = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default="ABERTA")

    # D2 - 5W2H estruturado
    d2_o_que = db.Column(db.Text)
    d2_onde = db.Column(db.Text)
    d2_quando = db.Column(db.Text)
    d2_quem = db.Column(db.Text)
    d2_como = db.Column(db.Text)
    d2_quanto = db.Column(db.Text)
    d2_por_que_problema = db.Column(db.Text)

    # D3 - contenção
    d3_estoque_qtd = db.Column(db.Integer)
    d3_estoque_nok = db.Column(db.Integer)
    d3_transito_qtd = db.Column(db.Integer)
    d3_transito_nok = db.Column(db.Integer)
    d3_cliente_qtd = db.Column(db.Integer)
    d3_cliente_nok = db.Column(db.Integer)
    d3_concluida_em = db.Column(db.DateTime)

    # D4 - validação (sem isso 5 Porquês é opinião)
    d4_causa_ocorrencia = db.Column(db.Text)
    d4_causa_nao_deteccao = db.Column(db.Text)
    d4_como_comprovada = db.Column(db.Text)
    d4_concluida_em = db.Column(db.DateTime)

    # D7 - prevenção
    d7_pfmea = db.Column(db.Boolean, default=False)
    d7_plano_controle = db.Column(db.Boolean, default=False)
    d7_instrucao_trabalho = db.Column(db.Boolean, default=False)
    d7_poka_yoke = db.Column(db.Boolean, default=False)
    d7_licoes = db.Column(db.Text)

    # D8 - eficácia
    d8_lotes_verificados = db.Column(db.Integer, default=0)
    d8_eficaz = db.Column(db.Boolean)
    fechada_em = db.Column(db.DateTime)

    cliente = db.relationship("Cliente")
    equipe = db.relationship("MembroEquipe", cascade="all, delete-orphan")
    causas = db.relationship("CausaIshikawa", cascade="all, delete-orphan")
    porques = db.relationship("Porque", cascade="all, delete-orphan",
                              order_by="Porque.tipo, Porque.ordem")
    acoes = db.relationship("Acao", cascade="all, delete-orphan")
    custos = db.relationship("Custo", cascade="all, delete-orphan", order_by="Custo.data")

    @property
    def custo_total(self):
        return sum(c.valor for c in self.custos)

    # ---- prazos (KPI que o cliente cobra) ----
    def prazo(self, etapa):
        c = self.cliente
        base = self.data_recebimento
        return {"D3": base + timedelta(hours=c.prazo_contencao_h),
                "D4": base + timedelta(days=c.prazo_causa_dias),
                "D8": base + timedelta(days=c.prazo_fechamento_dias)}[etapa]

    def semaforo(self, etapa):
        concluida = {"D3": self.d3_concluida_em, "D4": self.d4_concluida_em,
                     "D8": self.fechada_em}[etapa]
        limite = self.prazo(etapa)
        if concluida:
            return "verde" if concluida <= limite else "atrasada"
        restante = limite - datetime.now()
        if restante.total_seconds() < 0:
            return "vermelho"
        total = limite - self.data_recebimento
        return "amarelo" if restante < total * 0.25 else "verde"

    # ---- regras de bloqueio ----
    def pendencias_para_fechar(self):
        p = []
        if not self.d4_causa_nao_deteccao:
            p.append("Causa de NÃO DETECÇÃO não preenchida")
        if not self.d4_como_comprovada:
            p.append("Causa raiz sem comprovação")
        # cadeias só contam se ligadas a causa PROVAVEL e com ao menos uma resposta
        provaveis = {c.id for c in self.causas if c.situacao == "PROVAVEL"}
        tipos_ok = {x.tipo for x in self.porques if x.causa_id in provaveis and x.resposta}
        if "OCORRENCIA" not in tipos_ok:
            p.append("5 Porquês de ocorrência ausente")
        if "NAO_DETECCAO" not in tipos_ok:
            p.append("5 Porquês de não detecção ausente")
        for c in self.causas:
            if c.situacao == "DESCARTADA" and not c.evidencia:
                p.append(f"Causa descartada sem evidência: {c.descricao[:40]}")
        if not self.acoes:
            p.append("Nenhuma ação cadastrada (D5)")
        if not any(a.foco == "OCORRENCIA" for a in self.acoes):
            p.append("Sem ação com foco em OCORRÊNCIA")
        if not any(a.foco == "NAO_DETECCAO" for a in self.acoes):
            p.append("Sem ação com foco em NÃO DETECÇÃO")
        if any(a.status != "CONCLUIDA" for a in self.acoes):
            p.append("Ações em aberto")
        if (self.d8_lotes_verificados or 0) < 3:
            p.append("Eficácia: menos de 3 lotes verificados")
        if self.d8_eficaz is not True:
            p.append("Eficácia não confirmada (D8)")
        return p

    def recorrencias(self):
        return Reclamacao.query.filter(
            Reclamacao.id != self.id,
            Reclamacao.part_number == self.part_number,
            Reclamacao.modo_falha == self.modo_falha).all()


class MembroEquipe(db.Model):  # D1
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"))
    nome = db.Column(db.String(80))
    funcao = db.Column(db.String(60))
    lider = db.Column(db.Boolean, default=False)


class CausaIshikawa(db.Model):  # D4
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"))
    categoria = db.Column(db.String(20))                                  # um de CATEGORIAS_6M
    descricao = db.Column(db.Text, nullable=False)
    situacao = db.Column(db.String(12), default="EM_ANALISE")             # PROVAVEL / DESCARTADA
    evidencia = db.Column(db.Text)


class Porque(db.Model):  # D4 - cadeia ligada à causa do Ishikawa
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"))
    causa_id = db.Column(db.Integer, db.ForeignKey("causa_ishikawa.id"))
    tipo = db.Column(db.String(12))                                       # OCORRENCIA / NAO_DETECCAO
    ordem = db.Column(db.Integer)                                         # 1..5
    pergunta = db.Column(db.Text)
    resposta = db.Column(db.Text)


class Acao(db.Model):  # D5/D6
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"))
    tipo = db.Column(db.String(12))                                       # CORRETIVA / PREVENTIVA
    foco = db.Column(db.String(12))                                       # OCORRENCIA / NAO_DETECCAO
    descricao = db.Column(db.Text)
    responsavel = db.Column(db.String(80))
    prazo = db.Column(db.Date)
    status = db.Column(db.String(12), default="ABERTA")
    concluida_em = db.Column(db.DateTime)


TIPOS_CUSTO = ["Seleção / retrabalho", "Frete / transporte", "Refugo / sucata", "Técnico no cliente / viagem",
               "Débito do cliente", "Horas de engenharia / análise", "Outros"]


class Custo(db.Model):  # custo da reclamação: fica só no sistema, nunca vai para a IA
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"), index=True)
    tipo = db.Column(db.String(40))                                       # um de TIPOS_CUSTO
    descricao = db.Column(db.String(200))
    valor = db.Column(db.Float, nullable=False)                           # R$
    data = db.Column(db.Date)


class Evidencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"))
    etapa = db.Column(db.String(4))                                       # D2, D3...
    arquivo = db.Column(db.String(200))                                   # uuid_nome.ext em instance/
    descricao = db.Column(db.String(200))

    @staticmethod
    def nome_seguro(nome):
        return f"{uuid.uuid4().hex[:8]}_{nome}"


class Historico(db.Model):  # imutável, só INSERT
    id = db.Column(db.Integer, primary_key=True)
    reclamacao_id = db.Column(db.Integer, db.ForeignKey("reclamacao.id"))
    usuario = db.Column(db.String(80))
    acao = db.Column(db.String(200))
    momento = db.Column(db.DateTime, default=datetime.now)


class Usuario(db.Model):  # login (adicionado na Fase 1)
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(40), unique=True, nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    admin = db.Column(db.Boolean, default=False)   # exclui reclamações, gerencia usuários e backup

    def definir_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def conferir_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)
