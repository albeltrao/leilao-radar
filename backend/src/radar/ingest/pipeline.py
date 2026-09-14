"""Orquestracao: coletar -> enfileirar -> normalizar -> deduplicar -> persistir.

Cada execucao de conector vira uma linha em ``execucao_coleta``, que alimenta o
painel de saude das fontes (secao 5: observabilidade). Uma fonte que volta zero
itens ou quebra de layout aparece la, em vez de falhar em silencio.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.calendario.eventos import sincronizar_eventos
from radar.collectors.base import Conector, listar, obter
from radar.collectors.dto import LeiloeiroBruto, LoteBruto, PracaBruta, PublicacaoBruta
from radar.collectors.http import ErroColeta, EstruturaInesperada, Fetcher, RobotsBloqueado
from radar.config import Settings, get_settings
from radar.diarios.deteccao import (
    LeilaoDetectado,
    achados_da_deteccao,
    detectar_leilao,
    para_lote_bruto,
    uf_da_secao_judiciaria,
)
from radar.enums import (
    EsferaJustica,
    MetodoExtracao,
    StatusColeta,
    StatusLeiloeiro,
    StatusPraca,
    TipoDocumento,
    TipoFonte,
)
from radar.ingest.dedup import localizar_existente, mesclar
from radar.ingest.fila import (
    TOPICO_LEILOEIROS,
    TOPICO_LOTES,
    TOPICO_PUBLICACOES,
    FilaIngestao,
    Mensagem,
    criar_fila,
)
from radar.ingest.geocode import Geocodificador, GeocodificadorMunicipio
from radar.ingest.normalizador import UF_POR_TRIBUNAL, normalizar
from radar.models import (
    CampoExtraido,
    Comarca,
    Documento,
    ExecucaoColeta,
    Leilao,
    Leiloeiro,
    Lote,
    Praca,
    Processo,
    PublicacaoDiario,
    Tribunal,
)
from radar.normalizacao import limpar_espacos, normalizar_texto, remover_cpf, slugify

logger = logging.getLogger(__name__)

PRIORIDADE_FONTE = {
    TipoFonte.TRIBUNAL: 3,
    # O diario e publicacao oficial do proprio juizo: manda sobre processo,
    # comarca e vara, igual ao portal do tribunal.
    TipoFonte.DIARIO_OFICIAL: 3,
    TipoFonte.PROCESSUAL: 2,
    TipoFonte.LEILOEIRO: 1,
    TipoFonte.JUNTA_COMERCIAL: 1,
    TipoFonte.MERCADO: 0,
}


@dataclass(slots=True)
class EstatisticasIngestao:
    encontrados: int = 0
    novos: int = 0
    atualizados: int = 0
    inalterados: int = 0
    erros: int = 0
    remarcacoes: int = 0
    publicacoes_lidas: int = 0
    publicacoes_com_leilao: int = 0
    avisos: list[str] = field(default_factory=list)

    def somar(self, outro: EstatisticasIngestao) -> None:
        self.encontrados += outro.encontrados
        self.novos += outro.novos
        self.atualizados += outro.atualizados
        self.inalterados += outro.inalterados
        self.erros += outro.erros
        self.remarcacoes += outro.remarcacoes
        self.publicacoes_lidas += outro.publicacoes_lidas
        self.publicacoes_com_leilao += outro.publicacoes_com_leilao
        self.avisos.extend(outro.avisos)


# ---------------------------------------------------------------------------
# Etapa 1: coleta -> fila
# ---------------------------------------------------------------------------


def executar_coleta(
    conector: Conector | str,
    fetcher: Fetcher,
    fila: FilaIngestao,
    sessao: Session,
    *,
    incluir_nao_validados: bool = False,
) -> ExecucaoColeta:
    if isinstance(conector, str):
        conector = obter(conector)

    execucao = ExecucaoColeta(
        fonte_slug=conector.slug,
        tipo_fonte=conector.meta.tipo,
        status=StatusColeta.EM_ANDAMENTO,
        iniciado_em=datetime.now(UTC),
    )
    sessao.add(execucao)
    sessao.flush()
    inicio = time.monotonic()

    if not conector.meta.validado_ao_vivo and not incluir_nao_validados:
        execucao.status = StatusColeta.BLOQUEADA
        execucao.erro = (
            "conector ainda nao validado ao vivo; use --incluir-nao-validados para forcar"
        )
        _finalizar(execucao, fetcher, inicio)
        return execucao

    if "PREENCHER" in conector.meta.url_alvo:
        execucao.status = StatusColeta.BLOQUEADA
        execucao.erro = "perfil sem URL configurada (vaga a preencher no YAML)"
        _finalizar(execucao, fetcher, inicio)
        return execucao

    try:
        resultado = conector.coletar(fetcher)
    except RobotsBloqueado as exc:
        execucao.status = StatusColeta.BLOQUEADA
        execucao.erro = str(exc)
        logger.warning("%s bloqueada por robots.txt: %s", conector.slug, exc)
    except EstruturaInesperada as exc:
        execucao.status = StatusColeta.FALHA
        execucao.erro = f"estrutura inesperada: {exc}"
        execucao.detalhe = {"provavel_causa": "mudanca de layout na fonte"}
        logger.error("%s: %s", conector.slug, exc)
    except ErroColeta as exc:
        execucao.status = StatusColeta.FALHA
        execucao.erro = str(exc)
        logger.error("%s falhou: %s", conector.slug, exc)
    else:
        for lote in resultado.lotes:
            fila.publicar(Mensagem(TOPICO_LOTES, _serializar_lote(lote)))
        for leiloeiro in resultado.leiloeiros:
            fila.publicar(Mensagem(TOPICO_LEILOEIROS, _serializar_leiloeiro(leiloeiro)))
        for publicacao in resultado.publicacoes:
            fila.publicar(Mensagem(TOPICO_PUBLICACOES, _serializar_publicacao(publicacao)))

        execucao.itens_encontrados = (
            len(resultado.lotes) + len(resultado.leiloeiros) + len(resultado.publicacoes)
        )
        execucao.status = (
            StatusColeta.PARCIAL if resultado.avisos else StatusColeta.SUCESSO
        )
        execucao.detalhe = {
            "paginas": resultado.paginas_visitadas,
            "lotes": len(resultado.lotes),
            "leiloeiros": len(resultado.leiloeiros),
            "publicacoes": len(resultado.publicacoes),
            "avisos": resultado.avisos[:20],
        }

    _finalizar(execucao, fetcher, inicio)
    return execucao


def _finalizar(execucao: ExecucaoColeta, fetcher: Fetcher, inicio: float) -> None:
    execucao.finalizado_em = datetime.now(UTC)
    execucao.duracao_s = round(time.monotonic() - inicio, 3)
    execucao.requisicoes_http = fetcher.stats.requisicoes


def _serializar_lote(lote: LoteBruto) -> dict:
    dados = asdict(lote)
    dados["tipo_bem"] = str(lote.tipo_bem)
    dados["status"] = str(lote.status)
    dados["modalidade"] = str(lote.modalidade)
    for praca in dados["pracas"]:
        if praca["data_hora"] is not None:
            praca["data_hora"] = praca["data_hora"].isoformat()
    for doc in dados["documentos"]:
        doc["tipo"] = str(doc["tipo"])
    return dados


def _serializar_leiloeiro(leiloeiro: LeiloeiroBruto) -> dict:
    dados = asdict(leiloeiro)
    dados["status"] = str(leiloeiro.status)
    dados["junta"] = str(leiloeiro.junta) if leiloeiro.junta else None
    return dados


def _serializar_publicacao(publicacao: PublicacaoBruta) -> dict:
    dados = asdict(publicacao)
    dados["esfera"] = str(publicacao.esfera)
    for campo in ("data_publicacao", "data_divulgacao"):
        if dados[campo] is not None:
            dados[campo] = dados[campo].isoformat()
    return dados


def _desserializar_publicacao(dados: dict) -> PublicacaoBruta:
    dados = dict(dados)
    dados["esfera"] = EsferaJustica(dados.get("esfera") or EsferaJustica.DESCONHECIDA)
    for campo in ("data_publicacao", "data_divulgacao"):
        if dados.get(campo):
            dados[campo] = datetime.fromisoformat(dados[campo])
    return PublicacaoBruta(**dados)


def _desserializar_lote(dados: dict) -> LoteBruto:
    from decimal import Decimal

    from radar.collectors.dto import DocumentoBruto
    from radar.enums import ModalidadeLeilao, StatusLote, TipoBem

    dados = dict(dados)
    dados["tipo_bem"] = TipoBem(dados["tipo_bem"])
    dados["status"] = StatusLote(dados["status"])
    dados["modalidade"] = ModalidadeLeilao(dados["modalidade"])
    for campo in (
        "valor_avaliacao", "comissao_percentual", "area_total_m2",
    ):
        if dados.get(campo) is not None:
            dados[campo] = Decimal(str(dados[campo]))
    dados["pracas"] = [
        PracaBruta(
            ordem=p["ordem"],
            data_hora=datetime.fromisoformat(p["data_hora"]) if p["data_hora"] else None,
            percentual_minimo=(
                Decimal(str(p["percentual_minimo"]))
                if p["percentual_minimo"] is not None
                else None
            ),
            valor_minimo=(
                Decimal(str(p["valor_minimo"])) if p["valor_minimo"] is not None else None
            ),
        )
        for p in dados.get("pracas", [])
    ]
    dados["documentos"] = [
        DocumentoBruto(url=d["url"], tipo=TipoDocumento(d["tipo"]), titulo=d.get("titulo"))
        for d in dados.get("documentos", [])
    ]
    return LoteBruto(**dados)


# ---------------------------------------------------------------------------
# Etapa 2: fila -> banco
# ---------------------------------------------------------------------------


def processar_fila(
    fila: FilaIngestao,
    sessao: Session,
    geocodificador: Geocodificador | None = None,
    settings: Settings | None = None,
    limite: int = 500,
) -> EstatisticasIngestao:
    settings = settings or get_settings()
    geocodificador = geocodificador or GeocodificadorMunicipio()
    stats = EstatisticasIngestao()

    for mensagem in fila.consumir(TOPICO_LEILOEIROS, limite=limite):
        try:
            _, criado = persistir_leiloeiro(sessao, mensagem.payload)
            stats.encontrados += 1
            stats.novos += int(criado)
            stats.atualizados += int(not criado)
            fila.confirmar(mensagem)
        except Exception as exc:  # uma linha ruim nao pode derrubar a coleta toda
            stats.erros += 1
            stats.avisos.append(f"leiloeiro: {exc}")
            logger.exception("falha ao persistir leiloeiro")

    for mensagem in fila.consumir(TOPICO_PUBLICACOES, limite=limite):
        try:
            resumo = persistir_publicacao(
                sessao, mensagem.payload, settings, geocodificador
            )
            stats.publicacoes_lidas += 1
            if resumo.virou_lote:
                stats.publicacoes_com_leilao += 1
                stats.encontrados += 1
                stats.novos += int(resumo.criado)
                stats.atualizados += int(not resumo.criado)
                stats.remarcacoes += resumo.remarcacoes
            fila.confirmar(mensagem)
        except Exception as exc:
            stats.erros += 1
            stats.avisos.append(f"publicacao: {exc}")
            logger.exception("falha ao persistir publicacao de diario")

    for mensagem in fila.consumir(TOPICO_LOTES, limite=limite):
        try:
            bruto = _desserializar_lote(mensagem.payload)
            norm = normalizar(bruto, geocodificador)
            _, criado, alteracoes, remarcacoes = persistir_lote(sessao, norm, settings)
            stats.encontrados += 1
            if criado:
                stats.novos += 1
            elif alteracoes:
                stats.atualizados += 1
            else:
                stats.inalterados += 1
            stats.remarcacoes += remarcacoes
            stats.avisos.extend(norm.avisos)
            fila.confirmar(mensagem)
        except Exception as exc:
            stats.erros += 1
            stats.avisos.append(f"lote: {exc}")
            logger.exception("falha ao persistir lote")

    sessao.flush()
    return stats


def persistir_leiloeiro(sessao: Session, dados: dict) -> tuple[Leiloeiro, bool]:
    from radar.enums import JuntaComercial

    nome = limpar_espacos(dados["nome"])
    normalizado = normalizar_texto(nome)
    junta = JuntaComercial(dados["junta"]) if dados.get("junta") else None
    matricula = dados.get("matricula")

    consulta = select(Leiloeiro).where(Leiloeiro.nome_normalizado == normalizado)
    if matricula:
        consulta = select(Leiloeiro).where(
            (Leiloeiro.nome_normalizado == normalizado)
            | ((Leiloeiro.matricula == matricula) & (Leiloeiro.junta == junta))
        )
    existente = sessao.scalars(consulta).first()

    if existente is None:
        leiloeiro = Leiloeiro(
            nome=nome,
            nome_normalizado=normalizado,
            matricula=matricula,
            junta=junta,
            uf=dados["uf"],
            status=StatusLeiloeiro(dados["status"]),
            site_url=dados.get("site_url"),
            email=dados.get("email"),
            telefone=dados.get("telefone"),
            comarcas_atuacao=dados.get("comarcas") or [],
            credenciamentos={},
            fonte_slug=dados["fonte_slug"],
            fonte_url=dados["fonte_url"],
            verificado_em=datetime.now(UTC),
        )
        sessao.add(leiloeiro)
        sessao.flush()
        return leiloeiro, True

    # Atualiza sem apagar: a Junta e a Corregedoria trazem campos diferentes.
    for campo, valor in (
        ("matricula", matricula),
        ("site_url", dados.get("site_url")),
        ("email", dados.get("email")),
        ("telefone", dados.get("telefone")),
    ):
        if valor and not getattr(existente, campo):
            setattr(existente, campo, valor)
    if junta and not existente.junta:
        existente.junta = junta
    if dados.get("status") and dados["status"] != str(StatusLeiloeiro.DESCONHECIDO):
        existente.status = StatusLeiloeiro(dados["status"])
    novas = [c for c in (dados.get("comarcas") or []) if c not in (existente.comarcas_atuacao or [])]
    if novas:
        existente.comarcas_atuacao = list(existente.comarcas_atuacao or []) + novas

    # O credenciamento vem da corregedoria (fonte tipo TRIBUNAL).
    fonte = dados["fonte_slug"]
    if fonte.startswith("tj"):
        sigla = fonte.split("-")[0].upper()
        credenciamentos = dict(existente.credenciamentos or {})
        credenciamentos[sigla] = True
        existente.credenciamentos = credenciamentos

    existente.verificado_em = datetime.now(UTC)
    return existente, False


def _obter_tribunal(sessao: Session, sigla: str | None) -> Tribunal | None:
    if not sigla:
        return None
    tribunal = sessao.scalar(select(Tribunal).where(Tribunal.sigla == sigla))
    if tribunal is None:
        tribunal = Tribunal(
            sigla=sigla,
            nome=f"Tribunal de Justica ({sigla})",
            uf=UF_POR_TRIBUNAL.get(sigla, ""),
        )
        sessao.add(tribunal)
        sessao.flush()
    return tribunal


def _obter_comarca(
    sessao: Session, tribunal: Tribunal | None, nome: str | None
) -> Comarca | None:
    if tribunal is None or not nome:
        return None
    slug = slugify(nome)
    comarca = sessao.scalar(
        select(Comarca).where(Comarca.tribunal_id == tribunal.id, Comarca.slug == slug)
    )
    if comarca is None:
        comarca = Comarca(tribunal_id=tribunal.id, nome=nome, slug=slug, uf=tribunal.uf)
        sessao.add(comarca)
        sessao.flush()
    return comarca


def _obter_processo(sessao: Session, norm, tribunal, comarca) -> Processo | None:
    if not norm.processo_valido or not norm.numero_processo:
        return None
    processo = sessao.scalar(
        select(Processo).where(Processo.numero_cnj == norm.numero_processo)
    )
    if processo is None:
        processo = Processo(
            numero_cnj=norm.numero_processo,
            tribunal_id=tribunal.id if tribunal else None,
            comarca_id=comarca.id if comarca else None,
            vara=norm.bruto.vara,
        )
        sessao.add(processo)
        sessao.flush()
    elif comarca and processo.comarca_id is None:
        processo.comarca_id = comarca.id
    return processo


def _obter_leiloeiro(sessao: Session, nome: str | None, uf: str | None) -> Leiloeiro | None:
    if not nome:
        return None
    normalizado = normalizar_texto(nome)
    leiloeiro = sessao.scalar(
        select(Leiloeiro).where(Leiloeiro.nome_normalizado == normalizado)
    )
    if leiloeiro is None:
        leiloeiro = Leiloeiro(
            nome=limpar_espacos(nome),
            nome_normalizado=normalizado,
            uf=uf or "",
            status=StatusLeiloeiro.DESCONHECIDO,
        )
        sessao.add(leiloeiro)
        sessao.flush()
    return leiloeiro


def persistir_lote(
    sessao: Session, norm, settings: Settings | None = None
) -> tuple[Lote, bool, list[str], int]:
    """Grava (ou atualiza) o lote e tudo que ele pendura. Idempotente."""
    settings = settings or get_settings()
    bruto = norm.bruto

    tribunal = _obter_tribunal(sessao, norm.tribunal_sigla)
    comarca = _obter_comarca(sessao, tribunal, bruto.comarca or norm.cidade)
    processo = _obter_processo(sessao, norm, tribunal, comarca)
    leiloeiro = _obter_leiloeiro(sessao, bruto.leiloeiro_nome, norm.uf)

    existente = localizar_existente(sessao, norm)
    prioridade = PRIORIDADE_FONTE.get(_tipo_da_fonte(bruto.fonte_slug), 1)

    if existente is None:
        leilao = _criar_leilao(sessao, norm, tribunal, processo, leiloeiro)
        lote = Lote(
            chave_natural=norm.chave_natural,
            leilao=leilao,
            numero_lote=bruto.numero_lote,
            numero_processo=norm.numero_processo,
            tipo_bem=bruto.tipo_bem,
            natureza_bem=norm.classificacao.natureza,
            zona_imovel=norm.classificacao.zona,
            esfera=norm.esfera,
            titulo=bruto.titulo,
            descricao=norm.descricao,
            status=bruto.status,
            valor_avaliacao=bruto.valor_avaliacao,
            valor_minimo_primeira=norm.valor_minimo_primeira,
            valor_minimo_segunda=norm.valor_minimo_segunda,
            comissao_leiloeiro_percentual=bruto.comissao_percentual,
            formas_pagamento=list(bruto.formas_pagamento),
            endereco=norm.endereco,
            bairro=norm.bairro,
            cidade=norm.cidade,
            uf=norm.uf,
            cep=bruto.cep,
            latitude=norm.latitude,
            longitude=norm.longitude,
            geocodificacao_precisao=norm.geocodificacao_precisao,
            matricula=bruto.matricula_imovel,
            cartorio=bruto.cartorio,
            area_total_m2=bruto.area_total_m2,
            ocupado=bruto.ocupado,
            placa_parcial=norm.placa_parcial,
            marca=bruto.marca,
            modelo=bruto.modelo,
            ano_fabricacao=bruto.ano_fabricacao,
            ano_modelo=bruto.ano_modelo,
            combustivel=bruto.combustivel,
            onus=list(bruto.onus),
            debitos=list(bruto.debitos),
            fotos=list(bruto.fotos),
            fonte_slug=bruto.fonte_slug,
            fonte_url=bruto.fonte_url,
            fontes_secundarias=[],
            conteudo_hash=norm.conteudo_hash,
        )
        sessao.add(lote)
        sessao.flush()
        criado, alteracoes = True, []
    else:
        lote = existente
        criado = False
        alteracoes = mesclar(lote, norm, prioridade)
        lote.visto_por_ultimo_em = datetime.now(UTC)
        if norm.conteudo_hash != lote.conteudo_hash:
            lote.conteudo_hash = norm.conteudo_hash
        if lote.leilao is None:
            lote.leilao = _criar_leilao(sessao, norm, tribunal, processo, leiloeiro)
        elif leiloeiro and lote.leilao.leiloeiro_id is None:
            lote.leilao.leiloeiro_id = leiloeiro.id
        if processo and lote.leilao.processo_id is None:
            lote.leilao.processo_id = processo.id

    _sincronizar_pracas(sessao, lote.leilao, norm.pracas)
    _sincronizar_documentos(sessao, lote, bruto)
    _registrar_achados(sessao, lote, norm.classificacao.achados())
    sessao.flush()

    mudancas = sincronizar_eventos(sessao, lote, settings)
    remarcacoes = sum(1 for m in mudancas if m.motivo == "remarcado")
    return lote, criado, alteracoes, remarcacoes


def _tipo_da_fonte(slug: str) -> TipoFonte:
    for conector in listar():
        if conector.slug == slug:
            return conector.meta.tipo
    return TipoFonte.LEILOEIRO


def _criar_leilao(sessao, norm, tribunal, processo, leiloeiro) -> Leilao:
    bruto = norm.bruto
    chave = f"{bruto.fonte_slug}|{norm.numero_processo or norm.chave_natural}"
    leilao = sessao.scalar(select(Leilao).where(Leilao.chave_natural == chave))
    if leilao is None:
        leilao = Leilao(
            chave_natural=chave,
            titulo=bruto.leilao_titulo or bruto.titulo[:300],
            leiloeiro_id=leiloeiro.id if leiloeiro else None,
            processo_id=processo.id if processo else None,
            tribunal_id=tribunal.id if tribunal else None,
            modalidade=bruto.modalidade,
            fonte_slug=bruto.fonte_slug,
            fonte_url=bruto.fonte_url,
        )
        sessao.add(leilao)
        sessao.flush()
    return leilao


def _sincronizar_pracas(sessao: Session, leilao: Leilao, pracas: list[PracaBruta]) -> None:
    existentes = {p.ordem: p for p in leilao.pracas}
    for bruta in pracas:
        atual = existentes.get(bruta.ordem)
        if atual is None:
            sessao.add(
                Praca(
                    leilao=leilao,
                    ordem=bruta.ordem,
                    data_hora=bruta.data_hora,
                    percentual_minimo=bruta.percentual_minimo,
                    status=StatusPraca.DESIGNADA,
                )
            )
            continue
        if bruta.data_hora and atual.data_hora != bruta.data_hora:
            # A verificacao tem de olhar a data ANTERIOR, nao a nova. Atribuir
            # primeiro e testar depois fazia `atual.data_hora` ser sempre
            # verdadeiro, e uma praca que apenas ganhou data pela primeira vez
            # (de None para uma data publicada) era rotulada REMARCADA -- como
            # se tivesse sido adiada, o que nunca aconteceu.
            tinha_data = atual.data_hora is not None
            atual.data_hora = bruta.data_hora
            atual.status = StatusPraca.REMARCADA if tinha_data else StatusPraca.DESIGNADA
        if bruta.percentual_minimo and atual.percentual_minimo is None:
            atual.percentual_minimo = bruta.percentual_minimo


def _sincronizar_documentos(sessao: Session, lote: Lote, bruto: LoteBruto) -> None:
    urls = {d.url for d in lote.documentos}
    for doc in bruto.documentos:
        if doc.url in urls:
            continue
        sessao.add(
            Documento(lote=lote, tipo=doc.tipo, url=doc.url, caminho_local=None)
        )
        urls.add(doc.url)


def _registrar_achados(sessao: Session, lote: Lote, achados) -> None:
    """Grava campo_extraido a partir de Achados. Revisao manual tem a ultima palavra."""
    existentes = {c.nome: c for c in lote.campos}
    for achado in achados:
        campo = existentes.get(achado.nome)
        if campo is None:
            campo = CampoExtraido(lote=lote, nome=achado.nome)
            sessao.add(campo)
            existentes[achado.nome] = campo
        elif campo.metodo is MetodoExtracao.MANUAL:
            continue
        elif campo.confianca > achado.confianca:
            # Nao rebaixa: um achado do edital (0,92) nao e substituido pelo
            # mesmo campo lido do diario (0,60) so porque o diario veio depois.
            continue
        campo.valor_texto = achado.valor_texto
        campo.valor_numerico = achado.valor_numerico
        campo.valor_data = achado.valor_data
        campo.valor_booleano = achado.valor_booleano
        campo.confianca = achado.confianca
        campo.metodo = achado.metodo
        campo.evidencia = achado.evidencia
        campo.revisao_necessaria = achado.revisao_necessaria


# ---------------------------------------------------------------------------
# Etapa 2b: publicacao de diario -> deteccao -> lote
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResumoPublicacao:
    publicacao: PublicacaoDiario
    detectado: LeilaoDetectado | None = None
    lote: Lote | None = None
    criado: bool = False
    remarcacoes: int = 0

    @property
    def virou_lote(self) -> bool:
        return self.lote is not None


def persistir_publicacao(
    sessao: Session,
    dados: dict,
    settings: Settings | None = None,
    geocodificador: Geocodificador | None = None,
) -> ResumoPublicacao:
    """Grava a publicacao, roda a deteccao e, se for leilao, cria/atualiza o lote.

    As publicacoes que NAO sao leilao tambem ficam gravadas. Sem elas nao da para
    medir falso negativo do detector -- e o unico jeito de descobrir que o
    limiar esta alto demais e olhar o que ficou de fora.
    """
    settings = settings or get_settings()
    bruta = _desserializar_publicacao(dados)

    detectado = detectar_leilao(bruta.texto, limiar=settings.diario_limiar_deteccao)
    publicacao = sessao.scalar(
        select(PublicacaoDiario).where(
            PublicacaoDiario.diario_slug == bruta.diario_slug,
            PublicacaoDiario.identificador == bruta.identificador,
        )
    )
    if publicacao is None:
        publicacao = PublicacaoDiario(
            diario_slug=bruta.diario_slug, identificador=bruta.identificador
        )
        sessao.add(publicacao)

    # LGPD (secao 11): CPF fora, texto truncado no recorte que sustenta a prova.
    texto = (remover_cpf(limpar_espacos(bruta.texto)) or "")[
        : settings.diario_max_caracteres_texto
    ]
    publicacao.diario_nome = bruta.diario_nome
    publicacao.esfera = bruta.esfera
    publicacao.tribunal_sigla = bruta.tribunal_sigla
    publicacao.uf = bruta.uf or uf_da_secao_judiciaria(bruta.texto)
    publicacao.caderno = bruta.caderno
    publicacao.numero_edicao = bruta.numero_edicao
    publicacao.data_publicacao = bruta.data_publicacao
    publicacao.data_divulgacao = bruta.data_divulgacao
    publicacao.numero_processo = bruta.numero_processo
    publicacao.orgao = bruta.orgao
    publicacao.municipio = bruta.municipio
    publicacao.texto = texto
    publicacao.fonte_slug = bruta.fonte_slug
    publicacao.fonte_url = bruta.fonte_url
    publicacao.coletado_em = datetime.now(UTC)
    publicacao.detectado_como_leilao = detectado is not None
    publicacao.confianca_deteccao = detectado.confianca if detectado else 0.0
    publicacao.termos_deteccao = list(detectado.termos[:12]) if detectado else []
    publicacao.evidencia = detectado.evidencia_principal if detectado else None
    publicacao.revisao_necessaria = detectado.revisao_necessaria if detectado else False
    publicacao.versao_detector = detectado.versao if detectado else None
    sessao.flush()

    resumo = ResumoPublicacao(publicacao=publicacao, detectado=detectado)
    if detectado is None:
        return resumo

    bruto = para_lote_bruto(
        bruta, detectado, max_descricao=settings.diario_max_caracteres_texto
    )
    norm = normalizar(bruto, geocodificador, classificacao=detectado.classificacao)
    lote, criado, _, remarcacoes = persistir_lote(sessao, norm, settings)
    _registrar_achados(sessao, lote, achados_da_deteccao(detectado))
    publicacao.lote_id = lote.id
    sessao.flush()

    resumo.lote = lote
    resumo.criado = criado
    resumo.remarcacoes = remarcacoes
    return resumo


# ---------------------------------------------------------------------------
# Conveniencia: ciclo completo
# ---------------------------------------------------------------------------


def ciclo_completo(
    slugs: list[str] | None,
    sessao: Session,
    fetcher: Fetcher,
    *,
    settings: Settings | None = None,
    incluir_nao_validados: bool = False,
) -> tuple[list[ExecucaoColeta], EstatisticasIngestao]:
    settings = settings or get_settings()
    fila = criar_fila(settings)
    conectores = [obter(s) for s in slugs] if slugs else listar()
    execucoes = [
        executar_coleta(
            c, fetcher, fila, sessao, incluir_nao_validados=incluir_nao_validados
        )
        for c in conectores
    ]
    stats = processar_fila(fila, sessao, settings=settings)
    return execucoes, stats
