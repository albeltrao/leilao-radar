"""Rotas da API."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from radar.agenda import CATEGORIAS, FiltroAgenda, categoria_do_lote
from radar.agenda import montar as montar_agenda
from radar.api import conteudo, conversores, schemas
from radar.api.auth import (
    autenticar,
    criar_sessao,
    encerrar_sessao,
    registrar_usuario,
)
from radar.api.deps import SessaoDep, SettingsDep, UsuarioDep
from radar.calendario import ics
from radar.collectors.base import listar as listar_conectores
from radar.consultas import FiltroLotes, buscar
from radar.enums import (
    EsferaJustica,
    NaturezaBem,
    StatusLote,
    TipoBem,
    ZonaImovel,
)
from radar.market.analise import custo_total_estimado
from radar.models import (
    Alerta,
    EventoCalendario,
    ExecucaoColeta,
    Favorito,
    Leiloeiro,
    Lote,
    PublicacaoDiario,
    Usuario,
)

publico = APIRouter(prefix="/api", tags=["público"])
conta = APIRouter(prefix="/api", tags=["conta"])


# ---------------------------------------------------------------------------
# Saude e metadados
# ---------------------------------------------------------------------------


@publico.get("/saude")
def saude(sessao: SessaoDep) -> dict:
    return {
        "status": "ok",
        "lotes": sessao.scalar(select(func.count()).select_from(Lote)) or 0,
        "leiloeiros": sessao.scalar(select(func.count()).select_from(Leiloeiro)) or 0,
        "agora": datetime.now(UTC),
    }


@publico.get("/meta/glossario")
def glossario() -> dict:
    return {"passos": conteudo.PASSOS, "referencias": conteudo.REFERENCIAS}


@publico.get("/meta/facetas", response_model=schemas.FacetasResposta)
def facetas(sessao: SessaoDep) -> schemas.FacetasResposta:
    """Valores disponiveis para montar os filtros da UI sem chutar."""
    lotes = list(sessao.scalars(select(Lote)))
    cidades = Counter((lo.uf, lo.cidade) for lo in lotes if lo.cidade)
    tipos = Counter(str(lo.tipo_bem) for lo in lotes)
    estados = Counter(str(lo.status) for lo in lotes)
    categorias = Counter(categoria_do_lote(lo) for lo in lotes)
    esferas = Counter(str(lo.esfera) for lo in lotes)
    valores = [
        lo.valor_minimo_segunda or lo.valor_minimo_primeira
        for lo in lotes
        if (lo.valor_minimo_segunda or lo.valor_minimo_primeira)
    ]
    return schemas.FacetasResposta(
        ufs=sorted({lo.uf for lo in lotes if lo.uf}),
        cidades=[
            {"uf": uf, "cidade": cidade, "total": total}
            for (uf, cidade), total in sorted(cidades.items(), key=lambda x: -x[1])
        ],
        tipos_bem=[{"valor": t, "total": n} for t, n in tipos.items()],
        categorias_bem=[
            {"valor": chave, "rotulo": rotulo, "total": categorias.get(chave, 0)}
            for chave, rotulo in CATEGORIAS
        ],
        esferas=[{"valor": e, "total": n} for e, n in esferas.items()],
        status=[{"valor": s, "total": n} for s, n in estados.items()],
        leiloeiros=[
            schemas.LeiloeiroResumo.model_validate(le)
            for le in sessao.scalars(select(Leiloeiro).order_by(Leiloeiro.nome))
        ],
        faixa_valores={
            "minimo": min(valores) if valores else None,
            "maximo": max(valores) if valores else None,
        },
    )


@publico.get("/fontes", response_model=list[schemas.FonteSaude])
def fontes(sessao: SessaoDep) -> list[schemas.FonteSaude]:
    """Painel de saude das fontes (secao 5: observabilidade)."""
    limite = datetime.now(UTC) - timedelta(days=7)
    saidas: list[schemas.FonteSaude] = []
    for conector in listar_conectores():
        ultima = sessao.scalars(
            select(ExecucaoColeta)
            .where(ExecucaoColeta.fonte_slug == conector.slug)
            .order_by(ExecucaoColeta.iniciado_em.desc())
            .limit(1)
        ).first()
        recentes = list(
            sessao.scalars(
                select(ExecucaoColeta).where(
                    ExecucaoColeta.fonte_slug == conector.slug,
                    ExecucaoColeta.iniciado_em >= limite,
                )
            )
        )
        saidas.append(
            schemas.FonteSaude(
                slug=conector.slug,
                nome=conector.meta.nome,
                tipo=str(conector.meta.tipo),
                uf=conector.meta.uf,
                url_alvo=conector.meta.url_alvo,
                periodicidade_horas=conector.meta.periodicidade_horas,
                validado_ao_vivo=conector.meta.validado_ao_vivo,
                descricao=conector.meta.descricao,
                ultima_execucao_em=ultima.iniciado_em if ultima else None,
                ultimo_status=str(ultima.status) if ultima else None,
                ultimo_erro=ultima.erro if ultima else None,
                itens_ultima_coleta=ultima.itens_encontrados if ultima else None,
                duracao_ultima_s=ultima.duracao_s if ultima else None,
                execucoes_7d=len(recentes),
                falhas_7d=sum(1 for e in recentes if str(e.status) == "FALHA"),
            )
        )
    return saidas


@publico.get("/leiloeiros", response_model=list[schemas.LeiloeiroResumo])
def leiloeiros(
    sessao: SessaoDep, uf: str | None = None
) -> list[schemas.LeiloeiroResumo]:
    consulta = select(Leiloeiro).order_by(Leiloeiro.nome)
    if uf:
        consulta = consulta.where(Leiloeiro.uf == uf.upper())
    return [schemas.LeiloeiroResumo.model_validate(le) for le in sessao.scalars(consulta)]


# ---------------------------------------------------------------------------
# Lotes
# ---------------------------------------------------------------------------


def _filtro_da_query(
    uf, cidade, bairro, tipo_bem, status_lote, valor_minimo, valor_maximo,
    desconto_minimo, score_minimo, dias_ate_praca_max, leiloeiro_id,
    somente_desocupados, sem_onus, q, ordenar, pagina, tamanho,
    natureza_bem=None, zona_imovel=None, esfera=None,
) -> FiltroLotes:
    return FiltroLotes(
        uf=[u.upper() for u in (uf or [])],
        cidades=list(cidade or []),
        bairros=list(bairro or []),
        tipo_bem=[TipoBem(t) for t in (tipo_bem or [])],
        natureza_bem=[NaturezaBem(n) for n in (natureza_bem or [])],
        zona_imovel=[ZonaImovel(z) for z in (zona_imovel or [])],
        esfera=[EsferaJustica(e) for e in (esfera or [])],
        status=[StatusLote(s) for s in (status_lote or [])] or [StatusLote.ABERTO],
        valor_minimo=valor_minimo,
        valor_maximo=valor_maximo,
        desconto_minimo=desconto_minimo,
        score_minimo=score_minimo,
        dias_ate_praca_max=dias_ate_praca_max,
        leiloeiro_ids=list(leiloeiro_id or []),
        somente_desocupados=somente_desocupados,
        sem_onus=sem_onus,
        texto=q,
        ordenar=ordenar,
        pagina=pagina,
        tamanho=tamanho,
    )


@publico.get("/lotes", response_model=schemas.PaginaLotes)
def listar_lotes(
    sessao: SessaoDep,
    uf: list[str] | None = Query(default=None),
    cidade: list[str] | None = Query(default=None),
    bairro: list[str] | None = Query(default=None),
    tipo_bem: list[str] | None = Query(default=None),
    natureza_bem: list[str] | None = Query(default=None),
    zona_imovel: list[str] | None = Query(default=None),
    esfera: list[str] | None = Query(default=None),
    status_lote: list[str] | None = Query(default=None, alias="status"),
    valor_minimo: Decimal | None = None,
    valor_maximo: Decimal | None = None,
    desconto_minimo: float | None = None,
    score_minimo: float | None = None,
    dias_ate_praca_max: int | None = None,
    leiloeiro_id: list[int] | None = Query(default=None),
    somente_desocupados: bool = False,
    sem_onus: bool = False,
    q: str | None = None,
    ordenar: str = "score",
    pagina: int = Query(default=1, ge=1),
    tamanho: int = Query(default=24, ge=1, le=100),
) -> schemas.PaginaLotes:
    filtro = _filtro_da_query(
        uf, cidade, bairro, tipo_bem, status_lote, valor_minimo, valor_maximo,
        desconto_minimo, score_minimo, dias_ate_praca_max, leiloeiro_id,
        somente_desocupados, sem_onus, q, ordenar, pagina, tamanho,
        natureza_bem=natureza_bem, zona_imovel=zona_imovel, esfera=esfera,
    )
    itens, total = buscar(sessao, filtro)
    return schemas.PaginaLotes(
        itens=[conversores.para_resumo(lo) for lo in itens],
        total=total,
        pagina=filtro.pagina,
        tamanho=filtro.tamanho,
        paginas=max(1, -(-total // filtro.tamanho)),
    )


def _obter_lote(sessao, lote_id: int) -> Lote:
    lote = sessao.get(Lote, lote_id)
    if lote is None:
        raise HTTPException(status_code=404, detail="lote não encontrado")
    return lote


@publico.get("/lotes/comparar", response_model=list[schemas.LoteDetalhe])
def comparar(
    sessao: SessaoDep, ids: str = Query(description="IDs separados por vírgula, até 3")
) -> list[schemas.LoteDetalhe]:
    """Modo comparacao da secao 10: 2 a 3 lotes lado a lado."""
    try:
        identificadores = [int(i) for i in ids.split(",") if i.strip()][:3]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ids inválidos") from exc
    if len(identificadores) < 2:
        raise HTTPException(status_code=400, detail="informe ao menos 2 lotes")
    return [conversores.para_detalhe(_obter_lote(sessao, i)) for i in identificadores]


@publico.get("/lotes/{lote_id}", response_model=schemas.LoteDetalhe)
def detalhar_lote(sessao: SessaoDep, lote_id: int) -> schemas.LoteDetalhe:
    return conversores.para_detalhe(_obter_lote(sessao, lote_id))


@publico.get("/lotes/{lote_id}/simulacao", response_model=schemas.SimulacaoResposta)
def simular(
    sessao: SessaoDep, lote_id: int, lance: Decimal | None = None
) -> schemas.SimulacaoResposta:
    lote = _obter_lote(sessao, lote_id)
    total, detalhes = custo_total_estimado(lote, lance)
    return schemas.SimulacaoResposta(
        lance_base=lance or lote.valor_minimo_segunda or lote.valor_minimo_primeira,
        custo_total_estimado=total,
        detalhes=detalhes,
    )


@publico.get("/geo/lotes")
def geojson(
    sessao: SessaoDep,
    uf: list[str] | None = Query(default=None),
    tipo_bem: list[str] | None = Query(default=None),
) -> dict:
    """GeoJSON para o mapa da secao 10."""
    filtro = FiltroLotes(
        uf=[u.upper() for u in (uf or [])],
        tipo_bem=[TipoBem(t) for t in (tipo_bem or [])],
        tamanho=2000,
    )
    lotes, _ = buscar(sessao, filtro)
    feicoes = []
    for lote in lotes:
        if lote.latitude is None or lote.longitude is None:
            continue
        data, ordem = conversores.proxima_praca(lote)
        feicoes.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lote.longitude, lote.latitude]},
                "properties": {
                    "id": lote.id,
                    "titulo": lote.titulo,
                    "cidade": lote.cidade,
                    "uf": lote.uf,
                    "tipo_bem": str(lote.tipo_bem),
                    "valor_minimo": float(
                        lote.valor_minimo_segunda or lote.valor_minimo_primeira or 0
                    ),
                    "score": lote.score.total if lote.score else None,
                    "faixa": lote.score.faixa if lote.score else None,
                    "desconto": lote.score.desconto_destaque if lote.score else None,
                    "proxima_praca": data.isoformat() if data else None,
                    "proxima_praca_ordem": ordem,
                    # A UI desenha area, nao pino exato, quando a precisao e municipal.
                    "precisao": lote.geocodificacao_precisao,
                },
            }
        )
    return {"type": "FeatureCollection", "features": feicoes}


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------


def _eventos(sessao, de, ate, uf, tipo_bem, leiloeiro_id, limite=1000):
    consulta = select(EventoCalendario).order_by(EventoCalendario.data_hora)
    if de:
        consulta = consulta.where(EventoCalendario.data_hora >= de)
    if ate:
        consulta = consulta.where(EventoCalendario.data_hora <= ate)
    eventos = list(sessao.scalars(consulta.limit(limite)))
    if uf:
        alvos = {u.upper() for u in uf}
        eventos = [e for e in eventos if e.lote.uf in alvos]
    if tipo_bem:
        alvos = {TipoBem(t) for t in tipo_bem}
        eventos = [e for e in eventos if e.lote.tipo_bem in alvos]
    if leiloeiro_id:
        alvos = set(leiloeiro_id)
        eventos = [
            e for e in eventos
            if e.lote.leilao and e.lote.leilao.leiloeiro_id in alvos
        ]
    return eventos


@publico.get("/calendario", response_model=list[schemas.EventoResposta])
def calendario(
    sessao: SessaoDep,
    de: datetime | None = None,
    ate: datetime | None = None,
    uf: list[str] | None = Query(default=None),
    tipo_bem: list[str] | None = Query(default=None),
    leiloeiro_id: list[int] | None = Query(default=None),
) -> list[schemas.EventoResposta]:
    eventos = _eventos(sessao, de, ate, uf, tipo_bem, leiloeiro_id)
    return [schemas.EventoResposta.model_validate(e) for e in eventos]


@publico.get("/calendario.ics")
def calendario_ics(
    sessao: SessaoDep,
    de: datetime | None = None,
    ate: datetime | None = None,
    uf: list[str] | None = Query(default=None),
    tipo_bem: list[str] | None = Query(default=None),
    leiloeiro_id: list[int] | None = Query(default=None),
) -> Response:
    eventos = _eventos(sessao, de, ate, uf, tipo_bem, leiloeiro_id)
    return Response(
        content=ics.gerar(eventos),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="radar-leilao.ics"'},
    )


@publico.get("/lotes/{lote_id}/calendario.ics")
def lote_ics(sessao: SessaoDep, lote_id: int) -> Response:
    lote = _obter_lote(sessao, lote_id)
    return Response(
        content=ics.gerar(lote.eventos, nome=lote.titulo),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="lote-{lote_id}.ics"'},
    )


@publico.get(
    "/lotes/{lote_id}/historico", response_model=list[schemas.MudancaEventoResposta]
)
def historico(sessao: SessaoDep, lote_id: int) -> list[schemas.MudancaEventoResposta]:
    """Remarcacoes e suspensoes: "foi adiado de X para Y" (secao 9)."""
    lote = _obter_lote(sessao, lote_id)
    mudancas = [h for evento in lote.eventos for h in evento.historico]
    mudancas.sort(key=lambda h: h.registrado_em, reverse=True)
    return [schemas.MudancaEventoResposta.model_validate(h) for h in mudancas]


# ---------------------------------------------------------------------------
# Agenda e Diario da Justica
# ---------------------------------------------------------------------------


@publico.get("/agenda", response_model=schemas.AgendaResposta)
def agenda(
    sessao: SessaoDep,
    de: datetime | None = None,
    ate: datetime | None = None,
    dias: int = Query(default=60, ge=1, le=365),
    uf: list[str] | None = Query(default=None),
    esfera: list[str] | None = Query(default=None),
    categoria: list[str] | None = Query(default=None),
    somente_de_diario: bool = False,
    incluir_prazos: bool = False,
    limite: int = Query(default=500, ge=1, le=2000),
) -> schemas.AgendaResposta:
    """Leilões em ordem cronológica, com a contagem por tipo de bem.

    Um único endpoint para os dois recortes de propósito: se a tela pedisse a
    lista de um lado e as contagens de outro, os dois números divergiriam na
    primeira coleta que rodasse entre as duas requisições.
    """
    filtro = FiltroAgenda(
        de=de,
        ate=ate,
        dias=dias,
        ufs=[u.upper() for u in (uf or [])],
        esferas=[EsferaJustica(e) for e in (esfera or [])],
        categorias=list(categoria or []),
        somente_de_diario=somente_de_diario,
        incluir_prazos=incluir_prazos,
        limite=limite,
    )
    return schemas.AgendaResposta.model_validate(
        montar_agenda(sessao, filtro), from_attributes=True
    )


@publico.get("/agenda.ics")
def agenda_ics(
    sessao: SessaoDep,
    de: datetime | None = None,
    ate: datetime | None = None,
    dias: int = Query(default=60, ge=1, le=365),
    uf: list[str] | None = Query(default=None),
    esfera: list[str] | None = Query(default=None),
    categoria: list[str] | None = Query(default=None),
) -> Response:
    """A mesma agenda em .ics -- inclusive filtrada por categoria de bem."""
    filtro = FiltroAgenda(
        de=de,
        ate=ate,
        dias=dias,
        ufs=[u.upper() for u in (uf or [])],
        esferas=[EsferaJustica(e) for e in (esfera or [])],
        categorias=list(categoria or []),
    )
    agenda_montada = montar_agenda(sessao, filtro)
    # Exatamente os eventos que a tela mostrou -- nem o lote inteiro, nem a
    # janela toda. Um .ics com eventos que a lista nao trazia faria o usuario
    # duvidar dos dois.
    mostrados = {
        (item.lote_id, item.tipo_evento)
        for dia in agenda_montada.dias
        for item in dia.itens
    }
    ids = {lote_id for lote_id, _ in mostrados}
    eventos = [
        e
        for e in sessao.scalars(
            select(EventoCalendario)
            .where(EventoCalendario.lote_id.in_(ids or {0}))
            .order_by(EventoCalendario.data_hora)
        )
        if (e.lote_id, str(e.tipo)) in mostrados
    ]
    return Response(
        content=ics.gerar(eventos, nome="Radar Leilão — agenda"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="radar-agenda.ics"'},
    )


@publico.get("/diarios/publicacoes", response_model=schemas.PaginaPublicacoes)
def publicacoes(
    sessao: SessaoDep,
    diario: list[str] | None = Query(default=None),
    uf: list[str] | None = Query(default=None),
    esfera: list[str] | None = Query(default=None),
    somente_detectadas: bool = True,
    revisao_necessaria: bool | None = None,
    de: datetime | None = None,
    ate: datetime | None = None,
    pagina: int = Query(default=1, ge=1),
    tamanho: int = Query(default=50, ge=1, le=200),
) -> schemas.PaginaPublicacoes:
    """O que foi lido do Diário da Justiça, detectado como leilão ou não.

    As não detectadas ficam acessíveis de propósito: é o único jeito de alguém
    conferir se o limiar de detecção está engolindo leilão de verdade.
    """
    consulta = select(PublicacaoDiario).order_by(
        PublicacaoDiario.data_publicacao.desc(), PublicacaoDiario.id.desc()
    )
    if diario:
        consulta = consulta.where(PublicacaoDiario.diario_slug.in_(diario))
    if uf:
        consulta = consulta.where(PublicacaoDiario.uf.in_([u.upper() for u in uf]))
    if esfera:
        consulta = consulta.where(PublicacaoDiario.esfera.in_(esfera))
    if somente_detectadas:
        consulta = consulta.where(PublicacaoDiario.detectado_como_leilao.is_(True))
    if revisao_necessaria is not None:
        consulta = consulta.where(
            PublicacaoDiario.revisao_necessaria.is_(revisao_necessaria)
        )
    if de:
        consulta = consulta.where(PublicacaoDiario.data_publicacao >= de)
    if ate:
        consulta = consulta.where(PublicacaoDiario.data_publicacao <= ate)

    todas = list(sessao.scalars(consulta))
    inicio = (pagina - 1) * tamanho
    return schemas.PaginaPublicacoes(
        itens=[
            schemas.PublicacaoResposta.model_validate(p)
            for p in todas[inicio : inicio + tamanho]
        ],
        total=len(todas),
        detectadas=sum(1 for p in todas if p.detectado_como_leilao),
        pagina=pagina,
        tamanho=tamanho,
    )


# ---------------------------------------------------------------------------
# Conta
# ---------------------------------------------------------------------------


@conta.post("/auth/registrar", response_model=schemas.TokenResposta, status_code=201)
def registrar(
    sessao: SessaoDep, settings: SettingsDep, dados: schemas.RegistroEntrada
) -> schemas.TokenResposta:
    existente = sessao.scalar(
        select(Usuario).where(Usuario.email == dados.email.lower())
    )
    if existente is not None:
        raise HTTPException(status_code=409, detail="e-mail já cadastrado")
    usuario = registrar_usuario(sessao, dados.email, dados.senha, dados.nome)
    token = criar_sessao(sessao, usuario, settings)
    return schemas.TokenResposta(
        token=token,
        expira_em_horas=settings.sessao_duracao_horas,
        usuario=schemas.UsuarioResposta.model_validate(usuario),
    )


@conta.post("/auth/entrar", response_model=schemas.TokenResposta)
def entrar(
    sessao: SessaoDep, settings: SettingsDep, dados: schemas.LoginEntrada
) -> schemas.TokenResposta:
    usuario = autenticar(sessao, dados.email, dados.senha)
    if usuario is None:
        raise HTTPException(status_code=401, detail="e-mail ou senha inválidos")
    token = criar_sessao(sessao, usuario, settings)
    return schemas.TokenResposta(
        token=token,
        expira_em_horas=settings.sessao_duracao_horas,
        usuario=schemas.UsuarioResposta.model_validate(usuario),
    )


@conta.post("/auth/sair", status_code=204)
def sair(sessao: SessaoDep, usuario: UsuarioDep, authorization: str = "") -> Response:
    partes = authorization.split(None, 1)
    if len(partes) == 2:
        encerrar_sessao(sessao, partes[1].strip())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conta.get("/auth/eu", response_model=schemas.UsuarioResposta)
def eu(usuario: UsuarioDep) -> schemas.UsuarioResposta:
    return schemas.UsuarioResposta.model_validate(usuario)


@conta.get("/alertas", response_model=list[schemas.AlertaResposta])
def listar_alertas(sessao: SessaoDep, usuario: UsuarioDep) -> list[schemas.AlertaResposta]:
    consulta = select(Alerta).where(Alerta.usuario_id == usuario.id)
    return [schemas.AlertaResposta.model_validate(a) for a in sessao.scalars(consulta)]


@conta.post("/alertas", response_model=schemas.AlertaResposta, status_code=201)
def criar_alerta(
    sessao: SessaoDep, usuario: UsuarioDep, dados: schemas.AlertaEntrada
) -> schemas.AlertaResposta:
    # Valida os criterios agora: filtro salvo que nao casa com nada nunca avisa
    # o usuario, e ele so descobre meses depois.
    FiltroLotes.de_criterios(dados.criterios)
    alerta = Alerta(
        usuario_id=usuario.id,
        nome=dados.nome,
        criterios=dados.criterios,
        canal=dados.canal,
        ativo=dados.ativo,
    )
    sessao.add(alerta)
    sessao.flush()
    return schemas.AlertaResposta.model_validate(alerta)


@conta.patch("/alertas/{alerta_id}", response_model=schemas.AlertaResposta)
def atualizar_alerta(
    sessao: SessaoDep, usuario: UsuarioDep, alerta_id: int, dados: schemas.AlertaEntrada
) -> schemas.AlertaResposta:
    alerta = sessao.get(Alerta, alerta_id)
    if alerta is None or alerta.usuario_id != usuario.id:
        raise HTTPException(status_code=404, detail="alerta não encontrado")
    FiltroLotes.de_criterios(dados.criterios)
    alerta.nome = dados.nome
    alerta.criterios = dados.criterios
    alerta.canal = dados.canal
    alerta.ativo = dados.ativo
    return schemas.AlertaResposta.model_validate(alerta)


@conta.delete("/alertas/{alerta_id}", status_code=204)
def remover_alerta(sessao: SessaoDep, usuario: UsuarioDep, alerta_id: int) -> Response:
    alerta = sessao.get(Alerta, alerta_id)
    if alerta is None or alerta.usuario_id != usuario.id:
        raise HTTPException(status_code=404, detail="alerta não encontrado")
    sessao.delete(alerta)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conta.get("/alertas/{alerta_id}/previa", response_model=schemas.PaginaLotes)
def previa_alerta(
    sessao: SessaoDep, usuario: UsuarioDep, alerta_id: int
) -> schemas.PaginaLotes:
    """O que este filtro traria hoje -- para o usuario conferir antes de salvar."""
    alerta = sessao.get(Alerta, alerta_id)
    if alerta is None or alerta.usuario_id != usuario.id:
        raise HTTPException(status_code=404, detail="alerta não encontrado")
    filtro = FiltroLotes.de_criterios(alerta.criterios)
    itens, total = buscar(sessao, filtro)
    return schemas.PaginaLotes(
        itens=[conversores.para_resumo(lo) for lo in itens],
        total=total,
        pagina=1,
        tamanho=filtro.tamanho,
        paginas=max(1, -(-total // filtro.tamanho)),
    )


@conta.get("/favoritos", response_model=list[schemas.LoteResumo])
def listar_favoritos(sessao: SessaoDep, usuario: UsuarioDep) -> list[schemas.LoteResumo]:
    favoritos = sessao.scalars(
        select(Favorito).where(Favorito.usuario_id == usuario.id)
    )
    return [conversores.para_resumo(f.lote) for f in favoritos]


@conta.post("/favoritos/{lote_id}", response_model=schemas.FavoritoResposta, status_code=201)
def favoritar(
    sessao: SessaoDep, usuario: UsuarioDep, lote_id: int
) -> schemas.FavoritoResposta:
    _obter_lote(sessao, lote_id)
    existente = sessao.scalar(
        select(Favorito).where(
            Favorito.usuario_id == usuario.id, Favorito.lote_id == lote_id
        )
    )
    if existente is not None:
        return schemas.FavoritoResposta.model_validate(existente)
    favorito = Favorito(usuario_id=usuario.id, lote_id=lote_id)
    sessao.add(favorito)
    sessao.flush()
    return schemas.FavoritoResposta.model_validate(favorito)


@conta.delete("/favoritos/{lote_id}", status_code=204)
def desfavoritar(sessao: SessaoDep, usuario: UsuarioDep, lote_id: int) -> Response:
    favorito = sessao.scalar(
        select(Favorito).where(
            Favorito.usuario_id == usuario.id, Favorito.lote_id == lote_id
        )
    )
    if favorito is not None:
        sessao.delete(favorito)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
