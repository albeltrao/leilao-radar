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

app = typer.Typer(
    help="Radar Leilão — leilões judiciais de AL, BA, PE e SE.", no_args_is_help=True
)
fontes_app = typer.Typer(help="Fontes de coleta e sua saúde.", no_args_is_help=True)
leiloeiros_app = typer.Typer(
    help="Cadastro mestre de leiloeiros (juntas comerciais e corregedorias).",
    no_args_is_help=True,
)
mercado_app = typer.Typer(help="Referências de valor de mercado.", no_args_is_help=True)
diarios_app = typer.Typer(
    help="Diário da Justiça (estadual e federal): coleta, leitura e agenda.",
    no_args_is_help=True,
)
app.add_typer(fontes_app, name="fontes")
app.add_typer(leiloeiros_app, name="leiloeiros")
app.add_typer(mercado_app, name="mercado")
app.add_typer(diarios_app, name="diarios")

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


# ---------------------------------------------------------------------------
# Cadastro mestre de leiloeiros (secao 4.2)
# ---------------------------------------------------------------------------


@leiloeiros_app.command("coletar")
def leiloeiros_coletar(
    uf: Annotated[str | None, typer.Option(help="Limita a uma UF (AL, BA, PE, SE)")] = None,
    incluir_nao_validados: Annotated[
        bool, typer.Option(help="Inclui fontes ainda não validadas ao vivo")
    ] = False,
) -> None:
    """Popula o cadastro mestre a partir das juntas comerciais e corregedorias.

    É este o comando que traz os leiloeiros REAIS para dentro do sistema. Ele
    precisa rodar de um ambiente com saída de rede para os portais oficiais --
    os nomes e as matrículas vêm de lá, nunca de dados embutidos no repositório.
    """
    from sqlalchemy import func, select

    from radar.collectors.base import listar
    from radar.collectors.http import criar_fetcher
    from radar.enums import TipoFonte
    from radar.ingest.fila import criar_fila
    from radar.ingest.pipeline import executar_coleta, processar_fila
    from radar.models import Leiloeiro

    fontes = [
        c
        for c in listar(uf=uf.upper() if uf else None)
        if c.meta.tipo in (TipoFonte.JUNTA_COMERCIAL, TipoFonte.TRIBUNAL)
    ]
    if not fontes:
        raise typer.BadParameter(f"nenhuma fonte de cadastro para UF={uf}")

    criar_schema()
    fila = criar_fila()
    with abrir_sessao() as sessao, criar_fetcher() as fetcher:
        antes = sessao.scalar(select(func.count()).select_from(Leiloeiro)) or 0
        for conector in fontes:
            execucao = executar_coleta(
                conector, fetcher, fila, sessao, incluir_nao_validados=incluir_nao_validados
            )
            cor = {
                "SUCESSO": typer.colors.GREEN,
                "PARCIAL": typer.colors.YELLOW,
            }.get(str(execucao.status), typer.colors.RED)
            typer.secho(
                f"{execucao.fonte_slug:32s} {execucao.status:12s} "
                f"itens={execucao.itens_encontrados:<4} {execucao.erro or ''}",
                fg=cor,
            )
        stats = processar_fila(fila, sessao)
        depois = sessao.scalar(select(func.count()).select_from(Leiloeiro)) or 0

    eco(f"\ncadastro mestre: {antes} -> {depois} leiloeiros ({stats.novos} novos)")
    if depois == antes == 0:
        typer.secho(
            "\nNenhum leiloeiro entrou. As fontes de cadastro ainda não foram validadas\n"
            "ao vivo: rode `radar fontes validar --fonte <slug>` para conferir a URL e o\n"
            "parser de cada uma, e só então marque validado_ao_vivo: true.",
            fg=typer.colors.YELLOW,
        )


@leiloeiros_app.command("listar")
def leiloeiros_listar(
    uf: Annotated[str | None, typer.Option(help="Filtra por UF")] = None,
    com_site: Annotated[bool, typer.Option(help="Só os que têm site cadastrado")] = False,
) -> None:
    """Lista o cadastro mestre já coletado."""
    from sqlalchemy import select

    from radar.models import Leiloeiro

    with abrir_sessao() as sessao:
        consulta = select(Leiloeiro).order_by(Leiloeiro.uf, Leiloeiro.nome)
        if uf:
            consulta = consulta.where(Leiloeiro.uf == uf.upper())
        registros = list(sessao.scalars(consulta))
        if com_site:
            registros = [r for r in registros if r.site_url]

        if not registros:
            typer.secho(
                "Cadastro vazio. Rode `radar leiloeiros coletar` de um ambiente com "
                "rede para os portais oficiais.",
                fg=typer.colors.YELLOW,
            )
            return
        for r in registros:
            credenciais = ", ".join(sorted((r.credenciamentos or {}).keys())) or "—"
            eco(
                f"{r.uf}  {r.nome[:44]:44s} mat.{(r.matricula or '—'):10s} "
                f"{str(r.junta or '—'):8s} {r.status:12s} cred.{credenciais:14s} "
                f"{r.site_url or ''}"
            )
        eco(f"\ntotal: {len(registros)}")


