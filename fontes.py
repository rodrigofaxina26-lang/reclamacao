"""Fase 3: coleta de histórico nos outros sistemas da Pro-Metal (somente leitura).

Cada fonte devolve {"fonte", "ok", "erro", "registros"}. Se uma tela mudar de layout ou o
sistema estiver fora do ar, a fonte volta com ok=False e o assistente avisa - nunca inventa dado.
Endereços ficam em instance/fontes.json (criado com os valores padrão na primeira execução).
"""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser

PADRAO = {
    "cartao_amarelo": "http://192.168.1.150:5001",
    "refugo": "http://192.168.1.150:5003",
    "falhas": "http://192.168.1.150:5000",
    "materia_prima": "http://192.168.1.150:8765",
    "planilha_nc": r"P:\QUALIDADE\03. NÃO CONFORMIDADES\01. EXTERNAS"
                   r"\00. Gerenciamento de Reclamações 2026 - Externas - Rev 1.xlsx",
    "meses_historico": 12,
    # IA usada pelo assistente: "gemini" (chave em instance/gemini_key.txt)
    # ou "claude" (chave em instance/anthropic_key.txt)
    "provedor": "gemini",
    "modelo": "gemini-flash-latest",
    "modelos_reserva": ["gemini-flash-lite-latest"],
}
TIMEOUT = 15
MAX_REGISTROS = 40   # por fonte, para não estourar o pacote enviado ao Claude


def carregar_config(instance_path):
    caminho = os.path.join(instance_path, "fontes.json")
    if not os.path.exists(caminho):
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(PADRAO, f, ensure_ascii=False, indent=2)
    with open(caminho, encoding="utf-8") as f:
        return {**PADRAO, **json.load(f)}


# ---------------- leitura de tabelas HTML ----------------
class _Tabelas(HTMLParser):
    """Extrai todas as <table> como listas de linhas de texto (th e td)."""

    def __init__(self):
        super().__init__()
        self.tabelas, self._linha, self._celula = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tabelas.append([])
        elif tag == "tr" and self.tabelas:
            self._linha = []
        elif tag in ("td", "th") and self._linha is not None:
            self._celula = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._celula is not None:
            self._linha.append(" ".join(" ".join(self._celula).split()))
            self._celula = None
        elif tag == "tr" and self._linha is not None:
            if self._linha:
                self.tabelas[-1].append(self._linha)
            self._linha = None

    def handle_data(self, data):
        if self._celula is not None:
            self._celula.append(data)


def _sem_tags(m):
    return " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split()) if m else ""


def _get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def _tabela_com(html, coluna):
    """Primeira tabela cujo cabeçalho contém `coluna`, como lista de dicts."""
    p = _Tabelas()
    p.feed(html)
    for t in p.tabelas:
        if t and coluna in t[0]:
            cab = t[0]
            return [dict(zip(cab, linha)) for linha in t[1:] if len(linha) == len(cab)]
    return None


def _resultado(fonte, registros=None, erro=None):
    registros = registros or []
    return {"fonte": fonte, "ok": erro is None, "erro": erro,
            "total": len(registros), "registros": registros[:MAX_REGISTROS]}


def _inicio(cfg):
    return date.today() - timedelta(days=30 * int(cfg["meses_historico"]))


# ---------------- fontes ----------------
def cartao_amarelo(pn, cfg):
    nome = "Cartão Amarelo/Vermelho"
    try:
        vistos, regs = set(), []
        for pagina in ("lotes", "concluidos"):
            linhas = _tabela_com(_get(f"{cfg['cartao_amarelo']}/{pagina}", {"codigo_produto": pn}), "Lote")
            if linhas is None:
                if "Nenhum lote" in _get(f"{cfg['cartao_amarelo']}/{pagina}", {"codigo_produto": pn}):
                    continue
                return _resultado(nome, erro=f"tabela não encontrada em /{pagina} (a tela mudou?)")
            for l in linhas:
                if l.get("Lote") in vistos:
                    continue
                vistos.add(l.get("Lote"))
                regs.append({k: v for k, v in l.items() if k not in ("Foto", "Ações") and v not in ("", "-")})
        return _resultado(nome, regs)
    except Exception as e:  # rede, timeout, HTML inesperado
        return _resultado(nome, erro=str(e))


def refugo(pn, cfg):
    nome = "Refugo"
    params = {"produto": pn, "inicio": _inicio(cfg).isoformat(), "fim": date.today().isoformat()}
    try:
        modos = json.loads(_get(f"{cfg['refugo']}/modo_falha", params)).get("modos", [])
        turnos = json.loads(_get(f"{cfg['refugo']}/produto_turno", params)).get("turnos", [])
        regs = [{"tipo": "modo de falha", **m} for m in modos] + [{"tipo": "turno", **t} for t in turnos]
        return _resultado(nome, regs)
    except Exception as e:
        return _resultado(nome, erro=str(e))


def falhas(pn, cfg):
    nome = "Dashboard de Falhas (alertas)"
    try:
        html = _get(f"{cfg['falhas']}/alertas", {"busca": pn})
        cartoes = html.split('class="alerta-card')[1:]
        if not cartoes:
            if "Nenhum alerta" in html:
                return _resultado(nome)
            return _resultado(nome, erro="cartões de alerta não encontrados (a tela mudou?)")
        regs = []
        for c in cartoes:
            campo = lambda cls: _sem_tags(re.search(rf'class="{cls}"[^>]*>(.*?)</(div|span)>', c, re.S))
            regs.append({"alerta": campo("titulo"), "peça": campo("peca-info"), "modo": campo("modo"),
                         "tipo": "Externo" if "tipo-Externos" in c[:60] else "Interno",
                         "data": _sem_tags(re.search(r'<div class="meta">.*?</span>\s*<span>(.*?)</span>', c, re.S))})
        return _resultado(nome, regs)
    except Exception as e:
        return _resultado(nome, erro=str(e))


