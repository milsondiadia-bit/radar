#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_radar.py - Manda para o Telegram as manchetes do assunto que esta
dominando o noticiario, de tempos em tempos, sem repetir o que ja mandou.

Precisa do arquivo radar.py na MESMA PASTA.
Nao precisa instalar nada (so Python 3.8+).

CONFIGURACAO (uma vez so):
    Windows (cmd):
        set TELEGRAM_TOKEN=123456:AAF...
        set TELEGRAM_CHAT_ID=987654321
    Mac / Linux:
        export TELEGRAM_TOKEN=123456:AAF...
        export TELEGRAM_CHAT_ID=987654321

USO:
    python telegram_radar.py --teste            # so testa se o bot fala com voce
    python telegram_radar.py mundo --uma-vez    # manda uma vez e sai (use com cron)
    python telegram_radar.py mundo --loop 30    # fica rodando, manda a cada 30 min
    python telegram_radar.py brasil --loop 30   # mesma coisa, mas politica/justica
    python telegram_radar.py mundo --loop 30 --silencioso   # notificacao sem som

    --manchetes 5   quantas manchetes por envio (padrao 5)
    --horas 6       janela de coleta (padrao 6h, bom para envios frequentes)
    --seco          mostra na tela o que enviaria, sem mandar nada
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import radar
except ImportError:
    sys.exit("ERRO: coloque o telegram_radar.py na mesma pasta do radar.py")

API = "https://api.telegram.org/bot{token}/{metodo}"
HISTORICO = "radar_enviados_{modo}.json"
MAX_HISTORICO = 800          # quantas manchetes lembrar antes de esquecer as antigas
EMOJI = {"mundo": "\U0001F30D", "brasil": "\U0001F1E7\U0001F1F7"}
ROTULO = {"mundo": "Radar geopolitico", "brasil": "Radar Brasil - politica e justica"}


# ---------------------------------------------------------------- Telegram ---

def telegram(token, metodo, **campos):
    dados = urlencode({k: v for k, v in campos.items() if v is not None}).encode()
    req = Request(API.format(token=token, metodo=metodo), data=dados)
    try:
        with urlopen(req, timeout=25) as r:
            return json.load(r)
    except HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Telegram recusou ({e.code}): {corpo}") from None
    except URLError as e:
        raise RuntimeError(f"Sem conexao com o Telegram: {e.reason}") from None


def envia(token, chat_id, texto, silencioso=False):
    return telegram(token, "sendMessage",
                    chat_id=chat_id,
                    text=texto[:4000],
                    parse_mode="HTML",
                    disable_web_page_preview="true",
                    disable_notification="true" if silencioso else None)


# --------------------------------------------------------------- Historico ---

