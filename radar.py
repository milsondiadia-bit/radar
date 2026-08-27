#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
radar.py - Robo de radar de assuntos em tempo real.

Le dezenas de feeds RSS de noticias, conta termos e entidades nas manchetes
das ultimas N horas e ranqueia o que esta sendo mais comentado agora.

Nao precisa de chave de API. Nao precisa instalar nada (so Python 3.8+).

Uso:
    python radar.py mundo               # geopolitica global
    python radar.py brasil              # politica e justica no Brasil
    python radar.py mundo --horas 12    # janela de 12h (padrao: 24)
    python radar.py brasil --top 15     # mostra 15 assuntos
    python radar.py mundo --html        # gera relatorio radar_mundo.html
    python radar.py brasil --json        # gera radar_brasil.json
    python radar.py mundo --fontes      # so lista as fontes usadas

Dica: rode de hora em hora com cron/Agendador de Tarefas e compare os relatorios
para ver o que esta SUBINDO, nao so o que esta grande.
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from html import escape, unescape
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

# ----------------------------------------------------------------------------
# FONTES - edite a vontade. Formato: (nome curto, url do RSS)
# ----------------------------------------------------------------------------

def gnews(query, hl="pt-BR", gl="BR", ceid="BR:pt-419"):
    """Monta uma busca no Google News RSS (gratis, sem chave)."""
    return ("https://news.google.com/rss/search?q=" + quote(query)
            + f"&hl={hl}&gl={gl}&ceid={ceid}")


def gnews_topico(topico, hl="pt-BR", gl="BR", ceid="BR:pt-419"):
    return (f"https://news.google.com/rss/headlines/section/topic/{topico}"
            f"?hl={hl}&gl={gl}&ceid={ceid}")


