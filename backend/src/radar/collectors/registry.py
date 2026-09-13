"""Alias publico do registro (``from radar.collectors import registry``)."""

from radar.collectors.base import carregar_todos, listar, obter, registrar

__all__ = ["carregar_todos", "listar", "obter", "registrar"]
