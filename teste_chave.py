# -*- coding: utf-8 -*-
"""
Diagnostico da chave do Gemini.

Faz UMA chamada por modelo e mostra o erro EXATO que o Google devolve,
para separar limite por minuto de cota diaria esgotada, de chave
invalida, de modelo inexistente.

Grava em teste_chave.txt. Nao envia nada ao Telegram.
"""

import os
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

CHAVE = os.environ.get("GEMINI_API_KEY", "").strip()
ROTULO = os.environ.get("ROTULO", "?")

MODELOS = ["gemini-flash-lite-latest", "gemini-3-flash-preview",
           "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]


def testar(modelo, versao="v1beta"):
    url = (f"https://generativelanguage.googleapis.com/{versao}"
           f"/models/{modelo}:generateContent")
    corpo = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": "Responda: ok"}]}],
        "generationConfig": {"maxOutputTokens": 20},
    }).encode()
    cab = {"Content-Type": "application/json", "x-goog-api-key": CHAVE}
    try:
        req = Request(url, data=corpo, headers=cab)
        with urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        txt = d["candidates"][0]["content"]["parts"][0]["text"].strip()
        return "OK  -> %r" % txt[:40]
    except HTTPError as e:
        detalhe = ""
        try:
            corpo_erro = json.loads(e.read())
            err = corpo_erro.get("error", {})
            detalhe = "%s | %s" % (err.get("status", ""),
                                   err.get("message", "")[:220])
        except Exception:
            pass
        return "HTTP %s | %s" % (e.code, detalhe)
    except Exception as e:
        return "falhou: %s" % e


def main():
    if ROTULO == "ATUAL":
        open("teste_chave.txt", "w").close()
    linhas = ["", "=" * 60, "CHAVE %s" % ROTULO, "=" * 60]
    linhas.append("chave presente: %s" % ("sim" if CHAVE else "NAO"))
    if CHAVE:
        linhas.append("tamanho da chave: %d caracteres" % len(CHAVE))
        linhas.append("comeca com: %s..." % CHAVE[:6])
    linhas.append("")

    for m in MODELOS:
        linhas.append("%-28s %s" % (m, testar(m)))

    texto = "\n".join(linhas)
    print(texto)
    open("teste_chave.txt", "a", encoding="utf-8").write(texto + "\n")


if __name__ == "__main__":
    main()
