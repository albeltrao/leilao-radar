"""CLI do Radar Leilao (``radar --help``)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from radar import __version__
from radar.config import get_settings
from radar.db import criar_schema
from radar.db import sessao as abrir_sessao

app = typer.Typer(help="Radar Leilão — leilões judiciais de AL, SE e PE.", no_args_is_help=True)
fontes_app = typer.Typer(help="Fontes de coleta e sua saúde.", no_args_is_help=True)
mercado_app = typer.Typer(help="Referências de valor de mercado.", no_args_is_help=True)
app.add_typer(fontes_app, name="fontes")
app.add_typer(mercado_app, name="mercado")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
eco = typer.echo


@app.callback()
def principal() -> None:
    get_settings().garantir_diretorios()


@app.command()
def versao() -> None:
    """Mostra a versão instalada."""
    eco(f"Radar Leilão {__version__}")


@app.command("criar-schema")
def criar_schema_cmd() -> None:
    """Cria as tabelas no banco configurado."""
    criar_schema()
    eco(f"schema criado em {get_settings().database_url}")


@app.command()
def seed(
    sem_usuario: Annotated[bool, typer.Option(help="Não cria o usuário de demonstração")] = False,
) -> None:
    """Popula o banco com dados FICTÍCIOS de demonstração."""
    from radar.seed import popular

    criar_schema()
    with abrir_sessao() as sessao:
        resumo = popular(sessao, com_usuario=not sem_usuario)
    eco(f"lotes criados: {resumo['lotes_criados']}")
    if resumo.get("usuario_demo"):
        eco(f"usuário demo: {resumo['usuario_demo']} / {resumo['senha_demo']}")
    typer.secho(
        "ATENÇÃO: dados fictícios, apenas para demonstração. Nenhum leilão real.",
        fg=typer.colors.YELLOW,
    )


@app.command()
def coletar(
    fonte: Annotated[list[str] | None, typer.Option(help="Slug da fonte; repetível")] = None,
    todas: Annotated[bool, typer.Option(help="Coleta todas as fontes registradas")] = False,
    incluir_nao_validados: Annotated[
        bool, typer.Option(help="Inclui conectores ainda não validados ao vivo")
    ] = False,
) -> None:
    """Executa a coleta e processa a fila de ingestão."""
    from radar.collectors.http import criar_fetcher
    from radar.ingest.pipeline import ciclo_completo

    if not fonte and not todas:
        raise typer.BadParameter("informe --fonte <slug> ou --todas")

    criar_schema()
    with abrir_sessao() as sessao, criar_fetcher() as fetcher:
        execucoes, stats = ciclo_completo(
            list(fonte) if fonte else None,
            sessao,
            fetcher,
            incluir_nao_validados=incluir_nao_validados,
        )
    for execucao in execucoes:
        cor = {
            "SUCESSO": typer.colors.GREEN,
            "PARCIAL": typer.colors.YELLOW,
        }.get(str(execucao.status), typer.colors.RED)
        typer.secho(
            f"{execucao.fonte_slug:30s} {execucao.status:12s} "
            f"itens={execucao.itens_encontrados:<5} {execucao.erro or ''}",
            fg=cor,
        )
    eco(
        f"\ningestão: {stats.novos} novos, {stats.atualizados} atualizados, "
        f"{stats.inalterados} sem mudança, {stats.remarcacoes} remarcações, "
        f"{stats.erros} erros"
    )


@fontes_app.command("listar")
def fontes_listar() -> None:
    """Lista as fontes registradas e o estado de validação."""
    from radar.collectors.base import listar

    for conector in listar():
        selo = "validada" if conector.meta.validado_ao_vivo else "NÃO VALIDADA"
        cor = typer.colors.GREEN if conector.meta.validado_ao_vivo else typer.colors.YELLOW
        typer.secho(
            f"{conector.slug:30s} {str(conector.meta.tipo):16s} "
            f"{conector.meta.uf or '--':3s} {selo:13s} {conector.meta.url_alvo}",
            fg=cor,
        )


@fontes_app.command("validar")
def fontes_validar(
    fonte: Annotated[str, typer.Option(help="Slug da fonte a validar")],
    salvar_em: Annotated[Path | None, typer.Option(help="Grava o HTML capturado")] = None,
) -> None:
    """Baixa a fonte agora e mostra o que o parser extraiu, sem gravar no banco.

    É o passo obrigatório antes de marcar um conector como validado_ao_vivo.
    """
    from radar.collectors.base import obter
    from radar.collectors.http import criar_fetcher

    conector = obter(fonte)
    eco(f"fonte: {conector.meta.nome}\nURL:   {conector.meta.url_alvo}\n")
    with criar_fetcher() as fetcher:
        try:
            resultado = conector.coletar(fetcher)
        except Exception as exc:
            typer.secho(f"FALHOU: {type(exc).__name__}: {exc}", fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc

    eco(f"páginas visitadas: {resultado.paginas_visitadas}")
    eco(f"lotes: {len(resultado.lotes)} | leiloeiros: {len(resultado.leiloeiros)}")
    for aviso in resultado.avisos[:10]:
        typer.secho(f"  aviso: {aviso}", fg=typer.colors.YELLOW)
    for lote in resultado.lotes[:5]:
        eco(f"\n  {lote.titulo[:80]}")
        eco(f"    processo={lote.numero_processo} avaliação={lote.valor_avaliacao}")
        eco(f"    praças={[(p.ordem, p.data_hora, p.valor_minimo) for p in lote.pracas]}")
    for leiloeiro in resultado.leiloeiros[:5]:
        eco(f"\n  {leiloeiro.nome} — matrícula {leiloeiro.matricula} — {leiloeiro.status}")
    if salvar_em:
        salvar_em.parent.mkdir(parents=True, exist_ok=True)
        eco(f"\nHTML bruto está em {get_settings().diretorio_raw / fonte}")


@app.command()
def extrair(
    lote: Annotated[int | None, typer.Option(help="Extrai só este lote")] = None,
    todos: Annotated[bool, typer.Option(help="Extrai todos os documentos pendentes")] = False,
    limite: int = 50,
) -> None:
    """Baixa e extrai campos dos editais pendentes."""
    from sqlalchemy import select

    from radar.collectors.http import criar_fetcher
    from radar.extraction.servico import aplicar_no_lote, extrair_documento
    from radar.models import Documento

    if lote is None and not todos:
        raise typer.BadParameter("informe --lote <id> ou --todos")

    with abrir_sessao() as sessao, criar_fetcher() as fetcher:
        consulta = select(Documento).where(Documento.extraido_em.is_(None))
        if lote is not None:
            consulta = select(Documento).where(Documento.lote_id == lote)
        for documento in sessao.scalars(consulta.limit(limite)):
            resultado = extrair_documento(sessao, documento, fetcher=fetcher)
            alterados = aplicar_no_lote(documento.lote, resultado)
            revisao = len(resultado.campos_para_revisao)
            eco(
                f"documento {documento.id}: {len(resultado.achados)} campos "
                f"({revisao} para revisão), lote atualizado em {alterados or 'nada'}"
            )
            for aviso in resultado.avisos[:3]:
                typer.secho(f"  aviso: {aviso}", fg=typer.colors.YELLOW)


@mercado_app.command("importar-fipe")
def importar_fipe(arquivo: Path) -> None:
    """Importa um espelho da tabela FIPE (CSV)."""
    from radar.market.fipe import carregar_espelho

    with abrir_sessao() as sessao:
        total = carregar_espelho(sessao, arquivo)
    eco(f"{total} referências FIPE importadas de {arquivo}")


@mercado_app.command("importar-fipezap")
def importar_fipezap(arquivo: Path) -> None:
    """Importa o índice FipeZap extraído do boletim mensal (CSV)."""
    from radar.market.fipezap import carregar_indice

    with abrir_sessao() as sessao:
        total = carregar_indice(sessao, arquivo)
    eco(f"{total} índices FipeZap importados de {arquivo}")


@mercado_app.command("analisar")
def mercado_analisar(limite: int = 500) -> None:
    """Recalcula as análises de mercado e o score de todos os lotes."""
    from sqlalchemy import select

    from radar.market.analise import analisar
    from radar.models import Lote
    from radar.scoring.score import calcular

    with abrir_sessao() as sessao:
        total = 0
        for lote in sessao.scalars(select(Lote).limit(limite)):
            analisar(sessao, lote)
            sessao.flush()
            calcular(sessao, lote)
            total += 1
    eco(f"{total} lotes reanalisados")


@app.command()
def alertas(
    simular: Annotated[bool, typer.Option(help="Não envia; só mostra o que enviaria")] = False,
) -> None:
    """Avalia os filtros salvos e dispara os alertas."""
    from radar.alerts.servico import processar

    with abrir_sessao() as sessao:
        resumo = processar(sessao, simular=simular)
    eco(
        f"alertas avaliados: {resumo.alertas_avaliados} | disparados: "
        f"{resumo.alertas_disparados} | lotes notificados: {resumo.lotes_notificados}"
    )
    for erro in resumo.erros:
        typer.secho(f"  erro: {erro}", fg=typer.colors.RED)


@app.command("limpar-raw")
def limpar_raw() -> None:
    """Remove capturas de HTML bruto além da janela de retenção."""
    from radar.collectors.http import ArquivoBruto

    settings = get_settings()
    arquivo = ArquivoBruto(settings.diretorio_raw, settings.retencao_raw_dias)
    eco(f"{arquivo.limpar_expirados()} pasta(s) de captura removida(s)")


@app.command("criar-usuario")
def criar_usuario(
    email: str,
    senha: Annotated[str, typer.Option(prompt=True, hide_input=True)],
    nome: str | None = None,
) -> None:
    """Cria um usuário da aplicação."""
    from radar.api.auth import registrar_usuario

    criar_schema()
    with abrir_sessao() as sessao:
        usuario = registrar_usuario(sessao, email, senha, nome)
    eco(f"usuário {usuario.email} criado (id {usuario.id})")


@app.command()
def servir(
    host: str = "127.0.0.1",
    porta: int = 8000,
    recarregar: Annotated[bool, typer.Option("--recarregar")] = False,
) -> None:
    """Sobe a API (e o frontend compilado, se existir)."""
    import uvicorn

    criar_schema()
    uvicorn.run("radar.api.app:app", host=host, port=porta, reload=recarregar)


if __name__ == "__main__":  # pragma: no cover
    app()
