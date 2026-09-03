#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brasil_breaking.py - canal "Brasil - Breaking".

MODO ATUAL: MEDICAO. Ele NAO envia nada para o Telegram.

Por que medicao primeiro
------------------------
A regra combinada e "portal grande sozinho OU muitos portais juntos".
O "muitos" e o "sozinho" precisam de numero, e numero chutado aqui custa
caro nos dois sentidos: alto demais e o canal fica mudo; baixo demais e
volta a ser o Radar Brasil antigo, cheio de coisa morna.

Entao este arquivo roda algumas horas so OLHANDO e anotando, em log.txt,
o formato exato de cada assunto que aparece:

  - quantas manchetes ele juntou
  - quantos VEICULOS DIFERENTES publicaram
  - em quantos minutos isso aconteceu (o quao rapido explodiu)
  - quais veiculos foram, e se algum deles e dos grandes
  - as tres primeiras manchetes, para dar para reconhecer o assunto

Com esse log na mao da para ver onde fica a fronteira entre o que
explodiu e o que e rotina, e so entao escrever os cortes no codigo.

Reaproveita as fontes e o agrupamento do radar.py, que ja funcionavam -
nao ha feed novo nem logica nova de agrupamento aqui.

Uso:
    python brasil_breaking.py                 # janela padrao de 90 min
    python brasil_breaking.py --minutos 60
"""

import argparse
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from radar import FONTES, normaliza

from concurrent.futures import ThreadPoolExecutor


ARQUIVO_LOG = "log.txt"

# Janela de observacao. Breaking se mede em minutos, nao em horas: o
# Radar Brasil antigo rodava com 12h e por isso misturava o que estourou
# agora com o que saiu de manha.
MINUTOS_JANELA = 90

# Piso baixissimo DE PROPOSITO: na medicao eu quero enxergar tambem o
# que nao vai virar alerta. E comparando os dois grupos que se descobre
# onde fica o corte. Nao mexa nisto ainda.
MIN_MANCHETES_LOG = 2
MIN_FONTES_LOG = 2

# Quantos assuntos anotar por rodada.
QUANTOS_ANOTAR = 25

# Os "portais grandes" da regra "portal grande sozinho". Esta lista
# existe so para MARCAR no log quem e quem; ela ainda nao decide nada.
# Os nomes tem que bater com os de FONTES["brasil"] no radar.py.
GRANDES = {
    "G1 Politica",
    "Agencia Brasil Pol",
    "Agencia Brasil Just",
    "Poder360",
    "BBC Brasil",
    "Gazeta do Povo Rep",
}


import re
from xml.etree import ElementTree as ET

from radar import baixa, limpa_html, parse_data, _tag

_RE_VEICULO_GNEWS = re.compile(r"\s+-\s+([^-]{2,40})\s*$")


def le_feed_com_fonte(nome, url, timeout=15):
    """
    Igual ao le_feed() do radar.py, mas tambem captura a tag <source>.

    E ai que o Google News guarda o nome do veiculo que realmente
    publicou. O radar.py ignora essa tag, e por isso a mesma materia da
    CNN aparecendo em tres buscas diferentes do GNews era contada como
    tres veiculos distintos - inflando justamente o numero que vai
    decidir se algo "explodiu".

    O sufixo no titulo (" - cnnbrasil.com.br") tambem vale, mas nem todo
    item traz: nesta medicao, uns tinham e outros nao. A tag e o
    caminho confiavel; o sufixo fica de reserva.
    """
    itens = []
    try:
        raiz = ET.fromstring(baixa(url, timeout))
    except Exception as e:
        return itens, f"{nome}: {type(e).__name__}"

    for el in raiz.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        titulo = link = data = origem = None
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
            elif t == "source" and origem is None:
                origem = ("".join(f.itertext()) or "").strip() or None
        if titulo:
            itens.append({"titulo": titulo, "link": link or "",
                          "data": data, "fonte": nome, "origem": origem})
    return itens, None


def fonte_real(it):
    """
    Descobre QUEM publicou de verdade.

    O Google News nao e um veiculo: e um agregador. Na primeira medicao
    o assunto "Pesquisa" apareceu com 3 "veiculos" - GNews eleicoes,
    GNews governo e Poder360 - mas os dois primeiros eram UOL e
    MidiaNews. Contando assim, um assunto parece ter o dobro de
    cobertura que tem, e a diversidade de fontes (que e justamente o
    sinal de "explodiu") vira numero inflado.

    Nos feeds do Google News o veiculo verdadeiro vem no fim do titulo,
    depois de um hifen: "Gilmar defende ... - cnnbrasil.com.br".
    """
    if not it["fonte"].startswith("GNews"):
        return it["fonte"]
    if it.get("origem"):
        return it["origem"]
    m = _RE_VEICULO_GNEWS.search(it["titulo"])
    if m:
        return m.group(1).strip()
    return it["fonte"]


def titulo_limpo(it):
    """O titulo sem o ' - veiculo' que o Google News gruda no fim."""
    if it["fonte"].startswith("GNews"):
        return _RE_VEICULO_GNEWS.sub("", it["titulo"]).strip()
    return it["titulo"]


# Ajustes na lista do radar.py, feitos AQUI e nao la, para nao mexer nos
# bots que ainda usam aquele arquivo.
#
# Tres feeds falharam na medicao de 03/09 18:22 UTC:
#   Agencia Senado  -> URLError   (o endereco /noticias/feed esta vazio;
#                                  o certo e /noticias/feed/todasnoticias)
#   Agencia Camara  -> ParseError (nao devolve XML)
#   Migalhas        -> HTTPError
TROCAR = {
    "https://www12.senado.leg.br/noticias/feed":
        "https://www12.senado.leg.br/noticias/feed/todasnoticias",
}
REMOVER = {"Agencia Camara", "Migalhas"}

# Portais grandes que faltavam na lista e que sao justamente os que
# marcam "isso e breaking" quando publicam. Se algum destes enderecos
# estiver errado, ele aparece na linha "feeds que falharam" do log - e
# ai eu troco. Melhor descobrir medindo do que supondo.
ACRESCENTAR = [
    ("CNN Brasil Politica", "https://www.cnnbrasil.com.br/politica/feed/"),
    ("Folha Poder", "https://feeds.folha.uol.com.br/poder/rss091.xml"),
    ("UOL Noticias", "https://rss.uol.com.br/feed/noticias.xml"),
    ("Metropoles Politica", "https://www.metropoles.com/coluna-do-noblat/feed"),
]


def fontes_brasil():
    lista = []
    for nome, url in FONTES["brasil"]:
        if nome in REMOVER:
            continue
        lista.append((nome, TROCAR.get(url, url)))
    return lista + ACRESCENTAR


def coleta_minutos(minutos, workers=12):
    """Igual ao coleta() do radar.py, mas com a janela em MINUTOS."""
    feeds = fontes_brasil()
    itens, erros = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got, err in ex.map(lambda f: le_feed_com_fonte(*f), feeds):
            itens.extend(got)
            if err:
                erros.append(err)

    corte = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    recentes, vistos = [], set()
    sem_data = 0
    for it in itens:
        if it["data"] is None:
            # Feed que nao data direito entra, mas eu conto quantos sao:
            # se for muita gente, a medida de "em quantos minutos" perde
            # o sentido e eu preciso saber disso antes de confiar nela.
            sem_data += 1
        elif it["data"] < corte:
            continue
        it["titulo"] = titulo_limpo(it)
        it["fonte"] = fonte_real(it)
        chave = normaliza(it["titulo"])[:90]
        if chave in vistos:
            continue
        vistos.add(chave)
        recentes.append(it)
    return recentes, erros, sem_data


PALAVRAS_VAZIAS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela
para com que se e ao aos sobre entre apos sem sob ate mais menos ja nao
seu sua seus suas ele ela eles elas isso este esta esse essa foi ser tem
ter diz dizem vai vao sao era eram como quando onde qual quais veja saiba
entenda apos contra depois antes ainda tambem
""".split())

