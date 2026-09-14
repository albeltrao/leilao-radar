# Radar Leilão

Monitoramento de **leilões judiciais de Alagoas, Bahia, Pernambuco e Sergipe**: lê o
**Diário da Justiça** das esferas estadual e federal, coleta os editais das fontes
oficiais, lê o que está escrito neles, compara com referência de mercado e organiza
tudo em uma agenda cronológica separada por tipo de bem — móveis e imóveis, rurais e
urbanos — além do calendário e do painel.

O diferencial não é agregar leilões — é **traduzir edital jurídico denso em uma
decisão clara**, com honestidade sobre o limite de cada dado.

> O sistema organiza e enriquece informação pública. Ele **não** presta
> assessoria jurídica nem recomendação de investimento. Toda informação é
> extraída automaticamente do edital oficial: consulte o documento original e um
> advogado antes de participar de um leilão.

---

## Estado atual, sem maquiagem

O que **funciona e está testado** (248 testes, todos offline):

| Área | Estado |
|---|---|
| Modelo de dados (22 tabelas) | pronto |
| Normalização pt-BR (moeda, datas, área, dígito verificador CNJ) | pronto |
| Camada HTTP com robots.txt, rate limit e arquivamento do bruto | pronto |
| Pipeline de ingestão: fila, deduplicação, idempotência | pronto |
| Leitura do Diário da Justiça (DJEN/CNJ) e detecção de leilão | pronto |
| Classificação do bem: móvel/imóvel e rural/urbano, com evidência | pronto |
| Agenda cronológica por tipo de bem (API, `.ics` e tela) | pronto |
| Parser de edital (22 campos no edital de imóvel de referência) | pronto |
| Extração por LLM com verificação de evidência | pronto (desligada por padrão) |
| Comparação de mercado e score explicável | pronto |
| Calendário, exportação `.ics`, alertas por e-mail | pronto |
| API REST (27 rotas) e autenticação | pronto |
| Frontend (painel, detalhe, calendário, diários, mapa, onboarding) | pronto |

O que **ainda não foi validado**:

- **29 dos 30 conectores nunca rodaram contra a fonte real.** O ambiente onde
  este código foi escrito não tem saída de rede para os portais dos tribunais,
  das juntas comerciais nem para a API do CNJ. Os parsers foram exercitados
  contra fixtures sintéticas, modeladas na estrutura documentada de cada
  página — não contra capturas reais. Cada fonte carrega
  `validado_ao_vivo: false` e a coleta automática **pula** essas fontes até que
  alguém rode a validação (abaixo).

- **O contrato da API Comunica/DJEN não foi conferido.** Os nomes de campo dos
  seis conectores de diário (`djen-tjal`, `djen-tjba`, `djen-tjpe`, `djen-tjse`,
  `djen-trf1`, `djen-trf5`) vêm da documentação da API, não de uma resposta
  observada. O parser aceita mais de uma grafia por campo justamente por isso;
  ainda assim, confirme com `radar fontes validar --fonte djen-tjal` antes de
  ligar em produção.

- **O cadastro de leiloeiros está vazio.** Os nomes e as matrículas dos
  leiloeiros públicos oficiais são dados de pessoas reais e só entram no
  sistema vindos da fonte oficial — não há lista embutida no repositório.
  Um comando popula tudo (ver "Cadastro de leiloeiros" abaixo).

- **As URLs do TJBA e da JUCEB são candidatas, não confirmadas.** A
  especificação original cobria AL, SE e PE e trazia os caminhos exatos; para a
  Bahia eles foram inferidos do domínio do tribunal e da junta, e estão
  marcados como `URL CANDIDATA` na descrição da fonte.
- **Os dados de mercado do repositório são amostras de demonstração**, não a
  tabela FIPE nem o boletim FipeZap reais. Enquanto estiverem em uso, toda
  análise sai com aviso em caixa alta e confiança reduzida à metade.
- **DataJud precisa de chave.** Sem `RADAR_DATAJUD_API_KEY` o enriquecimento
  processual é pulado (o resto do pipeline segue funcionando).

- **O limiar de detecção de leilão no diário é um palpite calibrado, não medido.**
  `RADAR_DIARIO_LIMIAR_DETECCAO` vale 0,55 por padrão. Publicações abaixo do
  limiar ficam guardadas e visíveis na aba "Diários" — é assim que se descobre
  se ele está engolindo leilão de verdade.

