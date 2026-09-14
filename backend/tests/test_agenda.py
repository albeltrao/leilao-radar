"""Agenda cronológica por tipo de bem, e o caminho publicação -> lote -> agenda.

Roda sobre o banco de teste, sem rede: as publicações entram pelo mesmo
``persistir_publicacao`` que a coleta real usa.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

from radar.agenda import CATEGORIAS, FiltroAgenda, categoria_do_lote, montar
from radar.collectors.base import obter
from radar.enums import EsferaJustica, NaturezaBem, ZonaImovel
from radar.ingest.pipeline import _serializar_publicacao, persistir_publicacao
from radar.models import Lote, PublicacaoDiario

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "diarios"


def _publicacoes(nome: str):
    conector = obter("djen-tjal" if "tjal" in nome else "djen-trf5")
    corpo = (FIXTURES / nome).read_text(encoding="utf-8")
    return conector.parse(corpo, "https://exemplo.invalid/consulta").publicacoes


def _ingerir(sessao, nome: str) -> list:
    resumos = []
    for publicacao in _publicacoes(nome):
        resumos.append(
            persistir_publicacao(sessao, _serializar_publicacao(publicacao))
        )
    sessao.flush()
    return resumos


def _adiantar_pracas(sessao, dias: int = 5) -> None:
    """Traz os eventos para dentro da janela padrão da agenda.

    As fixtures têm datas fixas (2027) para que o teste não mude de resultado
    conforme o dia em que roda; a agenda olha para a frente a partir de hoje.
    """
    from radar.models import EventoCalendario

    alvo = datetime.now(UTC) + timedelta(days=dias)
    for indice, evento in enumerate(sessao.query(EventoCalendario).all()):
        evento.data_hora = alvo + timedelta(days=indice)
    sessao.flush()


def test_publicacao_de_leilao_vira_lote_e_nao_leilao_fica_guardada(sessao_db):
    resumos = _ingerir(sessao_db, "djen_tjal.json")
    assert len(resumos) == 3
    viraram = [r for r in resumos if r.virou_lote]
    assert len(viraram) == 2

    guardadas = sessao_db.query(PublicacaoDiario).all()
    assert len(guardadas) == 3
    descartada = next(p for p in guardadas if not p.detectado_como_leilao)
    assert descartada.lote_id is None
    assert descartada.confianca_deteccao == 0.0
    # A publicação descartada continua no banco: é como se mede falso negativo.
    assert descartada.texto


def test_ingestao_de_publicacao_e_idempotente(sessao_db):
    _ingerir(sessao_db, "djen_tjal.json")
    antes_lotes = sessao_db.query(Lote).count()
    antes_publicacoes = sessao_db.query(PublicacaoDiario).count()

    _ingerir(sessao_db, "djen_tjal.json")

    assert sessao_db.query(Lote).count() == antes_lotes
    assert sessao_db.query(PublicacaoDiario).count() == antes_publicacoes


def test_lote_do_diario_guarda_classificacao_com_evidencia(sessao_db):
    resumos = _ingerir(sessao_db, "djen_tjal.json")
    rural = next(
        r.lote
        for r in resumos
        if r.virou_lote and r.lote.zona_imovel is ZonaImovel.RURAL
    )
    assert rural.natureza_bem is NaturezaBem.IMOVEL
    assert categoria_do_lote(rural) == "IMOVEL_RURAL"
    assert rural.esfera is EsferaJustica.ESTADUAL

    campos = {c.nome: c for c in rural.campos}
    for nome in ("natureza_bem", "zona_imovel", "leilao_detectado_em_diario"):
        assert nome in campos, f"campo {nome} deveria ter sido gravado"
        assert campos[nome].evidencia, f"{nome} sem trecho literal"
        assert 0 < campos[nome].confianca < 1.0


def test_agenda_agrupa_por_dia_e_conta_por_categoria(sessao_db):
    _ingerir(sessao_db, "djen_tjal.json")
    _ingerir(sessao_db, "djen_trf5.json")
    _adiantar_pracas(sessao_db)

    agenda = montar(sessao_db, FiltroAgenda(dias=120))
    assert agenda.total > 0
    assert agenda.total_de_diario == agenda.total  # tudo veio do diário neste teste

    # Os dias saem em ordem cronológica.
    assert [d.data for d in agenda.dias] == sorted(d.data for d in agenda.dias)
    # O total das abas bate com o total da lista -- contagens derivadas da mesma
    # lista filtrada, nunca de uma consulta paralela.
    assert sum(c.total for c in agenda.categorias) == agenda.total
    assert sum(d.total for d in agenda.dias) == agenda.total
    assert [c.chave for c in agenda.categorias] == [chave for chave, _ in CATEGORIAS]

    por_categoria = {c.chave: c.total for c in agenda.categorias}
    assert por_categoria["IMOVEL_RURAL"] >= 1
    assert por_categoria["IMOVEL_URBANO"] >= 1
    assert por_categoria["MOVEL"] >= 1


def test_agenda_filtra_por_categoria_uf_e_esfera(sessao_db):
    _ingerir(sessao_db, "djen_tjal.json")
    _ingerir(sessao_db, "djen_trf5.json")
    _adiantar_pracas(sessao_db)

    rurais = montar(sessao_db, FiltroAgenda(dias=120, categorias=["IMOVEL_RURAL"]))
    assert rurais.total >= 1
    assert all(
        i.categoria == "IMOVEL_RURAL" for d in rurais.dias for i in d.itens
    )

    federais = montar(
        sessao_db, FiltroAgenda(dias=120, esferas=[EsferaJustica.FEDERAL])
    )
    assert federais.total >= 1
    assert all(i.esfera == "FEDERAL" for d in federais.dias for i in d.itens)

    alagoas = montar(sessao_db, FiltroAgenda(dias=120, ufs=["AL"]))
    assert alagoas.total >= 1
    assert all(i.uf == "AL" for d in alagoas.dias for i in d.itens)


def test_item_da_agenda_traz_a_procedencia_do_diario(sessao_db):
    _ingerir(sessao_db, "djen_tjal.json")
    _adiantar_pracas(sessao_db)

    agenda = montar(sessao_db, FiltroAgenda(dias=120))
    item = next(i for d in agenda.dias for i in d.itens)
    assert item.diario is not None
    assert item.diario.nome
    assert item.diario.evidencia  # o trecho literal que sustentou a detecção
    assert 0 < item.diario.confianca <= 0.95
    assert item.categoria_rotulo


def test_agenda_ignora_o_que_esta_fora_da_janela(sessao_db):
    _ingerir(sessao_db, "djen_tjal.json")
    _adiantar_pracas(sessao_db, dias=200)
    assert montar(sessao_db, FiltroAgenda(dias=30)).total == 0
    assert montar(sessao_db, FiltroAgenda(dias=365)).total > 0


def test_agenda_esconde_evento_cancelado_mas_mantem_remarcado(sessao_db):
    from radar.enums import StatusEvento
    from radar.models import EventoCalendario

    _ingerir(sessao_db, "djen_tjal.json")
    _adiantar_pracas(sessao_db)
    eventos = sessao_db.query(EventoCalendario).all()
    antes = montar(sessao_db, FiltroAgenda(dias=120)).total

    eventos[0].status = StatusEvento.CANCELADO
    eventos[1].status = StatusEvento.REMARCADO
    sessao_db.flush()

    agenda = montar(sessao_db, FiltroAgenda(dias=120))
    assert agenda.total == antes - 1
    assert any(i.status_evento == "REMARCADO" for d in agenda.dias for i in d.itens)


def test_api_da_agenda_responde_com_disclaimer(sessao_db, cliente_api):
    _ingerir(sessao_db, "djen_tjal.json")
    _adiantar_pracas(sessao_db)
    sessao_db.commit()

    resposta = cliente_api.get("/api/agenda?dias=120")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] > 0
    assert "não é assessoria jurídica" in corpo["disclaimer"]
    assert len(corpo["categorias"]) == len(CATEGORIAS)

    publicacoes = cliente_api.get("/api/diarios/publicacoes?somente_detectadas=false")
    dados = publicacoes.json()
    assert dados["total"] == 3
    assert dados["detectadas"] == 2
