"""Normalizacao de texto, valores e datas em portugues brasileiro.

Compartilhado entre coletores (HTML de leiloeiro) e extracao (texto de edital):
os dois precisam ler "R$ 1.234.567,89" e "15 de marco de 2026, as 14h30".
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

# Fuso de referencia do produto. Editais publicam horario local; AL, SE e PE
# estao todos em UTC-3 e nenhum adota horario de verao desde 2019.
FUSO_BRASILIA = -3
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def remover_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto(texto: str | None) -> str:
    """Minusculas, sem acento, espacos colapsados. Usado para comparar/casar."""
    if not texto:
        return ""
    return re.sub(r"\s+", " ", remover_acentos(texto).lower()).strip()


def limpar_espacos(texto: str | None) -> str | None:
    if texto is None:
        return None
    limpo = re.sub(r"[\s ]+", " ", texto).strip()
    return limpo or None


def slugify(texto: str, maximo: int = 80) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", normalizar_texto(texto)).strip("-")
    return base[:maximo] or "sem-nome"


def hash_conteudo(*partes: object) -> str:
    """Hash estavel usado como chave natural quando nao ha numero de processo."""
    bruto = "|".join("" if p is None else str(p) for p in partes)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Valores monetarios
# ---------------------------------------------------------------------------

_RE_MOEDA = re.compile(
    r"(?:R\$\s*)?(?P<num>\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)"
)


def parse_moeda(texto: str | None) -> Decimal | None:
    """Converte "R$ 1.234.567,89" -> Decimal("1234567.89").

    Aceita tambem o formato sem separador de milhar e valores por extenso
    parciais ("R$ 250 mil"). Retorna None quando nao ha numero plausivel.
    """
    if texto is None:
        return None
    if isinstance(texto, int | float | Decimal):
        return Decimal(str(texto))

    limpo = re.sub(r"[ \s]+", " ", str(texto)).strip()
    if not limpo:
        return None

    multiplicador = Decimal(1)
    baixo = normalizar_texto(limpo)
    if re.search(r"\bmilhoes?\b", baixo):
        multiplicador = Decimal(1_000_000)
    elif re.search(r"\bmil\b", baixo):
        multiplicador = Decimal(1_000)

    m = _RE_MOEDA.search(limpo)
    if not m:
        return None
    num = m.group("num")

    if "," in num:
        num = num.replace(".", "").replace(",", ".")
    elif num.count(".") == 1 and len(num.split(".")[1]) == 3 and multiplicador == 1:
        # "1.500" sem centavos: ponto e separador de milhar, nao decimal.
        num = num.replace(".", "")
    elif num.count(".") > 1:
        num = num.replace(".", "")

    try:
        valor = Decimal(num) * multiplicador
    except InvalidOperation:
        return None
    return valor if valor >= 0 else None


def parse_percentual(texto: str | None) -> Decimal | None:
    if not texto:
        return None
    m = re.search(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%", str(texto))
    if not m:
        return None
    try:
        valor = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    return valor if 0 <= valor <= 100 else None


def parse_area(texto: str | None) -> Decimal | None:
    """Extrai area em m2 de "area total de 120,50 m2" / "1.200m²"."""
    if not texto:
        return None
    m = re.search(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,4})?|\d+(?:,\d{1,4})?)\s*(?:m²|m2|metros\s+quadrados)",
        str(texto),
        re.IGNORECASE,
    )
    if not m:
        return None
    return parse_moeda(m.group(1))


# ---------------------------------------------------------------------------
# Datas e horas
# ---------------------------------------------------------------------------

_RE_DATA_NUM = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_RE_DATA_EXTENSO = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b", re.IGNORECASE
)
_RE_HORA = re.compile(
    r"\b(\d{1,2})\s*(?:h|:|horas?)\s*(\d{2})?\s*(?:min|m)?\b", re.IGNORECASE
)


def parse_hora(texto: str | None) -> time | None:
    if not texto:
        return None
    m = _RE_HORA.search(str(texto))
    if not m:
        return None
    hora = int(m.group(1))
    minuto = int(m.group(2) or 0)
    if hora > 23 or minuto > 59:
        return None
    return time(hora, minuto)


def parse_data(texto: str | None) -> date | None:
    if not texto:
        return None
    s = str(texto)
    m = _RE_DATA_NUM.search(s)
    if m:
        dia, mes, ano = (int(g) for g in m.groups())
        if ano < 100:
            ano += 2000
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
    m = _RE_DATA_EXTENSO.search(s)
    if m:
        dia = int(m.group(1))
        mes = _MESES.get(normalizar_texto(m.group(2)))
        ano = int(m.group(3))
        if mes:
            try:
                return date(ano, mes, dia)
            except ValueError:
                return None
    return None


def parse_data_hora(texto: str | None, hora_padrao: time | None = None) -> datetime | None:
    """Data + hora de um trecho livre, devolvida em UTC.

    Editais escrevem o horario local (UTC-3). Guardamos tudo em UTC para que o
    calendario e o .ics sejam corretos para qualquer cliente.
    """
    d = parse_data(texto)
    if d is None:
        return None
    h = parse_hora(texto) or hora_padrao or time(0, 0)
    local = datetime.combine(d, h)
    return (local - timedelta(hours=FUSO_BRASILIA)).replace(tzinfo=UTC)


def para_local(dt: datetime | None) -> datetime | None:
    """UTC -> horario de Brasilia, para exibicao."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC) + timedelta(hours=FUSO_BRASILIA)


