"""Objetos de transferencia entre coletor e pipeline de ingestao.

Deliberadamente "burros": o conector so preenche o que o site publica. Toda
normalizacao, deducao e validacao acontece em radar.ingest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from radar.enums import (
    JuntaComercial,
    ModalidadeLeilao,
    StatusLeiloeiro,
    StatusLote,
    TipoBem,
    TipoDocumento,
)


@dataclass(slots=True)
class DocumentoBruto:
    url: str
    tipo: TipoDocumento = TipoDocumento.EDITAL
    titulo: str | None = None


@dataclass(slots=True)
class PracaBruta:
    ordem: int
    data_hora: datetime | None = None
    percentual_minimo: Decimal | None = None
    valor_minimo: Decimal | None = None


@dataclass(slots=True)
class LoteBruto:
    """Um lote como o site do leiloeiro (ou o edital) o apresenta."""

    fonte_slug: str
    fonte_url: str
    titulo: str
    numero_lote: str | None = None
    tipo_bem: TipoBem = TipoBem.OUTRO
    descricao: str | None = None
    status: StatusLote = StatusLote.ABERTO

    valor_avaliacao: Decimal | None = None
    pracas: list[PracaBruta] = field(default_factory=list)
    comissao_percentual: Decimal | None = None
    formas_pagamento: list[str] = field(default_factory=list)

    numero_processo: str | None = None
    tribunal_sigla: str | None = None
    comarca: str | None = None
    vara: str | None = None
    leiloeiro_nome: str | None = None
    leiloeiro_matricula: str | None = None
    modalidade: ModalidadeLeilao = ModalidadeLeilao.DESCONHECIDA
    leilao_titulo: str | None = None

    # Imovel
    endereco: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    uf: str | None = None
    cep: str | None = None
    matricula_imovel: str | None = None
    cartorio: str | None = None
    area_total_m2: Decimal | None = None
    ocupado: bool | None = None

    # Veiculo
    placa: str | None = None
    marca: str | None = None
    modelo: str | None = None
    ano_fabricacao: int | None = None
    ano_modelo: int | None = None
    combustivel: str | None = None

    fotos: list[str] = field(default_factory=list)
    documentos: list[DocumentoBruto] = field(default_factory=list)
    onus: list[str] = field(default_factory=list)
    debitos: list[dict] = field(default_factory=list)
    extras: dict = field(default_factory=dict)


@dataclass(slots=True)
class LeiloeiroBruto:
    """Uma linha do cadastro de leiloeiros de uma Junta ou Corregedoria."""

    nome: str
    fonte_slug: str
    fonte_url: str
    uf: str
    matricula: str | None = None
    junta: JuntaComercial | None = None
    status: StatusLeiloeiro = StatusLeiloeiro.DESCONHECIDO
    site_url: str | None = None
    email: str | None = None
    telefone: str | None = None
    comarcas: list[str] = field(default_factory=list)
    credenciado_em: str | None = None
    extras: dict = field(default_factory=dict)


@dataclass(slots=True)
class ResultadoConector:
    lotes: list[LoteBruto] = field(default_factory=list)
    leiloeiros: list[LeiloeiroBruto] = field(default_factory=list)
    paginas_visitadas: int = 0
    avisos: list[str] = field(default_factory=list)

    def estender(self, outro: ResultadoConector) -> None:
        self.lotes.extend(outro.lotes)
        self.leiloeiros.extend(outro.leiloeiros)
        self.paginas_visitadas += outro.paginas_visitadas
        self.avisos.extend(outro.avisos)
