"""Agenda de leilões: cronológica e agrupada por tipo de bem.

O que se pediu: "destacar quais os leilões detectados, organizando de forma
cronológica e por tipo de bens, móveis e imóveis, rurais e urbanos". São dois
recortes da mesma lista, e este módulo devolve os dois de uma vez -- os dias em
ordem e a contagem por categoria -- para a tela não ter de contar sozinha e
divergir do backend.

O eixo do tempo é o **evento de praça**, não a data da publicação. Ordenar pela
publicação responderia "o que saiu no diário hoje"; quem vai a leilão precisa de
"o que acontece nos próximos dias". A data da publicação viaja junto, em cada
item, como procedência.

Uma categoria que este módulo não esconde: IMOVEL_INDEFINIDO. Imóvel cuja zona
não deu para determinar aparece na sua própria faixa, com a evidência do que se
leu. Empurrá-lo para "urbano" por ser o mais comum seria inventar dado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from radar.enums import EsferaJustica, NaturezaBem, StatusEvento, TipoEvento, ZonaImovel
from radar.models import EventoCalendario, Leilao, Lote
from radar.normalizacao import para_local

# Ordem das abas na tela. Mexer aqui muda a tela inteira, então o rótulo mora
# junto da chave -- não duplicado no frontend.
CATEGORIAS: tuple[tuple[str, str], ...] = (
    ("IMOVEL_URBANO", "Imóveis urbanos"),
    ("IMOVEL_RURAL", "Imóveis rurais"),
    ("IMOVEL_INDEFINIDO", "Imóveis sem zona identificada"),
    ("MOVEL", "Bens móveis"),
    ("INDEFINIDO", "Natureza não identificada"),
)
ROTULOS = dict(CATEGORIAS)

# Só as sessões do leilão entram na agenda por padrão. Prazo de habilitação e
# de caução são do calendário de quem já escolheu um lote, não da vitrine.
EVENTOS_DE_PRACA: frozenset[TipoEvento] = frozenset(
    {TipoEvento.PRACA_PRIMEIRA, TipoEvento.PRACA_SEGUNDA, TipoEvento.PRACA_UNICA}
)

# Evento cancelado sai da agenda; suspenso e remarcado ficam, sinalizados: quem
# tinha aquele lote na mira precisa justamente saber que mudou.
STATUS_OCULTOS: frozenset[StatusEvento] = frozenset({StatusEvento.CANCELADO})


def categoria_do_lote(lote: Lote) -> str:
    if lote.natureza_bem is NaturezaBem.IMOVEL:
        if lote.zona_imovel is ZonaImovel.RURAL:
            return "IMOVEL_RURAL"
        if lote.zona_imovel is ZonaImovel.URBANA:
            return "IMOVEL_URBANO"
        return "IMOVEL_INDEFINIDO"
    if lote.natureza_bem is NaturezaBem.MOVEL:
        return "MOVEL"
    return "INDEFINIDO"


@dataclass(slots=True)
class ProcedenciaDiario:
    slug: str
    nome: str
    esfera: str
    publicado_em: datetime | None
    url: str | None
    confianca: float
    evidencia: str | None
    revisao_necessaria: bool


@dataclass(slots=True)
class ItemAgenda:
    lote_id: int
    titulo: str
    categoria: str
    categoria_rotulo: str
    natureza_bem: str
    zona_imovel: str
    tipo_bem: str
    esfera: str
    tipo_evento: str
    status_evento: str
    data_hora: datetime
    estimado: bool
    uf: str | None = None
    cidade: str | None = None
    comarca: str | None = None
    tribunal_sigla: str | None = None
    numero_processo: str | None = None
    leiloeiro: str | None = None
    valor_avaliacao: float | None = None
    valor_minimo: float | None = None
    # Procedência da classificação: sem isto a aba é uma afirmação sem prova.
    confianca_natureza: float = 0.0
    evidencia_natureza: str | None = None
    confianca_zona: float = 0.0
    evidencia_zona: str | None = None
    diario: ProcedenciaDiario | None = None


@dataclass(slots=True)
class ContagemCategoria:
    chave: str
    rotulo: str
    total: int


@dataclass(slots=True)
class DiaAgenda:
    data: str  # AAAA-MM-DD, no fuso de Brasília (é o fuso dos editais)
    total: int
    itens: list[ItemAgenda] = field(default_factory=list)


@dataclass(slots=True)
class Agenda:
    de: datetime
    ate: datetime
    total: int
    total_de_diario: int
    categorias: list[ContagemCategoria] = field(default_factory=list)
    dias: list[DiaAgenda] = field(default_factory=list)


@dataclass(slots=True)
class FiltroAgenda:
    de: datetime | None = None
    ate: datetime | None = None
    dias: int = 60
    ufs: list[str] = field(default_factory=list)
    esferas: list[EsferaJustica] = field(default_factory=list)
    categorias: list[str] = field(default_factory=list)
    somente_de_diario: bool = False
    incluir_prazos: bool = False
    limite: int = 500

    def janela(self, agora: datetime | None = None) -> tuple[datetime, datetime]:
        inicio = self.de or (agora or datetime.now(UTC))
        return inicio, self.ate or inicio + timedelta(days=self.dias)


def _valor(numero) -> float | None:
    return float(numero) if numero is not None else None


def _procedencia(lote: Lote) -> ProcedenciaDiario | None:
    """A publicação de diário mais antiga que originou este lote.

    A mais antiga, e não a mais recente, porque o que interessa mostrar é quando
    o leilão apareceu pela primeira vez em fonte oficial.
    """
    publicacoes = [p for p in lote.publicacoes if p.detectado_como_leilao]
    if not publicacoes:
        return None
    publicacao = min(
        publicacoes, key=lambda p: (p.data_publicacao or datetime.max.replace(tzinfo=UTC))
    )
    return ProcedenciaDiario(
        slug=publicacao.diario_slug,
        nome=publicacao.diario_nome,
        esfera=str(publicacao.esfera),
        publicado_em=publicacao.data_publicacao,
        url=publicacao.fonte_url,
        confianca=publicacao.confianca_deteccao,
        evidencia=publicacao.evidencia,
        revisao_necessaria=publicacao.revisao_necessaria,
    )


def _campo(lote: Lote, nome: str) -> tuple[float, str | None]:
    for campo in lote.campos:
        if campo.nome == nome:
            return campo.confianca, campo.evidencia
    return 0.0, None


def _item(evento: EventoCalendario) -> ItemAgenda:
    lote = evento.lote
    categoria = categoria_do_lote(lote)
    conf_nat, prova_nat = _campo(lote, "natureza_bem")
    conf_zona, prova_zona = _campo(lote, "zona_imovel")
    leiloeiro = lote.leilao.leiloeiro if lote.leilao else None
    return ItemAgenda(
        lote_id=lote.id,
        titulo=lote.titulo,
        categoria=categoria,
        categoria_rotulo=ROTULOS[categoria],
        natureza_bem=str(lote.natureza_bem),
        zona_imovel=str(lote.zona_imovel),
        tipo_bem=str(lote.tipo_bem),
        esfera=str(lote.esfera),
        tipo_evento=str(evento.tipo),
        status_evento=str(evento.status),
        data_hora=evento.data_hora,
        estimado=evento.estimado,
        uf=lote.uf,
        cidade=lote.cidade,
        comarca=lote.leilao.processo.comarca.nome
        if lote.leilao and lote.leilao.processo and lote.leilao.processo.comarca
        else None,
        tribunal_sigla=lote.leilao.tribunal.sigla
        if lote.leilao and lote.leilao.tribunal
        else None,
        numero_processo=lote.numero_processo,
        leiloeiro=leiloeiro.nome if leiloeiro else None,
        valor_avaliacao=_valor(lote.valor_avaliacao),
        valor_minimo=_valor(lote.valor_minimo_segunda or lote.valor_minimo_primeira),
        confianca_natureza=conf_nat,
        evidencia_natureza=prova_nat,
        confianca_zona=conf_zona,
        evidencia_zona=prova_zona,
        diario=_procedencia(lote),
    )


def _dia_local(quando: datetime) -> str:
    """Agrupa pelo dia de Brasília: um leilão às 21h de AL não é do dia seguinte."""
    local = para_local(quando) or quando
    return local.strftime("%Y-%m-%d")


def montar(
    sessao: Session, filtro: FiltroAgenda, agora: datetime | None = None
) -> Agenda:
    de, ate = filtro.janela(agora)
    tipos = None if filtro.incluir_prazos else EVENTOS_DE_PRACA

    consulta = (
        select(EventoCalendario)
        .where(EventoCalendario.data_hora >= de, EventoCalendario.data_hora <= ate)
        .order_by(EventoCalendario.data_hora)
        .options(
            selectinload(EventoCalendario.lote).selectinload(Lote.campos),
            selectinload(EventoCalendario.lote).selectinload(Lote.publicacoes),
            selectinload(EventoCalendario.lote)
            .selectinload(Lote.leilao)
            .selectinload(Leilao.leiloeiro),
        )
    )
    if tipos is not None:
        consulta = consulta.where(EventoCalendario.tipo.in_(tipos))

    itens: list[ItemAgenda] = []
    ufs = {u.upper() for u in filtro.ufs}
    esferas = {str(e) for e in filtro.esferas}
    categorias = set(filtro.categorias)
    for evento in sessao.scalars(consulta):
        if evento.status in STATUS_OCULTOS or evento.lote is None:
            continue
        item = _item(evento)
        if ufs and item.uf not in ufs:
            continue
        if esferas and item.esfera not in esferas:
            continue
        if categorias and item.categoria not in categorias:
            continue
        if filtro.somente_de_diario and item.diario is None:
            continue
        itens.append(item)
        if len(itens) >= filtro.limite:
            break

    # A contagem por categoria sai da MESMA lista já filtrada. Contar por
    # consulta separada faria o total das abas divergir do total mostrado --
    # o usuário veria "12 imóveis rurais" e a aba abriria com 9.
    contagem: dict[str, int] = {chave: 0 for chave, _ in CATEGORIAS}
    dias: dict[str, DiaAgenda] = {}
    for item in itens:
        contagem[item.categoria] = contagem.get(item.categoria, 0) + 1
        chave = _dia_local(item.data_hora)
        dia = dias.get(chave)
        if dia is None:
            dia = DiaAgenda(data=chave, total=0)
            dias[chave] = dia
        dia.itens.append(item)
        dia.total += 1

    return Agenda(
        de=de,
        ate=ate,
        total=len(itens),
        total_de_diario=sum(1 for i in itens if i.diario is not None),
        categorias=[
            ContagemCategoria(chave=chave, rotulo=rotulo, total=contagem.get(chave, 0))
            for chave, rotulo in CATEGORIAS
        ],
        dias=[dias[chave] for chave in sorted(dias)],
    )
