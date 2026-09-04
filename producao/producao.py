# -*- coding: utf-8 -*-
"""
PRODUCAO

Voce da o link do video, o seu titulo e a frase da thumb.
O robo faz o resto e manda tudo no Telegram.

    link  ->  prints.py    (prints das publicacoes + @perfis)
          ->  extrair.py   (transcricao do video)
          ->  Gemini       (3 titulos, 5 frases, redacao)
          ->  revisor.py   (acabamento mecanico)
          ->  Telegram     (titulos, frases, links e a redacao)

Os prompts NAO estao dentro deste arquivo: ficam na pasta prompts,
em .txt. Assim voce ajusta o texto do prompt sem mexer em codigo.

Uso:
    PRODUZIR.bat
"""

import io
import os
import re
import sys
import glob
import json
import time
import shutil
import subprocess
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_PROMPTS = os.path.join(AQUI, "prompts")
PASTA_PRINTS = os.path.join(AQUI, "prints")
PASTA_ENTREGA = os.path.join(AQUI, "Pronto")

MODELOS = ["gemini-flash-latest", "gemini-3.6-flash",
           "gemini-flash-lite-latest", "gemini-3-flash-preview"]

# quanto tempo esperar o Gemini antes de desistir de um pedido
TETO_SEGUNDOS = 180


# ---------------------------------------------------------------------
# configuracao
# ---------------------------------------------------------------------

def ler_config():
    caminho = os.path.join(AQUI, "config.txt")
    if not os.path.exists(caminho):
        print("Nao achei o config.txt na pasta.")
        sys.exit(1)
    cfg = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            cfg[chave.strip()] = valor.strip()

    faltando = [c for c in ("GEMINI_API_KEY", "TELEGRAM_TOKEN", "CHAT_ID")
                if not cfg.get(c)]
    if faltando:
        print("\nFalta preencher no config.txt: " + ", ".join(faltando))
        sys.exit(1)
    return cfg


def ler_prompt(nome):
    caminho = os.path.join(PASTA_PROMPTS, nome + ".txt")
    if not os.path.exists(caminho):
        print(f"Nao achei o prompt: {caminho}")
        sys.exit(1)
    return open(caminho, encoding="utf-8").read()


# ---------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------

