"""Sanidade do código-fonte.

Guarda contra uma classe de bug que já apareceu duas vezes neste repositório:
sequência de escape inválida em string Python. Hoje o interpretador é leniente e
trata `"\;"` como barra-ponto-e-vírgula -- por acaso o que o RFC 5545 quer, o
que fez o bug passar despercebido pelos testes de comportamento. Mas isso é
DeprecationWarning e vira SyntaxError: quando virar, o módulo deixa de importar
e a exportação .ics para de funcionar inteira.

Vale a pena como teste porque o defeito é invisível no resultado e só aparece
num aviso perdido no log do CI.
"""

from __future__ import annotations

import pathlib
import warnings

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _modulos() -> list[pathlib.Path]:
    return sorted((RAIZ / "src").rglob("*.py")) + sorted((RAIZ / "tests").rglob("*.py"))


def test_sem_sequencia_de_escape_invalida():
    problemas: list[str] = []
    for caminho in _modulos():
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            compile(caminho.read_text(encoding="utf-8"), str(caminho), "exec")
            problemas += [
                f"{caminho.relative_to(RAIZ)}:{a.lineno} {a.message}"
                for a in avisos
                if "invalid escape sequence" in str(a.message)
            ]
    assert not problemas, "use string raw (r\"\") ou escape a barra:\n" + "\n".join(problemas)


def test_todo_modulo_compila():
    for caminho in _modulos():
        compile(caminho.read_text(encoding="utf-8"), str(caminho), "exec")
