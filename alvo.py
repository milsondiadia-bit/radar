#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alvo.py - Radar por figura publica.

Perfis:
    mendonca  - tudo sobre Andre Mendonca, ranqueado por repercussao (sem IA)
    flavio    - so o que e FAVORAVEL a Flavio Bolsonaro (usa IA)

Uso:
    python alvo.py mendonca
    python alvo.py flavio --horas 3
    python alvo.py flavio --seco        # mostra na tela, nao envia
    python alvo.py mendonca --zerar     # limpa o historico

Variaveis de ambiente:
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    GEMINI_API_KEY (so para perfis que usam IA)
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

MAX_HISTORICO = 800
MODELOS = ["gemini-flash-lite-latest", "gemini-3-flash-preview",
           "gemini-flash-latest"]


def gnews(query):
    return ("https://news.google.com/rss/search?q=" + quote(query)
            + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")


# Feeds gerais, usados por todos os perfis
FEEDS_BASE = [
    ("G1 Politica", "https://g1.globo.com/rss/g1/politica/"),
    ("Poder360", "https://www.poder360.com.br/feed/"),
    ("Congresso em Foco", "https://www.congressoemfoco.com.br/feed/"),
    ("Gazeta do Povo", "https://www.gazetadopovo.com.br/feed/rss/republica.xml"),
    ("Conjur", "https://www.conjur.com.br/rss.xml"),
    ("Agencia Senado", "https://www12.senado.leg.br/noticias/feed"),
    ("Agencia Camara", "https://www.camara.leg.br/noticias/rss/ultimas"),
    ("CNN Brasil Pol", "https://www.cnnbrasil.com.br/politica/feed/"),
    ("Agencia Brasil Pol", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("UOL Noticias", "https://rss.uol.com.br/feed/noticias.xml"),
    ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
]

PERFIS = {
    "mendonca": {
        "titulo": "ANDRE MENDONCA",
        "emoji": "⚖️",
        "arquivo": "alvo_enviados_mendonca.json",
        "horas": 6,
        "usa_ia": False,
        "feeds": [
            ("GNews Mendonca", gnews("\"Andre Mendonca\"")),
            ("GNews Mendonca STF", gnews("Mendonca STF ministro")),
            ("GNews Mendonca voto", gnews("Mendonca voto OR decisao OR liminar STF")),
        ],
        "alvos": [
            "andre mendonca", "andré mendonça", "mendonca", "mendonça",
        ],
        "excluir": [
            # evita homonimos comuns
            "mendonca filho", "mendonça filho",   # Rafael Mendonça Filho
            "duda mendonca", "duda mendonça",
            "mendonca lima", "mendonça lima",
        ],
    },
    "flavio": {
        "titulo": "FLAVIO BOLSONARO",
        "emoji": "🟢",
        "arquivo": "alvo_enviados_flavio.json",
        "horas": 3,
        "usa_ia": True,
        "direcao": (
            "Diga se a manchete e FAVORAVEL ao senador Flavio Bolsonaro. "
            "Ou seja: se ela mostra vitoria, crescimento em pesquisa, apoio "
            "recebido, elogio, absolvicao, arquivamento de processo, avanco de "
            "candidatura, boa repercussao ou qualquer ganho politico dele.\n\n"
            "Atencao: 'Flavio critica X' NAO e necessariamente favoravel a ele. "
            "'Flavio e elogiado por X' E favoravel. "
            "'Flavio e denunciado' NAO e favoravel. Leia a direcao da frase."
        ),
        "rotulo_nota": "favoravel",
        "feeds": [
            ("GNews Flavio", gnews("\"Flavio Bolsonaro\"")),
            ("GNews Flavio candidato", gnews("Flavio Bolsonaro candidatura OR pesquisa OR eleicao")),
            ("GNews Flavio senado", gnews("Flavio Bolsonaro senador OR Senado")),
        ],
        "alvos": [
            "flavio bolsonaro", "flávio bolsonaro",
        ],
        "excluir": [],
    },
}

STOP = set("""a o as os um uma de do da dos das em no na nos nas por pelo pela para com
sem sob sobre entre ate apos ante contra desde e ou mas porem que se ao aos eh sao foi
foram ser sera seria tem tinha teve ter havia ha estao esta este esse aquele isso isto
seu sua seus suas qual quais quando onde como porque mais menos muito pouco ja nao sim
tambem apenas so ainda depois antes agora hoje ontem diz disse dizem afirma afirmou veja
saiba entenda confira leia video fotos assista apos durante todo toda todos todas outro
outra novo nova maior menor primeiro segundo vai vao pode podem deve devem""".split())


def sem_acento(txt):
    return "".join(c for c in unicodedata.normalize("NFKD", txt)
                   if not unicodedata.combining(c)).lower()


def limpar(txt):
    txt = unescape(txt or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def baixar(url, timeout=20):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (radar)"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def data_de(txt):
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


def ler_feed(par):
    nome, url = par
    itens = []
    try:
        raiz = ET.fromstring(baixar(url))
    except Exception:
        return itens
    for it in raiz.iter("item"):
        titulo = limpar(it.findtext("title") or "")
        link = (it.findtext("link") or "").strip()
        quando = data_de(it.findtext("pubDate") or it.findtext("published"))
        if titulo:
            itens.append({"titulo": titulo, "link": link,
                          "fonte": nome, "quando": quando})
    if not itens:
        ns = "{http://www.w3.org/2005/Atom}"
        for it in raiz.iter(ns + "entry"):
            titulo = limpar(it.findtext(ns + "title") or "")
            el = it.find(ns + "link")
            link = el.get("href") if el is not None else ""
            quando = data_de(it.findtext(ns + "updated")
                             or it.findtext(ns + "published"))
            if titulo:
                itens.append({"titulo": titulo, "link": link,
                              "fonte": nome, "quando": quando})
    return itens


def coletar(feeds, horas):
    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    tudo = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for lote in ex.map(ler_feed, feeds):
            tudo.extend(lote)
    return [i for i in tudo if i["quando"] and i["quando"] >= corte]


def cita_alvo(titulo, perfil):
    t = " " + sem_acento(titulo) + " "
    for e in perfil["excluir"]:
        if sem_acento(e) in t:
            return False
    return any(sem_acento(a) in t for a in perfil["alvos"])


def chave(titulo):
    return {p for p in re.findall(r"[a-z0-9]+", sem_acento(titulo))
            if len(p) > 3 and p not in STOP}


def agrupar(itens):
    grupos = []
    for it in itens:
        k = chave(it["titulo"])
        if not k:
            continue
        achou = None
        for g in grupos:
            comum = len(k & g["chave"])
            menor = min(len(k), len(g["chave"])) or 1
            if comum / menor >= 0.5:
                achou = g
                break
        if achou:
            achou["itens"].append(it)
            achou["chave"] |= k
        else:
            grupos.append({"chave": k, "itens": [it]})
    for g in grupos:
        g["veiculos"] = len({i["fonte"] for i in g["itens"]})
        g["titulo"] = max((i["titulo"] for i in g["itens"]), key=len)
        g["link"] = g["itens"][0]["link"]
    return grupos


def classificar(grupos, perfil, chave_api):
    lista = "\n".join(f"{n+1}. {g['titulo']}" for n, g in enumerate(grupos))
    rotulo = perfil["rotulo_nota"]
    prompt = (
        "Voce analisa manchetes da imprensa brasileira.\n\n"
        + perfil["direcao"] + "\n\n"
        "Responda APENAS um array JSON, sem markdown, sem texto antes ou depois. "
        "Um objeto por manchete, na mesma ordem, no formato:\n"
        f'[{{"n":1,"{rotulo}":true,"nota":8,"motivo":"resumo em 6 palavras"}}]\n'
        "nota vai de 0 a 10 (10 = muito forte).\n\n"
        f"MANCHETES:\n{lista}"
    )
    corpo = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8000,
            "responseMimeType": "application/json",
        },
    }).encode()
    cabecalhos = {"Content-Type": "application/json", "x-goog-api-key": chave_api}

    txt, ultimo = None, None
    for modelo in MODELOS:
        for versao in ("v1beta", "v1"):
            url = (f"https://generativelanguage.googleapis.com/{versao}/models/"
                   f"{modelo}:generateContent")
            for espera in (0, 20, 40):
                if espera:
                    time.sleep(espera)
                try:
                    req = Request(url, data=corpo, headers=cabecalhos)
                    with urlopen(req, timeout=120) as r:
                        dados = json.loads(r.read())
                    txt = dados["candidates"][0]["content"]["parts"][0]["text"]
                    print(f"IA respondeu: {modelo} ({versao})")
                    break
                except Exception as e:
                    ultimo = f"{modelo}/{versao}: {e}"
                    print(ultimo, file=sys.stderr)
                    if any(c in str(e) for c in ("404", "401", "403")):
                        break
            if txt:
                break
        if txt:
            break
    if not txt:
        print(f"Gemini falhou: {ultimo}", file=sys.stderr)
        return {}

    txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    dado = None
    try:
        dado = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.S)
        if m:
            try:
                dado = json.loads(m.group(0))
            except Exception:
                pass
    if dado is None:
        recuperados = []
        for p in re.findall(r"\{[^{}]*\}", txt, re.S):
            try:
                recuperados.append(json.loads(p))
            except Exception:
                continue
        if recuperados:
            print(f"JSON truncado; recuperados {len(recuperados)} itens.",
                  file=sys.stderr)
            dado = recuperados
    if dado is None:
        print(f"JSON ilegivel. Resposta crua:\n{txt[:2000]}", file=sys.stderr)
        return {}

    if isinstance(dado, dict):
        for v in dado.values():
            if isinstance(v, list):
                dado = v
                break
    if not isinstance(dado, list):
        return {}

    saida = {}
    for pos, o in enumerate(dado, 1):
        if not isinstance(o, dict):
            continue
        try:
            n = int(o.get("n", pos))
        except Exception:
            n = pos
        saida[n] = o
    return saida


