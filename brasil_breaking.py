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
import json
import sys
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
    "Agencia Brasil",
    "Poder360",
    "BBC Brasil",
    "Gazeta do Povo Rep",
    "Veja",
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
    # O Senado nao responde XML em nenhum dos dois enderecos que testei
    # (03 e 04/09). Fica de fora ate eu achar o certo.
    "https://www12.senado.leg.br/noticias/feed":
        "https://www12.senado.leg.br/noticias/feed/todasnoticias",
}
# Fora da lista por nao devolverem XML valido, medido em varias
# rodadas seguidas de 03 e 04/09. Nao adianta insistir: cada um deles
# custa uma conexao e um timeout por rodada.
REMOVER = {"Agencia Camara", "Migalhas", "Agencia Senado",
           "Agencia Brasil Pol", "Agencia Brasil Just"}

# Portais grandes que faltavam na lista e que sao justamente os que
# marcam "isso e breaking" quando publicam. Se algum destes enderecos
# estiver errado, ele aparece na linha "feeds que falharam" do log - e
# ai eu troco. Melhor descobrir medindo do que supondo.
ACRESCENTAR = [
    ("Folha Poder", "https://feeds.folha.uol.com.br/poder/rss091.xml"),
    ("UOL Politica", "https://rss.uol.com.br/feed/politica.xml"),
    ("Metropoles", "https://www.metropoles.com/feed"),
    # Veiculos de linha conservadora, pedidos em 03/09. Entram porque
    # cobrem pauta que os grandes as vezes deixam passar - e e ai que
    # da para chegar antes.
    ("Revista Oeste", "https://revistaoeste.com/feed"),
    ("O Antagonista", "https://oantagonista.com.br/feed/"),
    ("Claudio Dantas", "https://claudiodantas.com.br/feed/"),
    ("Veja", "https://veja.abril.com.br/feed/"),
    ("Agencia Brasil", "https://agenciabrasil.ebc.com.br/feed/"),
]

# Os veiculos alinhados ao canal.
#
# Esta lista NAO decide se algo explodiu - ela so MARCA. A diferenca
# importa: o sinal de "explodiu" e quantos veiculos DIFERENTES
# publicaram a mesma coisa, e ele so vale porque veiculos de linhas
# opostas publicando junto e prova de que aconteceu algo grande. Se o
# criterio passasse a contar so um lado, cinco veiculos deixaria de
# significar explosao e passaria a significar afinidade editorial -
# que e outra coisa, e acontece toda hora.
#
# Entao o alerta carrega duas informacoes separadas:
#   1) quantos veiculos no total  -> isso explodiu mesmo?
#   2) quantos do campo do canal  -> ja tem material da minha linha?
#
# E ha um terceiro caso, que e o mais valioso: assunto que juntou
# varios veiculos DESTE campo e nenhum dos grandes. Isso costuma ser
# pauta que a imprensa tradicional esta deixando passar - exatamente
# onde da para chegar primeiro.
CAMPO_DO_CANAL = {
    "Gazeta do Povo Rep",
    "Veja",
    "Revista Oeste",
    "O Antagonista",
    "Claudio Dantas",
    "Diário do Poder",
    "Jornal Opção",
}


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
segunda terca quarta quinta sexta sabado domingo feira hoje ontem amanha
janeiro fevereiro marco abril maio junho julho agosto setembro outubro
novembro dezembro manha tarde noite madrugada semana mes ano dia dias
dizem afirma afirmou disse falou nesta neste nessa nesse pode podem
sobre ainda apenas assim entao agora nova novo novos novas primeiro
segundo terceiro ultimo ultima acao acoes caso casos pais brasil
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
        # Compara com o NUCLEO do grupo - as palavras que aparecem na
        # maioria das manchetes dele - e nao com uma manchete qualquer.
        #
        # Comparando item a item, os grupos viravam corrente: A parecia
        # com B, B parecia com C, e C entrava junto sem ter nada a ver
        # com A. Foi assim que "indicadores da 6a feira", "Planaltina
        # sem energia" e "bancos fechados sexta" acabaram no mesmo
        # grupo - so porque todas diziam "sexta-feira".
        destino = None
        melhor = 0.0
        for g in grupos:
            nucleo = g["nucleo"]
            comuns = len(minhas & nucleo)
            sim = comuns / max(1, min(len(minhas), len(nucleo)))
            if sim >= SEMELHANCA_HISTORIA and sim > melhor:
                destino, melhor = g, sim
        if destino is None:
            grupos.append({"itens": [it], "nucleo": set(minhas)})
        else:
            destino["itens"].append(it)
            # o nucleo fica so com o que a maioria repete
            conta = defaultdict(int)
            for x in destino["itens"]:
                for w in _palavras(x["titulo"]):
                    conta[w] += 1
            metade = len(destino["itens"]) / 2
            destino["nucleo"] = {w for w, n in conta.items() if n >= metade} \
                or set(minhas)

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


