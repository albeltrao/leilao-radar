"""PDF -> texto, com OCR para paginas digitalizadas (secao 7.1 e 7.2)."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from radar.config import Settings, get_settings
from radar.enums import OrigemTexto

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TextoDocumento:
    texto: str
    paginas: int
    origem: OrigemTexto
    paginas_ocr: int = 0
    aviso: str | None = None

    @property
    def vazio(self) -> bool:
        return len(self.texto.strip()) < 40


def normalizar_texto_pdf(bruto: str) -> str:
    """Junta hifenizacao de fim de linha e colapsa espacos.

    Editais quebram "aliena-\\ncao" e "R$ 320.000,\\n00"; sem consertar isso, as
    regex do parser perdem metade dos valores.
    """
    texto = bruto.replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)  # hifenizacao
    texto = re.sub(r"[ \t ]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    # Valores partidos pela quebra de linha: "R$ 320.000,\n00"
    texto = re.sub(r"(\d),\s*\n\s*(\d{2})\b", r"\1,\2", texto)
    return texto.strip()


def extrair_texto(
    caminho: Path, settings: Settings | None = None
) -> TextoDocumento:
    settings = settings or get_settings()
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pypdf e obrigatorio para ler editais") from exc

    try:
        leitor = PdfReader(str(caminho))
    except Exception as exc:
        return TextoDocumento("", 0, OrigemTexto.PDF_TEXTO, aviso=f"PDF ilegivel: {exc}")

    partes: list[str] = []
    paginas_para_ocr: list[int] = []
    for indice, pagina in enumerate(leitor.pages):
        try:
            conteudo = pagina.extract_text() or ""
        except Exception as exc:  # pagina corrompida nao invalida o documento
            logger.warning("pagina %s de %s ilegivel: %s", indice, caminho.name, exc)
            conteudo = ""
        if len(conteudo.strip()) < settings.ocr_minimo_caracteres_pagina:
            paginas_para_ocr.append(indice)
        partes.append(conteudo)

    paginas_ocr = 0
    if paginas_para_ocr and settings.ocr_habilitado:
        textos_ocr = _ocr_paginas(caminho, paginas_para_ocr, settings)
        for indice, conteudo in textos_ocr.items():
            if len(conteudo.strip()) > len(partes[indice].strip()):
                partes[indice] = conteudo
                paginas_ocr += 1

    texto = normalizar_texto_pdf("\n\n".join(partes))
    origem = OrigemTexto.OCR if paginas_ocr else OrigemTexto.PDF_TEXTO
    aviso = None
    if paginas_para_ocr and not settings.ocr_habilitado:
        aviso = (
            f"{len(paginas_para_ocr)} de {len(leitor.pages)} paginas parecem "
            "digitalizadas e o OCR esta desligado (RADAR_OCR_HABILITADO=1 para ligar)"
        )
    return TextoDocumento(
        texto=texto,
        paginas=len(leitor.pages),
        origem=origem,
        paginas_ocr=paginas_ocr,
        aviso=aviso,
    )


def _ocr_paginas(
    caminho: Path, indices: list[int], settings: Settings
) -> dict[int, str]:  # pragma: no cover - exige tesseract instalado
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        logger.warning("OCR pedido mas extras nao instalados: pip install 'radar-leilao[ocr]'")
        return {}

    resultado: dict[int, str] = {}
    for indice in indices:
        try:
            imagens = convert_from_path(
                str(caminho), first_page=indice + 1, last_page=indice + 1, dpi=300
            )
            if imagens:
                resultado[indice] = pytesseract.image_to_string(
                    imagens[0], lang=settings.ocr_idioma
                )
        except Exception as exc:
            logger.warning("OCR falhou na pagina %s de %s: %s", indice, caminho.name, exc)
    return resultado


def sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(65536), b""):
            digest.update(bloco)
    return digest.hexdigest()
