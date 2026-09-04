#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envio unico: um exemplo do formato novo, para aprovacao."""
import os, urllib.parse, urllib.request

TEXTO = (
 "🔴 <b>BREAKING — BRASIL</b>\n\n"
 "<b><a href=\"https://www.cnnbrasil.com.br/politica/\">"
 "Moraes acusa Mendonça de abuso de autoridade e pede investigação a Fachin</a></b>\n"
 "<i>CNN Brasil</i>\n"
 "21 veículos · 4 do seu campo\n\n"
 "• <a href=\"https://www.bbc.com/portuguese\">BBC</a> — Moraes acusa Mendonça de crime e pede inclusão do colega no inquérito das Fake News\n"
 "• <a href=\"https://www.gazetadopovo.com.br/republica/\">Gazeta do Povo</a> — Moraes diz que Mendonça entregou à PF decisão sem assinatura\n"
 "• <a href=\"https://www1.folha.uol.com.br/poder/\">Folha</a> — Crise no STF: Moraes aponta fortes indícios de crimes\n"
 "• <a href=\"https://oantagonista.com.br/\">O Antagonista</a> — Fachin dá 5 dias para as partes se manifestarem"
)

def main():
    d = urllib.parse.urlencode({
        "chat_id": os.environ["CHAT_ID_BREAKING"], "text": TEXTO,
        "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage", data=d)
    with urllib.request.urlopen(req, timeout=30) as r:
        print("enviado" if b'"ok":true' in r.read() else "falhou")

main()