FONTES = {
    "mundo": [
        # Agregadores em portugues
        ("GNews Mundo", gnews_topico("WORLD")),
        ("GNews geopolitica", gnews("geopolitica OR sancoes OR cessar-fogo OR diplomacia")),
        ("GNews conflitos", gnews("guerra OR ataque OR bombardeio OR ofensiva OR tregua")),
        ("GNews Oriente Medio", gnews("Ira OR Israel OR Oriente Medio OR Ormuz OR petroleo")),
        ("GNews potencias", gnews("Estados Unidos OR China OR Russia OR Trump OR Putin")),
        ("GNews organismos", gnews("ONU OR OTAN OR Uniao Europeia OR G7 OR BRICS OR Mercosul")),
        ("GNews America Latina", gnews("Venezuela OR Argentina OR America Latina OR Caribe")),
        # Veiculos em portugues
        ("G1 Mundo", "https://g1.globo.com/rss/g1/mundo/"),
        ("Agencia Brasil Intl", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
        ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
        ("DW Brasil", "https://rss.dw.com/rdf/rss-br-all"),
        ("RFI Brasil", "https://www.rfi.fr/br/rss"),
        ("France24 PT", "https://www.france24.com/pt/rss"),
        ("Euronews PT", "https://pt.euronews.com/rss"),
        ("CNN Brasil Intl", "https://www.cnnbrasil.com.br/internacional/feed/"),
        ("UOL Internacional", "https://rss.uol.com.br/feed/internacional.xml"),
        ("Observador Mundo", "https://observador.pt/seccao/mundo/feed/"),
        ("Publico PT", "https://www.publico.pt/rss"),
        ("Poder360", "https://www.poder360.com.br/feed/"),
        ("Google Trends BR", "https://trends.google.com/trending/rss?geo=BR"),
    ],
    "brasil": [
        ("GNews Brasil", gnews_topico("NATION")),
        ("GNews politica", gnews("politica Brasil")),
        ("GNews STF", gnews("STF OR Supremo Tribunal Federal")),
        ("GNews justica", gnews("justica OR judiciario OR STJ OR PGR OR Policia Federal")),
        ("GNews Congresso", gnews("Congresso OR Camara dos Deputados OR Senado")),
        ("GNews eleicoes", gnews("eleicoes 2026 OR TSE OR campanha eleitoral")),
        ("GNews governo", gnews("governo Lula OR Planalto OR ministerio")),
        # Veiculos
        ("G1 Politica", "https://g1.globo.com/rss/g1/politica/"),
        ("Agencia Brasil Pol", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
        ("Agencia Brasil Just", "https://agenciabrasil.ebc.com.br/rss/justica/feed.xml"),
        ("Poder360", "https://www.poder360.com.br/feed/"),
        ("Conjur", "https://www.conjur.com.br/rss.xml"),
        ("Migalhas", "https://www.migalhas.com.br/rss"),
        ("Congresso em Foco", "https://www.congressoemfoco.com.br/feed/"),
        ("Agencia Camara", "https://www.camara.leg.br/noticias/rss/ultimas"),
        ("Agencia Senado", "https://www12.senado.leg.br/noticias/feed"),
        ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
        ("Carta Capital", "https://www.cartacapital.com.br/feed/"),
        ("Gazeta do Povo Rep", "https://www.gazetadopovo.com.br/feed/rss/republica.xml"),
        ("Google Trends BR", "https://trends.google.com/trending/rss?geo=BR"),
    ],
}

# ----------------------------------------------------------------------------
# STOPWORDS
# ----------------------------------------------------------------------------

STOP_PT = """a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela
pelos pelas para com sem sob sobre entre ate apos ante contra desde e ou mas porem que
se ao aos as e eh sao foi foram ser sera seria tem tinha teve ter havia ha estao esta
este esse aquele isso isto aquilo seu sua seus suas meu minha nosso nossa qual quais
quando onde como porque mais menos muito pouco ja nao sim tambem apenas so ainda depois
antes agora hoje ontem amanha diz disse dizem afirma afirmou apos veja saiba entenda
confira leia noticia noticias reportagem video fotos ao vivo assista opiniao analise
brasil bra mundo internacional pais paises ano anos mes dia dias hora horas semana
milhoes milhao mil bilhoes r$ us$ novo nova novos novas maior menor primeiro primeira
segundo segunda terceiro deve devem pode podem vai vao fazer feito parte caso casos
apos durante grande grandes todo toda todos todas outro outra outros outras cada era eram sera serao apos diante frente meio
""".split()

STOP_EN = """the a an of in on to and for with at by from as is are was were be been being
has have had says said after over new says will would could should this that these those
it its his her their they we you i he she not no more most less least than then there
here what when where who whom which how why all any some other others live watch read
news video photos opinion analysis update updates breaking world year years day days
week month million billion first second third top best new latest amid into out up down
about against between during before under above per via like just also only still get
gets make makes take takes say sees seen may might can
""".split()

STOPWORDS = set(STOP_PT) | set(STOP_EN)

# ----------------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------------

UA = "Mozilla/5.0 (compatible; RadarBot/1.0; +https://example.local)"
TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*")
ENTIDADE_RE = re.compile(
    r"\b([A-ZÀ-Þ][\wÀ-ÿ'’\-]+(?:\s+(?:de|da|do|dos|das|of|the|von|van|el|al)\s+"
    r"[A-ZÀ-Þ\wÀ-ÿ'’\-]+|\s+[A-ZÀ-Þ][\wÀ-ÿ'’\-]+){0,3})"
)
SIGLA_RE = re.compile(r"\b([A-ZÀ-Þ]{2,6})\b")


def sem_acento(txt):
    return "".join(c for c in unicodedata.normalize("NFD", txt)
                   if unicodedata.category(c) != "Mn")


def normaliza(txt):
    return sem_acento(txt.lower()).strip()


def limpa_html(txt):
    return unescape(TAG_RE.sub(" ", txt or "")).strip()


def baixa(url, timeout=15):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml,*/*"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_data(txt):
    if not txt:
        return None
    try:
        d = parsedate_to_datetime(txt)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(txt.strip(), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _tag(el):
    return el.tag.split("}")[-1]


def le_feed(nome, url, timeout=15):
    """Retorna lista de dicts {titulo, link, data, fonte}. RSS 2.0, RDF ou Atom."""
    itens = []
    try:
        raiz = ET.fromstring(baixa(url, timeout))
    except Exception as e:
        return itens, f"{nome}: {type(e).__name__}"

    for el in raiz.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        titulo = link = data = None
        for f in el:
            t = _tag(f)
            if t == "title" and titulo is None:
                titulo = limpa_html("".join(f.itertext()))
            elif t == "link":
                if f.get("href"):
                    link = link or f.get("href")
                elif (f.text or "").strip():
                    link = link or f.text.strip()
            elif t in ("pubDate", "published", "updated", "date") and data is None:
                data = parse_data("".join(f.itertext()))
        if titulo:
            itens.append({"titulo": titulo, "link": link or "",
                          "data": data, "fonte": nome})
    return itens, None


def coleta(mode, horas, workers=12):
    feeds = FONTES[mode]
    itens, erros = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got, err in ex.map(lambda f: le_feed(*f), feeds):
            itens.extend(got)
            if err:
                erros.append(err)

    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    recentes, vistos = [], set()
    for it in itens:
        # sem data: mantem (muito feed nao datar direito), com data: filtra
        if it["data"] and it["data"] < corte:
            continue
        chave = normaliza(it["titulo"])[:90]
        if chave in vistos:
            continue
        vistos.add(chave)
        recentes.append(it)
    return recentes, erros


# ----------------------------------------------------------------------------
# SCORING
# ----------------------------------------------------------------------------

def termos_do_titulo(titulo):
    """Extrai entidades (nomes proprios/siglas) e bigramas relevantes."""
    achados = set()

    # Entidades: sequencias de palavras capitalizadas
    for m in ENTIDADE_RE.finditer(titulo):
        ent = m.group(1).strip(" -'’")
        palavras = ent.split()
        # tira artigos/verbos comuns das pontas ("O Ira era" -> "Ira")
        while palavras and normaliza(palavras[0]) in STOPWORDS:
            palavras.pop(0)
        while palavras and normaliza(palavras[-1]) in STOPWORDS:
            palavras.pop()
        ent = " ".join(palavras)
        # descarta se so tem palavra comum
        if all(normaliza(p) in STOPWORDS for p in palavras):
            continue
        if len(ent) < 3:
            continue
        achados.add(ent)

    # Siglas (STF, ONU, TSE, OPEC...)
    for m in SIGLA_RE.finditer(titulo):
        if len(m.group(1)) >= 2 and normaliza(m.group(1)) not in STOPWORDS:
            achados.add(m.group(1))

    # Bigramas de palavras nao-stopword (pega temas, nao so nomes)
    palavras = [w for w in WORD_RE.findall(titulo) if len(w) > 2]
    uteis = [w for w in palavras if normaliza(w) not in STOPWORDS]
    for i in range(len(uteis) - 1):
        achados.add(f"{uteis[i]} {uteis[i+1]}")
    for w in uteis:
        if len(w) > 4:
            achados.add(w)

    return {t: normaliza(t) for t in achados}


def ranqueia(itens, top=10, min_fontes=2):
    ocorrencias = defaultdict(list)   # chave normalizada -> itens
    rotulos = defaultdict(Counter)    # chave -> grafias originais

    for it in itens:
        for original, chave in termos_do_titulo(it["titulo"]).items():
            if len(chave) < 3:
                continue
            ocorrencias[chave].append(it)
            rotulos[chave][original] += 1

    pontuados = []
    for chave, lista in ocorrencias.items():
        fontes = {i["fonte"] for i in lista}
        if len(lista) < 2 or len(fontes) < min_fontes:
            continue
        # score = manchetes x diversidade de fontes (evita eco de um veiculo so)
        score = len(lista) * (1 + 0.6 * (len(fontes) - 1))
        pontuados.append({
            "chave": chave,
            "rotulo": rotulos[chave].most_common(1)[0][0],
            "score": round(score, 1),
            "manchetes": len(lista),
            "fontes": len(fontes),
            "itens": lista,
        })

    # empate -> vence o termo mais especifico ("Estreito de Ormuz" > "Estreito")
    pontuados.sort(key=lambda x: (-x["score"], -len(x["chave"].split()),
                                  -len(x["chave"]), x["rotulo"]))

    # Funde termos que falam da mesma coisa: se as manchetes se sobrepoem muito,
    # mantem um so - e fica com o rotulo mais informativo ("Estreito de Ormuz").
    final = []
    for p in pontuados:
        ids_p = {id(i) for i in p["itens"]}
        absorvido = False
        for j in final:
            ids_j = {id(i) for i in j["itens"]}
            sobrep = len(ids_p & ids_j) / max(1, min(len(ids_p), len(ids_j)))
            if sobrep >= 0.6:
                if j["chave"] in p["chave"] and len(p["chave"]) > len(j["chave"]):
                    j["rotulo"], j["chave"] = p["rotulo"], p["chave"]
                absorvido = True
                break
        if not absorvido:
            final.append(p)
        if len(final) >= top:
            break
    return final


# ----------------------------------------------------------------------------
# SAIDA
# ----------------------------------------------------------------------------

TITULOS = {"mundo": "GEOPOLITICA - MUNDO", "brasil": "POLITICA E JUSTICA - BRASIL"}


def imprime(mode, ranking, itens, horas, erros):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    print("\n" + "=" * 74)
    print(f" RADAR {TITULOS[mode]}  |  {agora}  |  ultimas {horas}h")
    print(f" {len(itens)} manchetes analisadas")
    print("=" * 74)
    if not ranking:
        print("\nNada acima do limiar. Tente --horas 48 ou --min-fontes 1.")
    for pos, p in enumerate(ranking, 1):
        print(f"\n{pos:2d}. {p['rotulo'].upper()}")
        print(f"    score {p['score']}  |  {p['manchetes']} manchetes  "
              f"|  {p['fontes']} veiculos")
        for it in sorted(p["itens"], key=lambda i: i["data"] or datetime.min.replace(
                tzinfo=timezone.utc), reverse=True)[:3]:
            print(f"    - [{it['fonte']}] {it['titulo'][:95]}")
            if it["link"]:
                print(f"      {it['link'][:110]}")
    if erros:
        print("\n" + "-" * 74)
        print("Feeds que falharam (normal, alguns bloqueiam robo):")
        for e in erros:
            print("  ! " + e)
    print()


def gera_html(mode, ranking, itens, horas, caminho):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    linhas = [f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Radar {escape(TITULOS[mode])}</title>
<style>
body{{font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;max-width:820px;
margin:40px auto;padding:0 20px;color:#1a1a1a}}
h1{{font-size:22px;margin-bottom:4px}} .meta{{color:#666;font-size:14px;margin-bottom:28px}}
.t{{border-left:3px solid #c8102e;padding:2px 0 2px 14px;margin:26px 0}}
.t h2{{font-size:18px;margin:0 0 4px}} .s{{color:#666;font-size:13px;margin-bottom:8px}}
ul{{margin:0;padding-left:18px}} li{{margin:4px 0;font-size:14px}}
a{{color:#0b57d0;text-decoration:none}} a:hover{{text-decoration:underline}}
.src{{color:#888;font-size:12px}}
</style>
<h1>Radar &mdash; {escape(TITULOS[mode])}</h1>
<div class="meta">{agora} &middot; ultimas {horas}h &middot; {len(itens)} manchetes</div>"""]
    for pos, p in enumerate(ranking, 1):
        linhas.append(f'<div class="t"><h2>{pos}. {escape(p["rotulo"])}</h2>'
                      f'<div class="s">score {p["score"]} &middot; {p["manchetes"]} '
                      f'manchetes &middot; {p["fontes"]} veiculos</div><ul>')
        for it in p["itens"][:5]:
            titulo = escape(it["titulo"])
            if it["link"]:
                titulo = f'<a href="{escape(it["link"])}" target="_blank">{titulo}</a>'
            linhas.append(f'<li>{titulo} <span class="src">'
                          f'[{escape(it["fonte"])}]</span></li>')
        linhas.append("</ul></div>")
    linhas.append("</html>")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    print(f"HTML salvo em: {caminho}")


def gera_json(mode, ranking, itens, horas, caminho):
    saida = {
        "modo": mode,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "janela_horas": horas,
        "manchetes_analisadas": len(itens),
        "assuntos": [{
            "posicao": i,
            "assunto": p["rotulo"],
            "score": p["score"],
            "manchetes": p["manchetes"],
            "veiculos": p["fontes"],
            "exemplos": [{"titulo": it["titulo"], "link": it["link"],
                          "fonte": it["fonte"],
                          "data": it["data"].isoformat() if it["data"] else None}
                         for it in p["itens"][:5]],
        } for i, p in enumerate(ranking, 1)],
    }
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    print(f"JSON salvo em: {caminho}")


# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Radar de assuntos em tempo real.")
    ap.add_argument("modo", choices=["mundo", "brasil"])
    ap.add_argument("--horas", type=int, default=24, help="janela de tempo (padrao 24)")
    ap.add_argument("--top", type=int, default=10, help="quantos assuntos (padrao 10)")
    ap.add_argument("--min-fontes", type=int, default=2,
                    help="minimo de veiculos distintos por assunto (padrao 2)")
    ap.add_argument("--html", action="store_true", help="gera relatorio HTML")
    ap.add_argument("--json", action="store_true", help="gera arquivo JSON")
    ap.add_argument("--fontes", action="store_true", help="so lista as fontes e sai")
    args = ap.parse_args()

    if args.fontes:
        for nome, url in FONTES[args.modo]:
            print(f"{nome:26s} {url}")
        return

    print(f"Coletando {len(FONTES[args.modo])} fontes...", file=sys.stderr)
    itens, erros = coleta(args.modo, args.horas)
    if not itens:
        print("Nenhuma manchete coletada. Verifique sua conexao.", file=sys.stderr)
        sys.exit(1)

    ranking = ranqueia(itens, top=args.top, min_fontes=args.min_fontes)
    imprime(args.modo, ranking, itens, args.horas, erros)

    if args.html:
        gera_html(args.modo, ranking, itens, args.horas, f"radar_{args.modo}.html")
    if args.json:
        gera_json(args.modo, ranking, itens, args.horas, f"radar_{args.modo}.json")


if __name__ == "__main__":
    main()
