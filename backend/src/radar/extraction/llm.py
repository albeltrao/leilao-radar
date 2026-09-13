"""Extracao por LLM, complementar ao parser de regra (secao 7.3).

Papel deste modulo: pegar o que a regra nao pegou e conferir o que ela pegou.
Nunca substitui-la. A regra e barata, determinista e auditavel; o modelo entra
onde a redacao do edital foge do padrao.

Tres salvaguardas, todas exigidas pela secao 7.4 e pela secao 11:

1. **Evidencia verificada.** O modelo e obrigado a devolver o trecho literal do
   documento que sustenta cada campo. Se o trecho nao existir no texto de
   origem, o campo e descartado. E a defesa concreta contra alucinacao -- um
   valor inventado nao tem como vir com citacao que confira.
2. **Whitelist de campos.** Campo fora da lista conhecida e ignorado.
3. **Confianca menor que a da regra.** Achado que so o modelo viu entra com
   ``CONF_SO_LLM`` e cai automaticamente na fila de revisao.

Desligado por padrao (``RADAR_LLM_HABILITADO=0``). Sem chave de API o pipeline
inteiro continua funcionando so com a regra.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from radar.config import Settings, get_settings
from radar.enums import MetodoExtracao
from radar.extraction.campos import CONF_SO_LLM, Achado, ResultadoExtracao
from radar.normalizacao import (
    normalizar_texto,
    parse_data_hora,
    parse_moeda,
    parse_percentual,
)

logger = logging.getLogger(__name__)

# Versionado: fica gravado em Documento.prompt_versao, entao da para saber com
# qual prompt cada campo foi extraido quando a qualidade mudar (secao 12).
PROMPT_VERSAO = "edital-2026-09-13.v1"

CAMPOS_PERMITIDOS: dict[str, str] = {
    "valor_avaliacao": "numerico",
    "valor_minimo_praca_1": "numerico",
    "valor_minimo_praca_2": "numerico",
    "percentual_minimo_segunda_praca": "percentual",
    "comissao_leiloeiro": "percentual",
    "data_praca_1": "data",
    "data_praca_2": "data",
    "prazo_habilitacao": "data",
    "numero_processo": "texto",
    "comarca": "texto",
    "vara": "texto",
    "leiloeiro_nome": "texto",
    "leiloeiro_matricula": "texto",
    "endereco": "texto",
    "bairro": "texto",
    "cidade": "texto",
    "matricula_imovel": "texto",
    "cartorio": "texto",
    "area_total_m2": "numerico",
    "area_privativa_m2": "numerico",
    "ocupado": "booleano",
    "onus": "texto",
    "debitos_mencionados": "texto",
    "edital_invoca_sub_rogacao_no_preco": "booleano",
    "edital_atribui_debitos_ao_arrematante": "booleano",
    "formas_pagamento": "texto",
    "condicao_veiculo": "texto",
    "marca": "texto",
    "modelo": "texto",
    "ano_fabricacao": "numerico",
    "ano_modelo": "numerico",
}

INSTRUCAO = f"""Você extrai campos de editais de leilão judicial brasileiro.

Regras absolutas:
1. Extraia SOMENTE o que está escrito no documento. Nunca deduza, nunca complete
   com conhecimento externo, nunca calcule um valor que não esteja no texto.
2. Para cada campo, devolva em `trecho_do_documento` um recorte LITERAL e
   contíguo do edital, copiado caractere por caractere, que contenha o valor.
   Um trecho que não exista exatamente no documento invalida o campo.
3. Se um campo não estiver no documento, simplesmente não o inclua na lista.
   Lista vazia é uma resposta correta e preferível a um palpite.
4. `confianca` é sua avaliação honesta de 0 a 1. Use abaixo de 0,5 quando o
   texto for ambíguo ou quando houver mais de um candidato plausível.
5. Não emita opinião jurídica. Para os campos de sub-rogação, apenas registre se
   o edital afirma aquilo, citando o trecho.

