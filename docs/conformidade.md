# Conformidade legal, ética e de confiabilidade

Os requisitos da seção 11 da especificação são **não negociáveis**. Este
documento diz onde cada um é cumprido, para que a revisão seja verificável.

## 1. O sistema informa, não aconselha

| Exigência | Onde |
|---|---|
| Disclaimer visível em cada lote | `api/schemas.py::DISCLAIMER_LOTE`, exibido no detalhe, no e-mail de alerta e na descrição de cada evento `.ics` |
| Não emitir parecer jurídico | `extraction/edital.py` relata que *o edital invoca* o art. 130 do CTN, com o trecho citado, e nunca conclui quem paga o quê |
| Conteúdo educativo com referência legal | `api/conteudo.py` — cada passo cita a norma (CPC arts. 891/895, CTN art. 130, Resolução CNJ 236/2016) |

Teste: `test_api.py::test_detalhe_traz_procedencia_de_tudo`,
`test_extracao.py::test_sub_rogacao_relata_os_dois_lados_sem_opinar`.

## 2. Nada extraído por IA é apresentado como garantido

Todo campo carrega `confianca`, `metodo` e `evidencia` (o trecho literal do
documento). Abaixo de `LIMIAR_REVISAO` (0,70) o campo vem com
`revisao_necessaria: true` e a interface mostra "confira no edital".

A extração por LLM tem três salvaguardas:

1. **Evidência verificada** — o modelo é obrigado a devolver o trecho literal
   que sustenta cada campo; se o trecho não existir no documento de origem, o
   campo é descartado. É a defesa concreta contra alucinação.
2. **Whitelist de campos** — campo fora da lista conhecida é ignorado, o que
   também impede o modelo de introduzir dado pessoal.
3. **Teto de confiança** — achado que só o modelo viu entra abaixo do limiar e
   cai automaticamente na fila de revisão.

Teste: `test_extracao.py::test_llm_descarta_campo_sem_evidencia_no_documento`,
`::test_llm_descarta_campo_fora_da_whitelist`.

## 3. LGPD — minimização

| Dado | Tratamento |
|---|---|
| CPF | removido do texto do edital **antes** de gravar (`remover_cpf`) |
| Placa de veículo | mascarada: `OKZ1D23` → `OKZ1**3` |
| Partes do processo | `Processo.partes_resumo` aceita apenas resumo já minimizado; a API não expõe |
| Endereço | só o do bem leiloado, nunca residencial de terceiro |

Teste: `test_ingestao.py::test_lgpd_cpf_removido_da_descricao`,
`::test_lgpd_placa_mascarada`.

## 4. Respeito às fontes

- `robots.txt` é consultado **antes de cada URL** e o resultado é cacheado por
  host. `Disallow` bloqueia; `Crawl-delay` vira limite de taxa daquele host.
- **5xx no `robots.txt` bloqueia a fonte** (RFC 9309). Preferimos perder uma
  coleta a raspar um site que talvez nos proíba. 404 libera, como manda a norma.
- User-Agent identificável com URL de contato — **troque o contato por um real
  antes de rodar contra site de terceiro** (`RADAR_USER_AGENT`).
- Limite mínimo de 1,5 s por host, com backoff exponencial e respeito a
  `Retry-After` em 429/503.
- Nunca há tentativa de contornar login, captcha ou controle de acesso.
- API oficial tem preferência sobre scraping: por isso o DataJud é cliente de
  API, não raspagem.

Teste: `test_http.py` inteiro (8 testes), incluindo a verificação de que a
requisição proibida **não sai**.

## 5. Auditoria

- O HTML bruto de cada coleta é arquivado por 30 dias, com a URL de origem ao
  lado, para depurar quebra de layout e servir de prova do que o site publicava
  naquele dia (`radar limpar-raw` aplica a retenção).
- Cada dado exibido leva link para o documento-fonte.
- Cada execução de coleta vira uma linha em `execucao_coleta`, com status,
  duração, contagem de itens e erro — exibida na página **Fontes**.

## 6. Idade e procedência da informação

- Cada lote mostra `coletado_em` e `visto_por_ultimo_em`.
- Cada análise de mercado mostra `data_referencia_fonte` (o mês do boletim
  FipeZap, o mês de referência da FIPE) e a metodologia em texto.
- Enquanto os dados de mercado de **demonstração** estiverem carregados, toda
  análise sai com aviso em caixa alta e confiança reduzida à metade.

## 7. O que ainda não está resolvido

- **Validação ao vivo dos conectores.** 19 de 20 nunca rodaram contra o site
  real. Até que rodem, a coleta automática os pula e a interface mostra o selo
  "não validada".
- **Termos de uso individuais.** Respeitar `robots.txt` é necessário, não
  suficiente: antes de ligar um conector de site de leiloeiro em produção, leia
  os termos daquele site e prefira parceria ou API oficial quando existir.
- **Portais de anúncio (OLX, VivaReal, Zap).** A camada de comparáveis da seção
  4.5 **não foi implementada** justamente porque exige acordo comercial ou API
  oficial. O código tem o enum `FonteMercado.COMPARAVEIS` reservado, sem coletor.
