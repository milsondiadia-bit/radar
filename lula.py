#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lula.py - Radar de desgaste do governo.

Le feeds RSS, separa as manchetes da ultima hora que citam Lula, o Planalto,
ministros, o PT ou a gestao, manda para o Gemini classificar se a materia
DESGASTA o governo, ranqueia por repercussao (quantos veiculos deram) e
envia as 5 mais fortes para o Telegram.

Uso:
    python lula.py                  # janela padrao de 1h
    python lula.py --horas 2
    python lula.py --seco           # mostra na tela, nao envia
    python lula.py --zerar          # limpa o historico anti-repeticao

Variaveis de ambiente:
    GEMINI_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ARQ_HISTORICO = "lula_enviados.json"
MAX_HISTORICO = 800
MODELOS = ["gemini-3-flash-preview", "gemini-flash-latest",
           "gemini-2.0-flash", "gemini-flash-lite-latest"]


def gnews(query):
    return ("https://news.google.com/rss/search?q=" + quote(query)
            + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")


FONTES = [
    ("GNews Lula", gnews("Lula")),
    ("GNews Planalto", gnews("Planalto OR \"governo federal\" OR Presidencia")),
    ("GNews ministros", gnews("ministro OR ministra OR ministerio governo Lula")),
    ("GNews PT", gnews("PT OR \"Partido dos Trabalhadores\" OR petista")),
    ("GNews gestao", gnews("governo Lula economia OR inflacao OR desemprego OR gastos")),
    ("GNews aprovacao", gnews("aprovacao Lula OR pesquisa Datafolha OR Quaest OR Genial")),
    ("GNews crise", gnews("crise governo OR derrota governo OR pressao Planalto")),
    ("G1 Politica", "https://g1.globo.com/rss/g1/politica/"),
    ("Poder360", "https://www.poder360.com.br/feed/"),
    ("Congresso em Foco", "https://www.congressoemfoco.com.br/feed/"),
    ("Gazeta do Povo Rep", "https://www.gazetadopovo.com.br/feed/rss/republica.xml"),
    ("Agencia Camara", "https://www.camara.leg.br/noticias/rss/ultimas"),
    ("Agencia Senado", "https://www12.senado.leg.br/noticias/feed"),
    ("CNN Brasil Pol", "https://www.cnnbrasil.com.br/politica/feed/"),
    ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
    ("Conjur", "https://www.conjur.com.br/rss.xml"),
    ("Agencia Brasil Pol", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("UOL Politica", "https://rss.uol.com.br/feed/noticias.xml"),
]

# Manchete precisa citar pelo menos um destes para entrar
ALVOS = [
    "lula", "planalto", "governo federal", "presidente da republica",
    "pt ", " pt", "petista", "petistas", "partido dos trabalhadores",
    "ministro", "ministra", "ministerio", "esplanada", "haddad",
    "rui costa", "gleisi", "padilha", "boulos", "lewandowski",
    "silvio almeida", "camilo santana", "wellington dias", "marina silva",
    "presidencia", "governo lula", "executivo federal",
]

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
    nodes = raiz.iter("item")
    for it in nodes:
        titulo = limpar((it.findtext("title") or ""))
        link = (it.findtext("link") or "").strip()
        quando = data_de(it.findtext("pubDate") or it.findtext("published"))
        if titulo:
            itens.append({"titulo": titulo, "link": link,
                          "fonte": nome, "quando": quando})
    if not itens:  # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for it in raiz.iter(ns + "entry"):
            titulo = limpar(it.findtext(ns + "title") or "")
            el = it.find(ns + "link")
            link = el.get("href") if el is not None else ""
            quando = data_de(it.findtext(ns + "updated") or it.findtext(ns + "published"))
            if titulo:
                itens.append({"titulo": titulo, "link": link,
                              "fonte": nome, "quando": quando})
    return itens


def coletar(horas):
    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    tudo = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for lote in ex.map(ler_feed, FONTES):
            tudo.extend(lote)
    return [i for i in tudo if i["quando"] and i["quando"] >= corte]


def cita_alvo(titulo):
    t = " " + sem_acento(titulo) + " "
    return any(a in t for a in ALVOS)


def chave(titulo):
    palavras = [p for p in re.findall(r"[a-z0-9]+", sem_acento(titulo))
                if len(p) > 3 and p not in STOP]
    return set(palavras)


def agrupar(itens):
    """Junta manchetes que contam a mesma historia em veiculos diferentes."""
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


def classificar(grupos, chave_api):
    """Pergunta ao Gemini quais manchetes desgastam o governo."""
    lista = "\n".join(f"{n+1}. {g['titulo']}" for n, g in enumerate(grupos))
    prompt = (
        "Voce analisa manchetes da imprensa brasileira.\n\n"
        "Para cada manchete abaixo, diga se ela e NEGATIVA para o presidente Lula, "
        "para o Planalto, para ministros do governo ou para o PT. Ou seja: se ela "
        "mostra erro, derrota, escancaro, crise, denuncia, queda de popularidade, "
        "atrito interno, recuo, contradicao ou desgaste politico do governo.\n\n"
        "Atencao: 'Lula critica X' NAO e negativa para Lula. "
        "'Lula e criticado por X' E negativa. Leia a direcao da frase.\n\n"
        "Responda APENAS um array JSON, sem markdown, sem texto antes ou depois. "
        "Um objeto por manchete, na mesma ordem, no formato:\n"
        '[{"n":1,"desgasta":true,"nota":8,"motivo":"resumo em 6 palavras"}]\n'
        "nota vai de 0 a 10 (10 = desgaste muito forte).\n\n"
        f"MANCHETES:\n{lista}"
    )
    corpo = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }).encode()
    cabecalhos = {"Content-Type": "application/json", "x-goog-api-key": chave_api}

    txt = None
    ultimo = None
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
                    if "404" in str(e) or "401" in str(e) or "403" in str(e):
                        break          # modelo nao existe, nao adianta insistir
            if txt:
                break
        if txt:
            break
    if not txt:
        print(f"Gemini falhou: {ultimo}", file=sys.stderr)
        return {}
    txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        arr = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.S)
        if not m:
            return {}
        try:
            arr = json.loads(m.group(0))
        except Exception:
            return {}
    return {int(o["n"]): o for o in arr if isinstance(o, dict) and "n" in o}


