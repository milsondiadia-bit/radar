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

from radar import FONTES, le_feed, normaliza, termos_do_titulo

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


def coleta_minutos(minutos, workers=12):
    """Igual ao coleta() do radar.py, mas com a janela em MINUTOS."""
    feeds = FONTES["brasil"]
    itens, erros = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got, err in ex.map(lambda f: le_feed(*f), feeds):
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
        chave = normaliza(it["titulo"])[:90]
        if chave in vistos:
            continue
        vistos.add(chave)
        recentes.append(it)
    return recentes, erros, sem_data


def agrupa(itens):
    """Junta as manchetes que falam do mesmo assunto. Mesma regra do radar.py."""
    ocorrencias = defaultdict(list)
    rotulos = defaultdict(lambda: defaultdict(int))

    for it in itens:
        for original, chave in termos_do_titulo(it["titulo"]).items():
            if len(chave) < 3:
                continue
            ocorrencias[chave].append(it)
            rotulos[chave][original] += 1

    grupos = []
    for chave, lista in ocorrencias.items():
        fontes = {i["fonte"] for i in lista}
        if len(lista) < MIN_MANCHETES_LOG or len(fontes) < MIN_FONTES_LOG:
            continue
        melhor = max(rotulos[chave].items(), key=lambda x: x[1])[0]
        grupos.append({
            "chave": chave,
            "rotulo": melhor,
            "manchetes": len(lista),
            "fontes": fontes,
            "itens": lista,
        })

    # Mais veiculos distintos primeiro; empate desempata por volume.
    grupos.sort(key=lambda g: (-len(g["fontes"]), -g["manchetes"]))

    # Funde assuntos que sao o mesmo (as manchetes se repetem muito).
    final = []
    for g in grupos:
        ids_g = {id(i) for i in g["itens"]}
        absorvido = False
        for j in final:
            ids_j = {id(i) for i in j["itens"]}
            sobrep = len(ids_g & ids_j) / max(1, min(len(ids_g), len(ids_j)))
            if sobrep >= 0.6:
                absorvido = True
                break
        if not absorvido:
            final.append(g)
        if len(final) >= QUANTOS_ANOTAR:
            break
    return final


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


def escreve_log(grupos, total, erros, sem_data, minutos):
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
    escreve_log(grupos, len(itens), erros, sem_data, args.minutos)

    print(f"\nMODO MEDICAO: nada foi enviado ao Telegram.")
    print(f"log.txt agora tem "
          f"{os.path.getsize(ARQUIVO_LOG) // 1024} KB")


if __name__ == "__main__":
    main()
