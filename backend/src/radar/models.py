"""Modelo de dados (secao 6 do spec).

Convencoes:
* Todo registro vindo de coleta guarda ``fonte_slug`` e ``fonte_url`` -- a trilha
  de auditoria da secao 7.5 depende disso.
* ``chave_natural`` implementa a idempotencia da secao 5: rodar o coletor de novo
  atualiza o lote em vez de duplicar.
* Nada aqui guarda CPF, RG ou endereco residencial de pessoa fisica que nao seja
  o proprio bem leiloado (secao 11 / LGPD). Ver ``Processo.partes_resumo``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from radar.enums import (
    CanalAlerta,
    FonteMercado,
    JuntaComercial,
    MetodoExtracao,
    ModalidadeLeilao,
    OrigemTexto,
    StatusColeta,
    StatusEvento,
    StatusLeiloeiro,
    StatusLote,
    StatusPraca,
    TipoBem,
    TipoDocumento,
    TipoEvento,
    TipoFonte,
)


def agora() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """DateTime que SEMPRE entra e sai em UTC com tzinfo preenchido.

    O SQLite nao tem tipo com fuso: ele devolveria datetimes ingenuos, e comparar
    ingenuo com consciente faz ``!=`` dar True para valores identicos. Isso
    marcaria uma remarcacao falsa a cada coleta e dispararia alerta indevido
    para quem tem lembrete. Postgres tambem se beneficia da normalizacao.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EnumTexto(TypeDecorator):
    """Guarda o *valor* do enum como texto e devolve o membro do enum.

    Com ``mapped_column(String(20))`` cru, o banco devolvia a string pura: a
    anotacao ``Mapped[StatusEvento]`` mentia e comparacoes com ``is`` falhavam
    silenciosamente. Texto (e nao ENUM nativo) porque adicionar um valor novo em
    ENUM nativo do Postgres exige migracao com ALTER TYPE.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls, length: int = 30) -> None:
        self._enum = enum_cls
        super().__init__(length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value.value) if isinstance(value, StrEnum) else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return self._enum(value)
        except ValueError:
            # Valor gravado por uma versao mais nova do codigo: nao derruba a
            # leitura, devolve o texto cru e deixa a aplicacao decidir.
            return value


class Base(DeclarativeBase):
    type_annotation_map = {
        dict: JSON,
        list: JSON,
        Decimal: Numeric(14, 2),
        datetime: UtcDateTime,
    }


class CarimboTempo:
    criado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, onupdate=agora
    )


# ---------------------------------------------------------------------------
# Estrutura judiciaria
# ---------------------------------------------------------------------------


class Tribunal(Base, CarimboTempo):
    __tablename__ = "tribunal"

    id: Mapped[int] = mapped_column(primary_key=True)
    sigla: Mapped[str] = mapped_column(String(10), unique=True)  # TJAL, TJSE, TJPE
    nome: Mapped[str] = mapped_column(String(160))
    uf: Mapped[str] = mapped_column(String(2), index=True)
    url_portal: Mapped[str | None] = mapped_column(String(500))
    url_leiloes: Mapped[str | None] = mapped_column(String(500))
    url_corregedoria: Mapped[str | None] = mapped_column(String(500))

    comarcas: Mapped[list[Comarca]] = relationship(back_populates="tribunal")


class Comarca(Base, CarimboTempo):
    __tablename__ = "comarca"
    __table_args__ = (UniqueConstraint("tribunal_id", "slug", name="uq_comarca_tribunal_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tribunal_id: Mapped[int] = mapped_column(ForeignKey("tribunal.id"))
    nome: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(160), index=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    circunscricao: Mapped[str | None] = mapped_column(String(160))

    tribunal: Mapped[Tribunal] = relationship(back_populates="comarcas")


class Leiloeiro(Base, CarimboTempo):
    """Cadastro mestre (secao 4.2): quem pode leiloar, segundo a Junta Comercial."""

    __tablename__ = "leiloeiro"
    __table_args__ = (UniqueConstraint("junta", "matricula", name="uq_leiloeiro_junta_matricula"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    nome_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    matricula: Mapped[str | None] = mapped_column(String(60))
    junta: Mapped[JuntaComercial | None] = mapped_column(EnumTexto(JuntaComercial))
    uf: Mapped[str] = mapped_column(String(2), index=True)
    status: Mapped[StatusLeiloeiro] = mapped_column(
        String(20), default=StatusLeiloeiro.DESCONHECIDO
    )
    site_url: Mapped[str | None] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(200))
    telefone: Mapped[str | None] = mapped_column(String(60))
    comarcas_atuacao: Mapped[list | None] = mapped_column(JSON, default=list)
    # Credenciamento na corregedoria de cada TJ (secao 4.1): {"TJAL": true, ...}
    credenciamentos: Mapped[dict | None] = mapped_column(JSON, default=dict)
    conector_slug: Mapped[str | None] = mapped_column(
        String(80), index=True, doc="Conector que raspa o site deste leiloeiro, se houver."
    )
    fonte_slug: Mapped[str | None] = mapped_column(String(80))
    fonte_url: Mapped[str | None] = mapped_column(String(500))
    verificado_em: Mapped[datetime | None] = mapped_column(UtcDateTime)

    leiloes: Mapped[list[Leilao]] = relationship(back_populates="leiloeiro")


class Processo(Base, CarimboTempo):
    __tablename__ = "processo"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_cnj: Mapped[str] = mapped_column(String(25), unique=True, index=True)
    tribunal_id: Mapped[int | None] = mapped_column(ForeignKey("tribunal.id"))
    comarca_id: Mapped[int | None] = mapped_column(ForeignKey("comarca.id"))
    classe: Mapped[str | None] = mapped_column(String(200))
    assunto: Mapped[str | None] = mapped_column(String(300))
    vara: Mapped[str | None] = mapped_column(String(200))
    grau: Mapped[str | None] = mapped_column(String(10))
    segredo_justica: Mapped[bool] = mapped_column(Boolean, default=False)
    # LGPD (secao 11): guardamos apenas um resumo textual ja minimizado, nunca
    # CPF/CNPJ de pessoa fisica nem endereco residencial das partes.
    partes_resumo: Mapped[str | None] = mapped_column(String(400))
    datajud_movimentacoes: Mapped[list | None] = mapped_column(JSON)
    datajud_atualizado_em: Mapped[datetime | None] = mapped_column(UtcDateTime)

    tribunal: Mapped[Tribunal | None] = relationship()
    comarca: Mapped[Comarca | None] = relationship()
    leiloes: Mapped[list[Leilao]] = relationship(back_populates="processo")


# ---------------------------------------------------------------------------
# Leilao / praca / lote
# ---------------------------------------------------------------------------


class Leilao(Base, CarimboTempo):
    __tablename__ = "leilao"

    id: Mapped[int] = mapped_column(primary_key=True)
    chave_natural: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    titulo: Mapped[str | None] = mapped_column(String(300))
    leiloeiro_id: Mapped[int | None] = mapped_column(ForeignKey("leiloeiro.id"))
    processo_id: Mapped[int | None] = mapped_column(ForeignKey("processo.id"))
    tribunal_id: Mapped[int | None] = mapped_column(ForeignKey("tribunal.id"))
    modalidade: Mapped[ModalidadeLeilao] = mapped_column(
        String(20), default=ModalidadeLeilao.DESCONHECIDA
    )
    comitente: Mapped[str | None] = mapped_column(String(200))
    fonte_slug: Mapped[str] = mapped_column(String(80), index=True)
    fonte_url: Mapped[str | None] = mapped_column(String(700))
    coletado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    leiloeiro: Mapped[Leiloeiro | None] = relationship(back_populates="leiloes")
    processo: Mapped[Processo | None] = relationship(back_populates="leiloes")
    tribunal: Mapped[Tribunal | None] = relationship()
    pracas: Mapped[list[Praca]] = relationship(
        back_populates="leilao", cascade="all, delete-orphan", order_by="Praca.ordem"
    )
    lotes: Mapped[list[Lote]] = relationship(back_populates="leilao", cascade="all, delete-orphan")


class Praca(Base, CarimboTempo):
    """Uma sessao do leilao. Remarcacao nao sobrescreve: gera EventoHistorico."""

    __tablename__ = "praca"
    __table_args__ = (UniqueConstraint("leilao_id", "ordem", name="uq_praca_leilao_ordem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    leilao_id: Mapped[int] = mapped_column(ForeignKey("leilao.id", ondelete="CASCADE"))
    ordem: Mapped[int] = mapped_column(Integer)  # 1 = primeira praca, 2 = segunda
    data_hora: Mapped[datetime | None] = mapped_column(UtcDateTime, index=True)
    percentual_minimo: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), doc="Percentual do valor de avaliacao aceito nesta praca (ex.: 50.00)."
    )
    status: Mapped[StatusPraca] = mapped_column(EnumTexto(StatusPraca), default=StatusPraca.DESIGNADA)

    leilao: Mapped[Leilao] = relationship(back_populates="pracas")


class Lote(Base, CarimboTempo):
    __tablename__ = "lote"
    __table_args__ = (
        Index("ix_lote_busca", "uf", "cidade", "tipo_bem", "status"),
        Index("ix_lote_geo", "latitude", "longitude"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # tribunal + numero do processo + numero do lote; hash do conteudo quando
    # o processo nao e divulgado (secao 5, idempotencia).
    chave_natural: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    leilao_id: Mapped[int] = mapped_column(ForeignKey("leilao.id", ondelete="CASCADE"))
    numero_lote: Mapped[str | None] = mapped_column(String(40))

    # Denormalizado do Processo: a deduplicacao e os filtros da API consultam
    # por processo o tempo todo, e um join por linha sairia caro.
    numero_processo: Mapped[str | None] = mapped_column(String(25), index=True)
    tipo_bem: Mapped[TipoBem] = mapped_column(EnumTexto(TipoBem), index=True, default=TipoBem.OUTRO)
    titulo: Mapped[str] = mapped_column(String(300))
    descricao: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StatusLote] = mapped_column(EnumTexto(StatusLote), default=StatusLote.ABERTO, index=True)

    valor_avaliacao: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valor_minimo_primeira: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valor_minimo_segunda: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    comissao_leiloeiro_percentual: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    formas_pagamento: Mapped[list | None] = mapped_column(JSON, default=list)

    # Localizacao (imovel)
    endereco: Mapped[str | None] = mapped_column(String(300))
    bairro: Mapped[str | None] = mapped_column(String(160), index=True)
    cidade: Mapped[str | None] = mapped_column(String(160), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    cep: Mapped[str | None] = mapped_column(String(9))
    latitude: Mapped[float | None] = mapped_column()
    longitude: Mapped[float | None] = mapped_column()
    geocodificacao_precisao: Mapped[str | None] = mapped_column(String(30))
    matricula: Mapped[str | None] = mapped_column(String(60))
    cartorio: Mapped[str | None] = mapped_column(String(200))
    area_total_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    area_privativa_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    quartos: Mapped[int | None] = mapped_column(Integer)
    vagas: Mapped[int | None] = mapped_column(Integer)
    ocupado: Mapped[bool | None] = mapped_column(Boolean)

    # Veiculo
    placa_parcial: Mapped[str | None] = mapped_column(
        String(10), doc="Placa mascarada (ex.: ABC1**4) -- minimizacao LGPD."
    )
    marca: Mapped[str | None] = mapped_column(String(80))
    modelo: Mapped[str | None] = mapped_column(String(160))
    ano_fabricacao: Mapped[int | None] = mapped_column(Integer)
    ano_modelo: Mapped[int | None] = mapped_column(Integer)
    combustivel: Mapped[str | None] = mapped_column(String(40))
    codigo_fipe: Mapped[str | None] = mapped_column(String(20))
    condicao_veiculo: Mapped[list | None] = mapped_column(
        JSON, default=list, doc="Ex.: ['SUCATA', 'SEM_CHAVE', 'SEM_DOCUMENTO']"
    )

    # Riscos documentais (secao 7.3)
    onus: Mapped[list | None] = mapped_column(JSON, default=list)
    debitos: Mapped[list | None] = mapped_column(JSON, default=list)

    fotos: Mapped[list | None] = mapped_column(JSON, default=list)
    fonte_slug: Mapped[str] = mapped_column(String(80), index=True)
    fonte_url: Mapped[str | None] = mapped_column(String(700))
    fontes_secundarias: Mapped[list | None] = mapped_column(
        JSON, default=list, doc="Outras URLs onde o mesmo lote foi visto (dedup, secao 5)."
    )
    conteudo_hash: Mapped[str | None] = mapped_column(String(64))
    coletado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)
    visto_por_ultimo_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    leilao: Mapped[Leilao] = relationship(back_populates="lotes")
    documentos: Mapped[list[Documento]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )
    campos: Mapped[list[CampoExtraido]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )
    analises: Mapped[list[AnaliseMercado]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )
    score: Mapped[ScoreOportunidade | None] = relationship(
        back_populates="lote", cascade="all, delete-orphan", uselist=False
    )
    eventos: Mapped[list[EventoCalendario]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Documentos e extracao (secao 7)
# ---------------------------------------------------------------------------


class Documento(Base, CarimboTempo):
    __tablename__ = "documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id", ondelete="CASCADE"))
    tipo: Mapped[TipoDocumento] = mapped_column(EnumTexto(TipoDocumento), default=TipoDocumento.EDITAL)
    url: Mapped[str | None] = mapped_column(String(700))
    caminho_local: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    paginas: Mapped[int | None] = mapped_column(Integer)
    texto: Mapped[str | None] = mapped_column(Text)
    origem_texto: Mapped[OrigemTexto | None] = mapped_column(EnumTexto(OrigemTexto))
    extraido_em: Mapped[datetime | None] = mapped_column(UtcDateTime)
    prompt_versao: Mapped[str | None] = mapped_column(
        String(40), doc="Versao do prompt de extracao usada (secao 12: prompts versionados)."
    )
    parser_versao: Mapped[str | None] = mapped_column(String(40))
    erro_extracao: Mapped[str | None] = mapped_column(String(500))

    lote: Mapped[Lote] = relationship(back_populates="documentos")
    campos: Mapped[list[CampoExtraido]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )


class CampoExtraido(Base, CarimboTempo):
    """Um campo por linha, com confianca e evidencia -- nunca um blob opaco.

    A regra da secao 7.4 (nada extraido por IA e apresentado como garantido)
    depende de ``confianca`` e ``revisao_necessaria`` chegarem ate a UI.
    """

    __tablename__ = "campo_extraido"
    __table_args__ = (
        UniqueConstraint("lote_id", "nome", name="uq_campo_lote_nome"),
        Index("ix_campo_revisao", "revisao_necessaria", "confianca"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id", ondelete="CASCADE"))
    documento_id: Mapped[int | None] = mapped_column(
        ForeignKey("documento.id", ondelete="CASCADE")
    )
    nome: Mapped[str] = mapped_column(String(80), index=True)
    valor_texto: Mapped[str | None] = mapped_column(Text)
    valor_numerico: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    valor_data: Mapped[datetime | None] = mapped_column(UtcDateTime)
    valor_booleano: Mapped[bool | None] = mapped_column(Boolean)
    confianca: Mapped[float] = mapped_column(default=0.0)
    metodo: Mapped[MetodoExtracao] = mapped_column(EnumTexto(MetodoExtracao), default=MetodoExtracao.REGRA)
    evidencia: Mapped[str | None] = mapped_column(
        Text, doc="Trecho literal do documento que sustenta o valor."
    )
    revisao_necessaria: Mapped[bool] = mapped_column(Boolean, default=False)

    lote: Mapped[Lote] = relationship(back_populates="campos")
    documento: Mapped[Documento | None] = relationship(back_populates="campos")


# ---------------------------------------------------------------------------
# Mercado e score (secoes 4.5 e 8)
# ---------------------------------------------------------------------------


class AnaliseMercado(Base, CarimboTempo):
    __tablename__ = "analise_mercado"
    __table_args__ = (UniqueConstraint("lote_id", "fonte", name="uq_analise_lote_fonte"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id", ondelete="CASCADE"))
    fonte: Mapped[FonteMercado] = mapped_column(EnumTexto(FonteMercado))
    valor_referencia: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valor_comparado: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), doc="Lance minimo da praca vigente usado no calculo."
    )
    praca_base: Mapped[int | None] = mapped_column(Integer)
    desconto_percentual: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    data_referencia_fonte: Mapped[datetime | None] = mapped_column(UtcDateTime)
    metodologia: Mapped[str] = mapped_column(Text)
    fonte_url: Mapped[str | None] = mapped_column(String(500))
    avisos: Mapped[list | None] = mapped_column(JSON, default=list)
    confianca: Mapped[float] = mapped_column(default=0.0)
    calculado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    lote: Mapped[Lote] = relationship(back_populates="analises")


class ScoreOportunidade(Base, CarimboTempo):
    __tablename__ = "score_oportunidade"

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(
        ForeignKey("lote.id", ondelete="CASCADE"), unique=True, index=True
    )
    total: Mapped[float] = mapped_column(default=0.0, index=True)
    faixa: Mapped[str] = mapped_column(String(20), default="INDEFINIDA")
    # Denormalizado da melhor AnaliseMercado no momento do calculo: filtrar e
    # ordenar por desconto e a operacao mais comum da listagem, e faze-la por
    # subconsulta em analise_mercado sairia caro em toda pagina.
    desconto_destaque: Mapped[float | None] = mapped_column(index=True)
    fonte_destaque: Mapped[str | None] = mapped_column(String(20))
    # Lista de componentes {chave, rotulo, pontos, maximo, explicacao}: e o que a
    # UI mostra no tooltip do termometro. Secao 8: nunca um numero sem explicacao.
    componentes: Mapped[list | None] = mapped_column(JSON, default=list)
    versao: Mapped[str] = mapped_column(String(20), default="1.0")
    calculado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    lote: Mapped[Lote] = relationship(back_populates="score")


# ---------------------------------------------------------------------------
# Calendario (secao 9)
# ---------------------------------------------------------------------------


class EventoCalendario(Base, CarimboTempo):
    __tablename__ = "evento_calendario"
    __table_args__ = (
        UniqueConstraint("lote_id", "tipo", name="uq_evento_lote_tipo"),
        Index("ix_evento_data", "data_hora", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id", ondelete="CASCADE"))
    praca_id: Mapped[int | None] = mapped_column(ForeignKey("praca.id", ondelete="SET NULL"))
    tipo: Mapped[TipoEvento] = mapped_column(EnumTexto(TipoEvento), index=True)
    titulo: Mapped[str] = mapped_column(String(300))
    data_hora: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    status: Mapped[StatusEvento] = mapped_column(EnumTexto(StatusEvento), default=StatusEvento.CONFIRMADO)
    estimado: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="True quando a data foi inferida, nao lida do edital."
    )
    lembretes_horas: Mapped[list | None] = mapped_column(JSON, default=list)

    lote: Mapped[Lote] = relationship(back_populates="eventos")
    historico: Mapped[list[EventoHistorico]] = relationship(
        back_populates="evento", cascade="all, delete-orphan", order_by="EventoHistorico.id"
    )


class EventoHistorico(Base):
    """Secao 9: remarcacao e suspensao sao eventos de primeira classe."""

    __tablename__ = "evento_historico"

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[int] = mapped_column(
        ForeignKey("evento_calendario.id", ondelete="CASCADE")
    )
    data_hora_anterior: Mapped[datetime | None] = mapped_column(UtcDateTime)
    data_hora_nova: Mapped[datetime | None] = mapped_column(UtcDateTime)
    status_anterior: Mapped[str | None] = mapped_column(String(20))
    status_novo: Mapped[str | None] = mapped_column(String(20))
    motivo: Mapped[str | None] = mapped_column(String(300))
    registrado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    evento: Mapped[EventoCalendario] = relationship(back_populates="historico")


# ---------------------------------------------------------------------------
# Usuarios, alertas, favoritos
# ---------------------------------------------------------------------------


class Usuario(Base, CarimboTempo):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nome: Mapped[str | None] = mapped_column(String(160))
    senha_hash: Mapped[str] = mapped_column(String(255))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    alertas: Mapped[list[Alerta]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    favoritos: Mapped[list[Favorito]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class Sessao(Base):
    __tablename__ = "sessao"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    criado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)
    expira_em: Mapped[datetime] = mapped_column(UtcDateTime)

    usuario: Mapped[Usuario] = relationship()


class Alerta(Base, CarimboTempo):
    __tablename__ = "alerta"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"))
    nome: Mapped[str] = mapped_column(String(160))
    criterios: Mapped[dict] = mapped_column(JSON, default=dict)
    canal: Mapped[CanalAlerta] = mapped_column(EnumTexto(CanalAlerta), default=CanalAlerta.EMAIL)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_envio_em: Mapped[datetime | None] = mapped_column(UtcDateTime)

    usuario: Mapped[Usuario] = relationship(back_populates="alertas")
    envios: Mapped[list[AlertaEnvio]] = relationship(
        back_populates="alerta", cascade="all, delete-orphan"
    )


class AlertaEnvio(Base):
    """Dedup: um lote so dispara um alerta uma vez por regra."""

    __tablename__ = "alerta_envio"
    __table_args__ = (UniqueConstraint("alerta_id", "lote_id", name="uq_envio_alerta_lote"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    alerta_id: Mapped[int] = mapped_column(ForeignKey("alerta.id", ondelete="CASCADE"))
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id", ondelete="CASCADE"))
    enviado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    alerta: Mapped[Alerta] = relationship(back_populates="envios")


class Favorito(Base):
    __tablename__ = "favorito"
    __table_args__ = (UniqueConstraint("usuario_id", "lote_id", name="uq_favorito"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"))
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id", ondelete="CASCADE"))
    criado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)

    usuario: Mapped[Usuario] = relationship(back_populates="favoritos")
    lote: Mapped[Lote] = relationship()


# ---------------------------------------------------------------------------
# Observabilidade de coleta (secao 5)
# ---------------------------------------------------------------------------


class ExecucaoColeta(Base):
    __tablename__ = "execucao_coleta"
    __table_args__ = (Index("ix_execucao_fonte_data", "fonte_slug", "iniciado_em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fonte_slug: Mapped[str] = mapped_column(String(80), index=True)
    tipo_fonte: Mapped[TipoFonte] = mapped_column(EnumTexto(TipoFonte))
    status: Mapped[StatusColeta] = mapped_column(EnumTexto(StatusColeta), default=StatusColeta.EM_ANDAMENTO)
    iniciado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)
    finalizado_em: Mapped[datetime | None] = mapped_column(UtcDateTime)
    duracao_s: Mapped[float | None] = mapped_column()
    itens_encontrados: Mapped[int] = mapped_column(Integer, default=0)
    itens_novos: Mapped[int] = mapped_column(Integer, default=0)
    itens_atualizados: Mapped[int] = mapped_column(Integer, default=0)
    requisicoes_http: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(Text)
    detalhe: Mapped[dict | None] = mapped_column(JSON, default=dict)


class IndiceFipeZap(Base):
    """Serie historica propria, extraida dos boletins mensais (secao 4.5)."""

    __tablename__ = "indice_fipezap"
    __table_args__ = (
        UniqueConstraint("uf", "cidade", "bairro", "mes_referencia", name="uq_fipezap"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    cidade: Mapped[str] = mapped_column(String(160), index=True)
    bairro: Mapped[str | None] = mapped_column(String(160))
    valor_m2_venda: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    mes_referencia: Mapped[str] = mapped_column(String(7), index=True)  # AAAA-MM
    fonte_url: Mapped[str | None] = mapped_column(String(500))
    observacao: Mapped[str | None] = mapped_column(String(300))


class ReferenciaFipe(Base):
    """Cache local da tabela FIPE (secao 4.5)."""

    __tablename__ = "referencia_fipe"
    __table_args__ = (
        UniqueConstraint("codigo_fipe", "ano_modelo", "mes_referencia", name="uq_fipe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_fipe: Mapped[str] = mapped_column(String(20), index=True)
    marca: Mapped[str] = mapped_column(String(80), index=True)
    modelo: Mapped[str] = mapped_column(String(200), index=True)
    modelo_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    ano_modelo: Mapped[int] = mapped_column(Integer, index=True)
    combustivel: Mapped[str | None] = mapped_column(String(40))
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    mes_referencia: Mapped[str] = mapped_column(String(7))
    atualizado_em: Mapped[datetime] = mapped_column(UtcDateTime, default=agora)