def carregar_historico():
    try:
        with open(ARQ_HISTORICO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def salvar_historico(lista):
    with open(ARQ_HISTORICO, "w", encoding="utf-8") as f:
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
    ap.add_argument("--horas", type=float, default=1.0)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-veiculos", type=int, default=1)
    ap.add_argument("--nota-minima", type=int, default=5)
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--zerar", action="store_true")
    args = ap.parse_args()

    if args.zerar:
        salvar_historico([])
        print("Historico zerado.")
        return

    chave_api = os.environ.get("GEMINI_API_KEY", "").strip()
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chave_api:
        sys.exit("Falta GEMINI_API_KEY")
    if not args.seco and (not token or not chat):
        sys.exit("Falta TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID")

    itens = coletar(args.horas)
    print(f"Manchetes na janela de {args.horas}h: {len(itens)}")

    alvo = [i for i in itens if cita_alvo(i["titulo"])]
    print(f"Citam o governo: {len(alvo)}")
    if not alvo:
        print("Nada a fazer.")
        return

    historico = carregar_historico()
    vistos = set(historico)
    alvo = [i for i in alvo if i["titulo"] not in vistos]
    print(f"Ineditas: {len(alvo)}")
    if not alvo:
        print("Tudo ja foi enviado antes.")
        return

    grupos = agrupar(alvo)
    grupos = [g for g in grupos if g["veiculos"] >= args.min_veiculos]
    grupos.sort(key=lambda g: -g["veiculos"])
    grupos = grupos[:40]          # teto para nao estourar o prompt
    print(f"Historias distintas: {len(grupos)}")

    veredito = classificar(grupos, chave_api)
    if not veredito:
        print("Sem resposta da IA. Abortando.")
        return

    fortes = []
    for n, g in enumerate(grupos, 1):
        v = veredito.get(n)
        if not v or not v.get("desgasta"):
            continue
        nota = int(v.get("nota") or 0)
        if nota < args.nota_minima:
            continue
        g["nota"] = nota
        g["motivo"] = (v.get("motivo") or "").strip()
        fortes.append(g)

    fortes.sort(key=lambda g: (-g["nota"], -g["veiculos"]))
    fortes = fortes[: args.top]
    print(f"Selecionadas: {len(fortes)}")

    if not fortes:
        print("Nenhuma manchete de desgaste nesta janela.")
        return

    agora = datetime.now(timezone.utc) - timedelta(hours=3)
    linhas = [f"<b>🔻 DESGASTE — ultimas {args.horas:g}h</b>",
              f"<i>{agora.strftime('%d/%m %H:%M')}</i>", ""]
    for g in fortes:
        veic = f"{g['veiculos']} veiculos" if g["veiculos"] > 1 else g["itens"][0]["fonte"]
        linhas.append(f"<b>{g['nota']}/10</b> · {veic}")
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
        salvar_historico(historico)
    else:
        print("Falha ao enviar.")


if __name__ == "__main__":
    main()
