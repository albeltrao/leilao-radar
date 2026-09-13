"""Schemas de resposta da API.

Principio que atravessa o arquivo: todo numero derivado viaja com a sua
procedencia. Campo extraido leva confianca e evidencia; analise de mercado leva
metodologia, data da fonte e avisos; score leva a lista de componentes. A UI nao
tem como mostrar um numero sem contexto porque o contexto vem junto.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

DISCLAIMER_LOTE = (
    "Informações extraídas automaticamente do edital oficial. Consulte o "
    "documento original e um advogado antes de participar do leilão."
)


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LeiloeiroResumo(Base):
    id: int
    nome: str
    matricula: str | None = None
    junta: str | None = None
    uf: str
    status: str
    site_url: str | None = None
    credenciamentos: dict | None = None


class PracaResposta(Base):
    ordem: int
    data_hora: datetime | None = None
    percentual_minimo: Decimal | None = None
    status: str


class EventoResposta(Base):
    id: int
    lote_id: int
    tipo: str
    titulo: str
    data_hora: datetime
    status: str
    estimado: bool = Field(
        description="True quando a data foi inferida pelo sistema, não lida do edital"
    )
    lembretes_horas: list | None = None


class MudancaEventoResposta(Base):
    data_hora_anterior: datetime | None = None
    data_hora_nova: datetime | None = None
    status_anterior: str | None = None
    status_novo: str | None = None
    motivo: str | None = None
    registrado_em: datetime


class CampoResposta(Base):
    nome: str
    valor: Any = None
    confianca: float
    metodo: str
    evidencia: str | None = None
    revisao_necessaria: bool = Field(
        description="True = não confirmado; a UI deve pedir conferência no edital"
    )


class AnaliseResposta(Base):
    fonte: str
    valor_referencia: Decimal | None = None
    valor_comparado: Decimal | None = None
    praca_base: int | None = None
    desconto_percentual: Decimal | None = None
    data_referencia_fonte: datetime | None = None
    metodologia: str
    fonte_url: str | None = None
    avisos: list | None = None
    confianca: float
    calculado_em: datetime


class ComponenteScore(BaseModel):
    chave: str
    rotulo: str
    pontos: float
    maximo: int
    explicacao: str


class ScoreResposta(Base):
    total: float
    faixa: str
    componentes: list[ComponenteScore] = Field(default_factory=list)
    desconto_destaque: float | None = None
    fonte_destaque: str | None = None
    versao: str
    calculado_em: datetime


class DocumentoResposta(Base):
    id: int
    tipo: str
    url: str | None = None
    paginas: int | None = None
    origem_texto: str | None = None
    extraido_em: datetime | None = None
    erro_extracao: str | None = None


class LoteResumo(Base):
    id: int
    titulo: str
    tipo_bem: str
    status: str
    numero_lote: str | None = None
    numero_processo: str | None = None
    valor_avaliacao: Decimal | None = None
    valor_minimo_primeira: Decimal | None = None
    valor_minimo_segunda: Decimal | None = None
    cidade: str | None = None
    bairro: str | None = None
    uf: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geocodificacao_precisao: str | None = None
    ocupado: bool | None = None
    onus: list | None = None
    condicao_veiculo: list | None = None
    fotos: list | None = None
    fonte_slug: str
    fonte_url: str | None = None
    atualizado_em: datetime
    score: ScoreResposta | None = None
    proxima_praca: datetime | None = None
    proxima_praca_ordem: int | None = None
    leiloeiro: LeiloeiroResumo | None = None


class LoteDetalhe(LoteResumo):
    descricao: str | None = None
    endereco: str | None = None
    cep: str | None = None
    matricula: str | None = None
    cartorio: str | None = None
    area_total_m2: Decimal | None = None
    area_privativa_m2: Decimal | None = None
    quartos: int | None = None
    vagas: int | None = None
    marca: str | None = None
    modelo: str | None = None
    ano_fabricacao: int | None = None
    ano_modelo: int | None = None
    combustivel: str | None = None
    placa_parcial: str | None = None
    comissao_leiloeiro_percentual: Decimal | None = None
    formas_pagamento: list | None = None
    debitos: list | None = None
    fontes_secundarias: list | None = None
    coletado_em: datetime
    visto_por_ultimo_em: datetime

    pracas: list[PracaResposta] = Field(default_factory=list)
    eventos: list[EventoResposta] = Field(default_factory=list)
    documentos: list[DocumentoResposta] = Field(default_factory=list)
    campos: list[CampoResposta] = Field(default_factory=list)
    analises: list[AnaliseResposta] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER_LOTE


class PaginaLotes(BaseModel):
    itens: list[LoteResumo]
    total: int
    pagina: int
    tamanho: int
    paginas: int


class SimulacaoResposta(BaseModel):
    lance_base: Decimal | None = None
    custo_total_estimado: Decimal | None = None
    detalhes: list[str]
    aviso: str = (
        "Estimativa de caixa, não parecer. Não inclui ITBI, custas de registro, "
        "despesas de imissão na posse nem reforma."
    )


class FonteSaude(BaseModel):
    slug: str
    nome: str
    tipo: str
    uf: str | None = None
    url_alvo: str
    periodicidade_horas: int
    validado_ao_vivo: bool
    descricao: str
    ultima_execucao_em: datetime | None = None
    ultimo_status: str | None = None
    ultimo_erro: str | None = None
    itens_ultima_coleta: int | None = None
    duracao_ultima_s: float | None = None
    execucoes_7d: int = 0
    falhas_7d: int = 0


class FacetasResposta(BaseModel):
    ufs: list[str]
    cidades: list[dict]
    tipos_bem: list[dict]
    status: list[dict]
    leiloeiros: list[LeiloeiroResumo]
    faixa_valores: dict


class PassoGlossario(BaseModel):
    chave: str
    titulo: str
    resumo: str
    detalhe: str
    atencao: str | None = None


# -- conta -------------------------------------------------------------------


class RegistroEntrada(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=8, max_length=200)
    nome: str | None = Field(default=None, max_length=160)


class LoginEntrada(BaseModel):
    email: EmailStr
    senha: str


class TokenResposta(BaseModel):
    token: str
    expira_em_horas: int
    usuario: UsuarioResposta


class UsuarioResposta(Base):
    id: int
    email: str
    nome: str | None = None


class AlertaEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    criterios: dict = Field(default_factory=dict)
    canal: str = "EMAIL"
    ativo: bool = True


class AlertaResposta(Base):
    id: int
    nome: str
    criterios: dict
    canal: str
    ativo: bool
    ultimo_envio_em: datetime | None = None
    criado_em: datetime


class FavoritoResposta(Base):
    id: int
    lote_id: int
    criado_em: datetime


TokenResposta.model_rebuild()
