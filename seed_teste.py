r"""Dados de TESTE. Nunca rodar em produção.
Grava em instance/teste.db (banco separado). Para usar a aplicação com ele:
    set RECLAMACAO_DB=<caminho>\instance\teste.db
    python app.py
"""
import os
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
os.environ["RECLAMACAO_DB"] = os.path.join(BASE, "instance", "teste.db")

from app import create_app  # noqa: E402
from models import db, Cliente, Reclamacao, Usuario, Historico  # noqa: E402
from servicos import gerar_codigo  # noqa: E402

app = create_app()
with app.app_context():
    if Reclamacao.query.count() and "--forcar" not in sys.argv:
        sys.exit("teste.db já tem dados. Use --forcar para acrescentar mais.")
    if not Usuario.query.filter_by(login="teste").first():
        u = Usuario(login="teste", nome="Usuário de Teste")
        u.definir_senha("teste")
        db.session.add(u)
    agora = datetime.now()
    casos = [  # cliente, PN, modo, dias atrás
        ("BOSCH", "PM-1001", "REBARBA EXCESSIVA", 2),
        ("BOSCH", "PM-1001", "REBARBA EXCESSIVA", 40),
        ("FORVIA", "PM-2002", "FURO FORA DE POSIÇÃO", 9),
        ("VOLVO", "PM-3003", "OXIDAÇÃO", 70),
        ("MARELLI", "PM-4004", "DIMENSIONAL FORA DE ESPECIFICAÇÃO", 1),
    ]
    for nome, pn, modo, dias in casos:
        c = Cliente.query.filter_by(nome=nome).one()
        r = Reclamacao(codigo=gerar_codigo(), cliente_id=c.id, part_number=pn, modo_falha=modo,
                       qtd_suspeita=100, data_recebimento=agora - timedelta(days=dias))
        db.session.add(r)
        db.session.flush()
        db.session.add(Historico(reclamacao_id=r.id, usuario="seed_teste", acao="Reclamação de teste criada"))
    db.session.commit()
    print("Seed de teste gravado em", os.environ["RECLAMACAO_DB"], "- login: teste / teste")
