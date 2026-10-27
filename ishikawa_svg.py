"""Gera o diagrama espinha de peixe (Ishikawa 6M) em SVG a partir das causas cadastradas."""
from xml.sax.saxutils import escape

from models import CATEGORIAS_6M

LARGURA = 1100
PASSO = 22          # distância vertical entre causas no mesmo osso
MAX_TEXTO = 26      # caracteres visíveis por causa (texto completo no tooltip)
CORES = {"PROVAVEL": "#b3261e", "DESCARTADA": "#9a9a9a", "EM_ANALISE": "#222"}


def _curto(txt):
    txt = " ".join(txt.split())
    return txt if len(txt) <= MAX_TEXTO else txt[:MAX_TEXTO - 1] + "…"


def gerar_svg(causas, efeito):
    por_cat = {c: [x for x in causas if x.categoria == c] for c in CATEGORIAS_6M}
    maior = max([len(v) for v in por_cat.values()] + [2])
    osso = 50 + maior * PASSO            # comprimento vertical de cada osso
    altura = 2 * osso + 120
    meio = altura / 2
    cabeca_x = LARGURA - 210
    pos_x = [cabeca_x - 60, cabeca_x - 320, cabeca_x - 580]   # onde cada osso toca a espinha
    inclinacao = 0.45                    # deslocamento horizontal por unidade vertical

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LARGURA} {altura:.0f}" '
         f'class="ishikawa" font-family="Segoe UI, Arial, sans-serif" font-size="12">',
         f'<line x1="30" y1="{meio}" x2="{cabeca_x}" y2="{meio}" stroke="#1f3a5f" stroke-width="4"/>',
         f'<polygon points="{cabeca_x},{meio - 8} {cabeca_x + 14},{meio} {cabeca_x},{meio + 8}" fill="#1f3a5f"/>',
         f'<rect x="{cabeca_x + 16}" y="{meio - 40}" width="185" height="80" rx="4" fill="#fff3cd" stroke="#1f3a5f"/>',
         f'<foreignObject x="{cabeca_x + 20}" y="{meio - 36}" width="177" height="72">'
         f'<div xmlns="http://www.w3.org/1999/xhtml" style="font:600 12px Segoe UI,Arial;display:flex;'
         f'align-items:center;justify-content:center;height:72px;text-align:center;overflow:hidden">'
         f'{escape(efeito or "")}</div></foreignObject>']

    for i, cat in enumerate(CATEGORIAS_6M):
        em_cima = i < 3
        x_base = pos_x[i % 3]
        sinal = -1 if em_cima else 1
        y_fim = meio + sinal * osso
        x_fim = x_base - osso * inclinacao
        s.append(f'<line x1="{x_base}" y1="{meio}" x2="{x_fim:.1f}" y2="{y_fim:.1f}" stroke="#1f3a5f" stroke-width="2"/>')
        y_rot = y_fim - 8 if em_cima else y_fim + 18
        s.append(f'<text x="{x_fim:.1f}" y="{y_rot:.1f}" text-anchor="middle" font-weight="700" '
                 f'font-size="13" fill="#1f3a5f">{escape(cat)}</text>')
        for j, c in enumerate(por_cat[cat]):
            dist = 30 + j * PASSO                      # distância da espinha ao longo do osso
            y = y_fim - sinal * dist
            x = x_base - abs(y - meio) * inclinacao
            cor = CORES.get(c.situacao, "#222")
            deco = ' text-decoration="line-through"' if c.situacao == "DESCARTADA" else ""
            peso = ' font-weight="700"' if c.situacao == "PROVAVEL" else ""
            s.append(f'<line x1="{x - 175:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{cor}" stroke-width="1"/>')
            s.append(f'<text x="{x - 177:.1f}" y="{y - 3:.1f}" fill="{cor}"{deco}{peso} text-anchor="start">'
                     f'<title>{escape(c.descricao)} ({c.situacao})</title>{escape(_curto(c.descricao))}</text>')
    s.append("</svg>")
    return "\n".join(s)