def carrega_historico(modo):
    try:
        with open(HISTORICO.format(modo=modo), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salva_historico(modo, chaves):
    with open(HISTORICO.format(modo=modo), "w", encoding="utf-8") as f:
        json.dump(chaves[-MAX_HISTORICO:], f, ensure_ascii=False)


def chave_da_manchete(item):
    """Identidade da noticia: o link, ou o titulo normalizado se nao houver link."""
    if item.get("link"):
        return item["link"].split("?")[0][:200]
    return radar.normaliza(item["titulo"])[:120]


# ---------------------------------------------------------------- Mensagem ---

def seleciona(ranking, ja_enviados, limite):
    """Pega manchetes ineditas, comecando pelos assuntos mais quentes.

    Faz duas passadas: primeiro uma manchete de cada assunto (para a mensagem
    nao virar cinco versoes da mesma noticia), depois completa se faltar.
    """
    vistos = set(ja_enviados)
    escolhidas, usadas = [], set()

    def recentes(assunto):
        return sorted(assunto["itens"],
                      key=lambda i: i["data"] or datetime.min.replace(tzinfo=timezone.utc),
                      reverse=True)

    ordem = {id(a): n for n, a in enumerate(ranking)}

    for passada in (1, limite):
        for assunto in ranking:
            pegos = 0
            for it in recentes(assunto):
                if len(escolhidas) >= limite:
                    break
                if pegos >= passada:
                    break
                ch = chave_da_manchete(it)
                if ch in vistos or ch in usadas:
                    continue
                usadas.add(ch)
                escolhidas.append((assunto, it))
                pegos += 1
            if len(escolhidas) >= limite:
                break
        if len(escolhidas) >= limite:
            break

    # reagrupa por assunto (assunto mais quente primeiro) para a mensagem
    # nao ficar com o mesmo cabecalho repetido em blocos separados
    escolhidas.sort(key=lambda par: ordem[id(par[0])])
    return escolhidas


def monta_mensagem(modo, escolhidas, total_manchetes, horas):
    agora = datetime.now().strftime("%d/%m %H:%M")
    linhas = [f"{EMOJI[modo]} <b>{ROTULO[modo]}</b>",
              f"<i>{agora} · últimas {horas}h · {total_manchetes} manchetes lidas</i>",
              ""]
    assunto_atual = None
    for assunto, it in escolhidas:
        if assunto["rotulo"] != assunto_atual:
            assunto_atual = assunto["rotulo"]
            linhas.append(f"\U0001F525 <b>{escape(assunto_atual.upper())}</b> "
                          f"<i>({assunto['manchetes']} manchetes · "
                          f"{assunto['fontes']} veículos)</i>")
        titulo = escape(it["titulo"][:180])
        if it.get("link"):
            titulo = f'<a href="{escape(it["link"])}">{titulo}</a>'
        linhas.append(f"  • {titulo}")
        linhas.append(f"    <i>{escape(it['fonte'])}</i>")
    return "\n".join(linhas)


# ------------------------------------------------------------------ Ciclo ----

def ciclo(modo, token, chat_id, horas, limite, silencioso, seco):
    carimbo = datetime.now().strftime("%H:%M:%S")
    itens, erros = radar.coleta(modo, horas)
    if not itens:
        print(f"[{carimbo}] nenhuma manchete coletada (conexao?)")
        return

    ranking = radar.ranqueia(itens, top=8, min_fontes=2)
    if not ranking:
        ranking = radar.ranqueia(itens, top=8, min_fontes=1)
    if not ranking:
        print(f"[{carimbo}] nada acima do limiar desta vez")
        return

    historico = carrega_historico(modo)
    escolhidas = seleciona(ranking, historico, limite)
    if not escolhidas:
        print(f"[{carimbo}] nada novo desde o ultimo envio - nao mandei nada")
        return

    texto = monta_mensagem(modo, escolhidas, len(itens), horas)

    if seco:
        print("\n--- ENVIARIA ISTO (modo --seco) ---")
        print(texto)
        print("--- fim ---\n")
        return

    envia(token, chat_id, texto, silencioso)
    salva_historico(modo, historico + [chave_da_manchete(i) for _, i in escolhidas])
    topo = escolhidas[0][0]["rotulo"]
    print(f"[{carimbo}] enviei {len(escolhidas)} manchetes · topo: {topo}"
          + (f" · {len(erros)} feeds falharam" if erros else ""))


def main():
    ap = argparse.ArgumentParser(description="Radar de noticias no Telegram.")
    ap.add_argument("modo", nargs="?", choices=["mundo", "brasil"], default="mundo")
    ap.add_argument("--loop", type=int, metavar="MIN",
                    help="fica rodando e envia a cada MIN minutos")
    ap.add_argument("--uma-vez", action="store_true", help="envia uma vez e sai")
    ap.add_argument("--manchetes", type=int, default=5, help="por envio (padrao 5)")
    ap.add_argument("--horas", type=int, default=6, help="janela de coleta (padrao 6)")
    ap.add_argument("--silencioso", action="store_true", help="sem som de notificacao")
    ap.add_argument("--seco", action="store_true", help="mostra na tela, nao envia")
    ap.add_argument("--teste", action="store_true", help="so testa a conexao do bot")
    ap.add_argument("--token", default=os.environ.get("TELEGRAM_TOKEN"))
    ap.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    ap.add_argument("--zerar", action="store_true",
                    help="apaga o historico e volta a poder repetir manchetes")
    args = ap.parse_args()

    if args.zerar:
        try:
            os.remove(HISTORICO.format(modo=args.modo))
            print("Historico apagado.")
        except FileNotFoundError:
            print("Nao havia historico.")
        return

    if not args.seco and (not args.token or not args.chat_id):
        sys.exit("ERRO: defina TELEGRAM_TOKEN e TELEGRAM_CHAT_ID "
                 "(ou passe --token e --chat-id). Veja o topo do arquivo.")

    if args.teste:
        info = telegram(args.token, "getMe")
        nome = info.get("result", {}).get("username", "?")
        envia(args.token, args.chat_id,
              "\u2705 <b>Radar conectado.</b>\nSe você está lendo isto, está tudo certo.")
        print(f"OK! Bot @{nome} falou com o chat {args.chat_id}.")
        return

    if not args.loop:
        ciclo(args.modo, args.token, args.chat_id, args.horas,
              args.manchetes, args.silencioso, args.seco)
        return

    print(f"Rodando a cada {args.loop} min. Ctrl+C para parar.")
    while True:
        try:
            ciclo(args.modo, args.token, args.chat_id, args.horas,
                  args.manchetes, args.silencioso, args.seco)
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return
        except Exception as e:
            print(f"[erro] {type(e).__name__}: {e} - tento de novo no proximo ciclo")
        # jitter pequeno para nao bater sempre no mesmo segundo
        try:
            time.sleep(args.loop * 60 + random.randint(0, 20))
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return


if __name__ == "__main__":
    main()
