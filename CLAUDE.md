# Notas para quem for trabalhar neste repositório

## O que este projeto é

Monitor de leilões judiciais de AL, BA, PE e SE. Lê o Diário da Justiça das
esferas estadual e federal, coleta os editais e organiza tudo numa agenda
cronológica separada por tipo de bem. Backend Python (FastAPI + SQLAlchemy),
frontend React/Vite. Leia o `README.md` primeiro — em especial a seção "Estado
atual, sem maquiagem".

## Comandos

```bash
make instalar      # venv + deps do backend e do frontend
make tudo          # o que o CI roda: lint + testes + build do frontend
make seed          # dados fictícios para ver a tela funcionando
make servir        # API + frontend compilado em :8000
```

Os testes rodam **offline**: nenhum toca a rede, manda e-mail ou chama LLM.
Se um teste novo precisar de rede, ele está errado — use fixture.

## Regras que não são negociáveis

Estão na seção 11 da especificação e em `docs/conformidade.md`. Em resumo, não
mexa nestas sem uma boa razão:

1. **`robots.txt` é consultado antes de cada URL.** 5xx no robots bloqueia a
   fonte. `RADAR_RESPEITAR_ROBOTS=false` existe só para teste offline.
2. **Nada extraído é apresentado como certeza.** Todo campo carrega confiança,
   método e o trecho literal do documento. Se você adicionar um campo novo,
   ele precisa dos três.
3. **O sistema relata, não opina.** "O edital invoca o art. 130 do CTN" é fato;
   "você não vai pagar o IPTU" é parecer jurídico e está fora.
4. **Minimização de dados pessoais.** CPF nunca é gravado, placa é mascarada.
5. **A regra dos 50% na 2ª praça não é assumida** — é lida do edital.
6. **Classificação do bem também carrega prova.** `natureza_bem` (móvel/imóvel)
   e `zona_imovel` (rural/urbana) são derivadas por regra; cada uma grava
   confiança e o trecho literal em `campo_extraido`. `INDEFINIDA` é resposta
   legítima e aparece na tela — não empurre para o lado mais provável.
7. **O detector do diário não dá booleano sozinho.** Uma publicação vira lote
   com confiança e evidência; abaixo do limiar ela continua gravada, visível e
   sem lote. Não apague publicação descartada: é o único jeito de medir falso
   negativo.

## Armadilhas conhecidas

- **NFKD converte ordinais.** No parser de edital, o casamento roda sobre texto
  sem acento, e `nº` vira `no`, `1ª` vira `1a`. Padrão que procure `º` literal
  nunca casa. Inclua a letra na classe: `[oº°]`. Isso já custou duas matrículas
  perdidas em silêncio.
- **SQLite devolve datetime sem fuso.** Por isso existe o `UtcDateTime` em
  `models.py`. Sem ele, comparar datas marca remarcação falsa a cada coleta e
  dispara alerta indevido. Não troque por `DateTime` cru.
- **Coluna de enum precisa do `EnumTexto`.** Com `String` cru o banco devolve
  texto, a anotação `Mapped[StatusEvento]` mente e `is` falha em silêncio.
- **Dedup: só a primeira chave que casar vale.** Somar evidências fracas junta
  apartamentos diferentes do mesmo prédio no mesmo processo.
- **O par TR do número CNJ depende do segmento.** `05` é TJBA no segmento 8 e
  TRF5 no segmento 4, e os dois passam no dígito verificador. `tribunal_do_cnj`
  precisa do segmento; ignorá-lo põe processo federal de PE como estadual da BA.
- **TRF não determina UF.** O TRF5 responde por seis estados. A UF de um lote
  federal sai da seção judiciária citada no texto
  (`diarios.deteccao.uf_da_secao_judiciaria`), nunca do código do tribunal.
- **Diário com zero leilões no dia é normal.** Não levante `EstruturaInesperada`
  por lista vazia no conector de diário — só por JSON que não dá para reconhecer.
  Alarme falso diário faz o painel de saúde virar ruído.

## Adicionando um conector de leiloeiro

Edite `backend/src/radar/data/perfis_leiloeiros.yaml` — não escreva código.
Depois valide contra o site real (`radar fontes validar --fonte <slug>`),
congele o HTML em `backend/tests/fixtures/html/`, escreva o teste de regressão
e só então marque `validado_ao_vivo: true`.

Perfil que precise de lógica impossível de declarar (JSON embutido, API interna)
vira uma subclasse de `Conector` própria.

## Mexendo no detector ou no classificador do diário

Os dois vivem em `backend/src/radar/diarios/`:

- `classificacao.py` — móvel × imóvel e rural × urbano, por tabela de termos com
  peso. Termo novo entra na tabela, com peso e rótulo; o rótulo aparece na tela.
- `deteccao.py` — decide se a publicação é leilão e monta o `LoteBruto`.

Regras da casa nesses dois arquivos:

- Os padrões rodam sobre texto **sem acento e em minúscula** (`Contexto.busca`),
  onde `nº` virou `no` e `1ª` virou `1a`. Padrão com acento ou com `º` literal
  nunca casa.
- Peso novo sem teste de regressão em `tests/test_diarios.py` não entra. Um peso
  mal calibrado não quebra nada: só manda lote para a aba errada, em silêncio.
- A detecção mora na ingestão, não no conector. O conector do diário só baixa e
  recorta; deduzir é trabalho de `radar.diarios` (mesma regra do cabeçalho de
  `collectors/dto.py`).

## Estilo

- Código, comentários, mensagens de commit e interface em **português**.
- Comentário explica **por quê**, não o quê. Se o código não é óbvio, o
  comentário diz qual armadilha ele evita.
- `ruff` decide formatação; rode `make lint` antes de commitar.