def carregar_historico(arq):
    try:
        with open(arq, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def salvar_historico(arq, lista):
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(lista[-MAX_HISTORICO:], f, ensure_ascii=False, indent=1)


def enviar(texto, token, chat):
    corpo = json.dumps({
        "chat_id": chat, "text": texto,
        "parse_mode": "HTML", "disable_web_page_preview": False,
    }).encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage",
                  data=corpo, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as r:
        return r.status == 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("perfil", choices=sorted(PERFIS))
    ap.add_argument("--horas", type=float, default=None)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-veiculos", type=int, default=1)
    ap.add_argument("--nota-minima", type=int, default=5)
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--zerar", action="store_true")
    args = ap.parse_args()

    perfil = PERFIS[args.perfil]
    arq = perfil["arquivo"]

    if args.zerar:
        salvar_historico(arq, [])
        print(f"Historico de {args.perfil} zerado.")
        return

    horas = args.horas if args.horas is not None else perfil["horas"]
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    chave_api = os.environ.get("GEMINI_API_KEY", "").strip()

    if not args.seco and (not token or not chat):
        sys.exit("Falta TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID")
    if perfil["usa_ia"] and not chave_api:
        sys.exit("Falta GEMINI_API_KEY")

    feeds = FEEDS_BASE + perfil["feeds"]
    itens = coletar(feeds, horas)
    print(f"Manchetes na janela de {horas}h: {len(itens)}")

    alvo = [i for i in itens if cita_alvo(i["titulo"], perfil)]
    print(f"Citam o alvo: {len(alvo)}")
    if not alvo:
        print("Nada a fazer.")
        return

    historico = carregar_historico(arq)
    vistos = set(historico)
    alvo = [i for i in alvo if i["titulo"] not in vistos]
    print(f"Ineditas: {len(alvo)}")
    if not alvo:
        print("Tudo ja foi enviado antes.")
        return

    grupos = agrupar(alvo)
    grupos = [g for g in grupos if g["veiculos"] >= args.min_veiculos]
    grupos.sort(key=lambda g: -g["veiculos"])
    grupos = grupos[:25]
    print(f"Historias distintas: {len(grupos)}")

    if perfil["usa_ia"]:
        veredito = classificar(grupos, perfil, chave_api)
        if not veredito:
            print("Sem resposta da IA. Abortando.")
            return
        rotulo = perfil["rotulo_nota"]
        fortes = []
        for n, g in enumerate(grupos, 1):
            v = veredito.get(n)
            if not v or not v.get(rotulo):
                continue
            nota = int(v.get("nota") or 0)
            if nota < args.nota_minima:
                continue
            g["nota"] = nota
            g["motivo"] = (v.get("motivo") or "").strip()
            fortes.append(g)
        fortes.sort(key=lambda g: (-g["nota"], -g["veiculos"]))
    else:
        fortes = grupos                      # sem IA: puro ranking por repercussao
        for g in fortes:
            g["nota"] = None
            g["motivo"] = ""

    fortes = fortes[: args.top]
    print(f"Selecionadas: {len(fortes)}")
    if not fortes:
        print("Nada relevante nesta janela.")
        return

    agora = datetime.now(timezone.utc) - timedelta(hours=3)
    cab = f"{perfil['emoji']} <b>{perfil['titulo']}</b> — ultimas {horas:g}h"
    linhas = [cab, f"<i>{agora.strftime('%d/%m %H:%M')}</i>", ""]
    for g in fortes:
        veic = (f"{g['veiculos']} veiculos" if g["veiculos"] > 1
                else g["itens"][0]["fonte"])
        if g["nota"] is not None:
            linhas.append(f"<b>{g['nota']}/10</b> · {veic}")
        else:
            linhas.append(f"· {veic}")
        linhas.append(f"<a href=\"{g['link']}\">{g['titulo']}</a>")
        if g["motivo"]:
            linhas.append(f"<i>{g['motivo']}</i>")
        linhas.append("")
    texto = "\n".join(linhas).strip()

    if args.seco:
        print("\n--- PREVIA ---\n")
        print(texto)
        return

    if enviar(texto, token, chat):
        print("Enviado.")
        for g in fortes:
            for i in g["itens"]:
                historico.append(i["titulo"])
        salvar_historico(arq, historico)
    else:
        print("Falha ao enviar.")


if __name__ == "__main__":
    main()
