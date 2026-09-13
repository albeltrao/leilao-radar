"""Pipeline de ingestao: idempotencia, deduplicacao e remarcacao (secoes 5 e 9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from radar.collectors.base import Conector, MetadadosFonte
from radar.collectors.dto import (
    DocumentoBruto,
    LeiloeiroBruto,
    LoteBruto,
    PracaBruta,
    ResultadoConector,
)
from radar.enums import (
    JuntaComercial,
    StatusColeta,
    StatusEvento,
    StatusLeiloeiro,
    StatusLote,
    TipoBem,
    TipoEvento,
    TipoFonte,
)
from radar.ingest.fila import TOPICO_LOTES, FilaMemoria, Mensagem
from radar.ingest.geocode import GeocodificadorMunicipio
from radar.ingest.normalizador import normalizar
from radar.ingest.pipeline import (
    executar_coleta,
    persistir_leiloeiro,
    persistir_lote,
    processar_fila,
    _serializar_leiloeiro,
    _serializar_lote,
)
from radar.models import EventoCalendario, EventoHistorico, Leiloeiro, Lote, Praca

PROCESSO = "0710702-95.2021.8.02.0001"


def _lote(**ajustes) -> LoteBruto:
    base = dict(
        fonte_slug="demo-leiloes-nordeste",
        fonte_url="https://exemplo.invalid/lote/1",
        titulo="Apartamento 2 quartos no Farol, Maceió/AL",
        numero_lote="001",
        tipo_bem=TipoBem.IMOVEL,
        descricao="Apartamento com 68 m². Executado CPF 123.456.789-00.",
        valor_avaliacao=Decimal("320000.00"),
        numero_processo=PROCESSO,
        comarca="Maceió",
        cidade="Maceió",
        bairro="Farol",
        uf="AL",
        matricula_imovel="12.345",
        leiloeiro_nome="Ana Paula Ferreira Lima",
        pracas=[
            PracaBruta(ordem=1, data_hora=datetime(2026, 11, 10, 17, tzinfo=UTC),
                       valor_minimo=Decimal("320000.00")),
            PracaBruta(ordem=2, data_hora=datetime(2026, 11, 24, 17, tzinfo=UTC),
                       valor_minimo=Decimal("160000.00")),
        ],
        documentos=[DocumentoBruto(url="https://exemplo.invalid/editais/1.pdf")],
    )
    base.update(ajustes)
    return LoteBruto(**base)


def _gravar(sessao, bruto: LoteBruto):
    norm = normalizar(bruto, GeocodificadorMunicipio())
    return persistir_lote(sessao, norm)


def test_persiste_lote_com_relacoes(sessao_db):
    lote, criado, _, _ = _gravar(sessao_db, _lote())
    sessao_db.flush()

    assert criado
    assert lote.numero_processo == PROCESSO
    assert lote.uf == "AL"
    assert lote.cidade == "Maceió"
    assert lote.valor_minimo_segunda == Decimal("160000.00")
    assert lote.leilao is not None
    assert lote.leilao.processo.numero_cnj == PROCESSO
    assert lote.leilao.tribunal.sigla == "TJAL"
    assert lote.leilao.leiloeiro.nome == "Ana Paula Ferreira Lima"
    assert len(lote.leilao.pracas) == 2
    assert len(lote.documentos) == 1
    # Geocodificado pelo centroide, com a precisao declarada.
    assert lote.latitude == pytest.approx(-9.6658)
    assert lote.geocodificacao_precisao == "MUNICIPIO"


def test_lgpd_cpf_removido_da_descricao(sessao_db):
    lote, _, _, _ = _gravar(sessao_db, _lote())
    assert "123.456.789-00" not in lote.descricao
    assert "[CPF removido]" in lote.descricao


def test_lgpd_placa_mascarada(sessao_db):
    lote, _, _, _ = _gravar(
        sessao_db,
        _lote(tipo_bem=TipoBem.VEICULO, placa="OKZ1D23", matricula_imovel=None,
              titulo="Fiat Uno 2015"),
    )
    assert lote.placa_parcial == "OKZ1**3"


def test_coleta_repetida_e_idempotente(sessao_db):
    _gravar(sessao_db, _lote())
    _gravar(sessao_db, _lote())
    _gravar(sessao_db, _lote())
    sessao_db.flush()
    assert sessao_db.scalar(select(func.count()).select_from(Lote)) == 1
    assert sessao_db.scalar(select(func.count()).select_from(Praca)) == 2


def test_mesmo_lote_em_duas_fontes_nao_duplica(sessao_db):
    """O TJPE publica o edital e o leiloeiro publica o lote: e um lote so."""
    _gravar(sessao_db, _lote())
    _, criado, alteracoes, _ = _gravar(
        sessao_db,
        _lote(
            fonte_slug="tjpe-leiloes-judiciais",
            fonte_url="https://portal.tjpe.jus.br/edital.pdf",
            titulo="Edital de leilão - processo 0710702-95.2021.8.02.0001",
            descricao=None,
            valor_avaliacao=None,
            bairro=None,
            vara="3ª Vara Cível",
        ),
    )
    sessao_db.flush()

    assert not criado
    assert sessao_db.scalar(select(func.count()).select_from(Lote)) == 1
    lote = sessao_db.scalars(select(Lote)).one()
    # O registro guarda as duas procedencias.
    assert len(lote.fontes_secundarias) == 1
    assert lote.fontes_secundarias[0]["fonte"] == "tjpe-leiloes-judiciais"
    # O dado rico do leiloeiro nao foi apagado pela fonte pobre.
    assert lote.valor_avaliacao == Decimal("320000.00")
    assert lote.bairro == "Farol"
    assert "fontes_secundarias" in alteracoes


def test_dedup_por_matricula_quando_processo_ausente(sessao_db):
    _gravar(sessao_db, _lote())
    _, criado, _, _ = _gravar(
        sessao_db,
        _lote(
            numero_processo=None,
            fonte_slug="outra-fonte",
            fonte_url="https://outra.invalid/x",
            titulo="Apto Farol - outro anúncio",
        ),
    )
    sessao_db.flush()
    assert not criado
    assert sessao_db.scalar(select(func.count()).select_from(Lote)) == 1


def test_lotes_diferentes_do_mesmo_processo_nao_sao_mesclados(sessao_db):
    """Dois apartamentos do mesmo predio no mesmo processo sao lotes distintos."""
    _gravar(sessao_db, _lote(numero_lote="001"))
    _gravar(
        sessao_db,
        _lote(numero_lote="002", matricula_imovel="12.346",
              fonte_url="https://exemplo.invalid/lote/2"),
    )
    sessao_db.flush()
    assert sessao_db.scalar(select(func.count()).select_from(Lote)) == 2


# ---------------------------------------------------------------------------
# Calendario: remarcacao como evento de primeira classe
# ---------------------------------------------------------------------------


def test_eventos_criados_para_pracas_e_habilitacao(sessao_db):
    lote, _, _, _ = _gravar(sessao_db, _lote())
    sessao_db.flush()
    tipos = {e.tipo for e in lote.eventos}
    assert TipoEvento.PRACA_PRIMEIRA in tipos
    assert TipoEvento.PRACA_SEGUNDA in tipos
    assert TipoEvento.PRAZO_HABILITACAO in tipos

    habilitacao = next(e for e in lote.eventos if e.tipo is TipoEvento.PRAZO_HABILITACAO)
    # O edital nao declarou o prazo: o evento sai marcado como estimado.
    assert habilitacao.estimado is True
    primeira = next(e for e in lote.eventos if e.tipo is TipoEvento.PRACA_PRIMEIRA)
    assert habilitacao.data_hora < primeira.data_hora
    assert primeira.lembretes_horas == [72, 24, 1]


def test_remarcacao_guarda_historico_em_vez_de_sobrescrever(sessao_db):
    _gravar(sessao_db, _lote())
    sessao_db.flush()

    nova_data = datetime(2026, 12, 15, 17, tzinfo=UTC)
    lote, _, _, remarcacoes = _gravar(
        sessao_db,
        _lote(
            pracas=[
                PracaBruta(ordem=1, data_hora=nova_data, valor_minimo=Decimal("320000.00")),
                PracaBruta(ordem=2, data_hora=datetime(2026, 12, 29, 17, tzinfo=UTC),
                           valor_minimo=Decimal("160000.00")),
            ]
        ),
    )
    sessao_db.flush()

    # Tres: as duas pracas e o prazo de habilitacao, que e derivado da 1a praca
    # e por isso anda junto -- quem tinha lembrete de habilitacao precisa saber.
    assert remarcacoes == 3
    primeira = next(e for e in lote.eventos if e.tipo is TipoEvento.PRACA_PRIMEIRA)
    assert primeira.data_hora == nova_data
    assert primeira.status is StatusEvento.REMARCADO

    historico = sessao_db.scalars(
        select(EventoHistorico).where(EventoHistorico.evento_id == primeira.id)
    ).all()
    assert len(historico) == 1
    # O sistema sabe dizer "foi adiado de X para Y".
    assert historico[0].data_hora_anterior == datetime(2026, 11, 10, 17, tzinfo=UTC)
    assert historico[0].data_hora_nova == nova_data


def test_suspensao_do_lote_marca_eventos_como_suspensos(sessao_db):
    _gravar(sessao_db, _lote())
    sessao_db.flush()
    lote, _, _, _ = _gravar(sessao_db, _lote(status=StatusLote.SUSPENSO))
    sessao_db.flush()

    lote.status = StatusLote.SUSPENSO
    from radar.calendario.eventos import sincronizar_eventos

    sincronizar_eventos(sessao_db, lote)
    sessao_db.flush()
    assert all(
        e.status is StatusEvento.SUSPENSO
        for e in lote.eventos
        if e.tipo is TipoEvento.PRACA_PRIMEIRA
    )


# ---------------------------------------------------------------------------
# Leiloeiros
# ---------------------------------------------------------------------------


def test_leiloeiro_de_junta_e_corregedoria_vira_um_registro(sessao_db):
    da_junta = LeiloeiroBruto(
        nome="Ana Paula Ferreira Lima",
        fonte_slug="juceal-leiloeiros",
        fonte_url="https://juceal.invalid",
        uf="AL",
        matricula="12/2019",
        junta=JuntaComercial.JUCEAL,
        status=StatusLeiloeiro.ATIVO,
        site_url="https://leiloes-al.invalid",
    )
    da_corregedoria = LeiloeiroBruto(
        nome="ANA PAULA FERREIRA LIMA",
        fonte_slug="tjal-banco-leiloeiros",
        fonte_url="https://cgj.tjal.jus.br",
        uf="AL",
        status=StatusLeiloeiro.ATIVO,
        email="ana@example.org",
        comarcas=["Maceió"],
    )

    _, criado1 = persistir_leiloeiro(sessao_db, _serializar_leiloeiro(da_junta))
    leiloeiro, criado2 = persistir_leiloeiro(sessao_db, _serializar_leiloeiro(da_corregedoria))
    sessao_db.flush()

    assert criado1 and not criado2
    assert sessao_db.scalar(select(func.count()).select_from(Leiloeiro)) == 1
    assert leiloeiro.matricula == "12/2019"
    assert leiloeiro.junta is JuntaComercial.JUCEAL
    assert leiloeiro.email == "ana@example.org"
    assert leiloeiro.site_url == "https://leiloes-al.invalid"
    # Credenciamento no tribunal registrado a partir da fonte da corregedoria.
    assert leiloeiro.credenciamentos.get("TJAL") is True
    assert "Maceió" in leiloeiro.comarcas_atuacao


# ---------------------------------------------------------------------------
# Fila e execucao de coleta
# ---------------------------------------------------------------------------


class _ConectorFalso(Conector):
    def __init__(self, slug="fonte-falsa", lotes=None, excecao=None, validado=True):
        self.meta = MetadadosFonte(
            slug=slug, nome=slug, tipo=TipoFonte.LEILOEIRO, uf="AL",
            url_alvo="https://exemplo.invalid", periodicidade_horas=24,
            validado_ao_vivo=validado,
        )
        self._lotes = lotes or []
        self._excecao = excecao

    def coletar(self, fetcher):
        if self._excecao:
            raise self._excecao
        return ResultadoConector(lotes=list(self._lotes), paginas_visitadas=1)


class _FetcherFalso:
    def __init__(self, settings):
        self.settings = settings
        from radar.collectors.http import EstatisticasFetcher

        self.stats = EstatisticasFetcher()


def test_coleta_publica_na_fila_e_worker_persiste(sessao_db, settings):
    fila = FilaMemoria()
    fetcher = _FetcherFalso(settings)
    execucao = executar_coleta(
        _ConectorFalso(lotes=[_lote()]), fetcher, fila, sessao_db
    )
    sessao_db.flush()

    assert execucao.status is StatusColeta.SUCESSO
    assert execucao.itens_encontrados == 1
    assert fila.pendentes(TOPICO_LOTES) == 1

    stats = processar_fila(fila, sessao_db, GeocodificadorMunicipio(), settings)
    sessao_db.flush()
    assert (stats.novos, stats.erros) == (1, 0)
    assert sessao_db.scalar(select(func.count()).select_from(Lote)) == 1
    assert fila.pendentes(TOPICO_LOTES) == 0


def test_conector_nao_validado_e_bloqueado_por_padrao(sessao_db, settings):
    execucao = executar_coleta(
        _ConectorFalso(slug="nao-validado", validado=False),
        _FetcherFalso(settings),
        FilaMemoria(),
        sessao_db,
    )
    assert execucao.status is StatusColeta.BLOQUEADA
    assert "nao validado" in execucao.erro


def test_estrutura_inesperada_vira_falha_diagnosticavel(sessao_db, settings):
    from radar.collectors.http import EstruturaInesperada

    execucao = executar_coleta(
        _ConectorFalso(slug="quebrado", excecao=EstruturaInesperada("sumiu a tabela")),
        _FetcherFalso(settings),
        FilaMemoria(),
        sessao_db,
    )
    assert execucao.status is StatusColeta.FALHA
    assert execucao.detalhe["provavel_causa"] == "mudanca de layout na fonte"


def test_robots_bloqueado_vira_status_bloqueada(sessao_db, settings):
    from radar.collectors.http import RobotsBloqueado

    execucao = executar_coleta(
        _ConectorFalso(slug="proibido", excecao=RobotsBloqueado("proibido por robots")),
        _FetcherFalso(settings),
        FilaMemoria(),
        sessao_db,
    )
    assert execucao.status is StatusColeta.BLOQUEADA


def test_mensagem_com_erro_nao_derruba_o_lote_seguinte(sessao_db, settings):
    fila = FilaMemoria()
    fila.publicar(Mensagem(TOPICO_LOTES, {"payload": "invalido"}))
    fila.publicar(Mensagem(TOPICO_LOTES, _serializar_lote(_lote())))

    stats = processar_fila(fila, sessao_db, GeocodificadorMunicipio(), settings)
    sessao_db.flush()
    assert stats.erros == 1
    assert stats.novos == 1
    assert sessao_db.scalar(select(func.count()).select_from(Lote)) == 1


def test_serializacao_ida_e_volta_preserva_decimais_e_datas():
    from radar.ingest.pipeline import _desserializar_lote

    original = _lote()
    reconstruido = _desserializar_lote(_serializar_lote(original))
    assert reconstruido.valor_avaliacao == original.valor_avaliacao
    assert reconstruido.pracas[0].data_hora == original.pracas[0].data_hora
    assert reconstruido.tipo_bem is original.tipo_bem
    assert reconstruido.documentos[0].url == original.documentos[0].url


def test_recoleta_apos_reler_do_banco_nao_inventa_remarcacao(sessao_db):
    """Regressao: datetime ingenuo vindo do SQLite fazia toda coleta virar remarcacao.

    Sem tzinfo, ``evento.data_hora != data_nova`` dava True para valores iguais e
    cada execucao do coletor disparava alerta de "praça adiada" para o usuario.
    """
    _gravar(sessao_db, _lote())
    sessao_db.commit()
    sessao_db.expire_all()  # forca releitura do banco, nao do cache de identidade

    _, _, _, remarcacoes = _gravar(sessao_db, _lote())
    sessao_db.flush()

    assert remarcacoes == 0
    assert sessao_db.scalar(select(func.count()).select_from(EventoHistorico)) == 0
    evento = sessao_db.scalars(
        select(EventoCalendario).where(EventoCalendario.tipo == TipoEvento.PRACA_PRIMEIRA)
    ).one()
    assert evento.status is StatusEvento.CONFIRMADO
    assert evento.data_hora.tzinfo is not None
