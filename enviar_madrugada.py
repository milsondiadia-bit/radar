#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Envio unico dos quatro momentos da madrugada de 04/09 ao canal
Brasil - Breaking. Eles foram detectados enquanto o bot ainda estava em
modo medicao, entao nunca chegaram ao Telegram.

Este arquivo e descartavel: roda uma vez e sai do repositorio.
"""

import os
import time
import urllib.parse
import urllib.request

EVENTOS = [
    {
        "hora": "00h02",
        "titulo": "Moraes encaminha a Fachin pedido de investigação contra Mendonça",
        "veiculos": 13,
        "campo": 4,
        "espalho": 52,
        "ineditas": "andrei, apuração, crimes, fake news, fortes, indícios, inquérito, investigação",
        "manchetes": [
            ("CNN Brasil", "Moraes usa inquérito das fake news para acusar Mendonça de crimes"),
            ("G1", "Moraes encaminha a Fachin pedido de investigação contra Mendonça"),
            ("G1", "Fachin dá 5 dias para que Mendonça, Moraes, PGR e Polícia Federal prestem informações sobre crise no STF"),
        ],
        "fontes": "CNN Brasil, Carta Capital, Claudio Dantas, Congresso em Foco, Folha Poder, G1, Gazeta do Povo, Metrópoles, O Antagonista",
    },
    {
        "hora": "00h42",
        "titulo": "Moraes aponta “fortes indícios” de crimes",
        "veiculos": 15,
        "campo": 2,
        "espalho": 77,
        "ineditas": "apuração, cobra, doer, gonet, informações, prestarem",
        "manchetes": [
            ("CNN Brasil", "Moraes acusa Mendonça de perseguir Alcolumbre e outros ministros do STF"),
            ("Brasil de Fato", "Moraes acusa Mendonça de abuso de autoridade e pede investigação a Fachin"),
            ("Folha de S.Paulo", "Fachin manda Mendonça, Moraes, Gonet e chefe da PF prestarem informações sobre diálogos com Vorcaro"),
        ],
        "fontes": "Agência Brasil, BBC Brasil, Brasil de Fato, CNN Brasil, Carta Capital, Congresso em Foco, Folha, Gazeta do Povo, Metrópoles",
    },
    {
        "hora": "01h12",
        "titulo": "Moraes acusa Mendonça de abuso de autoridade",
        "veiculos": 21,
        "campo": 4,
        "espalho": 88,
        "ineditas": "afastamento, alvo, colega, determinou, investigados, marinho, perseguir, revela",
        "manchetes": [
            ("CNN Brasil", "Moraes acusa Mendonça de perseguir Alcolumbre e outros ministros do STF"),
            ("CNN Brasil", "Moraes diz que Mendonça entregou à PF decisão sem assinatura"),
            ("BBC", "Moraes acusa Mendonça de crime e pede inclusão do colega no inquérito das Fake News; entenda"),
        ],
        "fontes": "Agência Brasil, BBC, CNN Brasil, Carta Capital, Claudio Dantas, Congresso em Foco, Folha Poder, G1, GZH, Gazeta do Povo",
    },
    {
        "hora": "02h12",
        "titulo": "Fachin cobra informações de Mendonça, Moraes e PGR",
        "veiculos": 13,
        "campo": 4,
        "espalho": 83,
        "ineditas": "afastamento, atuação, crítica, guerra, messias, ofensiva",
        "manchetes": [
            ("CNN Brasil", "Inteligência da PF vê Mendonça ciente de que investigação atingiria Moraes"),
            ("CNN Brasil", "Análise: o que representam para o STF as denúncias de Moraes a Mendonça?"),
            ("BBC", "Moraes acusa Mendonça de crime e pede inclusão do colega no inquérito das Fake News; entenda"),
        ],
        "fontes": "BBC Brasil, Claudio Dantas, Folha Poder, G1, Gazeta do Povo, Metrópoles, O Antagonista, Poder360, Valor Econômico",
    },
]


def escapa(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def monta(ev):
    linhas = [
        "🔴 <b>BREAKING — BRASIL</b>",
        f"<i>detectado às {ev['hora']} de hoje, durante a fase de testes</i>",
        "",
        f"<b>{escapa(ev['titulo'])}</b>",
        "",
        f"📊 {ev['veiculos']} veículos em {ev['espalho']} min",
        f"✅ {ev['campo']} do seu campo",
        f"🆕 {escapa(ev['ineditas'])}",
        "",
    ]
    for fonte, manchete in ev["manchetes"]:
        linhas.append(f"• <b>{escapa(fonte)}</b>: {escapa(manchete)}")
    linhas.append("")
    linhas.append(f"<i>{escapa(ev['fontes'])}</i>")
    return "\n".join(linhas)


def envia(texto):
    token = os.environ["TELEGRAM_TOKEN"]
    chat = os.environ["CHAT_ID_BREAKING"]
    dados = urllib.parse.urlencode({
        "chat_id": chat, "text": texto, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=dados)
    with urllib.request.urlopen(req, timeout=30) as r:
        return b'"ok":true' in r.read()


def main():
    for ev in EVENTOS:
        ok = envia(monta(ev))
        print(f"  {ev['hora']}  {'enviado' if ok else 'FALHOU'}")
        time.sleep(2)


if __name__ == "__main__":
    main()
