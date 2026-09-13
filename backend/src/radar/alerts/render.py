"""Montagem do e-mail de alerta.

HTML de e-mail e um ambiente hostil: nada de CSS externo, nada de flexbox
confiavel, estilo inline e tabela. Por isso este arquivo nao reusa o design
system do frontend -- ele reimplementa uma versao mais burra e mais compativel.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

from radar.enums import TipoEvento
from radar.market.analise import melhor_analise
from radar.models import Alerta, Lote
from radar.normalizacao import para_local

DISCLAIMER = (
    "Informações extraídas automaticamente do edital oficial. Consulte o "
    "documento original e um advogado antes de participar do leilão."
)

_COR_FAIXA = {
    "ALTA": "#0f7b6c",
    "BOA": "#2f6f4e",
    "MODERADA": "#8a6d1f",
    "BAIXA": "#6b6b6b",
}


def _reais(valor: Decimal | None) -> str:
    if valor is None:
        return "não informado"
    inteiro = f"{valor:,.2f}"
    return "R$ " + inteiro.replace(",", "X").replace(".", ",").replace("X", ".")


_TIPOS_PRACA = {
    TipoEvento.PRACA_PRIMEIRA,
    TipoEvento.PRACA_SEGUNDA,
    TipoEvento.PRACA_UNICA,
}


def _proxima_praca(lote: Lote) -> str:
    """Somente eventos de praça.

    O prazo de habilitação cai ANTES da praça, então pegar o menor evento de
    qualquer tipo mostraria a data de habilitação sob o rótulo "próxima praça".
    """
    datas = [e.data_hora for e in lote.eventos if e.data_hora and e.tipo in _TIPOS_PRACA]
    if not datas:
        return "sem data de praça"
    local = para_local(min(datas))
    return f"{local:%d/%m/%Y às %Hh%M}"


def _linha_lote(lote: Lote, base_url: str) -> str:
    analise = melhor_analise(lote)
    desconto = (
        f"{analise.desconto_percentual}% abaixo da referência de {analise.fonte}"
        if analise and analise.desconto_percentual and analise.desconto_percentual > 0
        else "sem desconto estimado"
    )
    faixa = lote.score.faixa if lote.score else "INDEFINIDA"
    cor = _COR_FAIXA.get(faixa, "#6b6b6b")
    local = ", ".join(p for p in (lote.bairro, lote.cidade, lote.uf) if p) or "local não informado"
    return f"""
    <tr><td style="padding:16px 0;border-bottom:1px solid #e4e4e7;">
      <div style="font:600 16px/1.4 system-ui,sans-serif;color:#18181b;">
        <a href="{escape(base_url)}/lote/{lote.id}" style="color:#18181b;text-decoration:none;">
          {escape(lote.titulo)}
        </a>
      </div>
      <div style="font:14px/1.6 system-ui,sans-serif;color:#52525b;margin-top:4px;">
        {escape(local)}<br>
        Lance mínimo: <strong>{_reais(lote.valor_minimo_segunda or lote.valor_minimo_primeira)}</strong>
        &nbsp;·&nbsp; Avaliação: {_reais(lote.valor_avaliacao)}<br>
        {escape(desconto)}<br>
        Próxima praça: {escape(_proxima_praca(lote))}
      </div>
      <div style="margin-top:8px;">
        <span style="display:inline-block;padding:3px 10px;border-radius:999px;
              background:{cor};color:#fff;font:600 12px system-ui,sans-serif;">
          Oportunidade {escape(faixa.title())}
          {f"· {lote.score.total:.0f}/100" if lote.score else ""}
        </span>
      </div>
    </td></tr>"""


def montar_html(alerta: Alerta, lotes: list[Lote], base_url: str) -> str:
    linhas = "".join(_linha_lote(lo, base_url) for lo in lotes)
    plural = "novo lote" if len(lotes) == 1 else "novos lotes"
    return f"""<!doctype html>
<html lang="pt-br"><body style="margin:0;background:#fafafa;padding:24px;">
<table role="presentation" width="100%" style="max-width:640px;margin:0 auto;
       background:#fff;border-radius:12px;padding:28px;">
  <tr><td>
    <div style="font:700 20px/1.3 system-ui,sans-serif;color:#18181b;">
      {len(lotes)} {plural} para “{escape(alerta.nome)}”
    </div>
    <div style="font:14px/1.6 system-ui,sans-serif;color:#71717a;margin-top:6px;">
      Radar Leilão · leilões judiciais de Alagoas, Sergipe e Pernambuco
    </div>
  </td></tr>
  {linhas}
  <tr><td style="padding-top:20px;">
    <p style="font:12px/1.6 system-ui,sans-serif;color:#71717a;margin:0 0 10px;">
      {escape(DISCLAIMER)}
    </p>
    <p style="font:12px/1.6 system-ui,sans-serif;color:#a1a1aa;margin:0;">
      Você recebe este e-mail porque salvou o filtro “{escape(alerta.nome)}”.
      <a href="{escape(base_url)}/alertas" style="color:#71717a;">Gerenciar alertas</a>
    </p>
  </td></tr>
</table></body></html>"""


def montar_texto(alerta: Alerta, lotes: list[Lote], base_url: str) -> str:
    partes = [f"{len(lotes)} novo(s) lote(s) para o alerta \"{alerta.nome}\"", ""]
    for lote in lotes:
        local = ", ".join(p for p in (lote.bairro, lote.cidade, lote.uf) if p)
        partes += [
            f"- {lote.titulo}",
            f"  {local}",
            f"  Lance mínimo: {_reais(lote.valor_minimo_segunda or lote.valor_minimo_primeira)}"
            f" | Avaliação: {_reais(lote.valor_avaliacao)}",
            f"  Próxima praça: {_proxima_praca(lote)}",
            f"  {base_url}/lote/{lote.id}",
            "",
        ]
    partes += [DISCLAIMER, "", f"Gerenciar alertas: {base_url}/alertas"]
    return "\n".join(partes)