def pergunta_ia(prompt, chave, etapa=""):
    """Uma pergunta ao Gemini, com cascata de modelos.

    O 429 do Gemini e limite POR MINUTO e passa sozinho - medido em
    04/09/2026. Entao nao desiste no primeiro: troca de modelo, que
    costuma estar livre, e so depois espera.
    """
    from urllib.request import Request, urlopen

    corpo = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 20000},
    }).encode()
    cab = {"Content-Type": "application/json", "x-goog-api-key": chave}

    comeco = time.time()
    ultimo_erro = ""
    for rodada, espera in enumerate((0, 8, 20, 40)):
        if espera:
            if time.time() - comeco > TETO_SEGUNDOS:
                break
            print(f"    limite do Gemini. Esperando {espera}s...")
            time.sleep(espera)
        for modelo in MODELOS:
            url = ("https://generativelanguage.googleapis.com/v1beta"
                   f"/models/{modelo}:generateContent")
            try:
                with urlopen(Request(url, data=corpo, headers=cab),
                             timeout=120) as r:
                    d = json.loads(r.read())
                return d["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                ultimo_erro = str(e)[:90]
                continue
    print(f"    o Gemini nao respondeu ({etapa}): {ultimo_erro}")
    return None


# ---------------------------------------------------------------------
# etapas
# ---------------------------------------------------------------------

ARQUIVO_HISTORICO = os.path.join(AQUI, "fatos_historicos_usados.txt")


def ler_historico():
    """Os fatos historicos ja usados em videos anteriores.

    Antes essa lista ficava dentro do prompt e voce atualizava na mao -
    e bastava esquecer uma vez para o Kuwait aparecer duas semanas
    seguidas. Agora o robo le daqui e grava sozinho no fim.
    """
    if not os.path.exists(ARQUIVO_HISTORICO):
        return []
    fatos = []
    for linha in open(ARQUIVO_HISTORICO, encoding="utf-8"):
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            fatos.append(linha)
    return fatos


def guardar_historico(redacao):
    """Pesca o fato historico na ultima linha da redacao e anota."""
    m = re.search(r"FATO HISTORICO USADO:\s*(.+)", redacao, re.I)
    if not m:
        return None, redacao
    fato = m.group(1).strip()
    # tira a linha do texto que vai para o Premiere
    limpo = re.sub(r"\n*FATO HISTORICO USADO:.*", "", redacao,
                   flags=re.I | re.S).rstrip()
    ja = ler_historico()
    if fato and not any(fato.lower()[:25] in f.lower() for f in ja):
        with open(ARQUIVO_HISTORICO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%d/%m/%Y')} - {fato}\n")
    return fato, limpo


def rodar(comando, descricao):
    print(f"\n>>> {descricao}")
    try:
        r = subprocess.run(comando, cwd=AQUI)
        return r.returncode == 0
    except Exception as e:
        print(f"    falhou: {e}")
        return False


def limpar_prints():
    if os.path.isdir(PASTA_PRINTS):
        shutil.rmtree(PASTA_PRINTS, ignore_errors=True)


def ler_perfis():
    """Le o _enderecos.txt e devolve os links dos perfis."""
    caminho = os.path.join(PASTA_PRINTS, "_enderecos.txt")
    if not os.path.exists(caminho):
        return []
    vistos, saida = set(), []
    for linha in open(caminho, encoding="utf-8"):
        partes = linha.strip().split("\t")
        if len(partes) < 2:
            continue
        perfil = partes[1].lstrip("@").strip()
        if perfil and perfil not in vistos:
            vistos.add(perfil)
            saida.append(perfil)
    return saida


def ler_transcricao():
    """Pega o texto que o extrair.py deixou pronto."""
    for nome in ("saida.txt", "transcricao.txt"):
        caminho = os.path.join(AQUI, nome)
        if os.path.exists(caminho):
            return open(caminho, encoding="utf-8", errors="replace").read()
    return ""


def aplicar_revisor(texto):
    """Passa a redacao pelo revisor, se ele estiver na pasta."""
    try:
        sys.path.insert(0, AQUI)
        import revisor
        novo, contagem, suspeitas = revisor.revisar(texto)
        total = sum(contagem.values())
        print(f"    revisor: {total} correcao(oes) mecanica(s)")
        for nome, n in sorted(contagem.items(), key=lambda x: -x[1])[:8]:
            print(f"      {n:3d}x {nome}")
        if suspeitas:
            print(f"    {len(suspeitas)} trecho(s) com cheiro de IA "
                  f"(vao no aviso do Telegram)")
        return novo, suspeitas
    except Exception as e:
        print(f"    revisor nao rodou: {e}")
        return texto, []


# ---------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------

def telegram_texto(cfg, texto):
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    url = f"https://api.telegram.org/bot{cfg['TELEGRAM_TOKEN']}/sendMessage"
    dados = urlencode({"chat_id": cfg["CHAT_ID"], "text": texto,
                       "parse_mode": "HTML",
                       "disable_web_page_preview": "true"}).encode()
    try:
        with urlopen(Request(url, data=dados), timeout=60) as r:
            return b'"ok":true' in r.read()
    except Exception as e:
        print(f"    Telegram falhou: {e}")
        return False


def telegram_arquivo(cfg, caminho, legenda=""):
    """Envia documento. Monta o multipart na mao para nao depender
    de biblioteca externa."""
    from urllib.request import Request, urlopen
    limite = "----------robo" + str(int(time.time()))
    nome = os.path.basename(caminho)
    with open(caminho, "rb") as f:
        conteudo = f.read()

    partes = []
    for campo, valor in (("chat_id", cfg["CHAT_ID"]), ("caption", legenda)):
        partes.append(("--" + limite + "\r\n"
                       f'Content-Disposition: form-data; name="{campo}"'
                       "\r\n\r\n" + valor + "\r\n").encode())
    partes.append(("--" + limite + "\r\n"
                   f'Content-Disposition: form-data; name="document"; '
                   f'filename="{nome}"\r\n'
                   "Content-Type: application/octet-stream\r\n\r\n").encode())
    corpo = b"".join(partes) + conteudo + \
        ("\r\n--" + limite + "--\r\n").encode()

    url = f"https://api.telegram.org/bot{cfg['TELEGRAM_TOKEN']}/sendDocument"
    req = Request(url, data=corpo, headers={
        "Content-Type": "multipart/form-data; boundary=" + limite})
    try:
        with urlopen(req, timeout=120) as r:
            return b'"ok":true' in r.read()
    except Exception as e:
        print(f"    envio do arquivo falhou: {e}")
        return False


def escapa(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------------

def main():
    print("=" * 54)
    print("   PRODUCAO  -  do link ao roteiro pronto")
    print("=" * 54)

    cfg = ler_config()

    link = " ".join(sys.argv[1:]).strip()
    if not link:
        link = input("\nCole o link do video de referencia: ").strip()
    if not link:
        print("Sem link, sem producao.")
        return

    print("\nAgora o SEU titulo (a tese central do video):")
    titulo = input("> ").strip()
    if not titulo:
        print("O titulo e obrigatorio: e ele que conduz a redacao.")
        return

    print("\nA frase da thumb (pode deixar em branco):")
    frase_thumb = input("> ").strip()

    comeco = time.time()

    # ---------- 1. prints ----------
    limpar_prints()
    rodar([sys.executable, "prints.py", "--layout", cfg.get("LAYOUT", "navegador"),
           link], "Capturando os prints das publicacoes")
    perfis = ler_perfis()
    imagens = sorted(glob.glob(os.path.join(PASTA_PRINTS, "[0-9]*.png")))
    print(f"    {len(imagens)} print(s), {len(perfis)} perfil(is)")

    # ---------- 2. transcricao ----------
    antes = ler_transcricao()
    subprocess.run("clip", input=link.encode("utf-16-le"), shell=True)
    rodar([sys.executable, "extrair.py", "--colar"],
          "Extraindo a transcricao do video")
    transcricao = ler_transcricao()
    if transcricao == antes or not transcricao.strip():
        print("    ATENCAO: nao consegui a transcricao. "
              "A redacao vai sair so com o titulo.")
        transcricao = ""

    base = (f"TITULO / TESE CENTRAL:\n{titulo}\n\n"
            f"FRASE DA THUMB:\n{frase_thumb or '(nao informada)'}\n\n"
            f"DATA DE HOJE: {datetime.now().strftime('%d/%m/%Y')}\n\n"
            f"PERFIS DAS PUBLICACOES NOS PRINTS:\n"
            + "\n".join("@" + p for p in perfis) + "\n\n"
            f"TRANSCRICAO E MATERIAL DO VIDEO DE REFERENCIA:\n{transcricao}")

    chave = cfg["GEMINI_API_KEY"]

    # Titulo e frase de capa NAO passam pela IA: quem define os dois e
    # voce, e e o seu titulo que carrega a tese central da redacao.
    # Tirar essas duas chamadas deixa a producao mais rapida e reduz o
    # risco de bater no limite por minuto do Gemini.

    # ---------- 3. redacao ----------
    print("\n>>> Escrevendo a redacao (esta e a parte demorada)")
    ja_usados = ler_historico()
    prompt_redacao = ler_prompt("redacao").replace(
        "{JA_USADOS}",
        "\n".join(ja_usados) if ja_usados else "(nenhum ainda)")
    if ja_usados:
        print(f"    {len(ja_usados)} fato(s) historico(s) ja usados, "
              f"nao vao repetir")
    redacao = pergunta_ia(prompt_redacao + "\n\n" + base, chave, "redacao")
    if not redacao:
        telegram_texto(cfg, "⚠️ <b>A redacao falhou</b>\n\nO Gemini nao "
                            "respondeu. Titulo: " + escapa(titulo))
        print("\nA redacao falhou. Nada foi entregue.")
        return

    fato_historico, redacao = guardar_historico(redacao)
    if fato_historico:
        print(f"    fato historico desta redacao: {fato_historico[:60]}")
    redacao, suspeitas = aplicar_revisor(redacao)

    # ---------- 4. entrega ----------
    os.makedirs(PASTA_ENTREGA, exist_ok=True)
    apelido = re.sub(r"[^\w ]", "", titulo)[:60].strip().replace(" ", "_")
    arquivo = os.path.join(
        PASTA_ENTREGA,
        f"{datetime.now().strftime('%d-%m')}_{apelido or 'roteiro'}.txt")
    with open(arquivo, "w", encoding="utf-8") as f:
        f.write(redacao)

    linhas = [f"🎬 <b>{escapa(titulo)}</b>"]
    if frase_thumb:
        linhas.append(f"<i>{escapa(frase_thumb)}</i>")
    if perfis:
        linhas.append("")
        linhas.append("<b>PERFIS DOS PRINTS</b>")
        for p in perfis:
            linhas.append(f"@{p} — https://x.com/{p}")
    if fato_historico:
        linhas.append("")
        linhas.append("<b>FATO HISTORICO</b> (ja anotado, nao repete)")
        linhas.append(escapa(fato_historico))
    if suspeitas:
        linhas.append("")
        linhas.append("<b>OLHE ANTES DE GRAVAR</b>")
        for s in suspeitas[:5]:
            linhas.append("• " + escapa(s.strip()[:110]))

    telegram_texto(cfg, "\n".join(linhas)[:4000])
    telegram_arquivo(cfg, arquivo,
                     f"Redacao — {len(redacao)} caracteres")

    minutos = (time.time() - comeco) / 60
    print("\n" + "=" * 54)
    print(f"  PRONTO em {minutos:.1f} min.")
    print(f"  {len(redacao)} caracteres.")
    print(f"  Salvo em: {arquivo}")
    print("  Tudo tambem foi para o Telegram.")
    print("=" * 54)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
    input("\nAperte Enter para fechar.")
