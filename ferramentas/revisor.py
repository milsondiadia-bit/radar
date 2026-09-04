# -*- coding: utf-8 -*-
"""
REVISOR

Aplica na redacao pronta as regras que NAO precisam de inteligencia -
as trocas mecanicas que hoje estao escritas no prompt e que a IA erra
justamente por serem mecanicas.

Cole a redacao, rode, e o texto corrigido volta para a area de
transferencia, pronto pra colar no Premiere ou no teleprompter.

O que ele NAO faz: estrutura, opiniao, storytelling, bloco historico.
Isso continua sendo trabalho da IA. Aqui e so acabamento.

Uso:
    REVISAR.bat
    ou:  python revisor.py --colar
    ou:  python revisor.py redacao.txt
"""

import os
import re
import sys
import subprocess

# ---------------------------------------------------------------------
# numeros por extenso
# ---------------------------------------------------------------------

UNIDADES = ["zero", "um", "dois", "tres", "quatro", "cinco", "seis",
            "sete", "oito", "nove", "dez", "onze", "doze", "treze",
            "quatorze", "quinze", "dezesseis", "dezessete", "dezoito",
            "dezenove"]
DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta",
           "sessenta", "setenta", "oitenta", "noventa"]
CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos",
            "quinhentos", "seiscentos", "setecentos", "oitocentos",
            "novecentos"]

# acentos que a lista acima nao carrega, para o texto sair correto
ACENTOS = {"tres": "três", "quatorze": "catorze", "seis": "seis"}


def por_extenso(n):
    """Numero inteiro em palavras. Cobre de 0 a 9999, que e o que
    aparece em roteiro: quantidades, anos e ordinais."""
    if n < 0:
        return str(n)
    if n < 20:
        return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return DEZENAS[d] + (" e " + UNIDADES[u] if u else "")
    if n == 100:
        return "cem"
    if n < 1000:
        c, r = divmod(n, 100)
        return CENTENAS[c] + (" e " + por_extenso(r) if r else "")
    if n < 2000:
        r = n - 1000
        return "mil" + (" e " + por_extenso(r) if r else "")
    if n < 10000:
        m, r = divmod(n, 1000)
        base = UNIDADES[m] + " mil"
        if not r:
            return base
        # "dois mil e vinte e seis", mas "dois mil trezentos e dez"
        return base + (" e " if r < 100 or r % 100 == 0 else " ") + por_extenso(r)
    return str(n)


ORD_UNI = ["", "primeiro", "segundo", "terceiro", "quarto", "quinto",
           "sexto", "setimo", "oitavo", "nono"]
ORD_DEZ = ["", "decimo", "vigesimo", "trigesimo", "quadragesimo",
           "quinquagesimo", "sexagesimo", "septuagesimo", "octogesimo",
           "nonagesimo"]
ORD_CEM = ["", "centesimo", "ducentesimo", "trecentesimo",
           "quadringentesimo", "quingentesimo", "sexcentesimo",
           "septingentesimo", "octingentesimo", "noningentesimo"]

ORD_ACENTO = {
    "setimo": "sétimo", "decimo": "décimo", "vigesimo": "vigésimo",
    "trigesimo": "trigésimo", "quadragesimo": "quadragésimo",
    "quinquagesimo": "quinquagésimo", "sexagesimo": "sexagésimo",
    "septuagesimo": "septuagésimo", "octogesimo": "octogésimo",
    "nonagesimo": "nonagésimo", "centesimo": "centésimo",
}


def ordinal_extenso(n, feminino=False):
    if n < 1 or n > 999:
        return None
    partes = []
    c, resto = divmod(n, 100)
    d, u = divmod(resto, 10)
    if c:
        partes.append(ORD_CEM[c])
    if d:
        partes.append(ORD_DEZ[d])
    if u:
        partes.append(ORD_UNI[u])
    txt = " ".join(partes)
    for sem, com in ORD_ACENTO.items():
        txt = txt.replace(sem, com)
    if feminino:
        txt = re.sub(r"o\b", "a", txt)
    return txt


# ---------------------------------------------------------------------
# as regras
# ---------------------------------------------------------------------