@leiloeiros_app.command("sugerir-perfis")
def leiloeiros_sugerir_perfis(
    uf: Annotated[str | None, typer.Option(help="Filtra por UF")] = None,
) -> None:
    """Gera perfis YAML para leiloeiros com site que ainda não têm conector.

    Fecha o ciclo da seção 4.3: o cadastro mestre diz QUEM pode leiloar e onde
    fica o site; este comando transforma isso no esqueleto do conector. Cole a
    saída em data/perfis_leiloeiros.yaml, valide e marque validado_ao_vivo.
    """
    from urllib.parse import urlparse

    from sqlalchemy import select

    from radar.collectors.leiloeiros.declarativo import carregar_perfis
    from radar.models import Leiloeiro
    from radar.normalizacao import slugify

    dominios_com_perfil = {
        urlparse(p.base_url).netloc.replace("www.", "")
        for p in carregar_perfis()
        if p.base_url and p.base_url != "PREENCHER"
    }

    with abrir_sessao() as sessao:
        consulta = select(Leiloeiro).where(Leiloeiro.site_url.isnot(None))
        if uf:
            consulta = consulta.where(Leiloeiro.uf == uf.upper())
        candidatos = [
            r
            for r in sessao.scalars(consulta.order_by(Leiloeiro.uf, Leiloeiro.nome))
            if urlparse(r.site_url).netloc.replace("www.", "") not in dominios_com_perfil
        ]

    if not candidatos:
        typer.secho(
            "Nenhum leiloeiro com site sem perfil. Se o cadastro está vazio, rode "
            "`radar leiloeiros coletar` primeiro.",
            fg=typer.colors.YELLOW,
        )
        return

    eco("# Cole em backend/src/radar/data/perfis_leiloeiros.yaml, sob `perfis:`.")
    eco("# Depois: radar fontes validar --fonte <slug>, congele a fixture, teste,")
    eco("# e só então marque validado_ao_vivo: true.\n")
    for r in candidatos:
        base = r.site_url.rstrip("/")
        eco("  - <<: *plataforma_padrao")
        eco(f"    slug: {slugify(r.nome)}")
        eco(f'    nome: "{r.nome}"')
        eco(f"    uf: {r.uf}")
        eco(f'    base_url: "{base}"')
        eco(f'    urls: ["{base}"]   # CONFIRMAR o caminho da listagem de lotes')
        eco(f"    leiloeiro_nome: \"{r.nome}\"")
        if r.matricula:
            eco(f'    leiloeiro_matricula: "{r.matricula}"')
        eco("    validado_ao_vivo: false")
        eco("")
    eco(f"# {len(candidatos)} perfil(is) sugerido(s).")


if __name__ == "__main__":  # pragma: no cover
    app()


# ---------------------------------------------------------------------------
# Diario da Justica
# ---------------------------------------------------------------------------


@diarios_app.command("coletar")
def diarios_coletar(
    uf: Annotated[str | None, typer.Option(help="Limita a uma UF (AL, BA, PE, SE)")] = None,
    esfera: Annotated[
        str | None, typer.Option(help="ESTADUAL ou FEDERAL; vazio traz as duas")
    ] = None,
    incluir_nao_validados: Annotated[
        bool, typer.Option(help="Inclui fontes ainda não validadas ao vivo")
    ] = False,
) -> None:
    """Lê o Diário da Justiça e transforma em lote o que for leilão.

    Precisa de rede liberada para a API Comunica do CNJ. Enquanto os conectores
    não forem validados ao vivo, use --incluir-nao-validados de propósito: assim
    ninguém liga a coleta em produção achando que o contrato foi conferido.
    """
    from radar.collectors.base import listar
    from radar.collectors.http import criar_fetcher
    from radar.enums import EsferaJustica, TipoFonte
    from radar.ingest.fila import criar_fila
    from radar.ingest.pipeline import executar_coleta, processar_fila

    alvo_esfera = EsferaJustica(esfera.upper()) if esfera else None
    fontes = [
        c
        for c in listar(tipo=TipoFonte.DIARIO_OFICIAL, uf=uf.upper() if uf else None)
        if alvo_esfera is None or c.esfera is alvo_esfera
    ]
    if not fontes:
        raise typer.BadParameter(f"nenhum diário para uf={uf} esfera={esfera}")

    criar_schema()
    fila = criar_fila()
    with abrir_sessao() as sessao, criar_fetcher() as fetcher:
        for conector in fontes:
            execucao = executar_coleta(
                conector, fetcher, fila, sessao, incluir_nao_validados=incluir_nao_validados
            )
            cor = {
                "SUCESSO": typer.colors.GREEN,
                "PARCIAL": typer.colors.YELLOW,
            }.get(str(execucao.status), typer.colors.RED)
            typer.secho(
                f"{execucao.fonte_slug:16s} {execucao.status:12s} "
                f"itens={execucao.itens_encontrados:<5} {execucao.erro or ''}",
                fg=cor,
            )
        stats = processar_fila(fila, sessao)

    eco(
        f"\npublicações lidas: {stats.publicacoes_lidas} | "
        f"detectadas como leilão: {stats.publicacoes_com_leilao} | "
        f"lotes novos: {stats.novos} | atualizados: {stats.atualizados}"
    )
    if stats.publicacoes_lidas and not stats.publicacoes_com_leilao:
        typer.secho(
            "Nenhuma publicação passou no limiar de detecção. Confira as guardadas com\n"
            "`radar diarios publicacoes --todas` antes de mexer em "
            "RADAR_DIARIO_LIMIAR_DETECCAO.",
            fg=typer.colors.YELLOW,
        )