# Duas manchetes falam da mesma historia quando repetem esta fatia das
# palavras que importam.
#
# MEDIDO nas 87 manchetes reais da rodada de 03/09 18:24 UTC:
#
#   corte   grupos   com 2+ veiculos   o que acontece
#   0.20      49          13           junta coisa diferente (o centro
#                                      veterinario de BH entrou junto)
#   0.30      64           8           grupos coerentes
#   0.40      69           5           comeca a partir historia em duas
#
# Em 0.30 os grupos ficaram limpos e ainda assim juntaram o que era
# para juntar (as 4 manchetes do impeachment de Moraes ficaram numa so).
SEMELHANCA_HISTORIA = 0.30


def _palavras(titulo):
    return {w for w in re.findall(r"[a-z0-9]{4,}", normaliza(titulo))
            if w not in PALAVRAS_VAZIAS}


def agrupa(itens):
    """
    Junta as manchetes que contam a MESMA HISTORIA.

    O radar.py agrupava por termo repetido, e para ranking de assunto
    isso servia. Para breaking, nao: na medicao das 18:22 o rotulo "STF"
    juntou 9 manchetes de 5 veiculos que nao tinham nada em comum -
    cotas para candidaturas negras, delegados da PF, crise interna do
    tribunal. Cinco veiculos falando de coisas diferentes nao e uma
    noticia explodindo; e a palavra "STF" sendo comum no Brasil.

    Aqui duas manchetes so caem no mesmo grupo se as PROPRIAS PALAVRAS
    delas se repetirem.
    """
    grupos = []
    for it in itens:
        minhas = _palavras(it["titulo"])
        if not minhas:
            continue
        destino = None
        for g in grupos:
            for outro in g["itens"]:
                dele = _palavras(outro["titulo"])
                if not dele:
                    continue
                comuns = len(minhas & dele)
                if comuns / max(1, min(len(minhas), len(dele))) >= SEMELHANCA_HISTORIA:
                    destino = g
                    break
            if destino:
                break
        if destino is None:
            grupos.append({"itens": [it]})
        else:
            destino["itens"].append(it)

    final = []
    for g in grupos:
        fontes = {i["fonte"] for i in g["itens"]}
        if len(g["itens"]) < MIN_MANCHETES_LOG or len(fontes) < MIN_FONTES_LOG:
            continue
        # o rotulo e a manchete mais antiga: foi quem deu primeiro
        com_data = [i for i in g["itens"] if i["data"]]
        primeira = min(com_data, key=lambda i: i["data"])["titulo"] \
            if com_data else g["itens"][0]["titulo"]
        final.append({
            "rotulo": primeira,
            "manchetes": len(g["itens"]),
            "fontes": fontes,
            "itens": g["itens"],
        })

    final.sort(key=lambda g: (-len(g["fontes"]), -g["manchetes"]))
    return final[:QUANTOS_ANOTAR]


