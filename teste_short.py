# -*- coding: utf-8 -*-
"""
Testa o detector de Short com videos REAIS do ANCAPSU e confere se a
memoria esta sendo guardada.

Grava o resultado em teste_short.txt. Nao envia nada ao Telegram.
"""

import re
import os
import json
import urllib.request
from xml.etree import ElementTree as ET

src = open("brasil_breaking.py", encoding="utf-8").read()
bloco = src[src.index("def eh_short("):src.index("def checa_ancapsu(")]
ns = {}
exec(bloco, ns)
eh_short = ns["eh_short"]

FEED = ("https://www.youtube.com/feeds/videos.xml"
        "?channel_id=UCLTWPE7XrHEe8m_xAmNbQ-Q")


def main():
    linhas = ["TESTE DO DETECTOR DE SHORT", ""]

    # 1) o video que gerou o alerta indevido
    linhas.append("Video que gerou o alerta indevido (deveria ser Short):")
    r = eh_short("5o3gwvSxSWs")
    linhas.append("  5o3gwvSxSWs -> eh_short = %s  %s"
                  % (r, "OK" if r else "ERRO - nao detectou"))
    linhas.append("")

    # 2) os 15 videos atuais do feed, para ver a proporcao
    linhas.append("Feed atual do canal:")
    try:
        req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as f:
            raiz = ET.fromstring(f.read())
        ns_ = {"a": "http://www.w3.org/2005/Atom",
               "yt": "http://www.youtube.com/xml/schemas/2015"}
        for e in raiz.findall("a:entry", ns_)[:12]:
            vid = e.findtext("yt:videoId", default="", namespaces=ns_)
            tit = e.findtext("a:title", default="", namespaces=ns_)
            linhas.append("  %-13s %-6s %s"
                          % (vid, "SHORT" if eh_short(vid) else "video",
                             tit[:58]))
    except Exception as ex:
        linhas.append("  falhou: %s" % ex)

    linhas.append("")
    linhas.append("Memoria do ANCAPSU no repositorio:")
    if os.path.exists("ancapsu_vistos.json"):
        d = json.load(open("ancapsu_vistos.json"))
        linhas.append("  existe, %d video(s) anotado(s)" % len(d))
    else:
        linhas.append("  NAO EXISTE - era por isso que o aviso repetia")

    texto = "\n".join(linhas)
    print(texto)
    open("teste_short.txt", "w", encoding="utf-8").write(texto + "\n")


if __name__ == "__main__":
    main()