def acentua(palavra):
    for sem, com in ACENTOS.items():
        palavra = re.sub(r"\b" + sem + r"\b", com, palavra)
    return palavra


def regra_horarios(t, rel):
    """04h09 -> quatro horas e nove minutos"""
    def troca(m):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        hora = acentua(por_extenso(h))
        if mi:
            return f"{hora} horas e {acentua(por_extenso(mi))} minutos"
        return f"{hora} horas"
    novo, n = re.subn(r"\b(\d{1,2})\s*[hH:]\s*(\d{2})\b", troca, t)
    rel("horario por extenso", n)
    novo, n2 = re.subn(r"\b(\d{1,2})\s*[hH]\b(?!\w)",
                       lambda m: acentua(por_extenso(int(m.group(1)))) + " horas",
                       novo)
    rel("horario por extenso", n2)
    return novo


def regra_virgula_numero(t, rel):
    """45,9% -> 45 virgula 9% ; 32,9 milhoes -> 32 virgula 9 milhoes"""
    novo, n = re.subn(r"(\d)\s*,\s*(\d)", r"\1 vírgula \2", t)
    rel("vírgula dentro de número", n)
    return novo


def regra_ordinais(t, rel):
    """1o, 2a, 82a -> por extenso"""
    def troca(m):
        n = int(m.group(1))
        fem = m.group(2) in ("ª", "a")
        e = ordinal_extenso(n, fem)
        return e if e else m.group(0)
    novo, n = re.subn(r"\b(\d{1,3})\s*([ºª°])", troca, t)
    rel("ordinal por extenso", n)
    return novo


# 16, 17 e 19 sempre por extenso - pedido expresso, a IA nunca acerta
NUMEROS_SEMPRE = {16: "dezesseis", 17: "dezessete", 19: "dezenove"}


def regra_numeros_criticos(t, rel):
    # anos: 2016 -> dois mil e dezesseis
    def troca_ano(m):
        ano = int(m.group(0))
        if ano % 100 in NUMEROS_SEMPRE:
            return acentua(por_extenso(ano))
        return m.group(0)
    novo, n = re.subn(r"\b(19|20)\d{2}\b", troca_ano, t)
    rel("ano com 16/17/19 por extenso", n)

    # numeros soltos
    def troca_num(m):
        return NUMEROS_SEMPRE[int(m.group(0))]
    novo, n2 = re.subn(r"\b(16|17|19)\b", troca_num, novo)
    rel("número 16/17/19 por extenso", n2)
    return novo


# troca simples: (o que achar, pelo que trocar, se e palavra inteira)
TROCAS = [
    (r"\bEUA\b", "Estados Unidos", "EUA"),
    (r"\bUE\b", "União Europeia", "UE"),
    (r"\bPoder\s*360\b", "Poder trezentos e sessenta", "Poder360"),
    (r"\bBrasil\s*247\b", "Brasil dois quatro sete", "Brasil247"),
    (r"\bG1\b", "G 1", "G1"),
    (r"\bFolha de S\.?\s?Paulo\b", "Folha de São Paulo", "Folha de S.Paulo"),
    (r"\bKwait\b", "Kuaite", "Kwait"),
    (r"\bKuwait\b", "Kuaite", "Kuwait"),
    (r"\bPeter\b", "Piter", "Peter"),
    (r"\bPete\b", "Pite", "Pete"),
    (r"\bEaí\b", "É aí", "Eaí"),
    (r"\bEai\b", "É aí", "Eai"),
    (r"\bestá\b", "tá", "está"),
    (r"\bEstá\b", "Tá", "Está"),
    (r"\bpara\s+os\b", "pros", "para os"),
    (r"\bpara\s+as\b", "pras", "para as"),
    (r"\bpara\s+o\b", "pro", "para o"),
    (r"\bpara\s+a\b", "pra", "para a"),
    (r"\bPara\s+o\b", "Pro", "Para o"),
    (r"\bPara\s+a\b", "Pra", "Para a"),
    (r"\bpara\b", "pra", "para"),
    (r"\bPara\b", "Pra", "Para"),
    (r"\bpor\s+quê\b", "porque", "por quê"),
    (r"\bpor\s+que\b", "porque", "por que"),
    (r"\bPor\s+que\b", "Porque", "Por que"),
]



