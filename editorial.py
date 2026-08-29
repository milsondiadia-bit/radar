#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
editorial.py - Vigia os videos embutidos nas materias do Editorial Central.

Le o news-sitemap do site, abre as materias recentes, procura embeds de
Instagram, Facebook, YouTube, TikTok e X, e manda os videos NOVOS no Telegram.

Uso:
    python editorial.py                 # janela padrao de 24h
    python editorial.py --horas 6
    python editorial.py --seco          # mostra na tela, nao envia
    python editorial.py --zerar         # limpa o historico
    python editorial.py --marcar-tudo   # marca tudo como visto, sem enviar

Variaveis de ambiente:
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import unquote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

SITE = "https://www.editorialcentral.com.br"
SITEMAP = f"{SITE}/news-sitemap.xml"
ARQ = "editorial_vistos.json"
MAX_HISTORICO = 2000
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 radar"

# ---------------------------------------------------------------- extratores

PADROES = [
    # (nome da rede, regex, molde do link limpo)
    ("Instagram", re.compile(
        r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]{5,})", re.I),
        "https://www.instagram.com/reel/{0}/"),
    ("YouTube", re.compile(
        r"(?:youtube\.com/(?:embed|shorts|watch\?v=)/?|youtu\.be/)([A-Za-z0-9_-]{11})", re.I),
        "https://www.youtube.com/watch?v={0}"),
    ("TikTok", re.compile(
        r"tiktok\.com/(?:@[\w.\-]+/video|embed/v2)/(\d{8,})", re.I),
        "https://www.tiktok.com/video/{0}"),
    ("X", re.compile(
        r"(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/status/(\d{8,})", re.I),
        "https://x.com/{0}/status/{1}"),
    ("Facebook", re.compile(
        r"facebook\.com/([\w.\-]+)/videos/(\d{6,})", re.I),
        "https://www.facebook.com/{0}/videos/{1}/"),
    ("Facebook", re.compile(r"fb\.watch/([A-Za-z0-9_-]{5,})", re.I),
        "https://fb.watch/{0}/"),
]

TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def baixar(url, timeout=25):
    req = Request(url, headers={"User-Agent": UA,
                                "Accept-Language": "pt-BR,pt;q=0.9"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def limpar(txt):
    txt = unescape(txt or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def ler_sitemap(horas):
    """Devolve [(url, data)] das materias dentro da janela."""
    try:
        raiz = ET.fromstring(baixar(SITEMAP))
    except Exception as e:
        print(f"Falha ao ler o sitemap: {e}", file=sys.stderr)
        return []

    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    saida = []
    for url in raiz.iter():
        if not url.tag.endswith("}url") and url.tag != "url":
            continue
        loc = quando = None
        for filho in url.iter():
            tag = filho.tag.split("}")[-1]
            if tag == "loc" and filho.text and "/noticia/" in filho.text:
                loc = filho.text.strip()
            elif tag in ("publication_date", "lastmod") and filho.text:
                quando = quando or filho.text.strip()
        if not loc:
            continue
        dt = None
        if quando:
            try:
                dt = datetime.fromisoformat(quando.replace("Z", "+00:00"))
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
        if dt is None or dt >= corte:
            saida.append((loc, dt))
    return saida


def extrair_videos(html):
    """Devolve lista de (rede, link_limpo) encontrados na pagina."""
    html = html + " " + unquote(html)   # pega embeds com URL codificada (%2F)
    achados, vistos = [], set()
    for rede, rx, molde in PADROES:
        for m in rx.finditer(html):
            link = molde.format(*m.groups())
            if link in vistos:
                continue
            vistos.add(link)
            achados.append((rede, link))
    return achados


def processar(url):
    try:
        html = baixar(url).decode("utf-8", "ignore")
    except Exception as e:
        print(f"  falhou {url}: {e}", file=sys.stderr)
        return None
    m = TITULO.search(html)
    titulo = limpar(m.group(1)) if m else url.rsplit("/", 1)[-1]
    titulo = re.sub(r"\s*\|\s*Editorial Central\s*$", "", titulo)
    return {"url": url, "titulo": titulo, "videos": extrair_videos(html)}


# ---------------------------------------------------------------- historico

def carregar():
    try:
        with open(ARQ, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def salvar(lista):
    with open(ARQ, "w", encoding="utf-8") as f:
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


# ---------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horas", type=float, default=24.0)
    ap.add_argument("--max-materias", type=int, default=40)
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--zerar", action="store_true")
    ap.add_argument("--marcar-tudo", action="store_true")
    args = ap.parse_args()

    if args.zerar:
        salvar([])
        print("Historico zerado.")
        return

    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not args.seco and not args.marcar_tudo and (not token or not chat):
        sys.exit("Falta TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID")

    materias = ler_sitemap(args.horas)
    print(f"Materias na janela de {args.horas:g}h: {len(materias)}")
    if not materias:
        print("Nada a fazer.")
        return

    urls = [u for u, _ in materias][: args.max_materias]
    with ThreadPoolExecutor(max_workers=6) as ex:
        paginas = [p for p in ex.map(processar, urls) if p]
    print(f"Materias lidas: {len(paginas)}")

    historico = carregar()
    vistos = set(historico)

    novos = []
    total_videos = 0
    for p in paginas:
        pendentes = [(rede, link) for rede, link in p["videos"]
                     if link not in vistos]
        total_videos += len(p["videos"])
        if pendentes:
            novos.append({**p, "videos": pendentes})

    print(f"Videos encontrados: {total_videos}")
    print(f"Videos ineditos: {sum(len(n['videos']) for n in novos)}")

    if args.marcar_tudo:
        for p in paginas:
            for _, link in p["videos"]:
                historico.append(link)
        salvar(historico)
        print("Tudo marcado como visto. Nada enviado.")
        return

    if not novos:
        print("Nenhum video novo.")
        return

    agora = datetime.now(timezone.utc) - timedelta(hours=3)
    linhas = ["🎬 <b>EDITORIAL CENTRAL — videos novos</b>",
              f"<i>{agora.strftime('%d/%m %H:%M')}</i>", ""]
    for n in novos:
        linhas.append(f"<a href=\"{n['url']}\">{n['titulo']}</a>")
        for rede, link in n["videos"]:
            linhas.append(f"   {rede}: {link}")
        linhas.append("")
    texto = "\n".join(linhas).strip()

    # Telegram corta em 4096 caracteres
    if len(texto) > 3900:
        texto = texto[:3900].rsplit("\n", 1)[0] + "\n\n<i>(lista truncada)</i>"

    if args.seco:
        print("\n--- PREVIA ---\n")
        print(texto)
        return

    if enviar(texto, token, chat):
        print("Enviado.")
        for n in novos:
            for _, link in n["videos"]:
                historico.append(link)
        salvar(historico)
    else:
        print("Falha ao enviar.")


if __name__ == "__main__":
    main()