CAMPOS_BOBINA = ("id_bobina", "corrida", "fornecedor", "usina_origem", "codigo_mp", "data_entrada",
                 "data_certificado", "grau_aco", "espessura_mm", "largura_mm", "c", "mn", "si", "p", "s", "al",
                 "cr", "ni", "mo", "n", "ti", "cu", "nb", "le_mpa", "lr_mpa", "alongamento", "r90", "n90",
                 "dureza", "clc0", "norma", "status", "resultado")


def materia_prima(pn, cfg):
    """Certificados e CEP das bobinas (ensaios mecânicos e química) da MP usada na peça."""
    nome = "Matéria-prima (certificados e CEP)"
    try:
        # Código Pro-Metal: final "A" = peça final; "B", "B1", "C1"... = componentes estampados.
        # A MP entra nos componentes, então para a peça final buscamos todos os componentes dela
        # (mesmo código base). Ex.: FV10196A -> FV10196B1 e FV10196C1.
        pecas = json.loads(_get(f"{cfg['materia_prima']}/api/info")).get("pecas", [])
        base = re.sub(r"[A-Z]\d*$", "", pn)
        alvos = sorted({pn} & set(pecas)) + sorted(p for p in pecas if p != pn and re.sub(r"[A-Z]\d*$", "", p) == base)
        if not alvos:
            return _resultado(nome)
        if alvos != [pn]:
            nome += f" - peças consultadas: {', '.join(alvos)}"
        regs = []
        for peca in alvos[:4]:
            cep = json.loads(_get(f"{cfg['materia_prima']}/api/cep", {"peca": peca, "periodo": "tudo"}))
            regs += [{"tipo": "estatística CEP", "componente": peca, **e} for e in cep.get("estatisticas", [])]
            if cep.get("alerta_clc"):
                regs.append({"tipo": "alerta de estampagem (CLC0)", "componente": peca, "detalhe": cep["alerta_clc"]})
            bobinas = sorted(cep.get("bobinas", []), key=lambda b: b.get("id", 0), reverse=True)
            regs += [{"tipo": "bobina", "componente": peca,
                      **{k: b[k] for k in CAMPOS_BOBINA if b.get(k) not in (None, "")}}
                     for b in bobinas[:20 // len(alvos[:4])]]
            certs = json.loads(_get(f"{cfg['materia_prima']}/api/busca", {"peca": peca}))
            regs += [{"tipo": "certificado", "componente": peca,
                      **{k: c[k] for k in ("codigo_mp", "fornecedor", "material", "lote",
                                          "num_certificado", "nf", "data") if c.get(k)}}
                     for c in certs[:5]]
        return _resultado(nome, regs)
    except Exception as e:
        return _resultado(nome, erro=str(e))


def _txt(v):
    if v is None:
        return ""
    return v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else " ".join(str(v).split())


SEMAFORO = {"+G": "verde (+G)", "-G": "verde (-G)", "+Y": "amarelo (+Y)", "-Y": "amarelo (-Y)",
            "R": "VERMELHO - não realizado/atrasado (R)", "N/A": "não se aplica"}


def _cabecalho_dados(cab):
    """A aba Dados repete 'PRAZO' e 'Realizado' depois de cada etapa: renomeia para
    '<etapa> - prazo' / '<etapa> - realizado' e ignora as colunas de contagem após 'Observações'."""
    novo, etapa = [], ""
    for c in cab:
        if novo and novo[-1] == "Observações":
            novo += [""] * (len(cab) - len(novo))
            break
        if c in ("PRAZO", "Realizado"):
            novo.append(f"{etapa} - {c.lower()}")
        else:
            etapa = c if c not in novo else f"{c} (2ª vez)"   # 'CLIENTE INFORMADO' aparece 2x
            novo.append(etapa)
    return novo


def planilha_nc(pn, cfg):
    nome = "Planilha de NC externas"
    try:
        import openpyxl
        wb = openpyxl.load_workbook(cfg["planilha_nc"], read_only=True, data_only=True)
        alvo, regs = pn.upper(), []
        # aba Dados: cabeçalho na linha 5
        ws = wb["Dados"]
        linhas = ws.iter_rows(min_row=5, values_only=True)
        cab = _cabecalho_dados([_txt(c) for c in next(linhas)])
        for l in linhas:
            d = {cab[i]: SEMAFORO.get(_txt(v), _txt(v)) for i, v in enumerate(l)
                 if i < len(cab) and cab[i] and _txt(v)}
            codigos = " ".join(v for k, v in d.items() if "digo" in k).upper()
            if alvo in codigos:
                regs.append({"aba": "Dados", **d})
        # Planilha1: código -> modo de falha -> ação tomada
        if "Planilha1" in wb.sheetnames:
            for l in wb["Planilha1"].iter_rows(min_row=3, values_only=True):
                if l and l[0] and alvo in str(l[0]).upper():
                    regs.append({"aba": "Ações anteriores", "código": _txt(l[0]), "peça": _txt(l[1]),
                                 "data": _txt(l[2]), "modo de falha": _txt(l[3]), "ação": _txt(l[4])})
        wb.close()
        return _resultado(nome, regs)
    except Exception as e:
        return _resultado(nome, erro=str(e))


FONTES = [cartao_amarelo, refugo, falhas, materia_prima, planilha_nc]


def coletar(pn, instance_path):
    cfg = carregar_config(instance_path)
    return [f(pn, cfg) for f in FONTES]
