"""Orquestra a extracao de um documento e aplica o resultado no lote."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from radar.collectors.http import Fetcher
from radar.config import Settings, get_settings
from radar.enums import MetodoExtracao, TipoBem
from radar.extraction.campos import LIMIAR_REVISAO, ResultadoExtracao
from radar.extraction.edital import ParserEdital
from radar.extraction.llm import ExtratorLLM
from radar.extraction.merge import combinar
from radar.extraction.pdf import extrair_texto, sha256_arquivo
from radar.models import CampoExtraido, Documento, Lote
from radar.normalizacao import remover_cpf

logger = logging.getLogger(__name__)

# Campos extraidos que podem preencher colunas do lote, e a coluna de destino.
MAPA_LOTE = {
    "valor_avaliacao": "valor_avaliacao",
    "valor_minimo_praca_1": "valor_minimo_primeira",
    "valor_minimo_praca_2": "valor_minimo_segunda",
    "comissao_leiloeiro": "comissao_leiloeiro_percentual",
    "matricula_imovel": "matricula",
    "cartorio": "cartorio",
    "area_total_m2": "area_total_m2",
    "area_privativa_m2": "area_privativa_m2",
    "endereco": "endereco",
    "bairro": "bairro",
    "cidade": "cidade",
    "ocupado": "ocupado",
    "marca": "marca",
    "modelo": "modelo",
    "ano_fabricacao": "ano_fabricacao",
    "ano_modelo": "ano_modelo",
}


def extrair_documento(
    sessao: Session,
    documento: Documento,
    *,
    fetcher: Fetcher | None = None,
    settings: Settings | None = None,
) -> ResultadoExtracao:
    """Baixa (se preciso), le, extrai e grava os campos com confianca."""
    settings = settings or get_settings()

    caminho = _garantir_arquivo(documento, fetcher, settings)
    if caminho is None:
        documento.erro_extracao = "documento indisponivel para download"
        return ResultadoExtracao(avisos=[documento.erro_extracao])

    lido = extrair_texto(caminho, settings)
    # LGPD: o texto do edital vai para o banco; CPF de pessoa fisica, nao.
    documento.texto = remover_cpf(lido.texto)
    documento.paginas = lido.paginas
    documento.origem_texto = lido.origem
    documento.sha256 = documento.sha256 or sha256_arquivo(caminho)
    documento.caminho_local = str(caminho)
    documento.extraido_em = datetime.now(UTC)

    if lido.vazio:
        documento.erro_extracao = lido.aviso or "nenhum texto extraido do documento"
        return ResultadoExtracao(avisos=[documento.erro_extracao])

    da_regra = ParserEdital().extrair(documento.texto)
    do_llm = ExtratorLLM(settings).extrair(documento.texto)
    resultado = combinar(da_regra, do_llm)
    if lido.aviso:
        resultado.avisos.append(lido.aviso)

    documento.parser_versao = resultado.parser_versao
    documento.prompt_versao = resultado.prompt_versao
    documento.erro_extracao = None

    _persistir_campos(sessao, documento, resultado)
    return resultado


def _garantir_arquivo(
    documento: Documento, fetcher: Fetcher | None, settings: Settings
) -> Path | None:
    if documento.caminho_local and Path(documento.caminho_local).exists():
        return Path(documento.caminho_local)
    if not documento.url or fetcher is None:
        return None
    try:
        resposta = fetcher.baixar_documento(documento.url, documento.lote.fonte_slug)
    except Exception as exc:
        logger.warning("falha ao baixar %s: %s", documento.url, exc)
        return None
    if not resposta.ok or resposta.caminho_arquivo is None:
        return None
    documento.sha256 = resposta.sha256
    return resposta.caminho_arquivo


def _persistir_campos(
    sessao: Session, documento: Documento, resultado: ResultadoExtracao
) -> None:
    existentes = {c.nome: c for c in documento.lote.campos}
    for achado in resultado.achados:
        campo = existentes.get(achado.nome)
        if campo is None:
            campo = CampoExtraido(lote_id=documento.lote_id, lote=documento.lote, nome=achado.nome)
            sessao.add(campo)
        elif campo.metodo is MetodoExtracao.MANUAL:
            continue  # revisao humana tem a ultima palavra
        campo.documento_id = documento.id
        campo.valor_texto = achado.valor_texto
        campo.valor_numerico = achado.valor_numerico
        campo.valor_data = achado.valor_data
        campo.valor_booleano = achado.valor_booleano
        campo.confianca = achado.confianca
        campo.metodo = achado.metodo
        campo.evidencia = achado.evidencia
        campo.revisao_necessaria = achado.revisao_necessaria


def aplicar_no_lote(lote: Lote, resultado: ResultadoExtracao) -> list[str]:
    """Preenche colunas vazias do lote com achados confiaveis.

    Nunca sobrescreve o que veio estruturado do site do leiloeiro: aquele dado
    foi publicado, este foi inferido de um PDF. So preenche buraco.
    """
    alterados: list[str] = []
    for nome, achado in resultado.por_nome().items():
        coluna = MAPA_LOTE.get(nome)
        if coluna is None or achado.confianca < LIMIAR_REVISAO:
            continue
        if not hasattr(lote, coluna):
            continue
        if getattr(lote, coluna) is not None:
            continue
        valor = achado.valor
        if isinstance(valor, str) and coluna in {"ano_fabricacao", "ano_modelo"}:
            continue
        setattr(lote, coluna, valor)
        alterados.append(coluna)

    # Onus e debitos entram como lista de risco, nao como coluna simples.
    onus = resultado.obter("onus")
    if onus and onus.valor_texto and not lote.onus:
        lote.onus = [t.strip() for t in onus.valor_texto.split(",") if t.strip()]
        alterados.append("onus")
    debitos = resultado.obter("debitos_mencionados")
    if debitos and debitos.valor_texto and not lote.debitos:
        lote.debitos = [
            {"tipo": t.strip(), "valor": _valor_debito(resultado, t.strip())}
            for t in debitos.valor_texto.split(",")
            if t.strip()
        ]
        alterados.append("debitos")
    condicao = resultado.obter("condicao_veiculo")
    if condicao and condicao.valor_texto and lote.tipo_bem is TipoBem.VEICULO:
        lote.condicao_veiculo = [t.strip() for t in condicao.valor_texto.split(",")]
        alterados.append("condicao_veiculo")
    formas = resultado.obter("formas_pagamento")
    if formas and formas.valor_texto and not lote.formas_pagamento:
        lote.formas_pagamento = [t.strip() for t in formas.valor_texto.split(",")]
        alterados.append("formas_pagamento")
    return alterados


def _valor_debito(resultado: ResultadoExtracao, tipo: str) -> float | None:
    achado = resultado.obter(f"debito_{tipo}")
    if achado is None or achado.valor_numerico is None:
        return None
    return float(achado.valor_numerico)
