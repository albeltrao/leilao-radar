"""Normalizacao de um LoteBruto para o formato do banco (secao 5).

Aqui moram as decisoes que NAO devem ficar espalhadas pelos conectores:
chave natural, inferencia de UF/tribunal, minimizacao LGPD e geocodificacao.

Regra que este modulo deliberadamente NAO aplica: "o lance minimo da 2a praca e
50% da avaliacao". Isso e o costume, nao a lei -- cada edital fixa o seu
percentual, e alguns exigem 60% ou vedam preco vil de outra forma. So derivamos
o valor quando o percentual veio do edital; caso contrario o campo fica vazio e
a UI mostra "nao informado" em vez de um numero inventado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from radar.collectors.dto import LoteBruto, PracaBruta
from radar.enums import TipoBem
from radar.ingest.geocode import Geocodificador, GeocodificadorNulo
from radar.normalizacao import (
    extrair_numero_cnj,
    hash_conteudo,
    limpar_espacos,
    mascarar_placa,
    normalizar_texto,
    numero_cnj_valido,
    remover_cpf,
    tribunal_do_cnj,
)

logger = logging.getLogger(__name__)

UF_POR_TRIBUNAL = {"TJAL": "AL", "TJSE": "SE", "TJPE": "PE"}
_UF_VALIDAS = frozenset(UF_POR_TRIBUNAL.values())


@dataclass(slots=True)
class LoteNormalizado:
    bruto: LoteBruto
    chave_natural: str
    conteudo_hash: str
    uf: str | None = None
    tribunal_sigla: str | None = None
    numero_processo: str | None = None
    processo_valido: bool = False
    cidade: str | None = None
    bairro: str | None = None
    endereco: str | None = None
    descricao: str | None = None
    placa_parcial: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geocodificacao_precisao: str | None = None
    pracas: list[PracaBruta] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def valor_minimo_primeira(self) -> Decimal | None:
        return self._minimo(1)

    @property
    def valor_minimo_segunda(self) -> Decimal | None:
        return self._minimo(2)

    def _minimo(self, ordem: int) -> Decimal | None:
        for praca in self.pracas:
            if praca.ordem == ordem:
                return praca.valor_minimo
        return None


def _inferir_uf(bruto: LoteBruto, tribunal: str | None) -> str | None:
    if bruto.uf and bruto.uf.upper() in _UF_VALIDAS:
        return bruto.uf.upper()
    if tribunal:
        return UF_POR_TRIBUNAL.get(tribunal)
    # "Maceió/AL" no titulo ou no endereco.
    for texto in (bruto.cidade, bruto.endereco, bruto.titulo):
        if not texto:
            continue
        alvo = texto.upper()
        for uf in _UF_VALIDAS:
            if f"/{uf}" in alvo or f"-{uf}" in alvo or alvo.endswith(f" {uf}"):
                return uf
    return None


def _chave_natural(
    bruto: LoteBruto, tribunal: str | None, processo: str | None, conteudo_hash: str
) -> str:
    """tribunal + processo + lote e o ideal; hash do conteudo e o fallback."""
    if processo:
        lote = normalizar_texto(bruto.numero_lote or "") or "unico"
        return f"{tribunal or 'NA'}|{processo}|{lote}"
    return f"{bruto.fonte_slug}|{conteudo_hash[:32]}"


def _derivar_minimos(bruto: LoteBruto, avisos: list[str]) -> list[PracaBruta]:
    """Preenche valor_minimo a partir do percentual quando o edital o declarou."""
    pracas = [
        PracaBruta(
            ordem=p.ordem,
            data_hora=p.data_hora,
            percentual_minimo=p.percentual_minimo,
            valor_minimo=p.valor_minimo,
        )
        for p in bruto.pracas
    ]
    for praca in pracas:
        if praca.valor_minimo is not None or praca.percentual_minimo is None:
            continue
        if bruto.valor_avaliacao is None:
            continue
        praca.valor_minimo = (
            bruto.valor_avaliacao * praca.percentual_minimo / Decimal(100)
        ).quantize(Decimal("0.01"))
        avisos.append(
            f"lance minimo da praca {praca.ordem} derivado de "
            f"{praca.percentual_minimo}% da avaliacao"
        )
    # A primeira praca, por definicao, sai pelo valor de avaliacao.
    for praca in pracas:
        if praca.ordem == 1 and praca.valor_minimo is None and bruto.valor_avaliacao:
            praca.valor_minimo = bruto.valor_avaliacao
    return pracas


def normalizar(
    bruto: LoteBruto, geocodificador: Geocodificador | None = None
) -> LoteNormalizado:
    geocodificador = geocodificador or GeocodificadorNulo()
    avisos: list[str] = []

    processo = bruto.numero_processo or extrair_numero_cnj(
        f"{bruto.titulo} {bruto.descricao or ''}"
    )
    processo_valido = numero_cnj_valido(processo)
    if processo and not processo_valido:
        avisos.append(
            f"numero de processo {processo} nao passa no digito verificador CNJ "
            "-- tratado como referencia textual, nao usado para consultar o DataJud"
        )

    tribunal = bruto.tribunal_sigla or (tribunal_do_cnj(processo) if processo_valido else None)
    uf = _inferir_uf(bruto, tribunal)
    if tribunal is None and uf:
        tribunal = {v: k for k, v in UF_POR_TRIBUNAL.items()}.get(uf)

    # LGPD (secao 11): nada de CPF, nada de placa inteira.
    descricao = remover_cpf(limpar_espacos(bruto.descricao))
    placa_parcial = mascarar_placa(bruto.placa)
    if bruto.placa and not placa_parcial:
        avisos.append("placa informada nao reconhecida; campo descartado")

    pracas = _derivar_minimos(bruto, avisos)

    conteudo_hash = hash_conteudo(
        bruto.fonte_slug,
        bruto.titulo,
        bruto.valor_avaliacao,
        [(p.ordem, p.data_hora, p.valor_minimo) for p in pracas],
        descricao,
    )
    chave = _chave_natural(bruto, tribunal, processo if processo_valido else None, conteudo_hash)

    cidade = limpar_espacos(bruto.cidade) or limpar_espacos(bruto.comarca)
    coord = None
    if bruto.tipo_bem is TipoBem.IMOVEL or bruto.endereco:
        coord = geocodificador.localizar(bruto.endereco, bruto.bairro, cidade, uf)

    return LoteNormalizado(
        bruto=bruto,
        chave_natural=chave,
        conteudo_hash=conteudo_hash,
        uf=uf,
        tribunal_sigla=tribunal,
        numero_processo=processo,
        processo_valido=processo_valido,
        cidade=cidade,
        bairro=limpar_espacos(bruto.bairro),
        endereco=limpar_espacos(bruto.endereco),
        descricao=descricao,
        placa_parcial=placa_parcial,
        latitude=coord.latitude if coord else None,
        longitude=coord.longitude if coord else None,
        geocodificacao_precisao=coord.precisao if coord else None,
        pracas=pracas,
        avisos=avisos,
    )


def esta_obsoleto(visto_em: datetime | None, dias: int = 45) -> bool:
    """Lote nao visto em nenhuma coleta recente provavelmente saiu do ar."""
    if visto_em is None:
        return True
    if visto_em.tzinfo is None:
        visto_em = visto_em.replace(tzinfo=UTC)
    return (datetime.now(UTC) - visto_em).days > dias
