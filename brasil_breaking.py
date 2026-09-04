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
HORAS_DE_MEMORIA = 12

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
MINIMO_INEDITAS = 5

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
    for antigas, quando in enviados:
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

    Curto de proposito. A primeira versao trazia tempo de espalhamento,
    lista de veiculos e as palavras ineditas - informacao demais para
    quem esta lendo no meio da rua, decidindo em 5 segundos se vale um
    video. Isso tudo continua no log.txt, para quando eu precisar
    calibrar.
    
    Aqui fica so: o que aconteceu, o tamanho da coisa, e links para
    clicar. O nome do veiculo E o link - assim nao ha URL comprida
    poluindo a tela.
    """
    campo = grupo["fontes"] & CAMPO_DO_CANAL

    com_data = [i for i in grupo["itens"] if i["data"]]
    primeiro = min(com_data, key=lambda i: i["data"]) if com_data \
        else grupo["itens"][0]

    linhas = ["🔴 <b>BREAKING — BRASIL</b>", ""]
    if primeiro["link"]:
        linhas.append(f'<b><a href="{escapa(primeiro["link"])}">'
                      f'{escapa(primeiro["titulo"])}</a></b>')
    else:
        linhas.append(f"<b>{escapa(primeiro['titulo'])}</b>")
    linhas.append(f"<i>{escapa(nome_curto(primeiro['fonte']))}</i>")

    resumo = f"{len(grupo['fontes'])} veículos"
    if campo:
        resumo += f" · {len(campo)} do seu campo"
    elif not (grupo["fontes"] & GRANDES):
        resumo += " · nenhum portal grande ainda"
    linhas.append(resumo)
    linhas.append("")

    # uma manchete por veiculo, com o nome do veiculo virando link.
    # o item que virou titulo la em cima nao se repete aqui.
    vistos = {primeiro["fonte"]}
    postos = 0
    for it in grupo["itens"]:
        if it["fonte"] in vistos or not it["link"]:
            continue
        vistos.add(it["fonte"])
        nome = escapa(nome_curto(it["fonte"]))
        texto = escapa(it["titulo"][:110])
        linhas.append(f'• <a href="{escapa(it["link"])}">{nome}</a> — {texto}')
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
            enviados = [(set(a), q) for a, q in json.load(f)]
    except Exception:
        enviados = []
    enviados = [(a, q) for a, q in enviados
                if q >= agora - HORAS_SEM_REPETIR * 3600]

    mandados = 0
    for g in grupos:
        if len(g["fontes"]) < MINIMO_VEICULOS:
            continue
        if len(g["novas"]) < MINIMO_INEDITAS:
            continue
        if ja_foi_avisado(g, enviados, agora):
            continue
        texto = monta_alerta(g, minutos_de_espalhamento(g))
        if args.mudo:
            print("\n--- SAIRIA ESTE ALERTA ---\n" + texto + "\n")
            mandados += 1
        elif envia(texto):
            print(f"  ALERTA enviado: {g['rotulo'][:60]}")
            enviados.append((palavras_do_grupo(g), agora))
            mandados += 1

    if not args.mudo:
        try:
            with open(ARQUIVO_ENVIADOS, "w", encoding="utf-8") as f:
                json.dump([[sorted(a), q] for a, q in enviados], f)
        except Exception as e:
            print(f"  nao gravei os enviados: {e}")

    print(f"  {mandados} alerta(s)")
    escreve_log(grupos, len(itens), erros, sem_data, args.minutos)

    print(f"\nMODO MEDICAO: nada foi enviado ao Telegram.")
    print(f"log.txt agora tem "
          f"{os.path.getsize(ARQUIVO_LOG) // 1024} KB")


if __name__ == "__main__":
    main()