@diarios_app.command("publicacoes")
def diarios_publicacoes(
    uf: Annotated[str | None, typer.Option(help="Filtra por UF")] = None,
    todas: Annotated[
        bool, typer.Option(help="Mostra também as que NÃO foram detectadas como leilão")
    ] = False,
    revisao: Annotated[
        bool, typer.Option(help="Só as marcadas para revisão humana")
    ] = False,
    limite: int = 30,
) -> None:
    """Lista o que foi lido do diário, com a confiança e o trecho da detecção."""
    from sqlalchemy import select

    from radar.models import PublicacaoDiario

    consulta = select(PublicacaoDiario).order_by(PublicacaoDiario.data_publicacao.desc())
    if uf:
        consulta = consulta.where(PublicacaoDiario.uf == uf.upper())
    if not todas:
        consulta = consulta.where(PublicacaoDiario.detectado_como_leilao.is_(True))
    if revisao:
        consulta = consulta.where(PublicacaoDiario.revisao_necessaria.is_(True))

    with abrir_sessao() as sessao:
        itens = list(sessao.scalars(consulta.limit(limite)))
        if not itens:
            eco("nenhuma publicação. Rode `radar diarios coletar` primeiro.")
            return
        for p in itens:
            marca = "LEILÃO" if p.detectado_como_leilao else "  --  "
            dia = p.data_publicacao.strftime("%d/%m/%Y") if p.data_publicacao else "??"
            eco(
                f"[{marca}] {dia} {p.diario_slug:14s} {str(p.esfera):9s} "
                f"{p.uf or '--'} conf={p.confianca_deteccao:.2f} "
                f"{'REVISAR' if p.revisao_necessaria else '       '} "
                f"lote={p.lote_id or '-'}"
            )
            if p.evidencia:
                eco(f"         {p.evidencia[:150]}")


@diarios_app.command("agenda")
def diarios_agenda(
    dias: Annotated[int, typer.Option(help="Janela a partir de hoje")] = 30,
    uf: Annotated[str | None, typer.Option(help="Filtra por UF")] = None,
    esfera: Annotated[str | None, typer.Option(help="ESTADUAL ou FEDERAL")] = None,
    categoria: Annotated[
        str | None,
        typer.Option(help="IMOVEL_URBANO, IMOVEL_RURAL, IMOVEL_INDEFINIDO, MOVEL"),
    ] = None,
    somente_de_diario: Annotated[
        bool, typer.Option(help="Só os leilões que vieram do Diário da Justiça")
    ] = False,
) -> None:
    """Agenda cronológica dos leilões, agrupada por tipo de bem."""
    from radar.agenda import FiltroAgenda, montar
    from radar.enums import EsferaJustica

    filtro = FiltroAgenda(
        dias=dias,
        ufs=[uf.upper()] if uf else [],
        esferas=[EsferaJustica(esfera.upper())] if esfera else [],
        categorias=[categoria.upper()] if categoria else [],
        somente_de_diario=somente_de_diario,
    )
    with abrir_sessao() as sessao:
        agenda = montar(sessao, filtro)

    eco(f"{agenda.total} leilões nos próximos {dias} dias ({agenda.total_de_diario} do diário)\n")
    for contagem in agenda.categorias:
        if contagem.total:
            eco(f"  {contagem.rotulo:34s} {contagem.total}")
    for dia in agenda.dias:
        eco(f"\n{dia.data} ({dia.total})")
        for item in dia.itens:
            hora = item.data_hora.strftime("%H:%M")
            eco(
                f"  {hora} [{item.categoria_rotulo}] {item.titulo[:70]} "
                f"- {item.cidade or item.comarca or '?'}/{item.uf or '?'} "
                f"({item.esfera.lower()})"
            )