Nada disso é escondido do usuário: a página **Fontes** do painel mostra o selo
de validação de cada conector e a data da última coleta bem-sucedida, e a página
**Diários** mostra a confiança e o trecho literal de cada detecção.

---

## Rodando em 3 minutos

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
.venv/bin/radar seed                 # dados FICTÍCIOS de demonstração
cd frontend && npm install && npm run build && cd ..
.venv/bin/radar servir               # http://127.0.0.1:8000
```

Usuário de demonstração: `demo@example.org` / `radar-demo-2026`.

> Já tinha um `radar.db` de uma versão anterior? O schema ganhou colunas nesta
> versão e ainda não há migração versionada: `make limpar` apaga o banco e
> `radar seed` recria. Se você tentar usar o banco antigo, o sistema avisa com
> as colunas que faltam em vez de quebrar no meio de uma consulta.

Para desenvolver o frontend com recarga automática, rode a API e o Vite em
paralelo (`radar servir` e `npm run dev` — o Vite já faz proxy de `/api`).

---

## Cadastro de leiloeiros

Os leiloeiros públicos oficiais são pessoas reais, com matrícula real numa junta
comercial. Por isso **não há lista embutida no repositório**: inventar nomes
criaria registro falso sobre gente identificável, e o cadastro é justamente o
que gera a lista de sites a monitorar e a credencial exibida em cada lote.

O caminho é um comando, a partir de um ambiente com saída de rede:

```bash
radar leiloeiros coletar                  # JUCEAL, JUCEB, JUCEPE, JUCESE + corregedorias
radar leiloeiros listar --uf BA           # confere o que entrou
radar leiloeiros sugerir-perfis --uf BA   # gera o YAML dos conectores de cada site
```

O último imprime perfis prontos para colar em
`backend/src/radar/data/perfis_leiloeiros.yaml` — é assim que o cadastro mestre
(quem pode leiloar) vira conector de coleta (o que está sendo leiloado), como
manda a seção 4.3 da especificação.

## Diário da Justiça: como um leilão é detectado

O sistema lê o **Diário de Justiça Eletrônico Nacional** (DJEN), onde tribunais
estaduais e federais publicam desde a Resolução CNJ nº 455/2022, pela **API
Comunica** do CNJ. É API oficial, pública e em JSON — a seção 11 da
especificação manda preferi-la a raspar o PDF de cada caderno.

```bash
radar diarios coletar --incluir-nao-validados   # lê a janela dos últimos dias
radar diarios publicacoes --todas               # o que entrou e o que foi descartado
radar diarios agenda --dias 30                  # a agenda, por tipo de bem
radar diarios agenda --categoria IMOVEL_RURAL --esfera FEDERAL
```

O caminho de uma publicação até a agenda:

1. **Coleta.** Um conector por tribunal (`djen-tjal`, `djen-tjba`, `djen-tjpe`,
   `djen-tjse`, `djen-trf1`, `djen-trf5`). Um por tribunal, e não um só para
   tudo, porque o painel de saúde mede fonte a fonte: assim "o DJEN do TJPE
   parou" aparece com nome.
2. **Detecção.** `radar.diarios.detectar_leilao` pontua a publicação e devolve
   **confiança + os trechos literais** que a sustentam. Leilão de energia da
   ANEEL e pregão de licitação são descontados de propósito. Abaixo do limiar a
   publicação fica gravada, mas não vira lote.
3. **Classificação do bem.** `radar.diarios.classificar_bem` decide
   móvel × imóvel e, sendo imóvel, rural × urbano — cada eixo com confiança,
   método e o trecho que o gerou, gravados em `campo_extraido`. Sinais em
   conflito ("sítio" + "perímetro urbano") dão `INDEFINIDA` com revisão marcada,
   nunca o lado mais pesado por uma diferença de 0,02.
4. **Lote.** A publicação vira um lote magro (processo, praças, avaliação,
   leiloeiro) que passa pela mesma deduplicação de sempre: quando o site do
   leiloeiro publicar o mesmo processo, os dois viram um só.
5. **Agenda.** `/api/agenda` devolve a lista cronológica **e** as contagens por
   categoria no mesmo payload — dois recortes do mesmo filtro, para a tela não
   contar por conta própria e divergir do backend.

Na tela, cada item traz "por que está nesta categoria?", que abre a frase lida.
Classificação derivada sem a prova ao lado seria afirmação sem procedência, e a
seção 11 não admite isso.

**Justiça federal.** O código TR do número CNJ **não** dá a UF de um processo
federal: o TRF5 responde por seis estados. A UF sai da seção judiciária citada no
texto (`uf_da_secao_judiciaria`). Sem isso, um lote federal de Pernambuco entraria
sem estado e sumiria de todo filtro.

**LGPD.** O diário cita as partes. O CPF é removido antes de gravar e o texto é
truncado no recorte que sustenta a detecção
(`RADAR_DIARIO_MAX_CARACTERES_TEXTO`, 4000 por padrão) — o caderno inteiro não é
arquivado.

---

## Validando um conector contra o site real

Este é o passo que falta para o sistema sair do laboratório. Para cada fonte:

```bash
# 1. Baixa a página agora e mostra o que o parser extraiu. Não grava nada.
.venv/bin/radar fontes validar --fonte tjpe-leiloes-judiciais

