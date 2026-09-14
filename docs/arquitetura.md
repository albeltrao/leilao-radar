# Arquitetura

## Por que três camadas de coleta

**Diário da Justiça** → quem decretou o leilão e quando ele acontece, em fonte
oficial, muitas vezes antes de qualquer site publicar. **Tribunais e Juntas
Comerciais** → quem pode leiloar. **Sites dos leiloeiros** → o detalhe do bem:
foto, descrição, condições.

As três se encontram na deduplicação: o mesmo processo visto no diário e no site
do leiloeiro vira um lote só, com o que cada fonte sabe melhor.

## Por que duas camadas de cadastro e oferta

Os tribunais e as Juntas Comerciais dizem **quem** pode leiloar; os sites dos
leiloeiros dizem **o que** e **quando** está sendo leiloado. Nenhuma das duas
fontes, sozinha, monta o produto.

O cadastro mestre de leiloeiros (JUCEAL + JUCESE + JUCEPE, cruzado com os bancos
de leiloeiros das corregedorias do TJAL e do TJSE) é o que **gera a lista de
sites a monitorar**. Por isso `perfis_leiloeiros.yaml` tem vagas explícitas para
leiloeiros regionais: elas se preenchem com o resultado da coleta do cadastro,
não com um palpite feito na mesa.

## Fluxo

```
coletor → fila → worker de ingestão → extração → análise → API
```

O diário entra pelo mesmo trilho, com uma etapa a mais antes da normalização:

```
conector do diário → PublicacaoBruta → fila
                                        ↓
                      detectar_leilao (confiança + trechos)
                                        ↓
                      classificar_bem (móvel/imóvel, rural/urbano)
                                        ↓
                      LoteBruto → normalizar → deduplicar → persistir
```

A detecção roda na **ingestão**, não no conector: o conector só baixa e recorta,
e deduzir é trabalho de `radar.diarios`. O ganho prático é que o mesmo detector
serve a qualquer diário, e mexer no limiar não encosta em nenhum conector.

Publicação que não passa no limiar **não some**: fica gravada em
`publicacao_diario` com `detectado_como_leilao = false`. Sem isso, não haveria
como descobrir que o limiar está engolindo leilão de verdade.

A fila existe para desacoplar coleta de processamento. O coletor precisa
terminar rápido e não perder o que já baixou; o worker faz o trabalho caro
(normalizar, deduplicar, baixar PDF, extrair, comparar com mercado) no seu
próprio ritmo e pode ser reiniciado sem refazer requisição HTTP.

Duas implementações atrás da mesma interface: memória (desenvolvimento e testes,
síncrona) e Redis Streams (produção, com ack e reentrega).

## Idempotência

Rodar o coletor de novo **atualiza**, não duplica. A chave natural é
`tribunal | número do processo | número do lote`; quando o processo não é
divulgado, um hash do conteúdo assume o lugar.

## Deduplicação

O mesmo lote aparece no portal do tribunal e no site do leiloeiro. A resolução é
uma escada de chaves de identidade, da mais forte para a mais fraca:

| Chave | Força | Quando vale |
|---|---|---|
| processo + número do lote | 100 | processo com dígito verificador válido |
| UF + matrícula do imóvel | 90 | imóvel com matrícula extraída |
| placa mascarada + ano | 80 | veículo |
| chave natural | 10 | último recurso |

**Só a primeira que casar vale.** Somar evidências fracas juntaria dois
apartamentos diferentes do mesmo prédio leiloados no mesmo processo.

Na mesclagem, a autoridade é por campo: o tribunal manda em processo, comarca e
vara; o site do leiloeiro manda no detalhe do bem (foto, descrição, valor).

## Remarcação é evento, não sobrescrita

Quando a data de uma praça muda, o histórico é gravado **antes** da mudança.
O sistema consegue dizer "essa praça foi adiada de 10/11 para 24/11", que é
exatamente o que quem tem lembrete marcado precisa ouvir. No `.ics`, o campo
`SEQUENCE` cresce a cada remarcação — é isso que faz o Google/Outlook/Apple
atualizarem o compromisso existente em vez de criar um duplicado.

## Extração: regra primeiro, modelo depois

O parser determinístico roda sobre uma cópia do texto sem acento e em
minúsculas. Como remover acento preserva o comprimento da string, os offsets
continuam válidos e **a evidência é recortada do texto original** — o usuário lê
o trecho como está no edital.

> Armadilha para quem for escrever padrão novo: a normalização NFKD também
> converte os indicadores ordinais. `nº` vira `no`, `1ª` vira `1a`. Um padrão que
> procure `º` literal nunca casa. Sempre inclua a letra na classe: `[oº°]`.