ARQUIVO_MEMORIA = "brasil_vistos.json"

# Quanto tempo um assunto continua sendo considerado "conhecido".
#
# Esta e a peca que separa NOTICIA ESTOURANDO de PAUTA AGENDADA - e sem
# ela o bot erra feio. Na medicao de 03/09 o topo do dia foi a "taxa das
# blusinhas", com 10 veiculos publicando junto. Parecia explosao. Nao
# era: a votacao estava marcada, todo mundo sabia, e o assunto ficou 3
# HORAS no ar, aparecendo em 6 rodadas seguidas. Cobertura sincronizada
# de coisa esperada nao e breaking news.
#
# Ja "Mendonça fala em honrar a confiança do povo", no meio da crise com
# Moraes, juntou 6 veiculos e apareceu em UMA rodada so. Apareceu do
# nada. Esse e o formato do que interessa.
#
# Entao o bot passa a guardar quando viu cada assunto pela primeira vez.
# Se ele ja rondava o noticiario ha horas, nao alerta - por mais
# veiculos que junte depois.
# Medido em 04/09/2026: com 12 horas, as palavras registradas as
# 23h22 do dia 03 ("acusa", "inquerito", "fake", "news") voltaram a
# contar como ineditas as 12h22 do dia 04. O alerta que saiu nessa
# hora nao era fato novo: era o assunto da noite anterior renascendo
# por expiracao da memoria - e chegou 80 minutos depois do fato real.
# Com 24 horas isso nao acontece.
HORAS_DE_MEMORIA = 24

# Um assunto so conta como novo se a primeira vez que foi visto tiver
# sido ha menos que isto. Acima disso, ja estava no radar.
MINUTOS_PARA_SER_NOVO = 45


def carrega_memoria():
    """O que o bot ja tinha visto, e desde quando."""
    try:
        with open(ARQUIVO_MEMORIA, encoding="utf-8") as f:
            bruto = json.load(f)
    except Exception:
        return {}

    agora = datetime.now(timezone.utc).timestamp()
    limite = agora - HORAS_DE_MEMORIA * 3600
    return {k: v for k, v in bruto.items() if v >= limite}


def salva_memoria(memoria):
    try:
        with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
            json.dump(memoria, f)
    except Exception as e:
        print(f"  nao consegui gravar a memoria: {e}")


def palavras_do_grupo(grupo, minimo=2):
    """
    As palavras que aparecem em pelo menos 2 manchetes do grupo.

    Exigir repeticao tira o ruido: nome de reporter, cidade citada de
    passagem, palavra que so um veiculo usou. O que sobra e do que o
    grupo esta falando de fato.
    """
    conta = defaultdict(int)
    for it in grupo["itens"]:
        for p in _palavras(it["titulo"]):
            conta[p] += 1
    fortes = {p for p, n in conta.items() if n >= minimo}
    return fortes or {p for p, _ in
                      sorted(conta.items(), key=lambda x: -x[1])[:4]}


def novidades(grupo, memoria, agora):
    """
    Quais palavras deste grupo o bot nunca tinha visto.

    Aqui esta a resposta para o caso mais dificil: FATO NOVO DENTRO DE
    ASSUNTO VELHO.
    
    O escandalo Vorcaro/Moraes domina o noticiario o dia inteiro. Se a
    memoria guardasse o assunto, ele entraria de manha e, a noite,
    "pedido de prisao do diretor-geral da PF" - que e a coisa mais forte
    do dia - sairia marcado como coisa velha, e o alerta morreria no
    melhor momento.
    
    Guardando PALAVRAS, nao: "vorcaro" e "prisao" ja sao conhecidas, mas
    "diretor" e "rodrigues" nunca apareceram. Duas palavras ineditas
    dentro de um assunto conhecido = aconteceu alguma coisa nova.
    """
    novas = set()
    for p in palavras_do_grupo(grupo):
        marca = memoria.get(p)
        if marca is None or (agora - marca) / 60 <= MINUTOS_PARA_SER_NOVO:
            novas.add(p)
    return novas