def minutos_de_espalhamento(grupo):
    """
    Em quantos minutos o assunto se espalhou.

    E a medida que separa "explodiu" de "assunto que existe ha horas":
    seis veiculos em 20 minutos e uma coisa; seis veiculos ao longo de
    uma tarde inteira e outra bem diferente.
    """
    datas = [i["data"] for i in grupo["itens"] if i["data"]]
    if len(datas) < 2:
        return None
    return round((max(datas) - min(datas)).total_seconds() / 60)


def escreve_log(grupos, total, erros, sem_data, minutos, TODAS):
    agora = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    linhas = []
    linhas.append("=" * 78)
    linhas.append(f"RODADA {agora}  |  janela {minutos} min  |  "
                  f"{total} manchetes  |  {sem_data} sem data  |  "
                  f"{len(erros)} feeds com erro")
    linhas.append("=" * 78)

    if erros:
        linhas.append("feeds que falharam: " + "; ".join(erros[:8]))

    if not grupos:
        linhas.append("(nenhum assunto com 2+ manchetes de 2+ veiculos)")
    else:
        linhas.append(f"{'veic':>4} {'manch':>6} {'min':>5}  {'grande':<7} "
                      f"assunto")
        linhas.append("-" * 78)

    for g in grupos:
        espalho = minutos_de_espalhamento(g)
        grandes = g["fontes"] & GRANDES
        linhas.append(
            f"{len(g['fontes']):>4} {g['manchetes']:>6} "
            f"{'?' if espalho is None else espalho:>5}  "
            f"{('sim' if grandes else 'nao'):<7} {g['rotulo'][:45]}"
        )
        linhas.append(f"       veiculos: {', '.join(sorted(g['fontes']))[:150]}")
        for it in g["itens"][:3]:
            linhas.append(f"       . [{it['fonte']}] {it['titulo'][:110]}")
        linhas.append("")

    # Lista crua de tudo que entrou na janela.
    #
    # Existe porque o agrupamento ainda esta em teste: a primeira
    # medicao juntou 9 manchetes sob o rotulo "STF" que nao tinham nada
    # a ver umas com as outras (cotas eleitorais, delegados da PF, crise
    # interna). Agrupar por termo repetido nao e agrupar por HISTORIA.
    # Com a lista crua da para testar regras de agrupamento fora do ar,
    # sobre manchetes reais, sem ficar chutando no escuro.
    linhas.append("--- MANCHETES DA JANELA (cruas) ---")
    for it in sorted(TODAS, key=lambda x: (x["data"] or datetime.min.replace(
            tzinfo=timezone.utc)), reverse=True):
        quando = it["data"].strftime("%H:%M") if it["data"] else "--:--"
        linhas.append(f"{quando} | {it['fonte'][:28]:<28} | {it['titulo']}")

    linhas.append("")
    texto = "\n".join(linhas)

    # append: cada rodada empilha na anterior, e o historico inteiro
    # fica em um arquivo so, que o Claude le pela API do GitHub.
    with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
        f.write(texto)
    print(texto)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutos", type=int, default=MINUTOS_JANELA)
    args = p.parse_args()

    itens, erros, sem_data = coleta_minutos(args.minutos)
    grupos = agrupa(itens)
    escreve_log(grupos, len(itens), erros, sem_data, args.minutos, itens)

    print(f"\nMODO MEDICAO: nada foi enviado ao Telegram.")
    print(f"log.txt agora tem "
          f"{os.path.getsize(ARQUIVO_LOG) // 1024} KB")


if __name__ == "__main__":
    main()
