"""Parser deterministico de edital de leilao judicial brasileiro (secao 7.3).

Por que regra antes de LLM: um edital e um documento de forma razoavelmente
fixa, e regra e auditavel, reproduzivel, gratuita e instantanea. O modelo de
linguagem entra depois, para o que a regra nao pegou e para conferir o que ela
pegou (ver ``merge.py``).

Todo casamento roda sobre uma copia do texto sem acento e em minusculas, e a
evidencia e recortada do texto ORIGINAL -- o usuario le o trecho como esta no
edital, com acento e maiuscula. Quem garante que os offsets batem nos dois e o
``Contexto`` de campos.py; leia o docstring de ``contexto()`` antes de confiar
neles em codigo novo.

ARMADILHA ao escrever padrao novo: a normalizacao NFKD tambem converte os
indicadores ordinais. "nº" vira "no", "1ª" vira "1a" e "2º" vira "2o" ANTES de o
regex rodar. Um padrao que procure literalmente "º" nunca casa. Sempre inclua
a letra na classe: ``[oº°]``, ``[aª]``.

Limite deliberado: este modulo relata o que o edital diz. Ele nao interpreta a
consequencia juridica. "O edital invoca o art. 130, paragrafo unico, do CTN" e
um fato; "voce nao vai pagar o IPTU atrasado" seria parecer juridico, e a secao
11 proibe.
"""

from __future__ import annotations

import re

from radar.extraction.campos import (
    CONF_INFERIDO,
    CONF_ROTULO_AMBIGUO,
    CONF_ROTULO_EXPLICITO,
    Achado,
    Contexto,
    ResultadoExtracao,
    contexto,
)
from radar.normalizacao import (
    extrair_numero_cnj,
    limpar_espacos,
    parse_area,
    parse_data_hora,
    parse_moeda,
    parse_percentual,
)

VERSAO_PARSER = "1.0"

_MOEDA = r"R\$\s*([\d][\d.\s]*,\d{2}|[\d][\d.\s]*)"


def _buscar(ctx: Contexto, padrao: str) -> list[re.Match]:
    return list(re.finditer(padrao, ctx.busca, re.IGNORECASE | re.DOTALL))


def _primeiro(ctx: Contexto, padroes: list[str]) -> tuple[re.Match, int] | None:
    """Primeiro padrao que casar, na ordem de confiabilidade dada."""
    for indice, padrao in enumerate(padroes):
        achados = _buscar(ctx, padrao)
        if achados:
            return achados[0], indice
    return None