# moeda: o simbolo vem ANTES do valor, a palavra vem DEPOIS.
# "R$ 32,9 milhoes" tem de virar "32 virgula 9 milhoes de Reais",
# nunca "Reais 32 virgula 9 milhoes".
MOEDAS = [(r"R\$", "Reais"), (r"US\$", "Dólares"),
          (r"USD", "Dólares"), (r"€", "Euros")]
# as alternativas vao da MAIS LONGA para a mais curta: com "mil"
# na frente, "milhoes" casava so o "mil" e sobrava "hoes"
ESCALAS = (r"(?:\s+(?:trilhões|trilhão|bilhões|bilhão|milhões|milhão|mil))?")


def regra_moeda(t, rel):
    for simbolo, nome in MOEDAS:
        padrao = simbolo + r"\s*(\d+(?:[.,]\d+)*" + ESCALAS + r")"
        def troca(m, nome=nome):
            valor = m.group(1).strip()
            if re.search(r"(mil|milh|bilh|trilh)", valor):
                return f"{valor} de {nome}"
            return f"{valor} {nome}"
        t, n = re.subn(padrao, troca, t)
        rel(f"moeda {nome}", n)
    return t


# "pais" e masculino, "nacao" e feminino: trocar a palavra sem trocar o
# artigo produz "o nacao". Entao o determinante entra na troca.
_DET_BASE = {
    "o": "a", "os": "as", "do": "da", "dos": "das",
    "no": "na", "nos": "nas", "ao": "à", "aos": "às",
    "pelo": "pela", "pelos": "pelas",
    "esse": "essa", "esses": "essas", "este": "esta", "estes": "estas",
    "aquele": "aquela", "aqueles": "aquelas",
    "um": "uma", "uns": "umas", "outro": "outra", "outros": "outras",
    "meu": "minha", "seu": "sua", "nosso": "nossa",
    "todo": "toda", "todos": "todas",
    "muitos": "muitas", "varios": "várias", "vários": "várias",
    "poucos": "poucas", "quantos": "quantas", "certos": "certas",
    "alguns": "algumas", "nenhum": "nenhuma", "cada": "cada",
}
# a versao com inicial maiuscula sai de graca - sem isso "Varios paises"
# virava "Varios nacoes", que foi o erro do primeiro teste
DETERMINANTES = dict(_DET_BASE)
for _k, _v in _DET_BASE.items():
    DETERMINANTES[_k.capitalize()] = _v.capitalize()


def regra_pais(t, rel):
    palavras = "|".join(sorted(DETERMINANTES, key=len, reverse=True))

    def com_determinante(m):
        det, palavra = m.group(1), m.group(2)
        nova = "nações" if palavra.lower().startswith("países") else "nação"
        return DETERMINANTES[det] + " " + nova

    novo, n = re.subn(r"\b(" + palavras + r")\s+(países|país)\b",
                      com_determinante, t)
    rel("país/países → nação/nações", n)

    # sem determinante na frente: troca so a palavra
    novo, n2 = re.subn(r"\bpaíses\b", "nações", novo)
    novo, n3 = re.subn(r"\bpaís\b", "nação", novo)
    rel("país/países → nação/nações", n2 + n3)
    return novo


def regra_trocas(t, rel):
    for padrao, novo_txt, nome in TROCAS:
        t, n = re.subn(padrao, novo_txt, t)
        rel(f"'{nome}' → '{novo_txt.strip()}'", n)
    return t


def regra_hifen_barra(t, rel):
    """pro-Uniao -> pro Uniao ; F/A -> F A. So em palavra composta,
    nunca em link nem em data."""
    def seguro(m):
        return m.group(1) + " " + m.group(2)
    novo, n = re.subn(r"(?<!/)\b([A-Za-zÀ-ú]{2,})[-‐]([A-Za-zÀ-ú]{2,})\b",
                      seguro, t)
    rel("hífen de palavra composta", n)
    novo, n2 = re.subn(r"\b([A-Z])/([A-Z])\b", r"\1 \2", novo)
    rel("barra em sigla", n2)
    return novo