def registra(grupo, memoria, agora):
    for p in palavras_do_grupo(grupo):
        memoria.setdefault(p, agora)


# --- QUANDO ALERTAR -------------------------------------------------
#
# Os dois numeros abaixo NAO foram escolhidos: foram medidos em 81
# rodadas, 444 grupos, entre a tarde de 03/09 e a manha de 04/09.
#
# O que a medicao mostrou, olhando so o dia 04:
#
#   99 dos 203 grupos tiveram ZERO palavras ineditas -> repeteco puro
#   os eventos de verdade ficam todos na cauda
#
# Com 6 veiculos e 5 palavras ineditas, os eventos que passariam na
# madrugada foram, em ordem:
#
#   00h02  Moraes encaminha a Fachin pedido de investigacao   13 veic
#   00h42  Moraes aponta "fortes indicios de crimes"          15 veic
#   01h12  Moraes acusa Mendonca de abuso de autoridade       21 veic
#   02h12  Fachin cobra informacoes de Mendonca               13 veic
#   02h52  Crise escala no STF                                11 veic
#
# Todos fatos reais, na ordem em que aconteceram. Nenhuma pauta de
# agenda passou - a taxa das blusinhas, que tinha 11 veiculos, ficou
# de fora porque nao trouxe palavra inedita nenhuma.
#
# Dao cerca de 27 alertas por dia.
MINIMO_VEICULOS = 6
# Medido em 04/09/2026 no log de 03/09 18h22 ate 04/09 12h52:
# o fato novo do dia ("Mendonca quis saber o que tinha sobre Moraes no
# celular de Vorcaro", Poder360) apareceu as 11h02 UTC com 6 veiculos
# e 4 palavras ineditas - reprovado por UMA palavra. Com o corte em 4
# ele sairia 80 minutos antes. Contando o log inteiro, baixar de 5
# para 4 libera apenas 2 grupos a mais no dia, os dois sobre esse
# mesmo caso. Nao gera enxurrada.
MINIMO_INEDITAS = 4

# Um evento so e avisado UMA vez. Sem isto, "Moraes acusa Mendonca"
# seria enviado em 5 rodadas seguidas, porque continua batendo o corte
# enquanto os veiculos publicam.
ARQUIVO_ENVIADOS = "brasil_enviados.json"
HORAS_SEM_REPETIR = 10


def ja_foi_avisado(grupo, enviados, agora):
    """
    Este evento ja saiu no canal?

    Compara pelas palavras do grupo, nao pelo titulo: o titulo muda a
    cada rodada conforme entram manchetes novas, mas o conjunto de
    palavras do assunto continua o mesmo.
    """
    minhas = palavras_do_grupo(grupo)
    limite = agora - HORAS_SEM_REPETIR * 3600
    for item in enviados:
        antigas, quando = item[0], item[1]
        if quando < limite:
            continue
        comuns = len(minhas & set(antigas))
        if comuns / max(1, min(len(minhas), len(antigas))) >= 0.5:
            return True
    return False


# Os nomes de fonte carregam o sufixo da editoria do feed - "Gazeta do
# Povo Rep", "Folha Poder", "G1 Politica". Serve para eu saber de qual
# feed veio, mas fica feio no alerta.
SUFIXOS = (" Rep", " Poder", " Politica", " Just", " Noticias",
           " Brasil Politica", " Intl")


def nome_curto(fonte):
    for s in SUFIXOS:
        if fonte.endswith(s):
            return fonte[:-len(s)]
    return fonte


