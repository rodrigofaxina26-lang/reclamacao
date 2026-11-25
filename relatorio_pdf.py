"""Relatório 8D em PDF (reportlab): completo ou só de algumas etapas. Mostra só o que foi preenchido.
Os anexos vão junto: imagens dentro da etapa, PDFs com as páginas acrescentadas no fim do arquivo,
os demais (Excel, Word, e-mail...) listados. Custos e histórico ficam de fora (internos)."""
import io
import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from servicos import CAMPOS

AZUL = colors.HexColor("#1f3a5f")
CINZA = colors.HexColor("#eef2f6")
LINHA = colors.HexColor("#c9d3de")
TIPOS_PORQUE = {"OCORRENCIA": "Ocorrência", "NAO_DETECCAO": "Não detecção"}
SITUACAO = {"RELEVANTE": "Relevante", "IRRELEVANTE": "Irrelevante"}
SIGLAS = {"OCORRENCIA": "O", "NAO_DETECCAO": "ND", "OCORRENCIA,NAO_DETECCAO": "O/ND"}
ETAPAS = ["DADOS", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]   # as que vão para o PDF (sem Custos/Histórico)
EXT_IMAGEM = {"jpg", "jpeg", "png", "gif", "bmp"}

_base = getSampleStyleSheet()
TXT = ParagraphStyle("txt", parent=_base["Normal"], fontName="Helvetica", fontSize=9, leading=11.5)
TXT_B = ParagraphStyle("txtb", parent=TXT, fontName="Helvetica-Bold")
TIT = ParagraphStyle("tit", parent=TXT, fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=AZUL)
SEC = ParagraphStyle("sec", parent=TXT, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.white)
PEQ = ParagraphStyle("peq", parent=TXT, fontSize=7.5, leading=9, textColor=colors.grey)


def _vazio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _p(v, estilo=TXT):
    """Texto seguro para o Paragraph (escapa < > & e mantém as quebras de linha). Vazio fica em branco."""
    return Paragraph("" if _vazio(v) else escape(str(v)).replace("\n", "<br/>"), estilo)


def _valor(rec, campo, tipo):
    """Valor para o relatório, ou None quando o campo não foi preenchido."""
    v = getattr(rec, campo)
    if tipo == "datetime":
        return v.strftime("%d/%m/%Y %H:%M") if v else None
    if tipo == "bool":
        return "Sim" if v else None          # caixa desmarcada = não preenchido
    if tipo == "tri":
        return {True: "Sim", False: "Não"}.get(v)
    if tipo == "int0":
        return v or None
    return None if _vazio(v) else v


def _secao(titulo):
    t = Table([[Paragraph(escape(titulo), SEC)]], colWidths=[180 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    depois = Spacer(1, 2 * mm)
    t.keepWithNext = depois.keepWithNext = True   # título nunca fica sozinho no pé da página
    return [Spacer(1, 7 * mm), t, depois]


def _tabela(linhas, larguras, cabecalho=True):
    t = Table(linhas, colWidths=[w * mm for w in larguras], repeatRows=1 if cabecalho else 0)
    estilo = [("GRID", (0, 0), (-1, -1), 0.4, LINHA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if cabecalho:
        estilo.append(("BACKGROUND", (0, 0), (-1, 0), CINZA))
    t.setStyle(TableStyle(estilo))
    return t


def _campos(rec, aba, largura_rotulo=60):
    """Tabela rótulo/valor só com os campos preenchidos; None se nenhum foi."""
    linhas = []
    for campo, rotulo, tipo in CAMPOS[aba]:
        v = _valor(rec, campo, tipo)
        if v is not None:
            linhas.append([_p(rotulo, TXT_B), _p(v)])
    if not linhas:
        return None
    t = _tabela(linhas, [largura_rotulo, 180 - largura_rotulo], cabecalho=False)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), CINZA)]))
    return t


