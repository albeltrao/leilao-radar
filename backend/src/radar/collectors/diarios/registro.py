"""Registra um conector de diário por tribunal -- estadual e federal.

Acrescentar um tribunal aqui é acrescentar uma linha, do mesmo jeito que
acrescentar um estado é uma linha em ``radar.jurisdicoes``. A lista sai de lá:
os TJs cobertos e os TRFs que respondem por esses estados.

Por que um conector por tribunal e não um só para tudo: o painel de saúde da
seção 5 mede fonte a fonte. Com um conector único, o DJEN do TJPE fora do ar
apareceria como "a fonte diário falhou", sem dizer qual tribunal sumiu.
"""

from __future__ import annotations

from radar.collectors.base import registrar
from radar.collectors.diarios.base import ColetorDiarioEletronico, meta_djen
from radar.enums import EsferaJustica
from radar.jurisdicoes import (
    JURISDICOES,
    JURISDICOES_FEDERAIS,
    ufs_do_tribunal,
)

CONECTORES: dict[str, ColetorDiarioEletronico] = {}


def _criar(sigla: str, nome: str, esfera: EsferaJustica) -> ColetorDiarioEletronico:
    ufs = ufs_do_tribunal(sigla)
    conector = ColetorDiarioEletronico(
        meta=meta_djen(sigla, nome, esfera),
        tribunal_sigla=sigla,
        esfera=esfera,
        uf=ufs[0] if len(ufs) == 1 else None,
    )
    CONECTORES[sigla] = conector
    return conector


def registrar_diarios() -> list[ColetorDiarioEletronico]:
    """Idempotente: chamar de novo devolve os conectores já registrados."""
    if CONECTORES:
        return list(CONECTORES.values())
    criados = [
        registrar(_criar(j.sigla, j.nome, EsferaJustica.ESTADUAL)) for j in JURISDICOES
    ]
    criados += [
        registrar(_criar(j.sigla, j.nome, EsferaJustica.FEDERAL))
        for j in JURISDICOES_FEDERAIS
    ]
    return criados