def monta_alerta(grupo, espalho):
    """
    O alerta que chega no celular.

    Formato aprovado em 04/09. Sai a lista de veiculos que ficava no
    rodape - era so nome empilhado, ocupava tres linhas e nao ajudava a
    decidir nada; quem publicou ja aparece em cada manchete abaixo.
    
    Entram os links: o nome do veiculo em cada linha vira clicavel,
    para abrir a materia direto sem ter que caçar no Google.
    """
    campo = grupo["fontes"] & CAMPO_DO_CANAL
    novas = grupo.get("novas", set())

    com_data = [i for i in grupo["itens"] if i["data"]]
    primeiro = min(com_data, key=lambda i: i["data"]) if com_data \
        else grupo["itens"][0]

    # horario de Brasilia: o servidor roda em UTC, 3 horas a mais. Sem
    # isto o alerta das 2h da manha chegaria marcado 05h.
    agora_br = datetime.now(timezone.utc) - timedelta(hours=3)

    linhas = [
        "🔴 <b>BREAKING — BRASIL</b>",
        f"<i>detectado às {agora_br.strftime('%Hh%M')}</i>",
        "",
        f"<b>{escapa(primeiro['titulo'])}</b>",
        "",
        f"📊 {len(grupo['fontes'])} veículos"
        + (f" em {espalho} min" if espalho else ""),
    ]
    if campo:
        linhas.append(f"✅ {len(campo)} do seu campo")
    elif not (grupo["fontes"] & GRANDES):
        linhas.append("⚠️ nenhum portal grande ainda")
    if novas:
        # as palavras da memoria sao guardadas sem acento, para
        # "investigação" e "investigacao" contarem como a mesma coisa.
        # Aqui elas voltam a forma escrita, pescando nos titulos.
        bonitas = {}
        for it in grupo["itens"]:
            for w in re.findall(r"[^\W\d_]{4,}", it["titulo"], re.UNICODE):
                bonitas.setdefault(normaliza(w), w.lower())
        exibir = sorted({bonitas.get(n, n) for n in novas})
        linhas.append(f"🆕 {escapa(', '.join(exibir)[:150])}")
    linhas.append("")

    # uma manchete por veiculo, com o nome virando link
    # deduplica pelo nome CURTO: "G1" e "G1 Politica" sao dois feeds,
    # mas o mesmo jornal - nao faz sentido aparecer duas vezes.
    vistos = set()
    postos = 0
    for it in grupo["itens"]:
        curto = nome_curto(it["fonte"])
        if curto in vistos:
            continue
        vistos.add(curto)
        nome = escapa(curto)
        texto = escapa(it["titulo"][:120])
        if it["link"]:
            linhas.append(f'• <a href="{escapa(it["link"])}">'
                          f'<b>{nome}</b></a>: {texto}')
        else:
            linhas.append(f"• <b>{nome}</b>: {texto}")
        postos += 1
        if postos >= 4:
            break

    return "\n".join(linhas)


