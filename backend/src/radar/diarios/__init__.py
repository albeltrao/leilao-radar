"""Leitura do Diário da Justiça: detecção de leilões e classificação do bem."""

from radar.diarios.classificacao import ClassificacaoBem, classificar_bem
from radar.diarios.deteccao import LeilaoDetectado, detectar_leilao

__all__ = [
    "ClassificacaoBem",
    "LeilaoDetectado",
    "classificar_bem",
    "detectar_leilao",
]
