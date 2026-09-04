# -*- coding: utf-8 -*-
"""
Teste do juiz de fato novo.

Roda os casos REAIS medidos no log de 03/09 e 04/09/2026 e grava o
resultado em teste_juiz.txt, para conferir se o Gemini separa fato novo
de repercussao antes de o juiz entrar no ar.

Nao envia nada ao Telegram. Nao altera nenhum arquivo do bot.
"""

import os
import re
import json
import time
import importlib.util

spec = importlib.util.spec_from_file_location("bb", "brasil_breaking.py")

# le so o bloco do juiz, sem executar o resto do arquivo
src = open("brasil_breaking.py", encoding="utf-8").read()
bloco = src[src.index("MODELOS_IA ="):src.index("def main():")]
ns = {"json": json, "re": re, "os": os}
exec(bloco, ns)
traz_fato_novo = ns["traz_fato_novo"]

CHAVE = os.environ.get("GEMINI_API_KEY", "").strip()

# o que o canal ja tinha avisado na noite de 03 e na manha de 04
JA_AVISADO = [
    "Moraes encaminha a Fachin pedido de investigacao contra Mendonca",
    "Moraes acusa Mendonca de abuso de autoridade e pede investigacao a Fachin",
]

# (manchete candidata, resposta esperada, de onde veio)
CASOS = [
    ("Moraes acusa Mendonca de agir para favorecer 'grupos politicos', "
     "pede providencias de Fachin e agrava crise no STF",
     False, "alerta de 10h43 - o que incomodou"),

    ("Moraes x Mendonca: analistas apontam crise sem precedentes e "
     "enraizada no STF",
     False, "repercussao da BBC, mesmo grupo"),

    ("Crise sem precedentes expoe as entranhas do Supremo Tribunal Federal",
     False, "analise da GZH, mesmo grupo"),

    ("Mendonca quis saber o que tinha sobre Moraes no celular de Vorcaro, "
     "diz PF",
     True, "FATO NOVO real, 11h02 - o que chegou tarde"),

    ("Fachin da 5 dias para Moraes, Mendonca, PGR e Policia Federal "
     "prestarem informacoes sobre crise no STF",
     True, "FATO NOVO - Fachin agiu"),

    ("Relatorio da PF usado por Moraes contra Mendonca nao tem valor "
     "probatorio",
     True, "FATO NOVO - achado sobre o documento"),

    ("Dino reconhece crise no STF e defende 'seguir julgando'",
     False, "declaracao de terceiro sobre o mesmo caso"),

    ("Imprensa internacional ve crise no STF apos revelacoes envolvendo "
     "Moraes e Vorcaro",
     False, "repercussao pura"),

    ("PF indicia Alexandre de Moraes por obstrucao de justica",
     True, "FATO NOVO inventado, para ver se ele deixa passar o forte"),
]


def main():
    linhas = []
    linhas.append("TESTE DO JUIZ DE FATO NOVO")
    linhas.append("chave presente: %s" % ("sim" if CHAVE else "NAO"))
    linhas.append("")
    linhas.append("Ja avisado:")
    for t in JA_AVISADO:
        linhas.append("  - " + t)
    linhas.append("")

    acertos = 0
    for i, (titulo, esperado, origem) in enumerate(CASOS):
        if i:
            time.sleep(6)   # nao estourar o limite de taxa do Gemini
        obtido, motivo = traz_fato_novo(titulo, JA_AVISADO, CHAVE)
        ok = (obtido == esperado)
        acertos += ok
        linhas.append("%s  esperado=%-5s obtido=%-5s | %s"
                      % ("OK  " if ok else "ERRO", esperado, obtido, origem))
        linhas.append("      %s" % titulo[:78])
        linhas.append("      motivo da IA: %s" % motivo)
        linhas.append("")

    linhas.append("ACERTOS: %d de %d" % (acertos, len(CASOS)))
    texto = "\n".join(linhas)
    print(texto)
    with open("teste_juiz.txt", "w", encoding="utf-8") as f:
        f.write(texto + "\n")


if __name__ == "__main__":
    main()
