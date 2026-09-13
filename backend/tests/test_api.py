"""Testes da API REST."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from radar.api.app import criar_app
from radar.seed import popular


@pytest.fixture
def cliente(sessao_db, settings, monkeypatch):
    """App apontando para o banco do teste, com dados de demonstracao."""
    popular(sessao_db)
    sessao_db.commit()

    app = criar_app(settings)
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def autenticado(cliente):
    resposta = cliente.post(
        "/api/auth/registrar",
        json={"email": "teste@example.org", "senha": "senha-bem-longa-1", "nome": "Teste"},
    )
    assert resposta.status_code == 201
    token = resposta.json()["token"]
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


# ---------------------------------------------------------------------------
# Publico
# ---------------------------------------------------------------------------


def test_saude(cliente):
    dados = cliente.get("/api/saude").json()
    assert dados["status"] == "ok"
    assert dados["lotes"] >= 8


def test_listagem_pagina_e_ordena(cliente):
    dados = cliente.get("/api/lotes", params={"tamanho": 3, "ordenar": "score"}).json()
    assert len(dados["itens"]) == 3
    assert dados["total"] >= 7
    scores = [i["score"]["total"] for i in dados["itens"]]
    assert scores == sorted(scores, reverse=True)


def test_listagem_filtra_por_uf_e_tipo(cliente):
    dados = cliente.get(
        "/api/lotes", params={"uf": "AL", "tipo_bem": "IMOVEL", "tamanho": 50}
    ).json()
    assert dados["total"] >= 1
    assert all(i["uf"] == "AL" and i["tipo_bem"] == "IMOVEL" for i in dados["itens"])


def test_listagem_filtra_por_desconto_minimo(cliente):
    dados = cliente.get("/api/lotes", params={"desconto_minimo": 40, "tamanho": 50}).json()
    assert all(i["score"]["desconto_destaque"] >= 40 for i in dados["itens"])


def test_busca_textual_sem_acento(cliente):
    dados = cliente.get("/api/lotes", params={"q": "maceio apartamento"}).json()
    assert dados["total"] >= 1


def test_lote_suspenso_fica_fora_do_padrao(cliente):
    padrao = cliente.get("/api/lotes", params={"tamanho": 50}).json()
    suspensos = cliente.get(
        "/api/lotes", params={"status": "SUSPENSO", "tamanho": 50}
    ).json()
    assert suspensos["total"] >= 1
    assert all(i["status"] != "SUSPENSO" for i in padrao["itens"])


def test_detalhe_traz_procedencia_de_tudo(cliente):
    lista = cliente.get("/api/lotes", params={"q": "Farol", "tamanho": 1}).json()
    lote_id = lista["itens"][0]["id"]
    dados = cliente.get(f"/api/lotes/{lote_id}").json()

    # Secao 11: disclaimer visivel em cada lote.
    assert "Consulte o documento original e um advogado" in dados["disclaimer"]

    # Secao 7.4: todo campo extraido leva confianca, metodo e evidencia.
    assert dados["campos"]
    for campo in dados["campos"]:
        assert 0.0 <= campo["confianca"] <= 1.0
        assert campo["metodo"]
        assert campo["evidencia"]
        assert isinstance(campo["revisao_necessaria"], bool)

    # Secao 4.5: toda analise leva metodologia e avisos.
    assert dados["analises"]
    for analise in dados["analises"]:
        assert len(analise["metodologia"]) > 20
        assert analise["avisos"] is not None

    # Secao 8: score explicado componente a componente.
    assert len(dados["score"]["componentes"]) == 5
    assert all(c["explicacao"] for c in dados["score"]["componentes"])


def test_detalhe_inexistente_da_404(cliente):
    assert cliente.get("/api/lotes/999999").status_code == 404


def test_comparar_exige_dois_e_limita_a_tres(cliente):
    ids = [i["id"] for i in cliente.get("/api/lotes", params={"tamanho": 4}).json()["itens"]]
    assert cliente.get("/api/lotes/comparar", params={"ids": str(ids[0])}).status_code == 400
    dados = cliente.get(
        "/api/lotes/comparar", params={"ids": ",".join(str(i) for i in ids)}
    ).json()
    assert len(dados) == 3


def test_simulacao_soma_comissao(cliente):
    lista = cliente.get("/api/lotes", params={"q": "Farol", "tamanho": 1}).json()
    lote_id = lista["itens"][0]["id"]
    dados = cliente.get(f"/api/lotes/{lote_id}/simulacao", params={"lance": 100000}).json()
    assert float(dados["custo_total_estimado"]) > 100000
    assert any("comissão" in d for d in dados["detalhes"])
    assert "ITBI" in dados["aviso"]


def test_geojson_declara_precisao(cliente):
    dados = cliente.get("/api/geo/lotes").json()
    assert dados["type"] == "FeatureCollection"
    assert dados["features"]
    for feicao in dados["features"]:
        assert feicao["geometry"]["type"] == "Point"
        # A UI precisa saber que a coordenada e do municipio, nao do endereco.
        assert feicao["properties"]["precisao"] in {"MUNICIPIO", "BAIRRO", "ENDERECO"}


def test_calendario_lista_eventos(cliente):
    eventos = cliente.get("/api/calendario").json()
    assert eventos
    assert {"tipo", "data_hora", "estimado", "titulo"} <= set(eventos[0])
    assert any(e["estimado"] for e in eventos)  # prazo de habilitacao estimado


def test_calendario_ics_e_baixavel(cliente):
    resposta = cliente.get("/api/calendario.ics")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/calendar")
    assert "attachment" in resposta.headers["content-disposition"]
    corpo = resposta.text
    assert corpo.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VALARM" in corpo


def test_ics_de_um_lote(cliente):
    lote_id = cliente.get("/api/lotes", params={"tamanho": 1}).json()["itens"][0]["id"]
    resposta = cliente.get(f"/api/lotes/{lote_id}/calendario.ics")
    assert resposta.status_code == 200
    assert "BEGIN:VEVENT" in resposta.text


def test_painel_de_saude_das_fontes(cliente):
    fontes = cliente.get("/api/fontes").json()
    assert len(fontes) >= 20
    por_slug = {f["slug"]: f for f in fontes}
    # O selo de validacao precisa chegar na UI.
    assert por_slug["tjpe-leiloes-judiciais"]["validado_ao_vivo"] is False
    assert por_slug["demo-leiloes-nordeste"]["validado_ao_vivo"] is True
    assert all("url_alvo" in f for f in fontes)


def test_facetas_para_montar_filtros(cliente):
    dados = cliente.get("/api/meta/facetas").json()
    assert set(dados["ufs"]) <= {"AL", "SE", "PE"}
    assert dados["cidades"]
    assert dados["leiloeiros"]
    assert dados["faixa_valores"]["minimo"] is not None


def test_glossario_de_onboarding(cliente):
    dados = cliente.get("/api/meta/glossario").json()
    chaves = {p["chave"] for p in dados["passos"]}
    assert {"pracas", "habilitacao", "caucao", "onus", "comissao"} <= chaves
    assert dados["referencias"]


# ---------------------------------------------------------------------------
# Conta
# ---------------------------------------------------------------------------


def test_registro_login_e_eu(cliente):
    registro = cliente.post(
        "/api/auth/registrar",
        json={"email": "novo@example.org", "senha": "uma-senha-longa", "nome": "Novo"},
    )
    assert registro.status_code == 201

    login = cliente.post(
        "/api/auth/entrar", json={"email": "novo@example.org", "senha": "uma-senha-longa"}
    )
    assert login.status_code == 200
    token = login.json()["token"]

    eu = cliente.get("/api/auth/eu", headers={"Authorization": f"Bearer {token}"})
    assert eu.json()["email"] == "novo@example.org"


def test_email_duplicado_e_recusado(cliente):
    corpo = {"email": "dup@example.org", "senha": "senha-longa-aqui"}
    assert cliente.post("/api/auth/registrar", json=corpo).status_code == 201
    assert cliente.post("/api/auth/registrar", json=corpo).status_code == 409


def test_senha_errada_nao_entra(cliente):
    cliente.post(
        "/api/auth/registrar", json={"email": "x@example.org", "senha": "senha-certa-1"}
    )
    resposta = cliente.post(
        "/api/auth/entrar", json={"email": "x@example.org", "senha": "senha-errada"}
    )
    assert resposta.status_code == 401


def test_senha_curta_e_recusada(cliente):
    resposta = cliente.post(
        "/api/auth/registrar", json={"email": "curta@example.org", "senha": "123"}
    )
    assert resposta.status_code == 422


def test_rota_protegida_sem_token(cliente):
    assert cliente.get("/api/alertas").status_code == 401


def test_token_invalido_e_recusado(cliente):
    resposta = cliente.get("/api/alertas", headers={"Authorization": "Bearer lixo"})
    assert resposta.status_code == 401


def test_ciclo_de_alerta(autenticado):
    criacao = autenticado.post(
        "/api/alertas",
        json={
            "nome": "Imóveis em AL",
            "criterios": {"uf": ["AL"], "tipo_bem": ["IMOVEL"], "desconto_minimo": 10},
        },
    )
    assert criacao.status_code == 201
    alerta_id = criacao.json()["id"]

    assert len(autenticado.get("/api/alertas").json()) == 1

    previa = autenticado.get(f"/api/alertas/{alerta_id}/previa").json()
    assert previa["total"] >= 1
    assert all(i["uf"] == "AL" for i in previa["itens"])

    atualizacao = autenticado.patch(
        f"/api/alertas/{alerta_id}",
        json={"nome": "Só Maceió", "criterios": {"uf": ["AL"]}, "ativo": False},
    )
    assert atualizacao.json()["ativo"] is False

    assert autenticado.delete(f"/api/alertas/{alerta_id}").status_code == 204
    assert autenticado.get("/api/alertas").json() == []


def test_alerta_de_outro_usuario_nao_e_acessivel(cliente, autenticado):
    alerta_id = autenticado.post(
        "/api/alertas", json={"nome": "meu", "criterios": {"uf": ["AL"]}}
    ).json()["id"]

    outro = cliente.post(
        "/api/auth/registrar",
        json={"email": "intruso@example.org", "senha": "senha-do-intruso"},
    ).json()["token"]
    cabecalho = {"Authorization": f"Bearer {outro}"}

    assert cliente.get(f"/api/alertas/{alerta_id}/previa", headers=cabecalho).status_code == 404
    assert cliente.delete(f"/api/alertas/{alerta_id}", headers=cabecalho).status_code == 404


def test_favoritos(autenticado):
    lote_id = autenticado.get("/api/lotes", params={"tamanho": 1}).json()["itens"][0]["id"]

    assert autenticado.post(f"/api/favoritos/{lote_id}").status_code == 201
    # Favoritar de novo nao duplica.
    autenticado.post(f"/api/favoritos/{lote_id}")
    assert len(autenticado.get("/api/favoritos").json()) == 1

    assert autenticado.delete(f"/api/favoritos/{lote_id}").status_code == 204
    assert autenticado.get("/api/favoritos").json() == []


def test_favoritar_lote_inexistente(autenticado):
    assert autenticado.post("/api/favoritos/999999").status_code == 404


def test_openapi_documenta_as_rotas(cliente):
    esquema = cliente.get("/api/openapi.json").json()
    assert len(esquema["paths"]) >= 20
    # A descricao quebra linha no meio da frase; comparamos com espacos normalizados.
    descricao = " ".join(esquema["info"]["description"].split())
    # "nao" vem em negrito markdown (**nao**), entao a asercao comeca depois dele.
    assert "presta assessoria jurídica nem recomendação de investimento" in descricao
