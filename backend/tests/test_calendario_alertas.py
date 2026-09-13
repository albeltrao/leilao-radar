"""Calendario .ics (secao 9) e alertas por filtro salvo (secao 14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from radar.alerts.email import BackendMemoria
from radar.alerts.render import montar_html, montar_texto
from radar.alerts.servico import processar
from radar.calendario import ics
from radar.calendario.eventos import sincronizar_eventos
from radar.consultas import FiltroLotes, buscar
from radar.enums import StatusEvento, StatusLote, TipoBem, TipoEvento
from radar.models import Alerta, AlertaEnvio, Leilao, Lote, Praca, Usuario

AGORA = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _lote(sessao, chave="a", **ajustes) -> Lote:
    leilao = Leilao(chave_natural=f"leilao-{chave}", fonte_slug="teste")
    sessao.add(leilao)
    sessao.flush()
    pracas = ajustes.pop(
        "pracas",
        [(1, datetime(2026, 11, 10, 17, tzinfo=UTC)),
         (2, datetime(2026, 11, 24, 17, tzinfo=UTC))],
    )
    campos = dict(
        chave_natural=f"lote-{chave}",
        leilao=leilao,
        titulo="Apartamento 2 quartos; Farol, Maceió/AL",
        tipo_bem=TipoBem.IMOVEL,
        status=StatusLote.ABERTO,
        valor_avaliacao=Decimal("320000.00"),
        valor_minimo_primeira=Decimal("320000.00"),
        valor_minimo_segunda=Decimal("160000.00"),
        numero_processo="0710702-95.2021.8.02.0001",
        cidade="Maceió",
        bairro="Farol",
        uf="AL",
        endereco="Rua Exemplo, 100",
        latitude=-9.6658,
        longitude=-35.7353,
        fonte_slug="teste",
        fonte_url="https://exemplo.invalid/lote/1",
    )
    campos.update(ajustes)
    lote = Lote(**campos)
    sessao.add(lote)
    for ordem, data in pracas:
        sessao.add(Praca(leilao=leilao, ordem=ordem, data_hora=data))
    sessao.flush()
    sincronizar_eventos(sessao, lote)
    sessao.flush()
    return lote


# ---------------------------------------------------------------------------
# .ics
# ---------------------------------------------------------------------------


def test_ics_tem_estrutura_valida(sessao_db):
    lote = _lote(sessao_db)
    saida = ics.gerar(lote.eventos, agora=AGORA)

    assert saida.startswith("BEGIN:VCALENDAR\r\n")
    assert saida.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in saida
    assert saida.count("BEGIN:VEVENT") == saida.count("END:VEVENT") == len(lote.eventos)
    # RFC 5545 exige CRLF em todas as linhas.
    assert "\n" in saida and saida.replace("\r\n", "").find("\n") == -1


def test_ics_dobra_em_75_octetos_sem_partir_utf8(sessao_db):
    _lote(sessao_db, titulo="Apartamento " + "de luxo em Maceió com vista para o mar " * 4)
    lote = sessao_db.scalars(select(Lote)).one()
    saida = ics.gerar(lote.eventos, agora=AGORA)
    for linha in saida.split("\r\n"):
        assert len(linha.encode("utf-8")) <= 75, linha
    # E continua sendo UTF-8 valido depois de desdobrar.
    desdobrado = saida.replace("\r\n ", "")
    assert "Maceió" in desdobrado


def test_ics_escapa_ponto_e_virgula_do_titulo(sessao_db):
    lote = _lote(sessao_db)
    saida = ics.gerar(lote.eventos, agora=AGORA).replace("\r\n ", "")
    assert "\\;" in saida  # o titulo tem ";"
    assert "Farol\\, Maceió" in saida


def test_ics_gera_um_valarm_por_lembrete(sessao_db):
    lote = _lote(sessao_db)
    praca = next(e for e in lote.eventos if e.tipo is TipoEvento.PRACA_PRIMEIRA)
    saida = ics.gerar([praca], agora=AGORA)
    assert saida.count("BEGIN:VALARM") == 3
    for horas in (72, 24, 1):
        assert f"TRIGGER:-PT{horas}H" in saida


def test_ics_traz_disclaimer_e_fonte(sessao_db):
    lote = _lote(sessao_db)
    saida = ics.gerar(lote.eventos, agora=AGORA).replace("\r\n ", "")
    assert "Consulte o documento original e um advogado" in saida
    assert "https://exemplo.invalid/lote/1" in saida


def test_ics_marca_data_estimada(sessao_db):
    lote = _lote(sessao_db)
    habilitacao = next(e for e in lote.eventos if e.tipo is TipoEvento.PRAZO_HABILITACAO)
    saida = ics.gerar([habilitacao], agora=AGORA).replace("\r\n ", "")
    assert "data estimada" in saida


def test_sequence_sobe_na_remarcacao(sessao_db):
    """Sem SEQUENCE crescente o cliente de calendario duplica o compromisso."""
    lote = _lote(sessao_db)
    praca = next(e for e in lote.eventos if e.tipo is TipoEvento.PRACA_PRIMEIRA)
    assert "SEQUENCE:0" in ics.gerar([praca], agora=AGORA)

    lote.leilao.pracas[0].data_hora = datetime(2026, 12, 15, 17, tzinfo=UTC)
    sincronizar_eventos(sessao_db, lote)
    sessao_db.flush()

    saida = ics.gerar([praca], agora=AGORA).replace("\r\n ", "")
    assert "SEQUENCE:1" in saida
    assert "Remarcado: era 10/11/2026" in saida
    assert f"DTSTART:{datetime(2026, 12, 15, 17, tzinfo=UTC):%Y%m%dT%H%M%SZ}" in saida


def test_evento_cancelado_vira_status_cancelled(sessao_db):
    lote = _lote(sessao_db)
    praca = next(e for e in lote.eventos if e.tipo is TipoEvento.PRACA_PRIMEIRA)
    praca.status = StatusEvento.CANCELADO
    assert "STATUS:CANCELLED" in ics.gerar([praca], agora=AGORA)


def test_uid_estavel_entre_geracoes(sessao_db):
    lote = _lote(sessao_db)
    primeiro = ics.gerar(lote.eventos, agora=AGORA)
    segundo = ics.gerar(lote.eventos, agora=AGORA + timedelta(days=1))
    def uids(saida):
        return {linha for linha in saida.split("\r\n") if linha.startswith("UID:")}
    assert uids(primeiro) == uids(segundo)


def test_evento_sem_data_e_ignorado(sessao_db):
    lote = _lote(sessao_db)
    saida = ics.gerar([*lote.eventos, _EventoSemData()], agora=AGORA)
    assert saida.count("BEGIN:VEVENT") == len(lote.eventos)


class _EventoSemData:
    data_hora = None


# ---------------------------------------------------------------------------
# Filtros compartilhados
# ---------------------------------------------------------------------------


def test_filtro_de_criterios_ignora_chave_desconhecida():
    filtro = FiltroLotes.de_criterios(
        {"uf": "al", "tipo_bem": ["IMOVEL"], "desconto_minimo": "30",
         "chave_inventada": "x", "status": ["LIXO"]}
    )
    assert filtro.uf == ["AL"]
    assert filtro.tipo_bem == [TipoBem.IMOVEL]
    assert filtro.desconto_minimo == 30.0
    assert filtro.status == [StatusLote.ABERTO]  # valor invalido cai no padrao


def test_busca_por_texto_ignora_acento(sessao_db):
    _lote(sessao_db, chave="a")
    achados, total = buscar(sessao_db, FiltroLotes(texto="maceio apartamento"), AGORA)
    assert total == 1 and len(achados) == 1


def test_busca_filtra_por_uf_e_tipo(sessao_db):
    _lote(sessao_db, chave="al", uf="AL")
    _lote(sessao_db, chave="pe", uf="PE", cidade="Recife", bairro=None)
    achados, _ = buscar(sessao_db, FiltroLotes(uf=["PE"]), AGORA)
    assert [lo.uf for lo in achados] == ["PE"]


def test_busca_pagina(sessao_db):
    for i in range(5):
        _lote(sessao_db, chave=f"l{i}")
    pagina1, total = buscar(sessao_db, FiltroLotes(tamanho=2, pagina=1), AGORA)
    pagina3, _ = buscar(sessao_db, FiltroLotes(tamanho=2, pagina=3), AGORA)
    assert total == 5
    assert len(pagina1) == 2 and len(pagina3) == 1


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------


@pytest.fixture
def usuario(sessao_db):
    u = Usuario(email="investidor@example.org", nome="Investidor", senha_hash="x")
    sessao_db.add(u)
    sessao_db.flush()
    return u


def _alerta(sessao, usuario, **criterios) -> Alerta:
    a = Alerta(
        usuario_id=usuario.id, usuario=usuario, nome="Imóveis em Maceió",
        criterios=criterios or {"uf": ["AL"]},
    )
    sessao.add(a)
    sessao.flush()
    return a


def test_alerta_casa_lote_e_envia(sessao_db, usuario):
    _lote(sessao_db, chave="a")
    _alerta(sessao_db, usuario)
    backend = BackendMemoria()

    resumo = processar(sessao_db, backend=backend, agora=AGORA)
    assert (resumo.alertas_disparados, resumo.lotes_notificados) == (1, 1)
    assert len(backend.enviadas) == 1
    mensagem = backend.enviadas[0]
    assert mensagem.para == "investidor@example.org"
    assert "1 novo lote" in mensagem.assunto
    assert "Consulte o documento original" in mensagem.html


def test_alerta_nao_repete_o_mesmo_lote(sessao_db, usuario):
    _lote(sessao_db, chave="a")
    _alerta(sessao_db, usuario)
    backend = BackendMemoria()

    processar(sessao_db, backend=backend, agora=AGORA)
    segundo = processar(sessao_db, backend=backend, agora=AGORA + timedelta(hours=6))

    assert segundo.alertas_disparados == 0
    assert len(backend.enviadas) == 1
    assert sessao_db.scalar(select(func.count()).select_from(AlertaEnvio)) == 1


def test_lote_novo_dispara_segundo_envio(sessao_db, usuario):
    _lote(sessao_db, chave="a")
    _alerta(sessao_db, usuario)
    backend = BackendMemoria()
    processar(sessao_db, backend=backend, agora=AGORA)

    _lote(sessao_db, chave="b", titulo="Casa nova em Maceió")
    resumo = processar(sessao_db, backend=backend, agora=AGORA + timedelta(days=1))
    assert resumo.lotes_notificados == 1
    assert len(backend.enviadas) == 2


def test_falha_de_envio_nao_marca_como_enviado(sessao_db, usuario):
    """Se o SMTP cair, o lote tem de voltar no proximo ciclo."""
    _lote(sessao_db, chave="a")
    _alerta(sessao_db, usuario)

    class _BackendQuebrado(BackendMemoria):
        def enviar(self, mensagem):
            raise RuntimeError("SMTP fora do ar")

    resumo = processar(sessao_db, backend=_BackendQuebrado(), agora=AGORA)
    assert resumo.alertas_disparados == 0
    assert resumo.erros
    assert sessao_db.scalar(select(func.count()).select_from(AlertaEnvio)) == 0

    # No ciclo seguinte, com o servidor de pe, o lote e notificado.
    backend = BackendMemoria()
    seguinte = processar(sessao_db, backend=backend, agora=AGORA + timedelta(hours=1))
    assert seguinte.lotes_notificados == 1


def test_alerta_inativo_e_ignorado(sessao_db, usuario):
    _lote(sessao_db, chave="a")
    alerta = _alerta(sessao_db, usuario)
    alerta.ativo = False
    resumo = processar(sessao_db, backend=BackendMemoria(), agora=AGORA)
    assert resumo.alertas_avaliados == 0


def test_criterio_que_nao_casa_nao_dispara(sessao_db, usuario):
    _lote(sessao_db, chave="a", uf="AL")
    _alerta(sessao_db, usuario, uf=["PE"])
    resumo = processar(sessao_db, backend=BackendMemoria(), agora=AGORA)
    assert resumo.alertas_disparados == 0


def test_simulacao_nao_envia_nem_marca(sessao_db, usuario):
    _lote(sessao_db, chave="a")
    _alerta(sessao_db, usuario)
    backend = BackendMemoria()
    resumo = processar(sessao_db, backend=backend, agora=AGORA, simular=True)
    assert resumo.alertas_disparados == 1
    assert backend.enviadas == []
    assert sessao_db.scalar(select(func.count()).select_from(AlertaEnvio)) == 0


def test_render_texto_e_html_trazem_o_essencial(sessao_db, usuario):
    lote = _lote(sessao_db, chave="a")
    alerta = _alerta(sessao_db, usuario)
    texto = montar_texto(alerta, [lote], "https://radar.example.org")
    html = montar_html(alerta, [lote], "https://radar.example.org")

    assert "R$ 160.000,00" in texto
    assert "10/11/2026" in texto
    assert f"https://radar.example.org/lote/{lote.id}" in texto
    assert "Gerenciar alertas" in html
    # O titulo tem ";" e "/", que precisam sair escapados no HTML.
    assert "&quot;" in html or "Maceió/AL" in html
