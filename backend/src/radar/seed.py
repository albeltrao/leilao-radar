"""Dados de demonstracao.

Existe para que alguem consiga rodar o produto e ver a tela funcionando sem
depender de coleta ao vivo -- util para desenvolvimento, para avaliar o design e
para os testes de ponta a ponta.

Tudo aqui e FICTICIO. As fontes apontam para dominios .invalid (reservados pela
RFC 2606) e os lotes sao marcados com fonte_slug "demo-leiloes-nordeste", que o
proprio conector declara como perfil sintetico. Nenhum dado corresponde a leilao
real, processo real ou pessoa real.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.api.auth import registrar_usuario
from radar.calendario.eventos import sincronizar_eventos
from radar.collectors.dto import (
    DocumentoBruto,
    LoteBruto,
    PracaBruta,
    PublicacaoBruta,
)
from radar.enums import (
    EsferaJustica,
    JuntaComercial,
    ModalidadeLeilao,
    StatusLeiloeiro,
    StatusLote,
    TipoBem,
    TipoDocumento,
)
from radar.extraction.edital import ParserEdital
from radar.extraction.servico import _persistir_campos, aplicar_no_lote
from radar.ingest.geocode import GeocodificadorMunicipio
from radar.ingest.normalizador import normalizar
from radar.ingest.pipeline import (
    persistir_leiloeiro,
    persistir_lote,
    persistir_publicacao,
)
from radar.market.analise import analisar
from radar.market.fipe import carregar_espelho
from radar.market.fipezap import carregar_indice
from radar.models import Alerta, Documento, Usuario
from radar.normalizacao import FUSO_BRASILIA, formatar_cnj
from radar.scoring import score as motor_score

logger = logging.getLogger(__name__)

# Dentro do pacote: o seed roda a partir de uma instalacao, onde o diretorio
# de testes nao existe. Apontar para tests/ fazia o seed pular a extracao em
# silencio e gerar lotes sem nenhum campo extraido.
EDITAIS_DEMO = Path(__file__).resolve().parent / "data" / "editais_demo"
FONTE = "demo-leiloes-nordeste"

LEILOEIROS = [
    dict(nome="Ana Paula Ferreira Lima", matricula="12/2019", junta=JuntaComercial.JUCEAL,
         uf="AL", site_url="https://leiloes-exemplo-al.invalid"),
    dict(nome="Marcos Vinícius Andrade", matricula="05/2018", junta=JuntaComercial.JUCESE,
         uf="SE", site_url="https://leiloeiro-se-exemplo.invalid"),
    dict(nome="José Almeida Leiloeiro Oficial", matricula="31/2016",
         junta=JuntaComercial.JUCEPE, uf="PE", site_url="https://leiloes-pe-exemplo.invalid"),
    dict(nome="Helena Barbosa Leiloeira Oficial", matricula="18/2017",
         junta=JuntaComercial.JUCEB, uf="BA", site_url="https://leiloes-ba-exemplo.invalid"),
]


DIARIO_DEMO = "demo-diario-justica"


def _publicacoes() -> list[PublicacaoBruta]:
    """Publicações FICTÍCIAS de diário, para a agenda ter o que mostrar.

    Existem porque a aba "Diários" precisa exibir o caminho inteiro -- detecção,
    confiança, trecho literal, categoria do bem -- e nenhum conector real pode
    rodar sem rede. Os textos imitam a forma de um edital publicado no DJEN; os
    processos usam dígito verificador válido para exercitar o mesmo caminho de
    código, mas o resto é inventado e as URLs são .invalid.
    """
    urbano = _daqui(21, 10)
    urbano_2 = _daqui(35, 10)
    rural = _daqui(28, 9)
    rural_2 = _daqui(42, 9)
    federal = _daqui(17, 11)
    federal_2 = _daqui(31, 11)
    processo_al = formatar_cnj("4400123", "2025", "8", "02", "0001")
    processo_ba = formatar_cnj("4400456", "2025", "8", "05", "0001")
    processo_pe = formatar_cnj("4400789", "2025", "4", "05", "8300")

    def publicado(dias: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=dias)

    return [
        PublicacaoBruta(
            fonte_slug=DIARIO_DEMO,
            fonte_url="https://diario-exemplo.invalid/edicao/3421#p1",
            diario_slug=DIARIO_DEMO,
            diario_nome="Diário da Justiça (demonstração) - TJAL",
            identificador="demo-1",
            esfera=EsferaJustica.ESTADUAL,
            tribunal_sigla="TJAL",
            uf="AL",
            data_publicacao=publicado(4),
            numero_edicao="3421",
            caderno="Editais",
            orgao="2ª Vara Cível da Comarca de Maceió",
            municipio="Maceió",
            texto=(
                f"EDITAL DE LEILÃO JUDICIAL. O Juízo da 2ª Vara Cível da Comarca de "
                f"Maceió/AL, nos autos da execução nº {processo_al}, FAZ SABER que levará "
                "a público leilão eletrônico o BEM: sala comercial nº 12, situada na "
                "Avenida Fictícia, nº 500, bairro Jatiúca, Maceió/AL, em zona urbana, "
                "matrícula nº 88.100 do Registro de Imóveis, avaliada em R$ 320.000,00. "
                f"1ª praça em {urbano:%d/%m/%Y}, às 10h00; 2ª praça em "
                f"{urbano_2:%d/%m/%Y}, às 10h00, não sendo aceito lance inferior a 55% "
                "do valor da avaliação. Leiloeira pública oficial ANA PAULA FERREIRA "
                "LIMA, matrícula JUCEAL nº 12/2019."
            ),
        ),
        PublicacaoBruta(
            fonte_slug=DIARIO_DEMO,
            fonte_url="https://diario-exemplo.invalid/edicao/2210#p7",
            diario_slug=DIARIO_DEMO,
            diario_nome="Diário da Justiça (demonstração) - TJBA",
            identificador="demo-2",
            esfera=EsferaJustica.ESTADUAL,
            tribunal_sigla="TJBA",
            uf="BA",
            data_publicacao=publicado(2),
            numero_edicao="2210",
            caderno="Editais",
            orgao="Vara Única da Comarca de Feira de Santana",
            municipio="Feira de Santana",
            texto=(
                f"EDITAL DE 1ª E 2ª PRAÇA. O Juízo da Vara Única da Comarca de Feira de "
                f"Santana/BA, nos autos da execução fiscal nº {processo_ba}, torna público "
                "que levará a hasta pública o BEM: imóvel rural denominado Fazenda "
                "Exemplo, situado na zona rural do município de Feira de Santana/BA, com "
                "área de 48 hectares, CCIR nº 000.000.000.000-0, matrícula nº 3.045 do "
                "Registro de Imóveis, avaliado em R$ 1.250.000,00. Primeira praça em "
                f"{rural:%d/%m/%Y}, às 09h00. Segunda praça em {rural_2:%d/%m/%Y}, às "
                "09h00, admitindo-se lance não inferior a 60% da avaliação. Leiloeira "
                "pública oficial HELENA BARBOSA, matrícula JUCEB nº 18/2017."
            ),
        ),
        PublicacaoBruta(
            fonte_slug=DIARIO_DEMO,
            fonte_url="https://diario-exemplo.invalid/edicao/0912#p3",
            diario_slug=DIARIO_DEMO,
            diario_nome="Diário da Justiça (demonstração) - TRF5",
            identificador="demo-3",
            esfera=EsferaJustica.FEDERAL,
            tribunal_sigla="TRF5",
            uf=None,  # a UF sai da seção judiciária citada no texto
            data_publicacao=publicado(1),
            caderno="Editais",
            orgao="9ª Vara Federal da Seção Judiciária de Pernambuco",
            texto=(
                "EDITAL DE LEILÃO. A Justiça Federal, por meio da 9ª Vara Federal da "
                "Seção Judiciária de Pernambuco, nos autos da execução fiscal nº "
                f"{processo_pe}, FAZ SABER que realizará leilão judicial eletrônico do "
                "BEM: veículo automóvel marca Volkswagen, modelo Delivery 9.170, ano de "
                "fabricação 2016, ano modelo 2017, placa PQR2A34, avaliado em "
                f"R$ 132.000,00. 1ª praça em {federal:%d/%m/%Y}, às 11h00; 2ª praça em "
                f"{federal_2:%d/%m/%Y}, às 11h00, não se admitindo lance inferior a 50% "
                "da avaliação. Leiloeiro público oficial JOSÉ ALMEIDA, matrícula JUCEPE "
                "nº 31/2016."
            ),
        ),
        PublicacaoBruta(
            fonte_slug=DIARIO_DEMO,
            fonte_url="https://diario-exemplo.invalid/edicao/3421#p9",
            diario_slug=DIARIO_DEMO,
            diario_nome="Diário da Justiça (demonstração) - TJAL",
            identificador="demo-4",
            esfera=EsferaJustica.ESTADUAL,
            tribunal_sigla="TJAL",
            uf="AL",
            data_publicacao=publicado(4),
            numero_edicao="3421",
            caderno="Intimações",
            orgao="1ª Vara de Família da Comarca de Maceió",
            # Publicação que NÃO é leilão, de propósito: o painel precisa mostrar
            # que o detector descarta, e com que base.
            texto=(
                "INTIMAÇÃO. Ficam as partes intimadas do despacho de fls. 210 para que "
                "se manifestem, no prazo de 15 (quinze) dias, sobre os documentos "
                "juntados aos autos, sob pena de preclusão."
            ),
        ),
    ]


def _daqui(dias: int, hora: int = 14) -> datetime:
    base = datetime.now(UTC) + timedelta(days=dias)
    return base.replace(hour=hora + 3, minute=0, second=0, microsecond=0)


def _lotes() -> list[LoteBruto]:
    def cnj(seq: str, ano: str, tr: str, org: str) -> str:
        return formatar_cnj(seq, ano, "8", tr, org)

    return [
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/1",
            titulo="Apartamento 2 quartos no Farol, Maceió/AL",
            numero_lote="001", tipo_bem=TipoBem.IMOVEL,
            descricao=(
                "Apartamento residencial nº 302 com área privativa de 68,50 m² e área "
                "total de 92,30 m², 2 quartos, 1 vaga. Imóvel ocupado pelo executado."
            ),
            valor_avaliacao=Decimal("320000.00"),
            numero_processo=cnj("710702", "2021", "02", "0001"),
            comarca="Maceió", vara="3ª Vara Cível", cidade="Maceió", bairro="Farol",
            uf="AL", endereco="Rua Exemplo de Souza, 100", cep="57055-000",
            matricula_imovel="45.678", area_total_m2=Decimal("92.30"),
            leiloeiro_nome="Ana Paula Ferreira Lima", modalidade=ModalidadeLeilao.ELETRONICO,
            comissao_percentual=Decimal("5"), ocupado=True,
            onus=["hipoteca", "penhora"],
            pracas=[
                PracaBruta(1, _daqui(12), valor_minimo=Decimal("320000.00")),
                PracaBruta(2, _daqui(26), Decimal("50"), Decimal("160000.00")),
            ],
            documentos=[DocumentoBruto("https://exemplo.invalid/editais/1.pdf",
                                       TipoDocumento.EDITAL, "Edital de leilão")],
            extras={"edital_fixture": "edital_imovel_maceio"},
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/2",
            titulo="Fiat Uno Mille Economy 2014/2015 — Aracaju/SE",
            numero_lote="002", tipo_bem=TipoBem.VEICULO,
            descricao="Veículo sem chave e sem documento, não vistoriado, avarias de lataria.",
            valor_avaliacao=Decimal("28500.00"),
            numero_processo=cnj("8001234", "2023", "25", "0003"),
            comarca="Aracaju", vara="1ª Vara de Execuções Fiscais", cidade="Aracaju",
            uf="SE", marca="FIAT", modelo="UNO MILLE ECONOMY", ano_fabricacao=2014,
            ano_modelo=2015, combustivel="Flex", placa="OKZ1D23",
            leiloeiro_nome="Marcos Vinícius Andrade", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(5, 15), valor_minimo=Decimal("28500.00")),
                PracaBruta(2, _daqui(19, 15), Decimal("60"), Decimal("17100.00")),
            ],
            documentos=[DocumentoBruto("https://exemplo.invalid/editais/2.pdf",
                                       TipoDocumento.EDITAL, "Edital de leilão")],
            extras={"edital_fixture": "edital_veiculo_aracaju"},
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/3",
            titulo="Casa em Boa Viagem, Recife/PE — 180 m²",
            numero_lote="003", tipo_bem=TipoBem.IMOVEL,
            descricao="Casa desocupada, livre de ocupantes, com área privativa de 180,00 m².",
            valor_avaliacao=Decimal("980000.00"),
            numero_processo=cnj("55012", "2024", "17", "2001"),
            comarca="Recife", vara="5ª Vara Cível", cidade="Recife", bairro="Boa Viagem",
            uf="PE", endereco="Av. Exemplo, 2000", matricula_imovel="98.765",
            area_total_m2=Decimal("180.00"), ocupado=False,
            leiloeiro_nome="José Almeida Leiloeiro Oficial", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(2, 10), valor_minimo=Decimal("980000.00")),
                PracaBruta(2, _daqui(16, 10), Decimal("50"), Decimal("490000.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/4",
            titulo="Terreno urbano em Arapiraca/AL — 450 m²",
            numero_lote="004", tipo_bem=TipoBem.IMOVEL,
            descricao="Terreno urbano desocupado, sem construção.",
            valor_avaliacao=Decimal("175000.00"),
            numero_processo=cnj("330120", "2022", "02", "0058"),
            comarca="Arapiraca", cidade="Arapiraca", uf="AL",
            matricula_imovel="21.004", area_total_m2=Decimal("450.00"), ocupado=False,
            leiloeiro_nome="Ana Paula Ferreira Lima", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(40, 9), valor_minimo=Decimal("175000.00")),
                PracaBruta(2, _daqui(54, 9), Decimal("50"), Decimal("87500.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/5",
            titulo="Volkswagen Gol 1.0 2019 — Recife/PE",
            numero_lote="005", tipo_bem=TipoBem.VEICULO,
            descricao="Veículo em bom estado, com documentação regular e chave.",
            valor_avaliacao=Decimal("44000.00"),
            numero_processo=cnj("772201", "2023", "17", "0810"),
            comarca="Caruaru", cidade="Caruaru", uf="PE", marca="VOLKSWAGEN",
            modelo="GOL 1.0 FLEX", ano_fabricacao=2018, ano_modelo=2019,
            placa="PEA2B34", leiloeiro_nome="José Almeida Leiloeiro Oficial",
            comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(8, 11), valor_minimo=Decimal("44000.00")),
                PracaBruta(2, _daqui(22, 11), Decimal("50"), Decimal("22000.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/6",
            titulo="Apartamento na Ponta Verde, Maceió/AL — 110 m²",
            numero_lote="006", tipo_bem=TipoBem.IMOVEL,
            descricao="Apartamento com área privativa de 110,00 m², ocupado por terceiros.",
            valor_avaliacao=Decimal("1150000.00"),
            numero_processo=cnj("118822", "2020", "02", "0001"),
            comarca="Maceió", cidade="Maceió", bairro="Ponta Verde", uf="AL",
            matricula_imovel="77.100", area_total_m2=Decimal("110.00"), ocupado=True,
            onus=["alienacao_fiduciaria"],
            leiloeiro_nome="Ana Paula Ferreira Lima", comissao_percentual=Decimal("5"),
            status=StatusLote.SUSPENSO,
            pracas=[
                PracaBruta(1, _daqui(33, 15), valor_minimo=Decimal("1150000.00")),
                PracaBruta(2, _daqui(47, 15), Decimal("50"), Decimal("575000.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/7",
            titulo="Sala comercial no Jardins, Aracaju/SE — 45 m²",
            numero_lote="007", tipo_bem=TipoBem.IMOVEL,
            descricao="Sala comercial desocupada em edifício com elevador.",
            valor_avaliacao=Decimal("390000.00"),
            numero_processo=cnj("440302", "2022", "25", "0001"),
            comarca="Aracaju", cidade="Aracaju", bairro="Jardins", uf="SE",
            matricula_imovel="33.221", area_total_m2=Decimal("45.00"), ocupado=False,
            leiloeiro_nome="Marcos Vinícius Andrade", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(1, 16), valor_minimo=Decimal("390000.00")),
                PracaBruta(2, _daqui(15, 16), Decimal("50"), Decimal("195000.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/9",
            titulo="Apartamento na Pituba, Salvador/BA — 95 m²",
            numero_lote="009", tipo_bem=TipoBem.IMOVEL,
            descricao="Apartamento com área privativa de 95,00 m², desocupado, 3 quartos.",
            valor_avaliacao=Decimal("690000.00"),
            numero_processo=cnj("220145", "2023", "05", "0001"),
            comarca="Salvador", vara="8ª Vara Cível", cidade="Salvador", bairro="Pituba",
            uf="BA", endereco="Rua Exemplo da Pituba, 400", matricula_imovel="55.210",
            area_total_m2=Decimal("95.00"), ocupado=False,
            leiloeiro_nome="Helena Barbosa Leiloeira Oficial", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(4, 10), valor_minimo=Decimal("690000.00")),
                PracaBruta(2, _daqui(18, 10), Decimal("50"), Decimal("345000.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/10",
            titulo="Chevrolet Onix 1.0 2018 — Feira de Santana/BA",
            numero_lote="010", tipo_bem=TipoBem.VEICULO,
            descricao="Veículo com documentação regular, chave única.",
            valor_avaliacao=Decimal("47000.00"),
            numero_processo=cnj("660033", "2024", "05", "0274"),
            comarca="Feira de Santana", cidade="Feira de Santana", uf="BA",
            marca="CHEVROLET", modelo="ONIX 1.0 FLEX", ano_fabricacao=2018, ano_modelo=2018,
            leiloeiro_nome="Helena Barbosa Leiloeira Oficial", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(11, 14), valor_minimo=Decimal("47000.00")),
                PracaBruta(2, _daqui(25, 14), Decimal("50"), Decimal("23500.00")),
            ],
        ),
        LoteBruto(
            fonte_slug=FONTE, fonte_url="https://exemplo.invalid/lote/8",
            titulo="Honda CG 160 Fan 2021 — Olinda/PE",
            numero_lote="008", tipo_bem=TipoBem.VEICULO,
            descricao="Motocicleta recolhida em depósito, sem chave.",
            valor_avaliacao=Decimal("13800.00"),
            numero_processo=cnj("991100", "2024", "17", "0730"),
            comarca="Olinda", cidade="Olinda", uf="PE", marca="HONDA",
            modelo="CG 160 FAN", ano_fabricacao=2021, ano_modelo=2021,
            leiloeiro_nome="José Almeida Leiloeiro Oficial", comissao_percentual=Decimal("5"),
            pracas=[
                PracaBruta(1, _daqui(6, 9), valor_minimo=Decimal("13800.00")),
                PracaBruta(2, _daqui(20, 9), Decimal("50"), Decimal("6900.00")),
            ],
        ),
    ]


def popular(sessao: Session, com_usuario: bool = True) -> dict:
    """Cria dados de demonstracao. Idempotente: rodar de novo nao duplica."""
    carregar_espelho(sessao)
    carregar_indice(sessao)

    for dados in LEILOEIROS:
        persistir_leiloeiro(
            sessao,
            {
                "nome": dados["nome"],
                "matricula": dados["matricula"],
                "junta": str(dados["junta"]),
                "uf": dados["uf"],
                "status": str(StatusLeiloeiro.ATIVO),
                "site_url": dados["site_url"],
                "email": None,
                "telefone": None,
                "comarcas": [],
                "fonte_slug": "seed",
                "fonte_url": "https://exemplo.invalid",
            },
        )

    geocodificador = GeocodificadorMunicipio()
    parser = ParserEdital()
    criados = 0

    for bruto in _lotes():
        norm = normalizar(bruto, geocodificador)
        lote, novo, _, _ = persistir_lote(sessao, norm)
        criados += int(novo)

        # Quando ha edital de exemplo, roda a extracao real sobre o texto para
        # que a tela mostre campos com confianca e evidencia de verdade.
        nome_fixture = bruto.extras.get("edital_fixture")
        if nome_fixture and lote.documentos:
            caminho = EDITAIS_DEMO / f"{nome_fixture}.txt"
            if not caminho.exists():
                raise FileNotFoundError(
                    f"edital de demonstracao ausente: {caminho}. Sem ele o seed "
                    "geraria lotes sem campos extraidos, o que esconde metade da UI."
                )
            if True:
                documento = lote.documentos[0]
                documento.texto = _sincronizar_datas_do_edital(
                    caminho.read_text(encoding="utf-8"), bruto
                )
                documento.paginas = 1
                documento.extraido_em = datetime.now(UTC)
                resultado = parser.extrair(documento.texto)
                documento.parser_versao = resultado.parser_versao
                sessao.flush()
                _persistir_campos(sessao, documento, resultado)
                aplicar_no_lote(lote, resultado)

        sessao.flush()
        sincronizar_eventos(sessao, lote)
        analisar(sessao, lote)
        sessao.flush()
        motor_score.calcular(sessao, lote)

    # Publicações de diário: passam pelo MESMO detector e pela mesma persistência
    # da coleta real, para a tela de demonstração não mostrar um caminho fictício.
    detectadas = 0
    for publicacao in _publicacoes():
        dados = _serializar_publicacao_demo(publicacao)
        resumo = persistir_publicacao(sessao, dados, geocodificador=geocodificador)
        if resumo.virou_lote:
            detectadas += 1
            sessao.flush()
            sincronizar_eventos(sessao, resumo.lote)
            analisar(sessao, resumo.lote)
            sessao.flush()
            motor_score.calcular(sessao, resumo.lote)

    usuario = None
    if com_usuario:
        usuario = sessao.scalar(select(Usuario).where(Usuario.email == "demo@example.org"))
        if usuario is None:
            usuario = registrar_usuario(
                sessao, "demo@example.org", "radar-demo-2026", "Investidor Demo"
            )
            sessao.add(
                Alerta(
                    usuario_id=usuario.id,
                    nome="Imóveis em Maceió com desconto",
                    criterios={
                        "uf": ["AL"],
                        "tipo_bem": ["IMOVEL"],
                        "desconto_minimo": 20,
                    },
                )
            )

    sessao.flush()
    return {
        "lotes_criados": criados,
        "publicacoes_diario": len(_publicacoes()),
        "publicacoes_detectadas": detectadas,
        "documentos": sessao.scalar(
            select(Documento).limit(1)
        )
        is not None,
        "usuario_demo": usuario.email if usuario else None,
        "senha_demo": "radar-demo-2026" if usuario else None,
    }


def _serializar_publicacao_demo(publicacao: PublicacaoBruta) -> dict:
    """Mesmo formato que a fila entrega ao pipeline, sem passar pela fila."""
    from radar.ingest.pipeline import _serializar_publicacao

    return _serializar_publicacao(publicacao)


# Datas fixas dos editais de exemplo, substituidas pelas datas geradas.
_DATAS_FIXTURE = {1: "10/11/2026", 2: "24/11/2026"}


def _sincronizar_datas_do_edital(texto: str, bruto: LoteBruto) -> str:
    """Alinha as datas do edital de exemplo com as pracas geradas pelo seed.

    O texto do edital tem datas fixas; as pracas do seed sao relativas a hoje,
    para que a demonstracao nunca mostre so leiloes vencidos. Sem esta
    substituicao, a tela exibiria "1a praca: 25/09" no calendario e
    "Data da 1a praca: 10/11" nos campos extraidos do MESMO lote -- o tipo de
    inconsistencia que destroi a confianca em tudo o mais que a tela afirma.
    """
    for praca in bruto.pracas:
        alvo = _DATAS_FIXTURE.get(praca.ordem)
        if not alvo or praca.data_hora is None:
            continue
        local = praca.data_hora + timedelta(hours=FUSO_BRASILIA)
        texto = texto.replace(alvo, f"{local:%d/%m/%Y}")
    return texto