class ParserEdital:
    VERSAO = VERSAO_PARSER

    def extrair(self, texto: str) -> ResultadoExtracao:
        resultado = ResultadoExtracao(parser_versao=self.VERSAO)
        if not texto or len(texto.strip()) < 60:
            resultado.avisos.append("texto do edital vazio ou curto demais para extrair")
            return resultado

        ctx = contexto(texto)
        for extrator in (
            self._processo,
            self._comarca_e_vara,
            self._leiloeiro,
            self._valor_avaliacao,
            self._pracas,
            self._percentual_minimo,
            self._comissao,
            self._imovel,
            self._ocupacao,
            self._onus,
            self._debitos,
            self._sub_rogacao,
            self._formas_pagamento,
            self._veiculo,
        ):
            try:
                resultado.achados.extend(extrator(ctx))
            except Exception as exc:  # um extrator ruim nao pode perder os outros
                resultado.avisos.append(f"{extrator.__name__}: {exc}")
        return resultado

    # -- identificacao processual ------------------------------------------

    def _processo(self, ctx: Contexto) -> list[Achado]:
        numero = extrair_numero_cnj(ctx.original)
        if not numero:
            return []
        pos = ctx.busca.find(numero.split("-")[0])
        return [
            Achado(
                nome="numero_processo",
                valor_texto=numero,
                confianca=CONF_ROTULO_EXPLICITO,
                evidencia=ctx.evidencia(max(pos, 0), max(pos, 0) + 25),
            )
        ]

    def _comarca_e_vara(self, ctx: Contexto) -> list[Achado]:
        achados: list[Achado] = []
        m = _primeiro(
            ctx,
            [
                # Terminadores incluem travessao: "COMARCA DE ARACAJU - 1a VARA".
                r"comarca\s+d[eao]s?\s+([a-zà-ÿ']{3,}(?:\s+[a-zà-ÿ']+){0,5}?)"
                r"(?:\s*[,.;/|]|\s*[-–—]|\s+estado\b|\n)",
                r"foro\s+d[eao]s?\s+([a-zà-ÿ']{3,}(?:\s+[a-zà-ÿ']+){0,5}?)"
                r"(?:\s*[,.;/|]|\s*[-–—]|\n)",
            ],
        )
        if m:
            match, indice = m
            bruto = ctx.original[match.start(1) : match.end(1)]
            achados.append(
                Achado(
                    nome="comarca",
                    valor_texto=limpar_espacos(bruto),
                    confianca=CONF_ROTULO_EXPLICITO if indice == 0 else CONF_ROTULO_AMBIGUO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            )
        m = _primeiro(
            ctx,
            [
                r"((?:\d{1,2}[ªa°º]?\s*)?vara\s+[a-zà-ÿ\s]{3,40}?)(?:\s*d[ao]\s+comarca|\s*[,.;]|\n)",
            ],
        )
        if m:
            match, _ = m
            achados.append(
                Achado(
                    nome="vara",
                    valor_texto=limpar_espacos(ctx.original[match.start(1) : match.end(1)]),
                    confianca=CONF_ROTULO_EXPLICITO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            )
        return achados

    def _leiloeiro(self, ctx: Contexto) -> list[Achado]:
        achados: list[Achado] = []
        m = _primeiro(
            ctx,
            [
                r"leiloeir[oa]\s+(?:p[uú]blic[oa]\s+)?oficial[,\s]+(?:sr[a]?\.?\s*)?"
                r"([a-zà-ÿ'\s.]{6,60}?)(?:\s*[,;(]|\s+matricula|\s+inscrit)",
            ],
        )
        if m:
            match, _ = m
            achados.append(
                Achado(
                    nome="leiloeiro_nome",
                    valor_texto=limpar_espacos(ctx.original[match.start(1) : match.end(1)]),
                    confianca=CONF_ROTULO_EXPLICITO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            )
        # ARMADILHA: "matricula" sozinho casa antes com a matricula do IMOVEL --
        # "matricula 12.345 do 2o Oficio" vinha parar aqui e era exibida como a
        # credencial do leiloeiro. O rotulo so vale quando a junta esta nomeada
        # ou quando a palavra "leiloeiro" esta por perto; sem isso, campo vazio,
        # que e melhor que uma credencial errada na tela.
        m = _primeiro(
            ctx,
            [
                # O grupo termina em digito de proposito: sem isso o ponto final
                # da frase entrava na matricula ("12/2019.").
                r"(?:juceal|jucese|jucepe|juceb|jucesp|jucerja|jucemg)\s*"
                r"(?:sob\s+)?(?:n?[oº°.]?\s*)?([\d./-]{1,14}\d)",
                r"matricula\s+(?:d[oa]\s+)?leiloeir[oa][^\d]{0,20}([\d./-]{1,14}\d)",
                # (?!\n\s*\n) impede atravessar paragrafo: dentro do mesmo bloco,
                # "matricula" depois de "leiloeiro" e do leiloeiro; no bloco
                # seguinte ("DO BEM:") ja e a matricula do imovel. Nao da para
                # usar [^.] porque "Sra." tem ponto e fica no meio da frase.
                r"leiloeir[oa](?:(?!\n\s*\n).){0,130}?matricula\s*"
                r"(?:n?[oº°.]?\s*)?([\d./-]{1,14}\d)",
            ],
        )
        if m:
            match, indice = m
            achados.append(
                Achado(
                    nome="leiloeiro_matricula",
                    valor_texto=limpar_espacos(ctx.original[match.start(1) : match.end(1)]),
                    confianca=CONF_ROTULO_EXPLICITO if indice < 2 else CONF_ROTULO_AMBIGUO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            )
        return achados

    # -- valores -----------------------------------------------------------

    def _valor_avaliacao(self, ctx: Contexto) -> list[Achado]:
        padroes = [
            rf"valor\s+d[ae]\s+avaliacao[^\d\n]{{0,40}}{_MOEDA}",
            rf"avaliad[oa]s?\s+(?:em|por)\s+{_MOEDA}",
            rf"avaliacao[:\s][^\d\n]{{0,30}}{_MOEDA}",
            rf"valor\s+do\s+bem[^\d\n]{{0,30}}{_MOEDA}",
        ]
        m = _primeiro(ctx, padroes)
        if not m:
            return []
        match, indice = m
        valor = parse_moeda(match.group(1))
        if valor is None or valor <= 0:
            return []
        # Varios valores de avaliacao no mesmo edital indicam lotes multiplos:
        # baixamos a confianca em vez de escolher um ao acaso. Mas "nao inferior
        # a 50% do valor da avaliacao, ou seja, R$ X" NAO e um segundo valor de
        # avaliacao -- e o lance minimo da 2a praca. Sem descartar essas mencoes
        # antes de contar, quase todo edital cairia em revisao e o selo de
        # confianca deixaria de significar alguma coisa.
        def _e_mencao_de_lance(posicao: int) -> bool:
            antes = ctx.busca[max(0, posicao - 90) : posicao]
            return bool(re.search(r"(inferior|lance|minimo|% d[ae])", antes))

        distintos = {
            parse_moeda(c.group(1))
            for c in _buscar(ctx, padroes[indice])
            if not _e_mencao_de_lance(c.start())
        }
        confianca = CONF_ROTULO_EXPLICITO if len(distintos) <= 1 else CONF_ROTULO_AMBIGUO
        return [
            Achado(
                nome="valor_avaliacao",
                valor_numerico=valor,
                confianca=confianca if indice < 2 else CONF_ROTULO_AMBIGUO,
                evidencia=ctx.evidencia(match.start(), match.end()),
            )
        ]

    def _pracas(self, ctx: Contexto) -> list[Achado]:
        achados: list[Achado] = []
        ordens = (
            (1, r"(?:1[ªa°º]|primeir[ao])\s*(?:praca|leilao|hasta|data)"),
            (2, r"(?:2[ªa°º]|segund[ao])\s*(?:praca|leilao|hasta|data)"),
        )
        for ordem, prefixo in ordens:
            for match in _buscar(ctx, prefixo):
                # Janela a frente do rotulo: data, hora e valor costumam vir juntos.
                janela_ini = match.start()
                janela_fim = min(len(ctx.busca), match.end() + 220)
                trecho_original = ctx.original[janela_ini:janela_fim]

                data = parse_data_hora(trecho_original)
                valor = parse_moeda(
                    next(
                        (
                            g.group(1)
                            for g in re.finditer(_MOEDA, trecho_original, re.IGNORECASE)
                        ),
                        None,
                    )
                )
                if data is not None:
                    achados.append(
                        Achado(
                            nome=f"data_praca_{ordem}",
                            valor_data=data,
                            confianca=CONF_ROTULO_EXPLICITO,
                            evidencia=ctx.evidencia(janela_ini, janela_fim, margem=0),
                        )
                    )
                if valor is not None and valor > 0:
                    achados.append(
                        Achado(
                            nome=f"valor_minimo_praca_{ordem}",
                            valor_numerico=valor,
                            confianca=CONF_ROTULO_EXPLICITO,
                            evidencia=ctx.evidencia(janela_ini, janela_fim, margem=0),
                        )
                    )
                if data is not None or valor is not None:
                    break  # primeira ocorrencia util por ordem de praca

        if not achados:
            m = _primeiro(ctx, [r"(?:praca|leilao)\s+unic[oa]"])
            if m:
                match, _ = m
                janela = ctx.original[match.start() : match.end() + 220]
                data = parse_data_hora(janela)
                if data is not None:
                    achados.append(
                        Achado(
                            nome="data_praca_1",
                            valor_data=data,
                            confianca=CONF_ROTULO_EXPLICITO,
                            evidencia=limpar_espacos(janela),
                        )
                    )
        return achados

    def _percentual_minimo(self, ctx: Contexto) -> list[Achado]:
        padroes = [
            r"nao\s+(?:sera|podera\s+ser|serao)\s+(?:aceito|admitido)?s?\s*"
            r"(?:lance|valor)?[^%\n]{0,60}inferior\s+a\s+(\d{1,3}(?:[.,]\d+)?)\s*%",
            r"lance\s+minimo[^%\n]{0,60}(\d{1,3}(?:[.,]\d+)?)\s*%",
            r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:do\s+valor\s+)?d[ae]\s+avaliacao",
        ]
        m = _primeiro(ctx, padroes)
        if not m:
            return []
        match, indice = m
        pct = parse_percentual(match.group(0))
        if pct is None:
            return []
        return [
            Achado(
                nome="percentual_minimo_segunda_praca",
                valor_numerico=pct,
                confianca=CONF_ROTULO_EXPLICITO if indice < 2 else CONF_INFERIDO,
                evidencia=ctx.evidencia(match.start(), match.end()),
            )
        ]

    def _comissao(self, ctx: Contexto) -> list[Achado]:
        m = _primeiro(
            ctx,
            [
                # Sem excluir \n: o percentual cai na linha seguinte com frequencia.
                r"comissao\s+d[oe]\s+leiloeir[oa][^%]{0,80}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
                r"comissao[^%]{0,60}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
            ],
        )
        if not m:
            return []
        match, indice = m
        pct = parse_percentual(match.group(0))
        if pct is None or pct > 20:  # comissao acima de 20% quase certamente e outro numero
            return []
        return [
            Achado(
                nome="comissao_leiloeiro",
                valor_numerico=pct,
                confianca=CONF_ROTULO_EXPLICITO if indice == 0 else CONF_ROTULO_AMBIGUO,
                evidencia=ctx.evidencia(match.start(), match.end()),
            )
        ]

    # -- descricao do bem --------------------------------------------------

    def _imovel(self, ctx: Contexto) -> list[Achado]:
        achados: list[Achado] = []
        # A matricula do IMOVEL e a matricula do LEILOEIRO usam a mesma palavra, e
        # a do leiloeiro costuma aparecer primeiro no edital. Por isso exigimos
        # contexto registral em vez de pegar a primeira ocorrencia.
        # Termina obrigatoriamente em digito: senao "matricula 99.123." leva o
        # ponto final da frase junto.
        matricula = r"([\d][\d.\-/]{0,17}\d)"
        ordinal = r"(?:n?[oº°.]?\s*)?"
        m = _primeiro(
            ctx,
            [
                rf"matricula\s*{ordinal}{matricula}\s+d[oe]\s+\d*\s*"
                r"(?:oficio|cartorio|registro|servico\s+registral)",
                rf"objeto\s+d[ao]\s+matricula\s*{ordinal}{matricula}",
                rf"imovel\s+matriculado\s+sob\s+(?:o\s+)?{ordinal}{matricula}",
                rf"matricula\s+(?:do\s+)?imovel\s*{ordinal}{matricula}",
            ],
        )
        if m is None:
            # Ultimo recurso, sempre marcado para revisao: qualquer "matricula N"
            # que nao esteja NA MESMA FRASE de uma mencao a leiloeiro ou junta.
            # O corte por frase (e nao por numero de caracteres) e o que separa
            # "Leiloeiro X, matricula 07/2010." de "Bem: terreno de matricula 99.123".
            for candidato in _buscar(ctx, rf"matricula\s*{ordinal}{matricula}"):
                antes = ctx.busca[max(0, candidato.start() - 200) : candidato.start()]
                frase_atual = re.split(r"[.;:\n]\s", antes)[-1]
                if re.search(r"leiloeir|juce", frase_atual):
                    continue
                m = (candidato, 99)
                break
        if m:
            match, indice = m
            achados.append(
                Achado(
                    nome="matricula_imovel",
                    valor_texto=limpar_espacos(ctx.original[match.start(1) : match.end(1)]),
                    confianca=CONF_ROTULO_EXPLICITO if indice < 99 else CONF_INFERIDO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            )
        m = _primeiro(
            ctx,
            [
                r"(\d+[ºo]?\s*(?:oficio|cartorio|servico\s+registral|registro\s+de\s+imoveis)"
                r"[a-zà-ÿ\s]{0,40})",
                r"(cartorio\s+d[eo]\s+[a-zà-ÿ\s]{3,40})",
            ],
        )
        if m:
            match, _ = m
            # O nome do cartorio costuma vir grudado em "da Comarca de X".
            cartorio = limpar_espacos(ctx.original[match.start(1) : match.end(1)]) or ""
            cartorio = re.split(r"\s+d[ao]\s+[Cc]omarca\b", cartorio, maxsplit=1)[0]
            achados.append(
                Achado(
                    nome="cartorio",
                    valor_texto=limpar_espacos(cartorio),
                    confianca=CONF_ROTULO_AMBIGUO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            )

        # Editais trazem as duas areas na mesma frase ("privativa de 68,50 m2 e
        # area total de 92,30 m2"). Guardamos as duas separadas: trocar uma pela
        # outra distorce o R$/m2 da comparacao de mercado da secao 4.5.
        for nome, rotulo in (
            ("area_total_m2", r"area\s+(?:total|do\s+terreno|do\s+lote)"),
            ("area_privativa_m2", r"area\s+(?:privativa|util|construida)"),
        ):
            m = _primeiro(ctx, [rotulo + r"[^\d\n]{0,20}([\d.,]+\s*m(?:2|²))"])
            if not m:
                continue
            match, _ = m
            area = parse_area(ctx.original[match.start() : match.end()])
            if area:
                achados.append(
                    Achado(
                        nome=nome,
                        valor_numerico=area,
                        confianca=CONF_ROTULO_EXPLICITO,
                        evidencia=ctx.evidencia(match.start(), match.end()),
                    )
                )

        if not any(a.nome.startswith("area_") for a in achados):
            m = _primeiro(ctx, [r"([\d.,]+\s*m(?:2|²))\s+de\s+area"])
            if m:
                match, _ = m
                area = parse_area(ctx.original[match.start() : match.end()])
                if area:
                    achados.append(
                        Achado(
                            nome="area_total_m2",
                            valor_numerico=area,
                            confianca=CONF_INFERIDO,
                            evidencia=ctx.evidencia(match.start(), match.end()),
                        )
                    )
        return achados

    def _ocupacao(self, ctx: Contexto) -> list[Achado]:
        """Ocupacao e um dos maiores fatores de risco -- e "desocupado" contem
        "ocupado", entao a ordem dos testes importa."""
        desocupado = _primeiro(
            ctx,
            [
                r"\bdesocupad[oa]\b",
                r"livre\s+de\s+(?:ocupantes|pessoas\s+e\s+coisas)",
                r"encontra-se\s+(?:vago|vazio)\b",
            ],
        )
        ocupado = _primeiro(
            ctx,
            [
                r"(?<!des)\bocupad[oa]\s+(?:por|pelo|pela)\b",
                r"encontra-se\s+(?<!des)ocupad[oa]\b",
                r"imovel\s+(?<!des)ocupad[oa]\b",
            ],
        )
        if ocupado and not desocupado:
            match, _ = ocupado
            return [
                Achado(
                    nome="ocupado",
                    valor_booleano=True,
                    confianca=CONF_ROTULO_EXPLICITO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            ]
        if desocupado and not ocupado:
            match, _ = desocupado
            return [
                Achado(
                    nome="ocupado",
                    valor_booleano=False,
                    confianca=CONF_ROTULO_EXPLICITO,
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            ]
        if desocupado and ocupado:
            match, _ = ocupado
            return [
                Achado(
                    nome="ocupado",
                    valor_booleano=True,
                    confianca=CONF_INFERIDO,  # contraditorio: vai para revisao
                    evidencia=ctx.evidencia(match.start(), match.end()),
                )
            ]
        return []

    _TERMOS_ONUS = (
        ("hipoteca", r"\bhipotec[ae]"),
        ("penhora", r"\bpenhor[ae]d?[oa]?\b"),
        ("alienacao_fiduciaria", r"alienacao\s+fiduciaria"),
        ("usufruto", r"\busufrut"),
        ("arresto", r"\barrest[oa]"),
        ("indisponibilidade", r"indisponibilidade\s+de\s+bens"),
        ("servidao", r"\bservidao\b"),
        ("inalienabilidade", r"clausula\s+de\s+inalienabilidade"),
        ("arrolamento", r"\barrolament"),
    )

    def _onus(self, ctx: Contexto) -> list[Achado]:
        encontrados: list[str] = []
        evidencias: list[str] = []
        for rotulo, padrao in self._TERMOS_ONUS:
            achados = _buscar(ctx, padrao)
            if not achados:
                continue
            # "livre de hipoteca" e o contrario de "gravado por hipoteca".
            match = achados[0]
            antes = ctx.busca[max(0, match.start() - 40) : match.start()]
            if re.search(r"(livre|sem|inexist|nao\s+consta|nada\s+consta)[^.]{0,25}$", antes):
                continue
            encontrados.append(rotulo)
            evidencias.append(ctx.evidencia(match.start(), match.end(), margem=80))
        if not encontrados:
            return []
        return [
            Achado(
                nome="onus",
                valor_texto=", ".join(encontrados),
                confianca=CONF_ROTULO_AMBIGUO,
                evidencia=" | ".join(evidencias[:3]),
            )
        ]

    _TERMOS_DEBITO = (
        ("iptu", r"\biptu\b"),
        ("condominio", r"\bcondominio\b"),
        ("ipva", r"\bipva\b"),
        ("multas", r"\bmultas?\s+(?:de\s+transito|do\s+detran)"),
        ("taxa_incendio", r"taxa\s+de\s+incendio"),
    )

    def _debitos(self, ctx: Contexto) -> list[Achado]:
        achados: list[Achado] = []
        rotulos: list[str] = []
        evidencias: list[str] = []
        for rotulo, padrao in self._TERMOS_DEBITO:
            encontrados = _buscar(ctx, padrao)
            if not encontrados:
                continue
            match = encontrados[0]
            rotulos.append(rotulo)
            evidencias.append(ctx.evidencia(match.start(), match.end(), margem=100))
            # Valor logo depois do termo, se houver.
            janela = ctx.original[match.start() : match.end() + 160]
            valor_match = re.search(_MOEDA, janela, re.IGNORECASE)
            if valor_match:
                valor = parse_moeda(valor_match.group(1))
                if valor:
                    achados.append(
                        Achado(
                            nome=f"debito_{rotulo}",
                            valor_numerico=valor,
                            confianca=CONF_ROTULO_AMBIGUO,
                            evidencia=limpar_espacos(janela),
                        )
                    )
        if rotulos:
            achados.append(
                Achado(
                    nome="debitos_mencionados",
                    valor_texto=", ".join(rotulos),
                    confianca=CONF_ROTULO_AMBIGUO,
                    evidencia=" | ".join(evidencias[:3]),
                )
            )
        return achados

    def _sub_rogacao(self, ctx: Contexto) -> list[Achado]:
        """O edital diz que o debito tributario sai do preco ou fica com quem arremata?

        Relatamos o que esta escrito, com o trecho literal. Nao emitimos parecer:
        a leitura juridica e do advogado do usuario (secao 11).
        """
        sub_roga = _primeiro(
            ctx,
            [
                r"sub-?rog(?:am|a)(?:-se)?\s+(?:no|sobre\s+o)\s+(?:respectivo\s+)?preco",
                r"art(?:igo)?\.?\s*130[^.]{0,60}(?:ctn|codigo\s+tributario)",
                r"art(?:igo)?\.?\s*908[^.]{0,40}(?:cpc|codigo\s+de\s+processo)",
            ],
        )
        assume = _primeiro(
            ctx,
            [
                r"(?:debitos|onus|dividas)[^.]{0,80}(?:correrao|ficarao|serao)[^.]{0,40}"
                r"(?:por\s+conta|de\s+responsabilidade)\s+d[oa]\s+arrematante",
                r"arrematante\s+(?:assume|arcara\s+com|sera\s+responsavel\s+por)"
                r"[^.]{0,80}(?:debitos|dividas|onus)",
            ],
        )
        achados: list[Achado] = []
        if sub_roga:
            match, _ = sub_roga
            achados.append(
                Achado(
                    nome="edital_invoca_sub_rogacao_no_preco",
                    valor_booleano=True,
                    confianca=CONF_ROTULO_EXPLICITO,
                    evidencia=ctx.evidencia(match.start(), match.end(), margem=160),
                )
            )
        if assume:
            match, _ = assume
            achados.append(
                Achado(
                    nome="edital_atribui_debitos_ao_arrematante",
                    valor_booleano=True,
                    confianca=CONF_ROTULO_EXPLICITO,
                    evidencia=ctx.evidencia(match.start(), match.end(), margem=160),
                )
            )
        return achados

    _FORMAS = (
        ("a_vista", r"(?:pagamento\s+)?a\s+vista"),
        ("parcelado", r"\bparcelad[oa]|parcelamento\b"),
        ("fgts", r"\bfgts\b"),
        ("financiamento", r"\bfinanciament"),
    )

    def _formas_pagamento(self, ctx: Contexto) -> list[Achado]:
        formas = [
            rotulo for rotulo, padrao in self._FORMAS if _buscar(ctx, padrao)
        ]
        if not formas:
            return []
        primeiro = _primeiro(ctx, [p for _, p in self._FORMAS])
        match = primeiro[0] if primeiro else None
        return [
            Achado(
                nome="formas_pagamento",
                valor_texto=", ".join(formas),
                confianca=CONF_ROTULO_AMBIGUO,
                evidencia=ctx.evidencia(match.start(), match.end()) if match else "",
            )
        ]

    _CONDICAO_VEICULO = (
        ("sucata", r"\bsucata|\bsinistrad[oa]\b|perda\s+total"),
        ("sem_chave", r"sem\s+(?:a\s+)?chave"),
        ("sem_documento", r"sem\s+(?:o\s+)?document|documentacao\s+(?:irregular|pendente)"),
        ("sem_motor", r"sem\s+motor"),
        ("nao_vistoriado", r"nao\s+(?:foi\s+)?vistoriad"),
    )

    def _veiculo(self, ctx: Contexto) -> list[Achado]:
        condicoes: list[str] = []
        evidencias: list[str] = []
        for rotulo, padrao in self._CONDICAO_VEICULO:
            achados = _buscar(ctx, padrao)
            if achados:
                condicoes.append(rotulo)
                evidencias.append(ctx.evidencia(achados[0].start(), achados[0].end(), margem=80))
        if not condicoes:
            return []
        return [
            Achado(
                nome="condicao_veiculo",
                valor_texto=", ".join(condicoes),
                confianca=CONF_ROTULO_AMBIGUO,
                evidencia=" | ".join(evidencias[:3]),
            )
        ]


def extrair_de_texto(texto: str) -> ResultadoExtracao:
    return ParserEdital().extrair(texto)