def escapa(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def envia(texto):
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("CHAT_ID_BREAKING", "")
    if not token or not chat:
        print("  faltou TELEGRAM_TOKEN ou CHAT_ID_BREAKING - nao enviei")
        return False
    try:
        import urllib.request, urllib.parse
        dados = urllib.parse.urlencode({
            "chat_id": chat, "text": texto, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dados)
        with urllib.request.urlopen(req, timeout=30) as r:
            return b'"ok":true' in r.read()
    except Exception as e:
        print(f"  Telegram falhou: {e}")
        return False


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
        linhas.append(f"{'veic':>4} {'campo':>6} {'espalh':>7} {'novas':>6}  "
                      f"assunto  /  palavras ineditas")
        linhas.append("-" * 78)

    for g in grupos:
        espalho = minutos_de_espalhamento(g)
        grandes = g["fontes"] & GRANDES
        campo = g["fontes"] & CAMPO_DO_CANAL
        novas = g.get("novas", set())
        linhas.append(
            f"{len(g['fontes']):>4} {len(campo):>6} "
            f"{'?' if espalho is None else espalho:>7} {len(novas):>6}  "
            f"{g['rotulo'][:42]}"
        )
        if novas:
            linhas.append(f"       ineditas: {', '.join(sorted(novas))[:120]}")
        linhas.append(f"       veiculos: {', '.join(sorted(g['fontes']))[:150]}")
        for it in g["itens"][:3]:
            linhas.append(f"       . [{it['fonte']}] {it['titulo'][:110]}")
        linhas.append("")

    # A lista crua de manchetes saiu daqui.
    #
    # Ela existia para eu calibrar o agrupamento fora do ar, e ja
    # cumpriu isso: foi com ela que o corte de 0.30 foi medido. Rodando
    # de 10 em 10 minutos, ela sozinha faria o log passar de 1 MB por
    # dia e atrapalhar a leitura do que interessa.
    linhas.append("")
    texto = "\n".join(linhas)

    # append: cada rodada empilha na anterior, e o historico inteiro
    # fica em um arquivo so, que o Claude le pela API do GitHub.
    with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
        f.write(texto)
    print(texto)


# =====================================================================
# ANCAPSU - aviso de video novo
# =====================================================================
#
# Canal ANCAPSU (@ancap_su). Vem pelo RSS do YouTube, que e de graca e
# nao gasta cota da YouTube Data API.
#
# Tres protecoes contra enxurrada:
#   1) so avisa video publicado nos ultimos ANCAPSU_MINUTOS
#   2) guarda os IDs ja avisados em ancapsu_vistos.json
#   3) na PRIMEIRA rodada a janela encolhe para ANCAPSU_MINUTOS_ESTREIA:
#      o feed traz 15 videos e o canal publica varios por dia, entao
#      com a janela cheia a estreia viraria uma rajada de avisos de
#      video que voce ja viu. Com 30 minutos, se ele subir alguma coisa
#      agora voce e avisado na hora, e o resto fica so anotado.
ANCAPSU_CANAL = "UCLTWPE7XrHEe8m_xAmNbQ-Q"
ANCAPSU_FEED = ("https://www.youtube.com/feeds/videos.xml"
                f"?channel_id={ANCAPSU_CANAL}")
ARQUIVO_ANCAPSU = "ancapsu_vistos.json"
ANCAPSU_MINUTOS = 180
ANCAPSU_MINUTOS_ESTREIA = 30
ANCAPSU_LIMITE_MEMORIA = 300


def envia_com_link(texto):
    """
    Igual ao envia(), mas DEIXA o Telegram abrir a previa do YouTube.

    No alerta de manchetes a previa atrapalha (sao quatro links), aqui
    ela e o ponto: aparece a thumb do video direto no celular.
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("CHAT_ID_BREAKING", "")
    if not token or not chat:
        print("  faltou TELEGRAM_TOKEN ou CHAT_ID_BREAKING - nao enviei")
        return False
    try:
        import urllib.request, urllib.parse
        dados = urllib.parse.urlencode({
            "chat_id": chat, "text": texto, "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dados)
        with urllib.request.urlopen(req, timeout=30) as r:
            return b'"ok":true' in r.read()
    except Exception as e:
        print(f"  Telegram falhou: {e}")
        return False


def eh_short(video_id):
    """
    Este video e um Short?

    O RSS do YouTube nao diz a duracao nem o formato, e a YouTube Data
    API gastaria cota. O truque e o proprio site: a pagina
    youtube.com/shorts/ID abre normal quando o video E um Short, e
    REDIRECIONA para /watch quando nao e. Basta olhar para onde ela
    manda, sem baixar a pagina.

    Na duvida devolve False: perder um Short incomoda menos do que
    perder um video de verdade.
    """
    import urllib.request

    class SemSeguir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    url = f"https://www.youtube.com/shorts/{video_id}"
    abridor = urllib.request.build_opener(SemSeguir)
    req = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with abridor.open(req, timeout=20) as r:
            return r.status == 200          # abriu como Short
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return False                    # mandou para /watch: video normal
        return False
    except Exception:
        return False


def checa_ancapsu(mudo=False):
    """Avisa quando o ANCAPSU sobe video novo."""
    import urllib.request
    import xml.etree.ElementTree as ET

    try:
        req = urllib.request.Request(
            ANCAPSU_FEED, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            bruto = r.read()
    except Exception as e:
        print(f"  ANCAPSU: nao consegui ler o feed: {e}")
        return

    ns = {"a": "http://www.w3.org/2005/Atom",
          "yt": "http://www.youtube.com/xml/schemas/2015"}
    try:
        raiz = ET.fromstring(bruto)
    except Exception as e:
        print(f"  ANCAPSU: feed veio quebrado: {e}")
        return

    try:
        with open(ARQUIVO_ANCAPSU, encoding="utf-8") as f:
            vistos = json.load(f)
        primeira_vez = False
    except Exception:
        vistos = []
        primeira_vez = True

    conhecidos = set(vistos)
    agora = datetime.now(timezone.utc)
    novos = []

    for entrada in raiz.findall("a:entry", ns):
        vid = entrada.findtext("yt:videoId", default="", namespaces=ns)
        if not vid or vid in conhecidos:
            continue
        titulo = entrada.findtext("a:title", default="", namespaces=ns)
        quando = entrada.findtext("a:published", default="", namespaces=ns)
        try:
            data = datetime.fromisoformat(quando.replace("Z", "+00:00"))
        except Exception:
            data = None
        novos.append((vid, titulo, data))
        conhecidos.add(vid)

    # a memoria e gravada SEMPRE, inclusive na primeira vez - e ela que
    # impede o proximo ciclo de tratar os mesmos 15 videos como novos
    if not mudo:
        try:
            with open(ARQUIVO_ANCAPSU, "w", encoding="utf-8") as f:
                json.dump(sorted(conhecidos)[-ANCAPSU_LIMITE_MEMORIA:], f)
        except Exception as e:
            print(f"  ANCAPSU: nao gravei os vistos: {e}")

    if primeira_vez:
        print(f"  ANCAPSU: primeira rodada, {len(novos)} videos no feed")

    minutos = ANCAPSU_MINUTOS_ESTREIA if primeira_vez else ANCAPSU_MINUTOS
    limite = agora - timedelta(minutes=minutos)
    for vid, titulo, data in novos:
        if data and data < limite:
            continue
        if eh_short(vid):
            print(f"  ANCAPSU: pulei um Short - {titulo[:50]}")
            continue
        hora_br = (data or agora) - timedelta(hours=3)
        texto = (
            "🟡 <b>ANCAPSU subiu vídeo</b>\n"
            f"<i>{hora_br.strftime('%Hh%M')}</i>\n\n"
            f"<b>{escapa(titulo)}</b>\n\n"
            f"https://www.youtube.com/watch?v={vid}"
        )
        if mudo:
            print("\n--- SAIRIA ESTE AVISO ---\n" + texto + "\n")
        elif envia_com_link(texto):
            print(f"  ANCAPSU avisado: {titulo[:60]}")


# =====================================================================
# O JUIZ - fato novo ou repercussao do mesmo fato?
# =====================================================================
#
# Medido em 04/09/2026, no log de 03/09 18h22 a 04/09 12h52:
#
#   fato novo real (11h02, "Mendonca quis saber o que tinha sobre
#   Moraes no celular de Vorcaro")          -> 4 palavras ineditas
#   repeteco (10h43, "crise sem precedentes") -> 5 palavras ineditas
#
# O repeteco tem MAIS vocabulario novo que o fato novo. Nenhum corte de
# numero separa os dois: contar palavra mede novidade de palavra, nao
# novidade de acontecimento. Baixar o corte do ja_foi_avisado tambem
# nao resolve - o alerta chato deu 0.36 de semelhanca com o anterior, e
# descer o corte ate ali barraria junto qualquer fato novo dentro da
# saga Moraes x Mendonca, que e justamente a saga em cobertura.
#
# A pergunta "aconteceu algo, ou estao repercutindo o que ja aconteceu?"
# e de leitura. Entao ela vai para quem le: o Gemini recebe a manchete
# candidata e as que ja foram avisadas, e responde sim ou nao.
#
# Custo: uma chamada por candidato, poucos por rodada, no modelo mais
# barato. Continua de graca.
# Medido em 04/09/2026 pelo diagnostico da chave: gemini-2.5-flash e
# gemini-2.0-flash sairam do ar (404), e o proprio Google aponta o
# gemini-3.6-flash como substituto. Ele entra primeiro; os demais ficam
# de reserva.
# Ordem medida em 04/09/2026, com a chave real:
#   gemini-flash-latest      respondeu OK
#   gemini-flash-lite-latest 503 (sobrecarga momentanea)
#   gemini-3-flash-preview   429 (limite por minuto)
#   gemini-2.5 e 2.0         404, sairam do ar
# O Google aponta o gemini-3.6-flash como substituto dos que sairam,
# entao ele fica de reserva. Na frente vai o que respondeu.
MODELOS_IA = ["gemini-flash-latest", "gemini-flash-lite-latest",
              "gemini-3.6-flash", "gemini-3-flash-preview"]


def _chama_gemini(prompt, chave, teto_seg=60):
    """
    Uma pergunta ao Gemini, com cascata de modelos.

    TETO DE TEMPO. O juiz opina, mas nao manda: se ele demora, o alerta
    atrasa - e alerta atrasado e o problema que este bot existe para
    resolver. Medido em 04/09/2026: sem teto, uma sequencia de 429 do
    Gemini deixou o teste rodando mais de 10 minutos; em producao isso
    estouraria o limite do workflow e o aviso nao sairia. Vencido o
    teto, desiste e o alerta segue sem julgamento.
    """
    import time
    from urllib.request import Request, urlopen

    corpo = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }).encode()
    cabecalhos = {"Content-Type": "application/json", "x-goog-api-key": chave}

    comeco = time.time()
    for modelo in MODELOS_IA:
        for versao in ("v1beta", "v1"):
            url = (f"https://generativelanguage.googleapis.com/{versao}"
                   f"/models/{modelo}:generateContent")
            # o 429 do Gemini e por minuto e passa sozinho. Medido em
            # 04/09/2026: com teto de 25s o juiz desistia antes de o
            # limite liberar e deixava tudo passar sem julgar (3 de 9);
            # esperando ate 60s ele julga (7 de 9) e ainda cabe folgado
            # no limite de 10 minutos do workflow.
            # espera curta DE PROPOSITO: o que resolve nao e insistir
            # no mesmo modelo, e passar para o proximo. Medido em
            # 04/09/2026: dois modelos falharam e o terceiro respondeu
            # na hora. Com espera longa o teto de 60s acabaria antes de
            # a fila chegar nele.
            for espera in (0, 3):
                if time.time() - comeco > teto_seg:
                    return None
                if espera:
                    time.sleep(espera)
                try:
                    req = Request(url, data=corpo, headers=cabecalhos)
                    with urlopen(req, timeout=20) as r:
                        dados = json.loads(r.read())
                    return dados["candidates"][0]["content"]["parts"][0]["text"]
                except Exception as e:
                    if any(c in str(e) for c in ("404", "401", "403")):
                        break
                    # 429 RESOURCE_EXHAUSTED aqui NAO e cota do plano:
                    # e limite por minuto, e passa sozinho. Medido em
                    # 04/09/2026: a mesma chave que devolvia 429 em
                    # todos os modelos respondeu OK poucos minutos
                    # depois, no gemini-flash-latest. Por isso a cascata
                    # continua para o proximo modelo em vez de desistir
                    # - foi o modelo seguinte que salvou o julgamento.
    return None


def traz_fato_novo(titulo, ja_avisados, chave):
    """
    Este alerta conta algo que ainda nao foi contado?

    Devolve (sim_ou_nao, motivo). Sem chave, sem historico ou com a IA
    fora do ar, devolve True: perder um breaking custa mais caro do que
    receber um alerta repetido, entao a duvida passa.
    """
    if not ja_avisados:
        return True, "primeiro alerta do assunto"
    if not chave:
        return True, "sem GEMINI_API_KEY - passou sem julgar"

    anteriores = "\n".join(f"- {t}" for t in ja_avisados if t)
    if not anteriores.strip():
        return True, "nao guardei os titulos anteriores"

    prompt = (
        "Voce cuida de um alerta de ultima hora sobre politica brasileira. "
        "O dono do canal ja foi avisado das manchetes abaixo nas ultimas "
        "horas e NAO quer ser avisado de novo do mesmo acontecimento.\n\n"
        f"JA AVISADO:\n{anteriores}\n\n"
        f"MANCHETE NOVA:\n- {titulo}\n\n"
        "Pergunte-se: QUEM FEZ O QUE de novo?\n\n"
        "E FATO NOVO quando alguem praticou um ato que ainda nao aparece "
        "na lista: decidiu, determinou, pediu, abriu, arquivou, prendeu, "
        "soltou, afastou, indiciou, denunciou, votou, marcou prazo, ou "
        "quando surgiu uma revelacao concreta sobre o caso.\n\n"
        "E REPERCUSSAO quando ninguem fez nada novo e a manchete apenas "
        "comenta o que ja foi avisado:\n"
        "- analise, opiniao, editorial, 'entenda o caso', 'o que se sabe'\n"
        "- reacao, declaracao ou avaliacao de quem observa de fora\n"
        "- 'imprensa internacional repercute', 'analistas apontam', "
        "'especialistas avaliam', 'crise se agrava', 'sem precedentes'\n"
        "- detalhamento ou reformulacao do mesmo ato ja avisado\n\n"
        "ATENCAO: citar os mesmos personagens ou trazer nomes novos NAO "
        "torna a manchete um fato novo. O que conta e se houve ATO NOVO. "
        "Uma manchete sobre a repercussao de um fato ja avisado continua "
        "sendo repercussao, mesmo que mencione pessoas ainda nao citadas.\n\n"
        "Na duvida entre as duas, responda false.\n\n"
        "Responda APENAS JSON, sem markdown:\n"
        '{"fato_novo": true, "motivo": "quem fez o que, ate 8 palavras"}'
    )

    txt = _chama_gemini(prompt, chave)
    if not txt:
        return True, "IA fora do ar - passou sem julgar"

    txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        d = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return True, "resposta ilegivel - passou sem julgar"
        try:
            d = json.loads(m.group(0))
        except Exception:
            return True, "resposta ilegivel - passou sem julgar"

    return bool(d.get("fato_novo", True)), str(d.get("motivo", ""))[:60]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutos", type=int, default=MINUTOS_JANELA)
    p.add_argument("--mudo", action="store_true",
                   help="mostra o que sairia, sem mandar ao Telegram")
    args = p.parse_args()

    itens, erros, sem_data = coleta_minutos(args.minutos)
    grupos = agrupa(itens)

    # marca a idade de cada assunto e guarda os que ainda nao conhecia
    memoria = carrega_memoria()
    agora = datetime.now(timezone.utc).timestamp()
    for g in grupos:
        g["novas"] = novidades(g, memoria, agora)
    for g in grupos:
        registra(g, memoria, agora)
    salva_memoria(memoria)
    com_fato = sum(1 for g in grupos if len(g["novas"]) >= 2)
    print(f"  {com_fato} grupos trazem fato novo, "
          f"{len(grupos) - com_fato} sao repeteco")

    # --- alertas ---
    try:
        with open(ARQUIVO_ENVIADOS, encoding="utf-8") as f:
            bruto = json.load(f)
        # formato antigo: [palavras, quando]. Novo: [palavras, quando,
        # titulo]. Le os dois para nao perder o historico da rotacao.
        enviados = []
        for item in bruto:
            palavras, quando = item[0], item[1]
            titulo = item[2] if len(item) > 2 else ""
            enviados.append((set(palavras), quando, titulo))
    except Exception:
        enviados = []
    enviados = [e for e in enviados
                if e[1] >= agora - HORAS_SEM_REPETIR * 3600]

    chave_ia = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chave_ia:
        print("  sem GEMINI_API_KEY: o juiz de fato novo fica desligado")

    mandados = 0
    for g in grupos:
        if len(g["fontes"]) < MINIMO_VEICULOS:
            continue
        if len(g["novas"]) < MINIMO_INEDITAS:
            continue
        if ja_foi_avisado(g, enviados, agora):
            continue

        # o titulo que vai no alerta e a manchete mais antiga do grupo
        com_data = [i for i in g["itens"] if i["data"]]
        primeiro = (min(com_data, key=lambda i: i["data"]) if com_data
                    else g["itens"][0])["titulo"]

        anteriores = [e[2] for e in enviados if len(e) > 2 and e[2]]
        novo, motivo = traz_fato_novo(primeiro, anteriores, chave_ia)
        if not novo:
            print(f"  BARRADO pelo juiz ({motivo}): {primeiro[:55]}")
            continue

        texto = monta_alerta(g, minutos_de_espalhamento(g))
        if args.mudo:
            print(f"\n--- SAIRIA ESTE ALERTA ({motivo}) ---\n" + texto + "\n")
            enviados.append((palavras_do_grupo(g), agora, primeiro))
            mandados += 1
        elif envia(texto):
            print(f"  ALERTA enviado: {g['rotulo'][:60]}")
            enviados.append((palavras_do_grupo(g), agora, primeiro))
            mandados += 1

    if not args.mudo:
        try:
            with open(ARQUIVO_ENVIADOS, "w", encoding="utf-8") as f:
                json.dump([[sorted(e[0]), e[1],
                            e[2] if len(e) > 2 else ""] for e in enviados], f,
                          ensure_ascii=False)
        except Exception as e:
            print(f"  nao gravei os enviados: {e}")

    print(f"  {mandados} alerta(s)")

    checa_ancapsu(mudo=args.mudo)

    escreve_log(grupos, len(itens), erros, sem_data, args.minutos)

    print(f"\nMODO MEDICAO: nada foi enviado ao Telegram.")
    print(f"log.txt agora tem "
          f"{os.path.getsize(ARQUIVO_LOG) // 1024} KB")


if __name__ == "__main__":
    main()
