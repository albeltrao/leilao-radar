# Notas para quem for trabalhar neste repositório

## O que este projeto é

Monitor de leilões judiciais de AL, BA, PE e SE. Backend Python (FastAPI +
SQLAlchemy), frontend React/Vite. Leia o `README.md` primeiro — em especial a
seção "Estado atual, sem maquiagem".

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

## Adicionando um conector de leiloeiro

Edite `backend/src/radar/data/perfis_leiloeiros.yaml` — não escreva código.
Depois valide contra o site real (`radar fontes validar --fonte <slug>`),
congele o HTML em `backend/tests/fixtures/html/`, escreva o teste de regressão
e só então marque `validado_ao_vivo: true`.

Perfil que precise de lógica impossível de declarar (JSON embutido, API interna)
vira uma subclasse de `Conector` própria.

## Estilo

- Código, comentários, mensagens de commit e interface em **português**.
- Comentário explica **por quê**, não o quê. Se o código não é óbvio, o
  comentário diz qual armadilha ele evita.
- `ruff` decide formatação; rode `make lint` antes de commitar.
