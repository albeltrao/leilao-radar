"""Exportacao .ics (RFC 5545) -- secao 9.

Escrito a mao, sem dependencia: o formato e simples e o que importa aqui sao
detalhes que bibliotecas genericas costumam errar no nosso caso:

* **SEQUENCE** sobe a cada remarcacao. E o que faz o Google/Outlook/Apple
  ATUALIZAR o compromisso que a pessoa ja tinha, em vez de criar um duplicado.
  Sem isso, um leilao adiado vira dois eventos na agenda do usuario.
* **UID estavel** por evento, pelo mesmo motivo.
* **VALARM** para cada lembrete configurado (72h, 24h, 1h antes).
* **STATUS/CANCELLED** quando a praca e suspensa, para o evento sumir da agenda.
* Dobra de linha em 75 octetos contando BYTES, nao caracteres -- "Maceió" tem
  6 caracteres e 7 bytes, e cortar no meio de um caractere UTF-8 corrompe o
  arquivo para alguns clientes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from radar.enums import StatusEvento, TipoEvento
from radar.models import EventoCalendario

PRODID = "-//Radar Leilao//Calendario de pracas//PT-BR"
DOMINIO_UID = "radar-leilao.example.org"

_STATUS_ICS = {
    StatusEvento.CONFIRMADO: "CONFIRMED",
    StatusEvento.REMARCADO: "CONFIRMED",
    StatusEvento.REALIZADO: "CONFIRMED",
    StatusEvento.SUSPENSO: "TENTATIVE",
    StatusEvento.CANCELADO: "CANCELLED",
}

DURACAO_PADRAO_MIN = {
    TipoEvento.PRACA_PRIMEIRA: 120,
    TipoEvento.PRACA_SEGUNDA: 120,
    TipoEvento.PRACA_UNICA: 120,
}


def escapar(texto: str | None) -> str:
    if not texto:
        return ""
    return (
        texto.replace("\\", "\\\\")
        .replace(";", "\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def dobrar(linha: str) -> list[str]:
    """Dobra em 75 octetos sem partir caractere UTF-8 no meio."""
    bruto = linha.encode("utf-8")
    if len(bruto) <= 75:
        return [linha]
    partes: list[str] = []
    atual = bytearray()
    limite = 75
    for caractere in linha:
        codificado = caractere.encode("utf-8")
        if len(atual) + len(codificado) > limite:
            partes.append(atual.decode("utf-8"))
            atual = bytearray()
            limite = 74  # continuacao gasta um octeto com o espaco inicial
        atual.extend(codificado)
    if atual:
        partes.append(atual.decode("utf-8"))
    return [partes[0]] + [f" {p}" for p in partes[1:]]


def _utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def uid(evento: EventoCalendario) -> str:
    return f"lote-{evento.lote_id}-{str(evento.tipo).lower()}@{DOMINIO_UID}"


def _descricao(evento: EventoCalendario) -> str:
    lote = evento.lote
    partes = [lote.titulo]
    if lote.valor_minimo_segunda or lote.valor_minimo_primeira:
        minimo = (
            lote.valor_minimo_segunda
            if evento.tipo is TipoEvento.PRACA_SEGUNDA
            else lote.valor_minimo_primeira
        )
        if minimo:
            partes.append(f"Lance mínimo: R$ {minimo}")
    if lote.valor_avaliacao:
        partes.append(f"Avaliação: R$ {lote.valor_avaliacao}")
    if lote.numero_processo:
        partes.append(f"Processo: {lote.numero_processo}")
    if evento.estimado:
        partes.append("ATENÇÃO: data estimada, não declarada no edital. Confirme na fonte.")
    if evento.historico:
        ultimo = evento.historico[-1]
        if ultimo.data_hora_anterior and ultimo.data_hora_nova != ultimo.data_hora_anterior:
            partes.append(
                f"Remarcado: era {ultimo.data_hora_anterior:%d/%m/%Y %H:%M} UTC."
            )
    partes.append(
        "Informações extraídas automaticamente do edital oficial. Consulte o "
        "documento original e um advogado antes de participar do leilão."
    )
    if lote.fonte_url:
        partes.append(f"Fonte: {lote.fonte_url}")
    return "\n".join(partes)


def _vevento(evento: EventoCalendario, agora: datetime) -> list[str]:
    inicio = evento.data_hora
    duracao = DURACAO_PADRAO_MIN.get(evento.tipo, 30)
    linhas = [
        "BEGIN:VEVENT",
        f"UID:{uid(evento)}",
        f"DTSTAMP:{_utc(agora)}",
        f"DTSTART:{_utc(inicio)}",
        f"DURATION:PT{duracao}M",
        # SEQUENCE = numero de mudancas ja registradas. Faz o cliente de
        # calendario atualizar o evento existente em vez de duplicar.
        f"SEQUENCE:{len(evento.historico)}",
        f"STATUS:{_STATUS_ICS.get(evento.status, 'CONFIRMED')}",
        f"SUMMARY:{escapar(evento.titulo)}",
        f"DESCRIPTION:{escapar(_descricao(evento))}",
    ]
    lote = evento.lote
    local = ", ".join(p for p in (lote.endereco, lote.bairro, lote.cidade, lote.uf) if p)
    if local:
        linhas.append(f"LOCATION:{escapar(local)}")
    if lote.latitude is not None and lote.longitude is not None:
        linhas.append(f"GEO:{lote.latitude};{lote.longitude}")
    if lote.fonte_url:
        linhas.append(f"URL:{escapar(lote.fonte_url)}")
    linhas.append(f"CATEGORIES:{escapar(str(lote.tipo_bem))}")

    for horas in sorted(evento.lembretes_horas or [], reverse=True):
        linhas += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER:-PT{int(horas)}H",
            f"DESCRIPTION:{escapar(f'{evento.titulo} em {horas}h')}",
            "END:VALARM",
        ]
    linhas.append("END:VEVENT")
    return linhas


def gerar(
    eventos: Iterable[EventoCalendario],
    nome: str = "Radar Leilão",
    agora: datetime | None = None,
) -> str:
    agora = agora or datetime.now(UTC)
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escapar(nome)}",
        "X-WR-TIMEZONE:America/Maceio",
    ]
    for evento in eventos:
        if evento.data_hora is None:
            continue
        linhas.extend(_vevento(evento, agora))
    linhas.append("END:VCALENDAR")

    dobradas: list[str] = []
    for linha in linhas:
        dobradas.extend(dobrar(linha))
    # RFC 5545 exige CRLF.
    return "\r\n".join(dobradas) + "\r\n"