def regra_travessao(t, rel):
    """Travessao e vicio de IA. Vira virgula ou some."""
    novo, n = re.subn(r"\s*[—–]\s*", ", ", t)
    rel("travessão", n)
    novo = re.sub(r",\s*,", ",", novo)
    novo = re.sub(r",\s*\.", ".", novo)
    return novo


# frases que denunciam texto de IA. Nao trocamos sozinhos porque
# dependem do contexto - so avisamos para voce decidir.
SUSPEITAS = [
    r"não é sobre .{1,40}, é sobre",
    r"\bNa minha avaliação\b",
    r"\bo ponto principal é direto\b",
    r"\bA mensagem foi direta\b",
    r"\bvale (?:notar|destacar|ressaltar)\b",
    r"\bem última análise\b",
    r"\bno fim(?: das contas)?, o fato\b",
    r"\bmais do que nunca\b",
    r"\bcabe lembrar\b",
]


def revisar(texto):
    contagem = {}

    def rel(nome, n):
        if n:
            contagem[nome] = contagem.get(nome, 0) + n

    t = texto
    # a ordem importa: horario antes de numeros, senao 19h vira dezenove h
    t = regra_horarios(t, rel)
    # moeda ANTES da virgula: depois de "32,9" virar "32 virgula 9"
    # a regra da moeda nao reconhece mais o valor como numero
    t = regra_moeda(t, rel)
    t = regra_virgula_numero(t, rel)
    t = regra_ordinais(t, rel)
    t = regra_numeros_criticos(t, rel)
    t = regra_pais(t, rel)
    t = regra_trocas(t, rel)
    t = regra_hifen_barra(t, rel)
    t = regra_travessao(t, rel)
    t = re.sub(r"[ \t]{2,}", " ", t)

    # a busca roda num texto de uma linha so: sem isso, um vicio que
    # cai bem na quebra de paragrafo ("Na minha\navaliacao") escapa
    achadas = []
    plano = re.sub(r"\s+", " ", t)
    for p in SUSPEITAS:
        for m in re.finditer(p, plano, re.I):
            ini = max(0, m.start() - 40)
            achadas.append(plano[ini:m.end() + 40])

    return t, contagem, achadas


# ---------------------------------------------------------------------

def copiar_para_area(texto):
    try:
        p = subprocess.Popen("clip", stdin=subprocess.PIPE, shell=True)
        p.communicate(texto.encode("utf-16-le"))
        return p.returncode == 0
    except Exception:
        return False


def ler_colado():
    print("Cole a redacao e aperte Enter duas vezes:\n")
    linhas, vazias = [], 0
    while True:
        try:
            linha = input()
        except EOFError:
            break
        if linha.strip() == "":
            vazias += 1
            if vazias >= 2:
                break
        else:
            vazias = 0
        linhas.append(linha)
    return "\n".join(linhas).strip()


def main():
    if "--colar" in sys.argv:
        texto = ler_colado()
    elif len(sys.argv) > 1 and os.path.exists(sys.argv[-1]):
        texto = open(sys.argv[-1], encoding="utf-8").read()
    else:
        texto = ler_colado()

    if not texto.strip():
        print("Nao veio texto nenhum.")
        return

    novo, contagem, suspeitas = revisar(texto)

    print("\n" + "=" * 52)
    print("   O QUE FOI CORRIGIDO")
    print("=" * 52)
    if contagem:
        for nome, n in sorted(contagem.items(), key=lambda x: -x[1]):
            print(f"  {n:3d}x  {nome}")
    else:
        print("  nada - o texto ja estava no padrao")

    if suspeitas:
        print("\n" + "=" * 52)
        print("   OLHE ISTO (cheiro de texto de IA)")
        print("=" * 52)
        for s in suspeitas[:12]:
            print(f"  ...{s.strip()}...")
        print("\n  Nao mexi nessas: dependem do contexto.")

    with open("redacao_revisada.txt", "w", encoding="utf-8") as f:
        f.write(novo)

    print("\n" + "=" * 52)
    print(f"  {len(novo)} caracteres.")
    if copiar_para_area(novo):
        print("  PRONTO. Ja esta na area de transferencia.")
    else:
        print("  Salvo em redacao_revisada.txt")
    print("=" * 52)


if __name__ == "__main__":
    main()
