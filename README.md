# Radar Leilão

Monitoramento de **leilões judiciais de Alagoas, Sergipe e Pernambuco**: coleta
os editais das fontes oficiais, lê o que está escrito neles, compara com
referência de mercado e organiza tudo em um calendário e um painel.

O diferencial não é agregar leilões — é **traduzir edital jurídico denso em uma
decisão clara**, com honestidade sobre o limite de cada dado.

> O sistema organiza e enriquece informação pública. Ele **não** presta
> assessoria jurídica nem recomendação de investimento. Toda informação é
> extraída automaticamente do edital oficial: consulte o documento original e um
> advogado antes de participar de um leilão.

---

## Estado atual, sem maquiagem

O que **funciona e está testado** (188 testes, todos offline):

| Área | Estado |
|---|---|
| Modelo de dados (21 tabelas) | pronto |
| Normalização pt-BR (moeda, datas, área, dígito verificador CNJ) | pronto |
| Camada HTTP com robots.txt, rate limit e arquivamento do bruto | pronto |
| Pipeline de ingestão: fila, deduplicação, idempotência | pronto |
| Parser de edital (22 campos no edital de imóvel de referência) | pronto |
| Extração por LLM com verificação de evidência | pronto (desligada por padrão) |
| Comparação de mercado e score explicável | pronto |
| Calendário, exportação `.ics`, alertas por e-mail | pronto |
| API REST (23 rotas) e autenticação | pronto |
| Frontend (painel, detalhe, calendário, mapa, onboarding) | pronto |

O que **ainda não foi validado**:

- **19 dos 20 conectores nunca rodaram contra o site real.** O ambiente onde
  este código foi escrito não tem saída de rede para `tjal.jus.br`,
  `tjse.jus.br`, `portal.tjpe.jus.br`, `juceal.al.gov.br`, `jucese.se.gov.br`
  nem `portal.jucepe.pe.gov.br`. Os parsers foram exercitados contra fixtures
  HTML sintéticas, modeladas na estrutura documentada de cada página — não
  contra capturas reais. Cada fonte carrega `validado_ao_vivo: false` e a coleta
  automática **pula** essas fontes até que alguém rode a validação (abaixo).
- **Os dados de mercado do repositório são amostras de demonstração**, não a
  tabela FIPE nem o boletim FipeZap reais. Enquanto estiverem em uso, toda
  análise sai com aviso em caixa alta e confiança reduzida à metade.
- **DataJud precisa de chave.** Sem `RADAR_DATAJUD_API_KEY` o enriquecimento
  processual é pulado (o resto do pipeline segue funcionando).

Nada disso é escondido do usuário: a página **Fontes** do painel mostra o selo
de validação de cada conector e a data da última coleta bem-sucedida.

---

## Rodando em 3 minutos

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
.venv/bin/radar seed                 # dados FICTÍCIOS de demonstração
cd frontend && npm install && npm run build && cd ..
.venv/bin/radar servir               # http://127.0.0.1:8000
```

Usuário de demonstração: `demo@example.org` / `radar-demo-2026`.

Para desenvolver o frontend com recarga automática, rode a API e o Vite em
paralelo (`radar servir` e `npm run dev` — o Vite já faz proxy de `/api`).

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
│ TJAL TJSE TJPE   │   │ fila           │   │ parser de edital │   │ API REST     │
│ JUCEAL/SE/PE     │──▶│ normalização   │──▶│ + LLM opcional   │──▶│ painel React │
│ sites leiloeiros │   │ deduplicação   │   │ FIPE / FipeZap   │   │ calendário   │
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

**A regra dos 50% na segunda praça não é assumida.** Cada edital fixa o seu
percentual; o parser lê do documento. A fixture de veículo exige 60% e o sistema
acerta.

---

## Comandos

```bash
radar seed                            # dados de demonstração
radar coletar --todas                 # coleta + ingestão
radar fontes listar|validar           # saúde e validação de fonte
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
| `RADAR_EMAIL_BACKEND` | `console` | `smtp` para enviar de verdade |
| `RADAR_FILA_BACKEND` | `memoria` | `redis` em produção |

Extras opcionais: `pip install -e "backend[ocr,llm,redis,postgres]"`.

## Testes

```bash
.venv/bin/python -m pytest backend/tests -q    # 188 testes, offline
.venv/bin/ruff check backend/src backend/tests
cd frontend && npm run build                   # typecheck + build
```

Nenhum teste toca a rede, manda e-mail ou chama LLM.

## Conformidade

Requisitos não negociáveis (seção 11 da especificação) e como são cumpridos:
[`docs/conformidade.md`](docs/conformidade.md). Resumo:

- `robots.txt` consultado antes de cada URL; 5xx no robots **bloqueia** a fonte;
  `Crawl-delay` respeitado; User-Agent identificável com contato.
- LGPD: CPF removido do texto antes de gravar, placa mascarada
  (`ABC1**4`), partes do processo não são exibidas.
- Disclaimer visível em cada lote, no e-mail de alerta e no `.ics`.
- Data/hora da última coleta e da referência de mercado sempre visíveis.

## Licença

MIT — veja [LICENSE](LICENSE).