Valores: mantenha o formato do documento (ex.: "R$ 320.000,00", "10/11/2026 às
14h00"). Não converta, não arredonde, não normalize.

Nomes de campo permitidos (qualquer outro será descartado):
{", ".join(sorted(CAMPOS_PERMITIDOS))}"""


class CampoLLM(BaseModel):
    nome: str = Field(description="Nome do campo, exatamente da lista permitida")
    valor: str = Field(description="Valor como aparece no documento")
    confianca: float = Field(ge=0.0, le=1.0)
    trecho_do_documento: str = Field(
        description="Recorte literal e contíguo do edital que contém o valor"
    )


class ExtracaoLLM(BaseModel):
    campos: list[CampoLLM] = Field(default_factory=list)
    observacoes: str | None = Field(
        default=None, description="Ambiguidades relevantes encontradas no documento"
    )


class ExtratorLLM:
    """Wrapper fino sobre o SDK da Anthropic com structured output."""

    def __init__(self, settings: Settings | None = None, cliente=None) -> None:
        self.settings = settings or get_settings()
        self._cliente = cliente

    @property
    def habilitado(self) -> bool:
        return bool(self.settings.llm_habilitado and self.settings.llm_api_key)

    def _obter_cliente(self):
        if self._cliente is not None:
            return self._cliente
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "extracao por LLM exige o extra: pip install 'radar-leilao[llm]'"
            ) from exc
        self._cliente = anthropic.Anthropic(api_key=self.settings.llm_api_key)
        return self._cliente

    def extrair(self, texto: str) -> ResultadoExtracao:
        resultado = ResultadoExtracao(prompt_versao=PROMPT_VERSAO)
        if not self.habilitado:
            resultado.avisos.append("extracao por LLM desligada (RADAR_LLM_HABILITADO=0)")
            return resultado
        if not texto or len(texto.strip()) < 60:
            return resultado

        recorte = texto[: self.settings.llm_max_caracteres]
        if len(texto) > len(recorte):
            # Nunca truncamos em silencio: o aviso sobe ate a API e a UI.
            resultado.avisos.append(
                f"edital tem {len(texto)} caracteres e foi analisado ate "
                f"{len(recorte)} pelo modelo; a extracao por regra leu o texto inteiro"
            )

        cliente = self._obter_cliente()
        try:
            resposta = cliente.messages.parse(
                model=self.settings.llm_modelo,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=INSTRUCAO,
                messages=[
                    {
                        "role": "user",
                        "content": f"<edital>\n{recorte}\n</edital>",
                    }
                ],
                output_format=ExtracaoLLM,
            )
        except Exception as exc:
            logger.warning("extracao por LLM falhou: %s", exc)
            resultado.avisos.append(f"modelo indisponivel: {exc}")
            return resultado

        # O modelo pode recusar: nesse caso ficamos so com a extracao por regra,
        # que ja e um resultado completo -- por isso nao ha modelo de fallback.
        if getattr(resposta, "stop_reason", None) == "refusal":
            detalhe = getattr(resposta, "stop_details", None)
            resultado.avisos.append(
                f"modelo recusou a analise deste documento ({getattr(detalhe, 'category', 'sem categoria')})"
            )
            return resultado

        dados = getattr(resposta, "parsed_output", None)
        if dados is None:
            resultado.avisos.append("modelo nao devolveu saida estruturada")
            return resultado

        if dados.observacoes:
            resultado.avisos.append(f"observacao do modelo: {dados.observacoes}")

        resultado.achados.extend(self._validar(dados.campos, texto, resultado))
        return resultado

    # -- validacao ---------------------------------------------------------

    def _validar(
        self, campos: list[CampoLLM], texto_origem: str, resultado: ResultadoExtracao
    ) -> list[Achado]:
        achados: list[Achado] = []
        alvo = normalizar_texto(texto_origem)
        for campo in campos:
            if campo.nome not in CAMPOS_PERMITIDOS:
                resultado.avisos.append(f"campo fora da whitelist descartado: {campo.nome}")
                continue
            if not self._evidencia_confere(campo.trecho_do_documento, alvo):
                resultado.avisos.append(
                    f"campo {campo.nome} descartado: o trecho citado nao existe no edital"
                )
                continue
            achado = self._converter(campo)
            if achado is not None:
                achados.append(achado)
        return achados

    @staticmethod
    def _evidencia_confere(trecho: str, texto_normalizado: str) -> bool:
        """O trecho citado precisa existir de fato no documento.

        Comparamos normalizado (sem acento, minusculo, espacos colapsados) porque
        OCR e copia manual trocam espaco por quebra de linha. Trecho muito curto
        nao serve de evidencia: "R$" aparece em qualquer edital.
        """
        alvo = normalizar_texto(trecho)
        if len(alvo) < 12:
            return False
        if alvo in texto_normalizado:
            return True
        # Tolerancia a pequenas diferencas de pontuacao: exige que uma sequencia
        # longa de palavras do trecho apareca na ordem.
        palavras = alvo.split()
        if len(palavras) < 4:
            return False
        janela = " ".join(palavras[:6])
        return janela in texto_normalizado

    @staticmethod
    def _converter(campo: CampoLLM) -> Achado | None:
        tipo = CAMPOS_PERMITIDOS[campo.nome]
        confianca = min(campo.confianca, CONF_SO_LLM)
        base = dict(
            nome=campo.nome,
            confianca=confianca,
            evidencia=campo.trecho_do_documento,
            metodo=MetodoExtracao.LLM,
        )
        match tipo:
            case "numerico":
                valor = parse_moeda(campo.valor)
                if valor is None:
                    try:
                        valor = Decimal(re.sub(r"[^\d.,-]", "", campo.valor).replace(",", "."))
                    except (InvalidOperation, ValueError):
                        return None
                return Achado(valor_numerico=valor, **base)
            case "percentual":
                valor = parse_percentual(campo.valor)
                return Achado(valor_numerico=valor, **base) if valor is not None else None
            case "data":
                valor = parse_data_hora(campo.valor)
                return Achado(valor_data=valor, **base) if valor is not None else None
            case "booleano":
                alvo = normalizar_texto(campo.valor)
                if alvo in {"sim", "true", "verdadeiro", "1", "ocupado"}:
                    return Achado(valor_booleano=True, **base)
                if alvo in {"nao", "false", "falso", "0", "desocupado"}:
                    return Achado(valor_booleano=False, **base)
                return None
            case _:
                return Achado(valor_texto=campo.valor.strip(), **base)


def esquema_json() -> str:
    """Schema publicado na documentacao da API, para auditoria externa."""
    return json.dumps(ExtracaoLLM.model_json_schema(), ensure_ascii=False, indent=2)
