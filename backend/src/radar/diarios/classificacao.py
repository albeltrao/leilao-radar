"""Classifica o bem anunciado em móvel/imóvel e, sendo imóvel, rural/urbano.

Dois eixos, porque foi isso que se pediu da agenda: "móveis e imóveis, rurais e
urbanos". O eixo natureza (arts. 79 a 84 do Código Civil) não sai de ``TipoBem``:
lá um trator e um rebanho caem em OUTRO, e OUTRO não diz se é móvel.

Como todo campo derivado neste sistema, a classificação sai com confiança, método
e o trecho literal que a sustenta. Quem lê a tela vê *por que* aquele lote foi
parar na aba "imóveis rurais" e pode discordar olhando a mesma frase.

Quando os sinais brigam -- "sítio" e "zona urbana" na mesma publicação, o que
acontece de verdade em imóvel dentro do perímetro urbano expandido -- o resultado
é INDEFINIDA com revisão marcada, não o sinal mais forte. Chutar um lado aqui
mandaria o lote para a aba errada com cara de certeza.

ARMADILHA: o casamento roda sobre texto sem acento (ver ``Contexto``), onde "1ª"
virou "1a" e "nº" virou "no". Padrão que procure "º" literal nunca casa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from radar.enums import MetodoExtracao, NaturezaBem, TipoBem, ZonaImovel
from radar.extraction.campos import Achado, Contexto, contexto

VERSAO_CLASSIFICADOR = "1.0"

# Teto deliberado: nenhuma classificação por regra chega a 1.0. A frase pode
# estar descrevendo o imóvel vizinho, o bem de outro lote da mesma publicação.
CONF_MAXIMA = 0.95
# Abaixo disto o campo vai para revisão (LIMIAR_REVISAO em campos.py é 0.70).
CONF_SINAL_FRACO = 0.55


@dataclass(frozen=True, slots=True)
class Termo:
    padrao: str
    peso: float
    rotulo: str
    peso_locativo: float | None = None
    """Peso a usar quando o termo aparece como LUGAR, não como o bem.

    "Trator localizado na Fazenda Boa Vista" cita uma fazenda, mas o bem é o
    trator. Sem isto, "fazenda" (0,90) empatava tecnicamente com "máquina"
    (0,82) e o trator saía como natureza indefinida -- uma dúvida inventada
    pela regra, não observada no texto.
    """


# Preposição de lugar logo antes do termo: "na Fazenda", "situado no Sítio".
_LOCATIVO = re.compile(
    r"(?:localizad[oa]s?|situad[oa]s?|sediad[oa]s?|instalad[oa]s?|\bem|\bn[oa])\s+$",
    re.IGNORECASE,
)


# Os padrões abaixo são escritos SEM ACENTO de propósito: eles rodam contra
# ``Contexto.busca``, onde "imóvel" já virou "imovel" e "1ª" virou "1a". Padrão
# com acento literal nunca casa. A evidência exibida sai do texto original.

# -- Natureza: móvel x imóvel ------------------------------------------------

_TERMOS_IMOVEL: tuple[Termo, ...] = (
    Termo(r"\bbens?\s+imove(?:l|is)\b", 0.95, "bem imóvel"),
    Termo(r"\bimove(?:l|is)\b", 0.90, "imóvel"),
    Termo(r"\bapartamento\b|\bapto\.?\b", 0.90, "apartamento"),
    Termo(r"\bterreno\b|\bgleba\b|\b(?:area|data)\s+de\s+terras?\b", 0.88, "terreno"),
    Termo(
        r"\bsitio\b|\bfazenda\b|\bchacara\b|\bgranja\b|\bengenho\b",
        0.90,
        "sítio/fazenda",
        peso_locativo=0.45,
    ),
    Termo(
        r"\bsala\s+comercial\b|\bloja\b|\bgalpao\b|\bbarracao\b|\bpredio\b"
        r"|\bedificio\b|\bsobrado\b|\bkitnet\b|\bcobertura\b",
        0.85,
        "edificação",
    ),
    Termo(
        r"\bfracao\s+ideal\b|\bunidade\s+autonoma\b|\b(?:vaga|box)\s+de\s+garagem\b",
        0.85,
        "fração ideal",
    ),
    Termo(r"\bregistro\s+de\s+imoveis\b|\bcartorio\s+de\s+imoveis\b", 0.88, "registro de imóveis"),
    Termo(r"\bmatricula\s+(?:no\s*)?[\d.]{3,}", 0.80, "matrícula"),
    Termo(r"\bbenfeitorias?\b|\balvenaria\b", 0.62, "benfeitoria"),
    Termo(r"\biptu\b", 0.60, "IPTU"),
    Termo(r"\bcasa\b", 0.70, "casa"),
)

_TERMOS_MOVEL: tuple[Termo, ...] = (
    Termo(r"\bbens?\s+move(?:l|is)\b", 0.93, "bem móvel"),
    Termo(
        r"\bveiculos?\b|\bautomove(?:l|is)\b|\bmotocicletas?\b|\bmotoneta\b"
        r"|\bcaminha(?:o|es)\b|\bcamionet[ae]\b|\bonibus\b|\bsemirreboque\b|\breboque\b",
        0.92,
        "veículo",
    ),
    Termo(r"\bchassi\b|\brenavam\b|\bplaca\s+[a-z]{3}", 0.90, "identificação veicular"),
    Termo(
        r"\btrator(?:es)?\b|\bcolheitadeira\b|\bretroescavadeira\b|\bempilhadeira\b"
        r"|\bmaquinas?\b|\bmaquinario\b|\bequipamentos?\b",
        0.82,
        "máquina",
    ),
    Termo(
        r"\bsemoventes?\b|\bbovinos?\b|\bequinos?\b|\bcaprinos?\b|\bsuinos?\b"
        r"|\brebanho\b|\bgado\b",
        0.88,
        "semovente",
    ),
    Termo(r"\bembarcacao\b|\blancha\b|\baeronave\b", 0.85, "embarcação/aeronave"),
    Termo(r"\bmobiliario\b|\bestoque\s+de\s+mercadorias\b", 0.80, "mobiliário/estoque"),
    Termo(r"\b(?:quotas?|cotas?)\s+sociais\b|\bacoes\s+da\s+empresa\b", 0.72, "quotas"),
    Termo(r"\bjoias?\b|\bobra\s+de\s+arte\b", 0.70, "joia/obra de arte"),
)

# -- Zona: rural x urbana ----------------------------------------------------

_TERMOS_RURAL: tuple[Termo, ...] = (
    # O substantivo qualificado direto -- "terreno rural", "gleba rural" -- e tao
    # forte quanto "zona rural" e muito mais comum em titulo de lote. Sem ele,
    # "Terreno urbano em Arapiraca" caia em zona indefinida.
    Termo(
        r"\b(?:imove(?:l|is)|terrenos?|lotes?|glebas?|areas?|propriedades?|posses?)"
        r"\s+rura(?:l|is)\b",
        0.95,
        "imóvel rural",
    ),
    Termo(r"\b(?:zona|area|perimetro|setor)\s+rural\b", 0.92, "zona rural"),
    Termo(r"\bccir\b|\bnirf\b|\bincra\b|\bitr\b", 0.88, "cadastro rural"),
    Termo(r"\bsitio\b|\bfazenda\b|\bchacara\b|\bgranja\b|\bengenho\b", 0.85, "sítio/fazenda"),
    Termo(r"\bgleba\s+(?:de\s+terras?|rural)\b|\blote\s+rural\b", 0.88, "gleba rural"),
    Termo(r"\bhectares?\b|\balqueires?\b|\btarefas?\s+de\s+terras?\b", 0.85, "medida agrária"),
    Termo(r"\bcadastro\s+ambiental\s+rural\b", 0.85, "CAR"),
    Termo(r"\bpovoado\b|\bassentamento\b", 0.60, "povoado"),
)

_TERMOS_URBANA: tuple[Termo, ...] = (
    Termo(
        r"\b(?:imove(?:l|is)|terrenos?|lotes?|glebas?|areas?|propriedades?|predios?)"
        r"\s+urban[ao]s?\b",
        0.92,
        "imóvel urbano",
    ),
    Termo(r"\b(?:zona|area|perimetro|setor)\s+urban[ao]\b", 0.92, "zona urbana"),
    Termo(r"\bapartamento\b|\bapto\.?\b|\bcondominio\s+edilicio\b", 0.85, "apartamento"),
    Termo(r"\biptu\b", 0.75, "IPTU"),
    Termo(r"\bquadra\s+[\w-]+,?\s*lote\b", 0.70, "quadra e lote"),
    Termo(
        r"\brua\b|\bavenida\b|\bav\.\s|\btravessa\b|\balameda\b|\bloteamento\b",
        0.62,
        "logradouro",
    ),
    Termo(r"\bbairro\b|\bcep\b", 0.58, "bairro/CEP"),
)


@dataclass(slots=True)
class Sinal:
    rotulo: str
    peso: float
    evidencia: str


@dataclass(slots=True)
class ClassificacaoBem:
    natureza: NaturezaBem = NaturezaBem.INDEFINIDA
    zona: ZonaImovel = ZonaImovel.INDEFINIDA
    confianca_natureza: float = 0.0
    confianca_zona: float = 0.0
    evidencia_natureza: str | None = None
    evidencia_zona: str | None = None
    sinais: list[Sinal] = field(default_factory=list)
    conflito_zona: bool = False
    versao: str = VERSAO_CLASSIFICADOR

    @property
    def categoria(self) -> str:
        """Chave da aba da agenda: uma só string para agrupar e filtrar."""
        if self.natureza is NaturezaBem.IMOVEL:
            if self.zona is ZonaImovel.RURAL:
                return "IMOVEL_RURAL"
            if self.zona is ZonaImovel.URBANA:
                return "IMOVEL_URBANO"
            return "IMOVEL_INDEFINIDO"
        if self.natureza is NaturezaBem.MOVEL:
            return "MOVEL"
        return "INDEFINIDO"

    def achados(self) -> list[Achado]:
        """Vira ``CampoExtraido`` pelo mesmo caminho dos campos do edital."""
        saida: list[Achado] = []
        if self.natureza is not NaturezaBem.INDEFINIDA:
            saida.append(
                Achado(
                    nome="natureza_bem",
                    valor_texto=str(self.natureza),
                    confianca=self.confianca_natureza,
                    evidencia=self.evidencia_natureza or "",
                    metodo=MetodoExtracao.REGRA,
                )
            )
        if self.zona is not ZonaImovel.INDEFINIDA:
            saida.append(
                Achado(
                    nome="zona_imovel",
                    valor_texto=str(self.zona),
                    confianca=self.confianca_zona,
                    evidencia=self.evidencia_zona or "",
                    metodo=MetodoExtracao.REGRA,
                )
            )
        return saida


def _coletar(ctx: Contexto, termos: tuple[Termo, ...]) -> list[Sinal]:
    sinais: list[Sinal] = []
    for termo in termos:
        m = re.search(termo.padrao, ctx.busca, re.IGNORECASE)
        if m is None:
            continue
        peso = termo.peso
        if termo.peso_locativo is not None and _LOCATIVO.search(
            ctx.busca[max(0, m.start() - 18) : m.start()]
        ):
            peso = termo.peso_locativo
        sinais.append(
            Sinal(rotulo=termo.rotulo, peso=peso, evidencia=ctx.evidencia(m.start(), m.end()))
        )
    return sorted(sinais, key=lambda s: -s.peso)


def _decidir(a: list[Sinal], b: list[Sinal]) -> tuple[bool | None, float, str | None, bool]:
    """Escolhe entre dois conjuntos de sinais. Devolve (a_venceu, conf, prova, conflito).

    ``a_venceu`` é None quando ninguém venceu -- nenhum sinal, ou empate técnico
    entre os dois lados. Empate técnico não vira "o mais forte leva": vira
    INDEFINIDA, porque a diferença entre 0.90 e 0.88 não é conhecimento.
    """
    melhor_a = a[0].peso if a else 0.0
    melhor_b = b[0].peso if b else 0.0
    if not a and not b:
        return None, 0.0, None, False

    conflito = bool(a and b) and abs(melhor_a - melhor_b) < 0.15
    if conflito:
        prova = " | ".join(s.evidencia for s in (a[0], b[0]))
        return None, round(min(melhor_a, melhor_b) * 0.5, 3), prova, True

    vencedores, perdedores = (a, b) if melhor_a >= melhor_b else (b, a)
    confianca = vencedores[0].peso
    # Dois termos independentes concordando valem um pouco mais que um só.
    if len(vencedores) > 1:
        confianca += 0.04
    # O outro lado apareceu, ainda que mais fraco: a dúvida entra no número.
    if perdedores:
        confianca -= 0.15
    confianca = round(max(0.0, min(CONF_MAXIMA, confianca)), 3)
    return (melhor_a >= melhor_b), confianca, vencedores[0].evidencia, False


def classificar_bem(texto: str | None, tipo_bem: TipoBem | None = None) -> ClassificacaoBem:
    """Lê o texto do anúncio e devolve natureza, zona, confiança e evidência.

    ``tipo_bem``, quando já veio estruturado da fonte, entra como desempate --
    nunca como sobrescrita: se a fonte diz VEICULO e o texto grita "imóvel", o
    resultado é conflito, e conflito vai para revisão.
    """
    resultado = ClassificacaoBem()
    if not texto or not texto.strip():
        return resultado

    ctx = contexto(texto)
    imovel = _coletar(ctx, _TERMOS_IMOVEL)
    movel = _coletar(ctx, _TERMOS_MOVEL)

    if tipo_bem is TipoBem.IMOVEL:
        imovel.insert(0, Sinal("tipo declarado pela fonte", 0.90, texto.strip()[:200]))
    elif tipo_bem is TipoBem.VEICULO:
        movel.insert(0, Sinal("tipo declarado pela fonte", 0.90, texto.strip()[:200]))

    venceu_imovel, conf_nat, prova_nat, _ = _decidir(imovel, movel)
    resultado.sinais = imovel + movel
    if venceu_imovel is True:
        resultado.natureza = NaturezaBem.IMOVEL
    elif venceu_imovel is False:
        resultado.natureza = NaturezaBem.MOVEL
    resultado.confianca_natureza = conf_nat
    resultado.evidencia_natureza = prova_nat

    # Zona só se pergunta de imóvel. Móvel não é rural nem urbano, e deixar o
    # eixo rodar assim mesmo faria "trator em fazenda" virar imóvel rural.
    if resultado.natureza is not NaturezaBem.IMOVEL:
        return resultado

    rural = _coletar(ctx, _TERMOS_RURAL)
    urbana = _coletar(ctx, _TERMOS_URBANA)
    venceu_rural, conf_zona, prova_zona, conflito = _decidir(rural, urbana)
    if venceu_rural is True:
        resultado.zona = ZonaImovel.RURAL
    elif venceu_rural is False:
        resultado.zona = ZonaImovel.URBANA
    resultado.confianca_zona = conf_zona
    resultado.evidencia_zona = prova_zona
    resultado.conflito_zona = conflito
    resultado.sinais += rural + urbana
    return resultado