def _imagem(caminho, legenda):
    """Imagem reduzida (fotos de celular têm 4000 px: o PDF ficaria enorme) e com a legenda embaixo."""
    from PIL import Image as PIL
    with PIL.open(caminho) as im:
        im = im.convert("RGB")
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
    buf.seek(0)
    larg, alt = ImageReader(buf).getSize()
    escala = min(180 * mm / larg, 115 * mm / alt)
    buf.seek(0)
    return KeepTogether([Spacer(1, 3 * mm), Image(buf, width=larg * escala, height=alt * escala),
                         Spacer(1, 1 * mm), _p(legenda, PEQ)])


def _anexos(evs, pasta, pdfs):
    """Bloco de anexos de uma etapa. Os PDFs entram em `pdfs` (vão para o fim do arquivo)."""
    if not evs:
        return []
    e = [Spacer(1, 4 * mm), _p(f"Anexos ({len(evs)})", TXT_B)]
    for ev in evs:
        nome = ev.arquivo.split("_", 1)[-1]
        rot = nome + (f" · {ev.categoria}" if ev.categoria else "") + (f" - {ev.descricao}" if ev.descricao else "")
        caminho = os.path.join(pasta, ev.arquivo)
        ext = nome.rsplit(".", 1)[-1].lower()
        if not os.path.isfile(caminho):
            e.append(_p(f"• {rot} (arquivo não encontrado no sistema)"))
        elif ext in EXT_IMAGEM:
            try:
                e.append(_imagem(caminho, rot))
            except Exception:
                e.append(_p(f"• {rot} (imagem não pôde ser aberta)"))
        elif ext == "pdf":
            pdfs.append((caminho, rot))
            e.append(Paragraph(f"• {escape(rot)}: <b>Anexo {len(pdfs)}</b>, páginas no fim deste relatório "
                               f"({{pag{len(pdfs)}}})", TXT))
        else:
            e.append(_p(f"• {rot} (arquivo .{ext}: abrir no sistema de reclamações 8D)"))
    return e