O LLM entra depois, com três salvaguardas: evidência citada precisa existir no
documento, whitelist de campos (que exclui dado pessoal) e teto de confiança
abaixo do da regra. Na fusão, concordância eleva a confiança e discordância
mantém o valor da regra e marca revisão.

## Comparação de mercado

Até três análises por lote, cada uma com metodologia, data da fonte e ressalvas:

- **Laudo judicial** — sempre disponível, mas mecânico: dá 0% na 1ª praça e
  exatamente o percentual do edital na 2ª. Serve de piso, nunca de destaque.
- **FIPE** (veículo) — referência para veículo em estado normal de uso; leilão
  costuma ter deságio adicional.
- **FipeZap** (imóvel) — preço de *anúncio* por m² de área útil. Por isso o
  cálculo prefere área privativa a área total: trocar uma pela outra
  superestima a referência.

O destaque prioriza fonte de mercado sobre o laudo. Sem isso, o desconto exibido
seria 0% em toda 1ª praça — escondendo justamente o número que o usuário abriu o
produto para ver.

## Score

Cinco componentes, cada um com pontos, máximo e uma frase em português dizendo
por quê:

| Componente | Peso |
|---|---|
| Desconto estimado | 40 |
| Qualidade da informação | 20 |
| Risco documental | 25 |
| Janela de decisão | 10 |
| Histórico do leiloeiro | 5 |

Os pesos são constantes nomeadas em `radar/scoring/score.py` justamente para
serem discutíveis: mudar a política de ranqueamento é editar um arquivo, não
caçar número mágico espalhado pelo sistema.

## Banco

SQLite por padrão, PostgreSQL em produção (`RADAR_DATABASE_URL`). O schema é
criado por `metadata.create_all`, não por migração versionada — ainda muda a
cada conector novo. Quando o schema estabilizar, o passo é adotar Alembic; a
troca é local, porque todo acesso passa por `radar.db`.

Dois `TypeDecorator` merecem nota, porque ambos corrigem bugs silenciosos:

- `UtcDateTime` garante fuso na ida e na volta. Sem ele o SQLite devolve
  datetime ingênuo, e comparar ingênuo com consciente faz `!=` dar `True` para
  valores idênticos — marcando remarcação falsa a cada coleta e disparando
  alerta indevido.
- `EnumTexto` reconstrói o membro do enum na leitura. Sem ele a anotação
  `Mapped[StatusEvento]` mente e comparações com `is` falham em silêncio.

## Dois eixos de classificação do bem

A agenda pedia "móveis e imóveis, rurais e urbanos". Esses dois eixos **não** são
derivados de `TipoBem` (IMOVEL/VEICULO/OUTRO): lá, um trator, um rebanho e uma
joia caem todos em OUTRO, e OUTRO não diz se é móvel.

Então `Lote` tem colunas próprias, `natureza_bem` e `zona_imovel`, preenchidas
por `diarios/classificacao.py` — tabela de termos com peso, casando sobre o texto
sem acento, com a evidência recortada do texto **original**.

Três decisões que mudam o resultado:

- **Zona só se pergunta de imóvel.** Deixar o eixo rodar sobre móvel faria
  "trator na Fazenda Boa Vista" virar imóvel rural.
- **Termo locativo vale menos.** "Fazenda" depois de "localizado na" é o lugar
  do bem, não o bem. Sem esse desconto, "fazenda" (0,90) empatava com "máquina"
  (0,82) e o trator saía com natureza indefinida — dúvida inventada pela regra.
- **Empate técnico é `INDEFINIDA`.** Diferença menor que 0,15 entre os dois lados
  não é conhecimento: vira revisão, com as duas frases lado a lado.

A classificação roda para **todo** lote, não só os do diário — em `normalizar`,
sobre título, descrição, endereço e bairro. Quem vem do diário chega com a
classificação pronta, feita sobre o trecho do bem, que é mais preciso que a
publicação inteira (o endereço do fórum no rodapé puxaria tudo para "urbano").

## Geocodificação

O padrão é o centroide do município, carregado de um CSV próprio: funciona
offline e é honesto sobre a precisão, que viaja junto com a coordenada até a
interface. O mapa desenha círculo por município, com o nome da cidade — não pino
sobre rua, que sugeriria uma precisão que o dado não tem.

Para precisão de endereço existe `GeocodificadorNominatim`, que respeita o
limite de 1 req/s e o User-Agent identificável exigidos pelo OpenStreetMap.
