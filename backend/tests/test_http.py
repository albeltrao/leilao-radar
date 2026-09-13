"""Conformidade da camada HTTP (secoes 4.3 e 11 -- requisitos nao negociaveis)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from radar.collectors.http import (
    ArquivoBruto,
    Fetcher,
    RobotsBloqueado,
)


@pytest.fixture
def fetcher(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "diretorio_raw", tmp_path / "raw")
    monkeypatch.setattr(settings, "delay_minimo_por_host_s", 0.0)
    monkeypatch.setattr(settings, "max_tentativas_http", 2)
    settings.garantir_diretorios()
    f = Fetcher(settings)
    yield f
    f.fechar()


@respx.mock
def test_respeita_disallow_do_robots(fetcher):
    respx.get("https://exemplo.invalid/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /privado\n")
    )
    rota = respx.get("https://exemplo.invalid/privado/lote").mock(
        return_value=httpx.Response(200, text="<html>não deveria chegar aqui</html>")
    )
    with pytest.raises(RobotsBloqueado):
        fetcher.get("https://exemplo.invalid/privado/lote")
    assert not rota.called, "a requisicao proibida nao pode sair"
    assert fetcher.stats.bloqueios_robots == 1


@respx.mock
def test_permite_caminho_liberado_e_arquiva_o_bruto(fetcher):
    respx.get("https://exemplo.invalid/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /privado\n")
    )
    respx.get("https://exemplo.invalid/publico").mock(
        return_value=httpx.Response(200, text="<html>ok</html>")
    )
    resposta = fetcher.get("https://exemplo.invalid/publico", fonte_slug="fonte-x")
    assert resposta.ok
    assert "ok" in resposta.texto
    assert resposta.caminho_arquivo is not None and resposta.caminho_arquivo.exists()
    assert resposta.caminho_arquivo.read_bytes() == b"<html>ok</html>"
    # A URL de origem fica ao lado do HTML, para auditoria.
    url_salva = resposta.caminho_arquivo.with_suffix(".html.url").read_text()
    assert url_salva == "https://exemplo.invalid/publico"


@respx.mock
def test_robots_com_erro_5xx_bloqueia_a_fonte(fetcher):
    """RFC 9309: robots.txt inacessivel por falha do servidor => nao rastrear."""
    respx.get("https://instavel.invalid/robots.txt").mock(
        return_value=httpx.Response(503, text="indisponivel")
    )
    rota = respx.get("https://instavel.invalid/lotes").mock(
        return_value=httpx.Response(200, text="<html/>")
    )
    with pytest.raises(RobotsBloqueado):
        fetcher.get("https://instavel.invalid/lotes")
    assert not rota.called


@respx.mock
def test_robots_ausente_404_libera(fetcher):
    respx.get("https://semrobots.invalid/robots.txt").mock(
        return_value=httpx.Response(404, text="nao encontrado")
    )
    respx.get("https://semrobots.invalid/lotes").mock(
        return_value=httpx.Response(200, text="<html>lotes</html>")
    )
    assert fetcher.get("https://semrobots.invalid/lotes").ok


@respx.mock
def test_crawl_delay_do_robots_vira_limite_por_host(fetcher):
    respx.get("https://lento.invalid/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 7\n")
    )
    respx.get("https://lento.invalid/a").mock(return_value=httpx.Response(200, text="a"))
    fetcher.get("https://lento.invalid/a")
    assert fetcher.limitador._delays_especificos["lento.invalid"] == 7.0


@respx.mock
def test_user_agent_identifica_o_coletor(fetcher):
    capturado = {}

    def responder(request):
        capturado["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, text="ok")

    respx.get("https://exemplo.invalid/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get("https://exemplo.invalid/x").mock(side_effect=responder)
    fetcher.get("https://exemplo.invalid/x")
    assert "RadarLeilaoBot" in capturado["ua"]
    assert "http" in capturado["ua"]  # traz URL de contato


@respx.mock
def test_retenta_apos_429(fetcher):
    respx.get("https://exemplo.invalid/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    rota = respx.get("https://exemplo.invalid/lento")
    rota.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, text="<html>fim</html>"),
    ]
    resposta = fetcher.get("https://exemplo.invalid/lento")
    assert resposta.ok
    assert rota.call_count == 2


def test_arquivo_bruto_limpa_alem_da_retencao(tmp_path):
    arquivo = ArquivoBruto(tmp_path, retencao_dias=30)
    arquivo.salvar("fonte", "https://x.invalid/a", b"<html/>", "a" * 64, "html")

    antigo = tmp_path / "fonte" / (
        (datetime.now(UTC) - timedelta(days=45)).strftime("%Y-%m-%d")
    )
    antigo.mkdir(parents=True)
    (antigo / "velho.html").write_bytes(b"antigo")

    assert arquivo.limpar_expirados() == 1
    assert not antigo.exists()
    # A captura de hoje continua la.
    assert list((tmp_path / "fonte").iterdir())