def _gerar_corpo(rec, evidencias, raiz_static, gerado_por, etapas, pasta, paginas_anexos):
    """Monta o relatório; devolve (bytes, [(pdf_anexo, legenda)]). paginas_anexos: página onde cada
    PDF anexado começa (calculada numa primeira passada)."""
    buf = io.BytesIO()
    titulo = f"Relatório 8D · {rec.codigo}" + ("" if etapas == ETAPAS else " · " + ", ".join(
        "Dados" if x == "DADOS" else x for x in etapas))
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title=titulo, author="Pro-Metal")
    agora = datetime.now()
    pdfs = []
    por_etapa = {x: [ev for ev in evidencias if ev.etapa == x] for x in ETAPAS}

    def rodape(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 9 * mm, f"Pro-Metal · {titulo} · gerado em {agora:%d/%m/%Y %H:%M} por {gerado_por}")
        canvas.drawRightString(195 * mm, 9 * mm, f"Página {d.page}")
        canvas.restoreState()

    e = []
    logo = os.path.join(raiz_static, "logo.png")
    cab_esq = Image(logo, width=40 * mm, height=15 * mm, kind="proportional") if os.path.exists(logo) else ""
    cab = Table([[cab_esq, Paragraph(escape(titulo), TIT)]], colWidths=[50 * mm, 130 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                             ("LINEBELOW", (0, 0), (-1, 0), 1.2, AZUL), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    e += [cab, Spacer(1, 4 * mm)]

    # resumo (sempre): só os pares preenchidos, dois por linha
    pares = [(r, v) for r, v in (
        ("Cliente", rec.cliente.nome), ("Status", rec.status), ("Part number", rec.part_number),
        ("Nº no cliente", rec.num_reclamacao_cliente), ("Modo de falha", rec.modo_falha), ("Lote", rec.lote),
        ("Recebida em", f"{rec.data_recebimento:%d/%m/%Y %H:%M}" if rec.data_recebimento else None),
        ("Qtd. suspeita", rec.qtd_suspeita),
        ("Fechada em", f"{rec.fechada_em:%d/%m/%Y %H:%M}" if rec.fechada_em else None)) if not _vazio(v)]
    resumo = []
    for n in range(0, len(pares), 2):
        par = pares[n:n + 2] + [("", None)] * (2 - len(pares[n:n + 2]))
        resumo.append([_p(par[0][0], TXT_B), _p(par[0][1]), _p(par[1][0], TXT_B), _p(par[1][1])])
    t = _tabela(resumo, [32, 58, 32, 58], cabecalho=False)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), CINZA), ("BACKGROUND", (2, 0), (2, -1), CINZA)]))
    e.append(t)
    if "DADOS" in etapas:
        e += _anexos(por_etapa["DADOS"], pasta, pdfs)

    def secao(chaves, titulo_sec, conteudo):
        """Seção de uma ou mais etapas: conteúdo + anexos. Some se estiver vazia, a não ser que a etapa
        tenha sido pedida sozinha (aí avisa que não há nada preenchido)."""
        if not any(k in etapas for k in chaves):
            return
        anexos = [x for k in chaves for x in _anexos(por_etapa[k], pasta, pdfs)]
        if not conteudo and not anexos:
            if len(etapas) == 1:
                e.extend(_secao(titulo_sec) + [_p("Nada preenchido nesta etapa.")])
            return
        e.extend(_secao(titulo_sec) + conteudo + anexos)

    d1 = []
    if rec.equipe:
        d1.append(_tabela([[_p("Nome", TXT_B), _p("Função", TXT_B), _p("Líder", TXT_B)]] +
                          [[_p(m.nome), _p(m.funcao), _p("Sim" if m.lider else "")] for m in rec.equipe], [80, 75, 25]))
    secao(["D1"], "D1 · Equipe", d1)

    t = _campos(rec, "D2", 45)
    secao(["D2"], "D2 · Descrição do problema (5W2H)", [t] if t else [])

    d3 = []
    for nome, pref in (("Estoque Pro-Metal", "d3_estoque"), ("Em trânsito", "d3_transito"), ("No cliente", "d3_cliente")):
        qtd, nok = getattr(rec, pref + "_qtd"), getattr(rec, pref + "_nok")
        if qtd is not None or nok is not None:
            d3.append([_p(nome), _p(qtd), _p(nok)])
    c3 = []
    if d3:
        c3.append(_tabela([[_p("Local", TXT_B), _p("Qtd. verificada", TXT_B), _p("NOK", TXT_B)]] + d3, [80, 50, 50]))
    if rec.d3_concluida_em:
        c3 += [Spacer(1, 2 * mm), _p(f"Contenção concluída em: {rec.d3_concluida_em:%d/%m/%Y %H:%M}")]
    secao(["D3"], "D3 · Contenção", c3)

    d4 = []
    if rec.causas:
        linhas = [[_p("6M", TXT_B), _p("Tipo", TXT_B), _p("Causa", TXT_B), _p("Classificação", TXT_B), _p("Evidência", TXT_B)]]
        for c in sorted(rec.causas, key=lambda c: (c.categoria or "", c.id)):
            linhas.append([_p(c.categoria), _p(SIGLAS.get(c.tipo_causa(rec.porques))), _p(c.descricao),
                           _p(SITUACAO.get(c.situacao, c.situacao)), _p(c.evidencia)])
        d4 += [_p("Ishikawa (6M)", TXT_B), Spacer(1, 1.5 * mm), _tabela(linhas, [22, 13, 63, 27, 55]),
               Spacer(1, 1 * mm), _p("Tipo: O = ocorrência · ND = não detecção · O/ND = as duas", PEQ)]
    for c in [c for c in rec.causas if c.situacao == "RELEVANTE"]:
        for tipo, nome in TIPOS_PORQUE.items():
            cadeia = sorted((p for p in rec.porques if p.causa_id == c.id and p.tipo == tipo and not _vazio(p.resposta)),
                            key=lambda p: p.ordem or 0)
            passos = [p for p in cadeia if p.ordem]
            if passos:
                inicio = next((p.resposta for p in cadeia if not p.ordem), c.descricao)
                linhas = [[_p("Problema", TXT_B), _p(inicio, TXT_B)]]
                linhas += [[_p(f"Por quê? {n}", TXT_B), _p(p.resposta)] for n, p in enumerate(passos, 1)]
                t = _tabela(linhas, [28, 152], cabecalho=False)
                t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), CINZA), ("BACKGROUND", (1, 0), (1, 0), CINZA)]))
                d4.append(KeepTogether([Spacer(1, 3 * mm), _p(f"5 Porquês · {nome}", TXT_B), Spacer(1, 1.5 * mm), t]))
    t = _campos(rec, "D4", 55)
    if t:
        d4 += [Spacer(1, 3 * mm), t]
    secao(["D4"], "D4 · Análise de causa raiz", d4)

    d56 = []
    if rec.acoes:
        linhas = [[_p(h, TXT_B) for h in ("Tipo", "Foco", "Ação", "Responsável", "Prazo", "Status / concluída")]]
        for a in sorted(rec.acoes, key=lambda a: (a.prazo or datetime.max.date())):
            concl = a.status + (f"\n{a.concluida_em:%d/%m/%Y}" if a.concluida_em else "")
            linhas.append([_p(a.tipo), _p(TIPOS_PORQUE.get(a.foco, a.foco)), _p(a.descricao), _p(a.responsavel),
                           _p(a.prazo.strftime("%d/%m/%Y") if a.prazo else None), _p(concl)])
        d56.append(_tabela(linhas, [25, 21, 55, 26, 21, 32]))
    secao(["D5", "D6"], "D5/D6 · Ações corretivas e implementação", d56)

    t = _campos(rec, "D7", 60)
    secao(["D7"], "D7 · Prevenção", [t] if t else [])

    t = _campos(rec, "D8", 60)
    secao(["D8"], "D8 · Verificação de eficácia e encerramento", [t] if t else [])

    # número da página onde cada PDF anexado começa (na 1ª passada ainda não se sabe)
    for f in e:
        if isinstance(f, Paragraph) and "{pag" in f.text:
            for n in range(1, len(pdfs) + 1):
                f.text = f.text.replace(f"{{pag{n}}}", f"página {paginas_anexos[n - 1]}" if paginas_anexos else "página ?")
            f.__init__(f.text, f.style)

    doc.build(e, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue(), pdfs


def gerar(rec, evidencias, raiz_static, gerado_por, etapas=None, pasta_uploads=""):
    """etapas=None: relatório completo. PDFs anexados vão depois das páginas do relatório."""
    from pypdf import PdfReader, PdfWriter
    etapas = [x for x in ETAPAS if x in (etapas or ETAPAS)]
    corpo, pdfs = _gerar_corpo(rec, evidencias, raiz_static, gerado_por, etapas, pasta_uploads, None)
    if not pdfs:
        return corpo
    leitores, inicio, paginas = [], len(PdfReader(io.BytesIO(corpo)).pages) + 1, []
    for caminho, _ in pdfs:
        try:
            r = PdfReader(caminho)
            n = len(r.pages)
        except Exception:
            r, n = None, 0
        leitores.append(r)
        paginas.append(inicio if r else "não pôde ser incluído")
        inicio += n
    corpo2, _ = _gerar_corpo(rec, evidencias, raiz_static, gerado_por, etapas, pasta_uploads, paginas)
    saida = PdfWriter()
    saida.append(PdfReader(io.BytesIO(corpo2)))
    for r, (_, legenda) in zip(leitores, pdfs):
        if r:
            saida.append(r, outline_item=legenda)
    buf = io.BytesIO()
    saida.write(buf)
    return buf.getvalue()
