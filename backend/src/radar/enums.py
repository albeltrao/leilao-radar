"""Enumeracoes de dominio.

Valores sao strings estaveis: eles aparecem na API publica e no banco, entao
renomear um valor e uma mudanca incompativel.
"""

from __future__ import annotations

from enum import StrEnum


class UF(StrEnum):
    AL = "AL"
    SE = "SE"
    PE = "PE"


class TipoBem(StrEnum):
    IMOVEL = "IMOVEL"
    VEICULO = "VEICULO"
    OUTRO = "OUTRO"


class StatusLote(StrEnum):
    ABERTO = "ABERTO"
    SUSPENSO = "SUSPENSO"
    ARREMATADO = "ARREMATADO"
    DESERTO = "DESERTO"
    CANCELADO = "CANCELADO"
    ENCERRADO = "ENCERRADO"


class ModalidadeLeilao(StrEnum):
    ELETRONICO = "ELETRONICO"
    PRESENCIAL = "PRESENCIAL"
    HIBRIDO = "HIBRIDO"
    DESCONHECIDA = "DESCONHECIDA"


class StatusPraca(StrEnum):
    DESIGNADA = "DESIGNADA"
    REALIZADA = "REALIZADA"
    SUSPENSA = "SUSPENSA"
    REMARCADA = "REMARCADA"
    CANCELADA = "CANCELADA"


class TipoEvento(StrEnum):
    PRACA_PRIMEIRA = "PRACA_PRIMEIRA"
    PRACA_SEGUNDA = "PRACA_SEGUNDA"
    PRACA_UNICA = "PRACA_UNICA"
    PRAZO_HABILITACAO = "PRAZO_HABILITACAO"
    PRAZO_CAUCAO = "PRAZO_CAUCAO"
    PRAZO_IMPUGNACAO = "PRAZO_IMPUGNACAO"
    VISITACAO = "VISITACAO"


class StatusEvento(StrEnum):
    CONFIRMADO = "CONFIRMADO"
    REMARCADO = "REMARCADO"
    SUSPENSO = "SUSPENSO"
    CANCELADO = "CANCELADO"
    REALIZADO = "REALIZADO"


class TipoDocumento(StrEnum):
    EDITAL = "EDITAL"
    MATRICULA = "MATRICULA"
    LAUDO = "LAUDO"
    CERTIDAO = "CERTIDAO"
    OUTRO = "OUTRO"


class OrigemTexto(StrEnum):
    PDF_TEXTO = "PDF_TEXTO"
    OCR = "OCR"
    HTML = "HTML"


class MetodoExtracao(StrEnum):
    """Como um campo foi obtido. Determina o nivel de confianca exibido."""

    REGRA = "REGRA"  # parser deterministico sobre o texto do edital
    LLM = "LLM"  # modelo de linguagem com structured output
    REGRA_E_LLM = "REGRA_E_LLM"  # as duas fontes concordaram
    FONTE = "FONTE"  # veio estruturado do site do leiloeiro
    MANUAL = "MANUAL"  # revisado por humano


class StatusLeiloeiro(StrEnum):
    ATIVO = "ATIVO"
    SUSPENSO = "SUSPENSO"
    INATIVO = "INATIVO"
    DESCONHECIDO = "DESCONHECIDO"


class JuntaComercial(StrEnum):
    JUCEAL = "JUCEAL"
    JUCESE = "JUCESE"
    JUCEPE = "JUCEPE"


class TipoFonte(StrEnum):
    TRIBUNAL = "TRIBUNAL"
    JUNTA_COMERCIAL = "JUNTA_COMERCIAL"
    LEILOEIRO = "LEILOEIRO"
    PROCESSUAL = "PROCESSUAL"
    MERCADO = "MERCADO"


class StatusColeta(StrEnum):
    SUCESSO = "SUCESSO"
    FALHA = "FALHA"
    PARCIAL = "PARCIAL"
    BLOQUEADA = "BLOQUEADA"  # robots.txt ou termos de uso impediram a coleta
    EM_ANDAMENTO = "EM_ANDAMENTO"


class FonteMercado(StrEnum):
    FIPE = "FIPE"
    FIPEZAP = "FIPEZAP"
    LAUDO_JUDICIAL = "LAUDO_JUDICIAL"
    COMPARAVEIS = "COMPARAVEIS"


class CanalAlerta(StrEnum):
    EMAIL = "EMAIL"
    PUSH = "PUSH"
