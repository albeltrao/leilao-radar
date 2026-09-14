# Conformidade legal, ética e de confiabilidade

Os requisitos da seção 11 da especificação são **não negociáveis**. Este
documento diz onde cada um é cumprido, para que a revisão seja verificável.

## 1. O sistema informa, não aconselha

| Exigência | Onde |
|---|---|
| Disclaimer visível em cada lote | `api/schemas.py::DISCLAIMER_LOTE`, exibido no detalhe, no e-mail de alerta e na descrição de cada evento `.ics` |
| Disclaimer na agenda por tipo de bem | `api/schemas.py::DISCLAIMER_AGENDA`, devolvido em `/api/agenda` e exibido no rodapé da página **Diários** |
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

O mesmo vale para o que a leitura do Diário da Justiça deriva:

| Campo | Como é obtido | Onde a prova aparece |
|---|---|---|
| `natureza_bem` (móvel/imóvel) | regra sobre o texto, `diarios/classificacao.py` | `campo_extraido`, e no item da agenda como `evidencia_natureza` |
| `zona_imovel` (rural/urbana) | idem, só para imóvel | `campo_extraido`, e como `evidencia_zona` |
| `leilao_detectado_em_diario` | `diarios/deteccao.py` | `PublicacaoDiario.evidencia` e `ItemAgenda.diario.evidencia` |

Três limites deliberados do classificador:

1. **Teto de confiança em 0,95.** Nenhuma classificação por regra chega a 1,0: a
   frase pode estar descrevendo outro lote da mesma publicação.
2. **Conflito vira `INDEFINIDA`, não o sinal mais forte.** "Sítio" e "perímetro
   urbano" na mesma publicação — que acontece de verdade em imóvel dentro do
   perímetro urbano expandido — dá zona indefinida com revisão marcada. A
   diferença entre 0,90 e 0,88 não é conhecimento.
3. **`INDEFINIDA` é exibida, não escondida.** A agenda tem a faixa "Imóveis sem
   zona identificada". Empurrar esses lotes para "urbano" por ser o mais comum
   seria inventar dado.

Teste: `test_diarios.py::test_classificacao_sempre_traz_evidencia_literal`,
`::test_zona_em_conflito_fica_indefinida_e_vai_para_revisao`,
`test_agenda.py::test_lote_do_diario_guarda_classificacao_com_evidencia`.

## 3. LGPD — minimização

| Dado | Tratamento |
|---|---|
| CPF | removido **antes** de gravar (`remover_cpf`), tanto do texto do edital quanto da publicação de diário |
| Texto do diário | truncado no recorte que sustenta a detecção (`RADAR_DIARIO_MAX_CARACTERES_TEXTO`, 4000); o caderno completo não é arquivado |
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
  API, não raspagem — e por isso o Diário da Justiça é lido pela **API Comunica**
  do CNJ (DJEN, Res. CNJ 455/2022), e não raspando o PDF do caderno de cada
  tribunal. A API cobre as duas esferas exigidas, estadual e federal.
- A busca do diário já vai ao servidor **filtrada pelos termos de leilão**, em
  vez de baixar o caderno inteiro para descartar quase tudo: menos tráfego para
  os dois lados. O filtro é peneira grossa; quem decide se é leilão é o detector
  local, com evidência auditável.

Teste: `test_http.py` inteiro (8 testes), incluindo a verificação de que a
requisição proibida **não sai**.

## 5. Auditoria

- O conteúdo bruto de cada coleta é arquivado por 30 dias, com a URL de origem
  ao lado, para depurar quebra de layout e servir de prova do que a fonte
  publicava naquele dia — HTML dos portais e o JSON das respostas do DJEN
  (`radar limpar-raw` aplica a retenção).
- Cada publicação de diário lida fica gravada com o identificador da comunicação,
  a data, a confiança da detecção e o trecho que a sustentou — inclusive as
  **descartadas**, que é o que permite auditar o falso negativo do detector.
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

- **Validação ao vivo dos conectores.** 29 de 30 nunca rodaram contra a fonte
  real. Até que rodem, a coleta automática os pula e a interface mostra o selo
  "não validada".
- **Contrato da API Comunica/DJEN não conferido.** Os nomes de campo vieram da
  documentação, não de uma resposta observada; o parser aceita mais de uma
  grafia por campo por causa disso. Confirme com
  `radar fontes validar --fonte djen-tjal` antes de ligar em produção.
- **Limiar de detecção não medido.** `RADAR_DIARIO_LIMIAR_DETECCAO` = 0,55 é
  calibragem de laboratório. Só dá para ajustá-lo com diário real: as
  publicações descartadas ficam gravadas e visíveis (`radar diarios publicacoes
  --todas`, ou o filtro na página **Diários**) exatamente para permitir medir o
  falso negativo.
- **Termos de uso individuais.** Respeitar `robots.txt` é necessário, não
  suficiente: antes de ligar um conector de site de leiloeiro em produção, leia
  os termos daquele site e prefira parceria ou API oficial quando existir.
- **Portais de anúncio (OLX, VivaReal, Zap).** A camada de comparáveis da seção
  4.5 **não foi implementada** justamente porque exige acordo comercial ou API
  oficial. O código tem o enum `FonteMercado.COMPARAVEIS` reservado, sem coletor.
