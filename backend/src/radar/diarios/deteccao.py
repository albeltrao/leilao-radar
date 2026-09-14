"""Decide se uma publicação de diário anuncia um leilão -- e extrai o que dá.

Por que isso é um módulo de ingestão e não do conector: o conector do diário só
sabe baixar e separar publicações. Deduzir "isto é um leilão" é dedução, e neste
repositório dedução mora em ``radar.ingest`` / ``radar.diarios``, nunca no
coletor (ver o cabeçalho de ``collectors/dto.py``).

O detector devolve confiança e os trechos literais que a sustentam. Ele NÃO
devolve um booleano solitário: uma publicação classificada como leilão com 0,58
de confiança aparece na tela marcada como não confirmada, e o usuário lê a mesma
frase que o sistema leu. O limiar é configurável porque diário é ruidoso e cada
tribunal escreve de um jeito.

Um leilão detectado no diário raramente traz o bem detalhado -- o diário publica
"os bens penhorados às fls. 120". Por isso o lote gerado aqui é magro de
propósito e depende do edital para engordar (seção 7). O que ele acrescenta, e é
o ponto do recurso, é a **data** e a **existência** do leilão, em fonte oficial,
antes de qualquer site de leiloeiro publicar.

ARMADILHA: os padrões rodam sobre texto sem acento. "1ª praça" chega como
"1a praca". Padrão com "ª" literal nunca casa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from radar.collectors.dto import DocumentoBruto, LoteBruto, PracaBruta, PublicacaoBruta
from radar.diarios.classificacao import ClassificacaoBem, classificar_bem
from radar.enums import (
    EsferaJustica,
    ModalidadeLeilao,
    NaturezaBem,
    TipoBem,
    TipoDocumento,
)
from radar.extraction.campos import Achado, Contexto, ResultadoExtracao, contexto
from radar.extraction.edital import ParserEdital
from radar.jurisdicoes import NOME_POR_UF
from radar.normalizacao import (
    extrair_numero_cnj,
    hash_conteudo,
    limpar_espacos,
    remover_cpf,
)

VERSAO_DETECTOR = "1.0"

# Acima disto a publicação entra como leilão. Abaixo, fica guardada como
# publicação lida e não vira lote -- o número aparece no painel de fontes, então
# calibrar o limiar é observável, não adivinhação.
LIMIAR_PADRAO = 0.55


@dataclass(frozen=True, slots=True)
class Termo:
    padrao: str
    peso: float
    rotulo: str


# Expressões que, sozinhas, já dizem "isto é um leilão judicial".
_FORTES: tuple[Termo, ...] = (
    Termo(r"\bedital\s+de\s+leil(?:ao|oes)\b", 0.50, "edital de leilão"),
    Termo(r"\bedital\s+de\s+(?:1a|primeira|2a|segunda|unica)\s+praca\b", 0.50, "edital de praça"),
    Termo(r"\bhasta\s+publica\b", 0.50, "hasta pública"),
    Termo(r"\bleilao\s+(?:judicial|eletronico|publico|presencial|hibrido)\b", 0.48, "leilão judicial"),
    Termo(r"\balienacao\s+judicial\b", 0.45, "alienação judicial"),
    Termo(r"\b(?:1a|primeira|2a|segunda|unica)\s+(?:praca|hasta)\b", 0.40, "praça designada"),
    Termo(r"\bcarta\s+de\s+arremata[cç]ao\b", 0.40, "carta de arrematação"),
    Termo(r"\barremat(?:acao|ante|ar|e|ado)\b", 0.32, "arrematação"),
)

# Sozinhas não bastam; somam.
_MEDIOS: tuple[Termo, ...] = (
    Termo(r"\blance\s+(?:minimo|inicial|vencedor)\b", 0.25, "lance mínimo"),
    Termo(r"\bleiloeir[oa]\b", 0.22, "leiloeiro"),
    Termo(r"\bleil(?:ao|oes)\b", 0.20, "leilão"),
    Termo(r"\bvalor\s+d[ae]\s+avaliacao\b|\bavaliad[oa]\s+em\b", 0.15, "avaliação"),
    Termo(r"\bbens?\s+penhorad[oa]s?\b", 0.15, "bem penhorado"),
)

# Leilão que não é judicial. Sem isto, o diário da Justiça Federal encheria a
# agenda de leilão de energia elétrica e de pregão de licitação.
_RUIDO: tuple[Termo, ...] = (
    Termo(r"\bleilao\s+de\s+energia\b", 0.60, "leilão de energia"),
    Termo(r"\bleilao\s+reverso\b", 0.50, "leilão reverso"),
    Termo(r"\bpregao\s+(?:eletronico|presencial)\b", 0.35, "pregão licitatório"),
    Termo(r"\bleilao\s+beneficente\b", 0.45, "leilão beneficente"),
)

_CONTEXTO_JUDICIAL = re.compile(
    r"\bvara\b|\bjuiz|\bcomarca\b|\bexequente\b|\bexecutad[oa]\b|\bexecucao\s+fiscal\b"
    r"|\bcumprimento\s+de\s+sentenca\b|\bsecao\s+judiciaria\b|\bautos\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class LeilaoDetectado:
    confianca: float
    termos: list[str] = field(default_factory=list)
    evidencias: list[str] = field(default_factory=list)
    ruidos: list[str] = field(default_factory=list)
    contexto_judicial: bool = False
    extracao: ResultadoExtracao = field(default_factory=ResultadoExtracao)
    classificacao: ClassificacaoBem = field(default_factory=ClassificacaoBem)
    numero_processo: str | None = None
    trecho_bem: str | None = None
    versao: str = VERSAO_DETECTOR

    @property
    def revisao_necessaria(self) -> bool:
        """Confiança baixa, sem contexto judicial ou com ruído: alguém confere."""
        return self.confianca < 0.75 or not self.contexto_judicial or bool(self.ruidos)

    @property
    def evidencia_principal(self) -> str:
        return self.evidencias[0] if self.evidencias else ""


def _somar(ctx: Contexto, termos: tuple[Termo, ...]) -> tuple[float, list[str], list[str]]:
    total = 0.0
    rotulos: list[str] = []
    provas: list[str] = []
    for termo in termos:
        m = re.search(termo.padrao, ctx.busca, re.IGNORECASE)
        if m is None:
            continue
        total += termo.peso
        rotulos.append(termo.rotulo)
        provas.append(ctx.evidencia(m.start(), m.end()))
    return total, rotulos, provas


def detectar_leilao(
    texto: str | None, limiar: float = LIMIAR_PADRAO
) -> LeilaoDetectado | None:
    """Devolve o leilão detectado, ou None se a publicação não parece leilão."""
    if not texto or len(texto.strip()) < 40:
        return None

    ctx = contexto(texto)
    # Porta de entrada barata: sem radical de leilão/hasta/praça/arrematação não
    # há o que pontuar, e o diário inteiro passa por aqui todo dia.
    if not re.search(r"leil|hasta|\bpraca\b|arremat", ctx.busca):
        return None

    peso_forte, rot_fortes, prov_fortes = _somar(ctx, _FORTES)
    peso_medio, rot_medios, prov_medios = _somar(ctx, _MEDIOS)
    peso_ruido, rot_ruido, _ = _somar(ctx, _RUIDO)

    confianca = min(0.95, peso_forte + peso_medio) - peso_ruido
    judicial = bool(_CONTEXTO_JUDICIAL.search(ctx.busca))
    if not judicial:
        # "Leilão" sem nenhuma marca de processo pode ser notícia administrativa.
        confianca -= 0.20
    confianca = round(max(0.0, min(0.95, confianca)), 3)

    if confianca < limiar:
        return None

    extracao = ParserEdital().extrair(texto)
    numero = extrair_numero_cnj(texto)
    trecho_bem = _trecho_do_bem(ctx)
    return LeilaoDetectado(
        confianca=confianca,
        termos=rot_fortes + rot_medios,
        evidencias=prov_fortes + prov_medios,
        ruidos=rot_ruido,
        contexto_judicial=judicial,
        extracao=extracao,
        classificacao=classificar_bem(trecho_bem or texto),
        numero_processo=numero,
        trecho_bem=trecho_bem,
    )


_RE_BEM = re.compile(
    r"(?:bem|bens|im[o]vel|lote)\s*(?:penhorad[oa]s?|a\s+ser\s+leiload[oa]s?|"
    r"objeto\s+d[oa]\s+leilao)?\s*[:;-]\s*(.{40,600})",
    re.IGNORECASE | re.DOTALL,
)


def _trecho_do_bem(ctx: Contexto) -> str | None:
    """Recorta a descrição do bem, quando a publicação a traz destacada.

    Classificar sobre o trecho do bem, e não sobre a publicação inteira, evita
    que o endereço do fórum ("Rua do Imperador, sede da 3ª Vara") conte como
    sinal de imóvel urbano do lote.
    """
    m = _RE_BEM.search(ctx.busca)
    if m is None:
        return None
    return limpar_espacos(ctx.original[m.start(1) : m.end(1)])


# ---------------------------------------------------------------------------
# Publicação detectada -> LoteBruto
# ---------------------------------------------------------------------------


def _numerico(extracao: ResultadoExtracao, nome: str) -> Decimal | None:
    achado = extracao.obter(nome)
    return achado.valor_numerico if achado else None


def _texto(extracao: ResultadoExtracao, nome: str) -> str | None:
    achado = extracao.obter(nome)
    return achado.valor_texto if achado else None


def _data(extracao: ResultadoExtracao, nome: str) -> datetime | None:
    achado = extracao.obter(nome)
    return achado.valor_data if achado else None


def _tipo_bem(classificacao: ClassificacaoBem) -> TipoBem:
    if classificacao.natureza is NaturezaBem.IMOVEL:
        return TipoBem.IMOVEL
    if classificacao.natureza is NaturezaBem.MOVEL:
        veicular = {"veículo", "identificação veicular"}
        if any(s.rotulo in veicular for s in classificacao.sinais):
            return TipoBem.VEICULO
    return TipoBem.OUTRO


_RE_SECAO = re.compile(
    r"(?:sub)?se[cç][aã]o\s+judici[aá]ria\s+d[eoa]s?\s+([A-Za-zÀ-ÿ'\s-]{3,40})", re.IGNORECASE
)


def uf_da_secao_judiciaria(texto: str | None) -> str | None:
    """"Seção Judiciária de Alagoas" -> "AL".

    Existe porque o código TR do número CNJ **não** dá a UF de processo federal:
    o TRF5 responde por seis estados. Sem isto, um lote da Justiça Federal de
    Pernambuco entraria sem UF e sumiria de todo filtro por estado.
    """
    if not texto:
        return None
    m = _RE_SECAO.search(texto)
    if m is None:
        return None
    alvo = limpar_espacos(m.group(1)) or ""
    for uf, nome in NOME_POR_UF.items():
        if nome.lower() in alvo.lower():
            return uf
    return None


def _titulo(publicacao: PublicacaoBruta, detectado: LeilaoDetectado) -> str:
    """Título legível de um lote que veio do diário.

    Prioriza o trecho do bem, cortado na primeira vírgula ou ponto: "veículo
    automóvel marca Volkswagen" diz mais numa lista do que "Leilão judicial · 9ª
    Vara Federal da Seção Judiciária de Pernambuco", que era o que saía antes.
    O órgão continua no título, depois do bem, porque desempata homônimos.
    """
    bem = detectado.trecho_bem or _texto(detectado.extracao, "endereco")
    if bem:
        # Ponto so corta quando ha espaco depois: "Delivery 9.170" e um modelo,
        # nao o fim da frase.
        bem = limpar_espacos(re.split(r";|\.\s| - ", bem)[0])
    partes = [p for p in (bem, publicacao.orgao or publicacao.municipio) if p]
    if not partes:
        return "Leilão judicial"
    return " · ".join(p[:140] for p in partes)[:300]


def para_lote_bruto(
    publicacao: PublicacaoBruta, detectado: LeilaoDetectado, *, max_descricao: int = 4000
) -> LoteBruto:
    """Monta o lote magro que a publicação sustenta. Nada aqui é chute.

    O que a publicação não disser fica vazio -- em especial o lance mínimo da 2ª
    praça, que só é preenchido se o percentual estiver escrito no texto. A regra
    dos 50% é costume, não lei, e este sistema não a assume (ver CLAUDE.md).
    """
    extracao = detectado.extracao
    pracas: list[PracaBruta] = []
    for ordem in (1, 2):
        data = _data(extracao, f"data_praca_{ordem}")
        valor = _numerico(extracao, f"valor_minimo_praca_{ordem}")
        pct = _numerico(extracao, "percentual_minimo_segunda_praca") if ordem == 2 else None
        if data is None and valor is None and pct is None:
            continue
        pracas.append(
            PracaBruta(ordem=ordem, data_hora=data, percentual_minimo=pct, valor_minimo=valor)
        )

    uf = publicacao.uf or uf_da_secao_judiciaria(publicacao.texto)
    # LGPD (seção 11): o texto do diário cita as partes. CPF nunca é gravado, e
    # guardamos só o recorte que sustenta a detecção, não o caderno inteiro.
    descricao = (remover_cpf(limpar_espacos(publicacao.texto)) or "")[:max_descricao]
    classificacao = detectado.classificacao

    return LoteBruto(
        fonte_slug=publicacao.fonte_slug,
        fonte_url=publicacao.fonte_url,
        titulo=_titulo(publicacao, detectado),
        tipo_bem=_tipo_bem(classificacao),
        descricao=descricao,
        valor_avaliacao=_numerico(extracao, "valor_avaliacao"),
        pracas=pracas,
        comissao_percentual=_numerico(extracao, "comissao_leiloeiro"),
        numero_processo=detectado.numero_processo or publicacao.numero_processo,
        tribunal_sigla=publicacao.tribunal_sigla,
        comarca=_texto(extracao, "comarca") or publicacao.municipio,
        vara=_texto(extracao, "vara") or publicacao.orgao,
        leiloeiro_nome=_texto(extracao, "leiloeiro_nome"),
        leiloeiro_matricula=_texto(extracao, "leiloeiro_matricula"),
        modalidade=ModalidadeLeilao.DESCONHECIDA,
        uf=uf,
        cidade=_texto(extracao, "cidade"),
        endereco=_texto(extracao, "endereco"),
        bairro=_texto(extracao, "bairro"),
        matricula_imovel=_texto(extracao, "matricula_imovel"),
        cartorio=_texto(extracao, "cartorio"),
        area_total_m2=_numerico(extracao, "area_total_m2"),
        documentos=[
            DocumentoBruto(
                url=publicacao.fonte_url,
                tipo=TipoDocumento.PUBLICACAO_DIARIO,
                titulo=f"{publicacao.diario_nome} de {_dia(publicacao.data_publicacao)}",
            )
        ],
        extras={
            "origem": "diario",
            "diario_slug": publicacao.diario_slug,
            "diario_nome": publicacao.diario_nome,
            "esfera": str(publicacao.esfera),
            "publicacao_identificador": publicacao.identificador,
            "publicado_em": _iso(publicacao.data_publicacao),
            "confianca_deteccao": detectado.confianca,
            "termos_deteccao": detectado.termos[:8],
            "evidencia_deteccao": detectado.evidencia_principal,
            "natureza_bem": str(classificacao.natureza),
            "zona_imovel": str(classificacao.zona),
            "categoria_bem": classificacao.categoria,
            "chave_fallback": hash_conteudo(
                publicacao.diario_slug, publicacao.identificador
            ),
        },
    )


def _dia(quando: datetime | None) -> str:
    return quando.strftime("%d/%m/%Y") if quando else "data não informada"


def _iso(quando: datetime | None) -> str | None:
    return quando.isoformat() if quando else None


def achados_da_deteccao(detectado: LeilaoDetectado) -> list[Achado]:
    """Campos que a detecção em si produz, além dos do parser de edital."""
    saida = [
        Achado(
            nome="leilao_detectado_em_diario",
            valor_booleano=True,
            confianca=detectado.confianca,
            evidencia=detectado.evidencia_principal,
        )
    ]
    saida.extend(detectado.classificacao.achados())
    saida.extend(detectado.extracao.achados)
    return saida


def esfera_do_texto(texto: str | None) -> EsferaJustica:
    """Fallback quando o conector não declara a esfera."""
    if not texto:
        return EsferaJustica.DESCONHECIDA
    alvo = texto.lower()
    if "justica federal" in alvo or "justiça federal" in alvo or "secao judiciaria" in alvo:
        return EsferaJustica.FEDERAL
    if "tribunal de justica" in alvo or "tribunal de justiça" in alvo:
        return EsferaJustica.ESTADUAL
    return EsferaJustica.DESCONHECIDA
