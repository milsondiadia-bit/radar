# -*- coding: utf-8 -*-
"""
PDF CLICAVEL

Pega um PDF escaneado - aquele em que o Ctrl+F nao acha nada porque a
pagina e uma foto - e devolve o MESMO arquivo com o texto embutido por
baixo da imagem, invisivel.

Na tela nao muda nada: continua a digitalizacao original, boa para
mostrar na camera. Mas o Ctrl+F passa a funcionar, da para selecionar
trecho, copiar e o Chrome mostra os resultados na lateral.

Uso:
    arraste o PDF em cima de PDF_CLICAVEL.bat
    ou:  python pdf_clicavel.py caminho\\do\\arquivo.pdf
    ou:  python pdf_clicavel.py https://site.com/arquivo.pdf
"""

import io
import os
import sys
import time
import tempfile

TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        print("\nFalta a biblioteca de PDF. Rode uma vez:")
        print("    pip install pymupdf\n")
        input("Aperte Enter para fechar.")
        sys.exit(1)

try:
    import pytesseract
    from PIL import Image
except ImportError:
    print("\nFalta o OCR. Rode uma vez:")
    print("    pip install pytesseract pillow\n")
    input("Aperte Enter para fechar.")
    sys.exit(1)

if os.path.exists(TESSERACT_EXE):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

# 200 dpi: medido no relatorio da PF (04/09/2026). A 150 o Tesseract
# troca numero por letra em carimbo e rodape; acima de 200 a leitura
# nao melhora e o tempo dobra.
DPI = 200

# Abaixo disto a pagina e imagem: nao tem letra de verdade nela.
MINIMO_POR_PAGINA = 80


def baixar(url, destino):
    import urllib.request
    print("Baixando...")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=120) as r:
        dados = r.read()
    if not dados.startswith(b"%PDF"):
        raise RuntimeError("o link nao devolveu um PDF")
    with open(destino, "wb") as f:
        f.write(dados)
    return destino


def ocr_pagina(par):
    """Uma pagina -> PDF de uma pagina com texto invisivel embutido."""
    numero, png = par
    try:
        bruto = pytesseract.image_to_pdf_or_hocr(
            Image.open(io.BytesIO(png)), extension="pdf", lang="por")
        return numero, bruto
    except Exception:
        # se o pacote de portugues faltar, tenta o padrao
        try:
            bruto = pytesseract.image_to_pdf_or_hocr(
                Image.open(io.BytesIO(png)), extension="pdf")
            return numero, bruto
        except Exception:
            return numero, None


def converter(entrada):
    tmp = None
    if entrada.lower().startswith("http"):
        tmp = os.path.join(tempfile.mkdtemp(), "baixado.pdf")
        caminho = baixar(entrada, tmp)
        nome_base = entrada.split("/")[-1].split("?")[0] or "documento.pdf"
        pasta = os.getcwd()
    else:
        caminho = entrada
        nome_base = os.path.basename(caminho)
        pasta = os.path.dirname(os.path.abspath(caminho))

    if not nome_base.lower().endswith(".pdf"):
        nome_base += ".pdf"
    destino = os.path.join(pasta, nome_base[:-4] + " (CLICAVEL).pdf")

    doc = fitz.open(caminho)
    total = doc.page_count
    print(f"\n{total} pagina(s). Lendo...")

    # quais paginas ja tem letra e quais sao foto
    precisa = []
    for n in range(total):
        try:
            texto = doc.load_page(n).get_text("text")
        except Exception:
            texto = ""
        if len(texto.strip()) < MINIMO_POR_PAGINA:
            precisa.append(n)

    if not precisa:
        print("\nEste PDF JA e clicavel - todas as paginas tem texto.")
        print("Se o Ctrl+F nao acha, o problema e outro (acento, ou o")
        print("termo esta quebrado entre duas linhas).")
        doc.close()
        return None

    print(f"{len(precisa)} pagina(s) sao imagem. Passando OCR...")
    print("(cerca de 1 segundo por pagina)\n")

    zoom = fitz.Matrix(DPI / 72.0, DPI / 72.0)
    pares = []
    for n in precisa:
        pares.append((n, doc.load_page(n).get_pixmap(matrix=zoom).tobytes("png")))

    comeco = time.time()
    prontos = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        trabalhadores = min(8, max(1, os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
            for i, (n, bruto) in enumerate(pool.map(ocr_pagina, pares), 1):
                prontos[n] = bruto
                if i % 5 == 0 or i == len(pares):
                    print(f"    {i} de {len(pares)}")
    except Exception:
        for i, par in enumerate(pares, 1):
            n, bruto = ocr_pagina(par)
            prontos[n] = bruto
            print(f"    {i} de {len(pares)}")

    novo = fitz.open()
    for n in range(total):
        bruto = prontos.get(n)
        if bruto:
            novo.insert_pdf(fitz.open("pdf", bruto))
        else:
            novo.insert_pdf(doc, from_page=n, to_page=n)

    novo.save(destino, garbage=3, deflate=True)
    novo.close()
    doc.close()

    minutos = (time.time() - comeco) / 60
    print(f"\nPronto em {minutos:.1f} min.")
    print(f"Salvo em:\n    {destino}")
    return destino


def main():
    if len(sys.argv) > 1:
        entrada = " ".join(sys.argv[1:]).strip('"')
    else:
        print("=" * 55)
        print("   PDF CLICAVEL  -  faz o Ctrl+F funcionar")
        print("=" * 55)
        entrada = input("\nCole o link do PDF (ou o caminho do arquivo): ")
        entrada = entrada.strip().strip('"')

    if not entrada:
        return

    try:
        destino = converter(entrada)
    except Exception as e:
        print(f"\nDEU ERRO: {e}")
        input("\nAperte Enter para fechar.")
        return

    if destino:
        try:
            os.startfile(destino)
        except Exception:
            pass

    input("\nAperte Enter para fechar.")


if __name__ == "__main__":
    main()
