# Critérios de aceite do MVP — estado real

Avaliação honesta contra a seção 14 da especificação. "Parcial" aqui significa
**o código está pronto e testado, mas falta a validação contra a fonte real**,
que não pôde ser feita no ambiente onde o sistema foi construído (sem saída de
rede para os domínios dos tribunais e das juntas comerciais).

| # | Critério | Estado | O que falta |
|---|---|---|---|
| 1 | Coleta automatizada diária de TJAL, TJSE e TJPE, com log de sucesso/erro visível | **Parcial** | Conectores e observabilidade prontos (`execucao_coleta` + página Fontes). Falta validar os seletores contra o HTML real e agendar a execução (cron ou Airflow) |
| 2 | Cadastro mestre de leiloeiros das Juntas, vinculado aos lotes | **Parcial** | Parser, fusão Junta+Corregedoria, vínculo com o lote e os comandos `radar leiloeiros coletar / listar / sugerir-perfis` prontos e testados. Falta rodar contra JUCEAL/JUCEB/JUCEPE/JUCESE de verdade — os nomes dos leiloeiros vêm de lá, não do repositório |
| 3 | ≥ 10 conectores de sites de leiloeiro, com deduplicação funcionando | **Parcial** | 12 conectores configurados; deduplicação **funciona e está testada** (mesmo processo não duplica, mesmo vindo de duas fontes). Falta validar cada perfil contra o site |
| 4 | Extração estruturada de avaliação, mínimos por praça, datas, tipo e localização, com acerto validado em amostra | **Feito, com ressalva** | Extrai 22 campos no edital de imóvel de referência e 15 no de veículo, com confiança e evidência por campo. A amostra validada são as duas fixtures do repositório — falta repetir sobre editais reais coletados |
| 5 | Comparação de mercado para veículos (FIPE) e primeira aproximação para imóveis (FipeZap) | **Feito, com dados de demonstração** | Motor pronto e testado. Os arquivos do repositório são **amostras**; falta importar espelho FIPE e boletim FipeZap reais (`radar mercado importar-*`) |
| 6 | Calendário consolidado navegável, com exportação `.ics` | **Feito** | — |
| 7 | Alertas por e-mail configuráveis por filtro salvo | **Feito** | Falta apenas apontar `RADAR_EMAIL_BACKEND=smtp` para um servidor real |
| 8 | Painel visual com a diretriz da seção 10, responsivo e com modo claro/escuro | **Feito** | — |
| 9 | Disclaimers legais visíveis conforme seção 11 | **Feito** | — |

## O caminho crítico para fechar o MVP

Tudo que está "Parcial" depende do **mesmo passo**, e só dele: rodar os
conectores contra as fontes reais, a partir de um ambiente com saída de rede.

```bash
for fonte in tjal-banco-leiloeiros tjse-leiloeiros-credenciados \
             tjse-leilao-judicial tjpe-leiloes-judiciais \
             juceal-leiloeiros jucese-leiloeiros jucepe-leiloeiros; do
  radar fontes validar --fonte "$fonte"
done
```

Para cada uma: conferir o que saiu, congelar o HTML como fixture, ajustar o
parser até o teste passar, marcar `validado_ao_vivo: true`. A estimativa
realista é de algumas horas por fonte na primeira rodada — a estrutura semântica
dos parsers (que procura "a tabela cujo cabeçalho fala de matrícula", em vez de
um caminho CSS fixo) existe justamente para reduzir esse trabalho e, depois,
sobreviver a redesigns.

## Fora do escopo declarado da v1

Registrado aqui para não parecer esquecimento:

- **Camada de comparáveis de portais de anúncio** (OLX, VivaReal, Zap) — a
  seção 4.5 pede parceria ou API oficial antes de qualquer coleta. O enum
  `FonteMercado.COMPARAVEIS` está reservado, sem coletor.
- **Justiça Federal, Justiça do Trabalho e leilões da União** — seção 2, fase futura.
- **Leilões extrajudiciais de bancos** — seção 2, fase futura.
- **App mobile e canal WhatsApp** — seção 13, fase 4.
- **Migrações versionadas (Alembic)** — o schema ainda muda a cada conector novo.