# 2. O HTML bruto fica em data/raw/<fonte>/<data>/. Copie para as fixtures:
cp data/raw/tjpe-leiloes-judiciais/2026-09-13/*.html \
   backend/tests/fixtures/html/tjpe_leiloes.html

# 3. Ajuste o parser até o teste de regressão passar com o HTML real.
# 4. Marque validado_ao_vivo: true (no MetadadosFonte ou no perfil YAML).
# 5. A partir daí a fonte entra na coleta automática.
```

Sites de leiloeiro são configurados em
[`backend/src/radar/data/perfis_leiloeiros.yaml`](backend/src/radar/data/perfis_leiloeiros.yaml):
adicionar um leiloeiro é editar YAML, não escrever código.

```bash
.venv/bin/radar fontes listar                     # estado de validação de tudo
.venv/bin/radar coletar --todas                   # só as fontes validadas
.venv/bin/radar coletar --fonte X --incluir-nao-validados   # forçar uma
```

---

## Como o sistema está montado

```
  fontes oficiais           ingestão                 análise              produto
┌──────────────────┐   ┌────────────────┐   ┌──────────────────┐   ┌──────────────┐
│ DJEN: TJ + TRF   │   │ fila           │   │ detector de      │   │ API REST     │
│ TJAL TJBA TJPE   │   │                │   │ leilão no diário │   │              │
│ TJSE             │   │ normalização   │   │ parser de edital │   │ painel React │
│ JUCEAL/EB/PE/SE  │──▶│ classificação  │──▶│ + LLM opcional   │──▶│ agenda por   │
│ sites leiloeiros │   │ deduplicação   │   │ FIPE / FipeZap   │   │ tipo de bem  │
│ DataJud (CNJ)    │   │ geocodificação │   │ score explicável │   │ alertas      │
└──────────────────┘   └────────────────┘   └──────────────────┘   └──────────────┘
```

Detalhes em [`docs/arquitetura.md`](docs/arquitetura.md). As decisões que mais
afetam o resultado:

**O tribunal diz quem pode leiloar; o leiloeiro diz o que está sendo leiloado.**
Por isso há dois níveis de coleta, e o cadastro mestre das Juntas Comerciais é o
que gera a lista de sites a monitorar.

**Parser determinístico antes de LLM.** Edital é documento de forma fixa; regra
é auditável, reproduzível, gratuita e instantânea. O modelo entra depois, para o
que a regra não pegou — e é obrigado a citar o trecho literal do documento. Se o
trecho não existir no edital, o campo é descartado. É a defesa concreta contra
alucinação.

**Nada extraído é apresentado como certeza.** Todo campo carrega confiança,
método e evidência; abaixo de 0,70 a interface pede conferência no edital.

**O sistema relata, não opina.** Ele diz "o edital invoca o art. 130, parágrafo
único, do CTN", com o trecho citado. Não diz "você não vai pagar o IPTU
atrasado" — isso seria parecer jurídico.

**O diário decide se existe leilão; o detector mostra por quê.** A publicação
não vira lote por conter a palavra "leilão": ela é pontuada, e a confiança e os
trechos que a sustentam viajam até a tela. O que fica abaixo do limiar não é
apagado — fica visível, para que dê para perceber que o limiar está alto demais.

**Móvel × imóvel e rural × urbano são eixos próprios, não derivados do tipo de
bem.** Um trator é `TipoBem.OUTRO` e `NaturezaBem.MOVEL`; derivar a natureza do
tipo jogaria maquinário, semovente e joia num balaio sem natureza. E `INDEFINIDA`
é resposta legítima: um imóvel citado em uma linha do diário muitas vezes não diz
se é rural ou urbano, e escrever "urbano" porque é o mais comum seria inventar.

**A regra dos 50% na segunda praça não é assumida.** Cada edital fixa o seu
percentual; o parser lê do documento. A fixture de veículo exige 60% e o sistema
acerta.

---

## Comandos

```bash
radar seed                            # dados de demonstração
radar coletar --todas                 # coleta + ingestão
radar fontes listar|validar           # saúde e validação de fonte
radar diarios coletar                 # lê o Diário da Justiça e detecta leilões
radar diarios publicacoes [--todas]   # o que foi lido, com confiança e trecho
radar diarios agenda [--categoria X]  # agenda cronológica por tipo de bem
radar leiloeiros coletar|listar       # cadastro mestre nas juntas comerciais
radar extrair --todos                 # baixa e lê os editais pendentes
radar mercado importar-fipe <csv>     # espelho FIPE real
radar mercado importar-fipezap <csv>  # boletim FipeZap real
radar mercado analisar                # recalcula análises e score
radar alertas --simular               # mostra o que os alertas enviariam
radar limpar-raw                      # aplica a retenção de 30 dias
radar servir                          # API + frontend compilado
```

## Configuração

Tudo por variável de ambiente com prefixo `RADAR_` (ou um `.env`). As que mais
importam:

| Variável | Padrão | Para quê |
|---|---|---|
| `RADAR_DATABASE_URL` | SQLite local | `postgresql+psycopg://…` em produção |
| `RADAR_USER_AGENT` | `RadarLeilaoBot/0.1…` | **troque o contato por um real** |
| `RADAR_RESPEITAR_ROBOTS` | `true` | nunca desligue em produção |
| `RADAR_DELAY_MINIMO_POR_HOST_S` | `1.5` | limite de taxa por host |
| `RADAR_LLM_HABILITADO` / `RADAR_LLM_API_KEY` | desligado | extração por LLM |
| `RADAR_OCR_HABILITADO` | `false` | editais digitalizados (exige Tesseract) |
| `RADAR_DATAJUD_API_KEY` | vazio | enriquecimento processual via CNJ |
| `RADAR_DIARIO_LIMIAR_DETECCAO` | `0.55` | confiança mínima para a publicação virar lote |
| `RADAR_DIARIO_MAX_CARACTERES_TEXTO` | `4000` | quanto do texto do diário é guardado (LGPD) |
| `RADAR_DIARIO_DIAS_RETROATIVOS` | `3` | janela relida a cada coleta (repetição é idempotente) |
| `RADAR_EMAIL_BACKEND` | `console` | `smtp` para enviar de verdade |
| `RADAR_FILA_BACKEND` | `memoria` | `redis` em produção |

Extras opcionais: `pip install -e "backend[ocr,llm,redis,postgres]"`.

## Testes

```bash
.venv/bin/python -m pytest backend/tests -q    # 248 testes, offline
.venv/bin/ruff check backend/src backend/tests
cd frontend && npm run build                   # typecheck + build
```

Nenhum teste toca a rede, manda e-mail ou chama LLM.

## Conformidade

Requisitos não negociáveis (seção 11 da especificação) e como são cumpridos:
[`docs/conformidade.md`](docs/conformidade.md). Resumo:

- `robots.txt` consultado antes de cada URL; 5xx no robots **bloqueia** a fonte;
  `Crawl-delay` respeitado; User-Agent identificável com contato.
- LGPD: CPF removido do texto antes de gravar — do edital **e** da publicação de
  diário —, placa mascarada (`ABC1**4`), partes do processo não são exibidas, e
  do diário guarda-se só o recorte que sustenta a detecção.
- Disclaimer visível em cada lote, na agenda por tipo de bem, no e-mail de
  alerta e no `.ics`.
- Classificação do bem e detecção no diário sempre acompanhadas de confiança e
  do trecho literal que as sustenta — nunca apresentadas como fato.
- Data/hora da última coleta e da referência de mercado sempre visíveis.

## Licença

MIT — veja [LICENSE](LICENSE).