# ---------------------------------------------------------------------------
# Numero CNJ
# ---------------------------------------------------------------------------

# Lookarounds em vez de \b: no texto real o numero vem colado em "nº" ou entre
# aspas, e "º" conta como caractere de palavra, o que anularia o \b.
_RE_CNJ = re.compile(
    r"(?<!\d)(\d{7})\s*-?\s*(\d{2})\s*\.?\s*(\d{4})\s*\.?\s*(\d)"
    r"\s*\.?\s*(\d{2})\s*\.?\s*(\d{4})(?!\d)"
)


def extrair_numero_cnj(texto: str | None) -> str | None:
    """Extrai e formata o numero unico CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO."""
    if not texto:
        return None
    m = _RE_CNJ.search(str(texto))
    if not m:
        return None
    seq, dv, ano, seg, trib, org = m.groups()
    return f"{seq}-{dv}.{ano}.{seg}.{trib}.{org}"


def numero_cnj_valido(numero: str | None) -> bool:
    """Valida o digito verificador (modulo 97 base 10, Res. CNJ 65/2008)."""
    if not numero:
        return False
    digitos = re.sub(r"\D", "", numero)
    if len(digitos) != 20:
        return False
    seq, dv, resto = digitos[:7], digitos[7:9], digitos[9:]
    return int(f"{seq}{resto}00") % 97 == 98 - int(dv)


def calcular_dv_cnj(sequencial: str, ano: str, segmento: str, tribunal: str, origem: str) -> str:
    """Calcula o digito verificador (ISO 7064 MOD 97-10) de um numero CNJ.

    Usado para gerar dados de demonstracao validos e para corrigir numeros lidos
    de editais com OCR ruim antes de consultar o DataJud.
    """
    base = f"{int(sequencial):07d}{int(ano):04d}{segmento}{int(tribunal):02d}{int(origem):04d}"
    return f"{98 - int(base + '00') % 97:02d}"


def formatar_cnj(sequencial: str, ano: str, segmento: str, tribunal: str, origem: str) -> str:
    dv = calcular_dv_cnj(sequencial, ano, segmento, tribunal, origem)
    return (
        f"{int(sequencial):07d}-{dv}.{int(ano):04d}.{segmento}"
        f".{int(tribunal):02d}.{int(origem):04d}"
    )


def tribunal_do_cnj(numero: str | None) -> str | None:
    """Deriva a sigla do TJ a partir do segmento J=8 (justica estadual) + TR."""
    if not numero:
        return None
    digitos = re.sub(r"\D", "", numero)
    if len(digitos) != 20:
        return None
    segmento, tr = digitos[13], digitos[14:16]
    if segmento != "8":
        return None
    # Import local: jurisdicoes nao depende deste modulo, mas manter o import no
    # topo criaria acoplamento desnecessario para uma unica funcao.
    from radar.jurisdicoes import tribunal_por_codigo_tr  # noqa: PLC0415

    return tribunal_por_codigo_tr(tr)


# ---------------------------------------------------------------------------
# Minimizacao de dados pessoais (secao 11 / LGPD)
# ---------------------------------------------------------------------------

_RE_PLACA = re.compile(r"\b([A-Z]{3})[- ]?(\d)([A-Z0-9])(\d{2})\b")
_RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


def mascarar_placa(texto: str | None) -> str | None:
    """"ABC1D23" -> "ABC1**3": identifica o veiculo sem publicar a placa inteira."""
    if not texto:
        return None
    m = _RE_PLACA.search(str(texto).upper().strip())
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}**{m.group(4)[-1]}"


def remover_cpf(texto: str | None) -> str | None:
    """Substitui CPFs por marcador. Nunca persistimos CPF de pessoa fisica."""
    if texto is None:
        return None
    return _RE_CPF.sub("[CPF removido]", texto)
