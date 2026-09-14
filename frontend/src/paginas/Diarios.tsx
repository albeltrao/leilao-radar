import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { emData, emReais } from "../formatos";
import type { Agenda, CategoriaBem, ItemAgenda, PublicacaoDiario } from "../tipos";
import { UFS } from "../ufs";

/**
 * Agenda dos leilões detectados: cronológica e por tipo de bem.
 *
 * Duas decisões que valem comentário:
 *
 * 1. As abas de categoria e as contagens vêm do MESMO endpoint da lista. Contar
 *    no frontend daria divergência assim que o filtro mudasse; pedir a contagem
 *    em outra chamada daria divergência assim que uma coleta rodasse no meio.
 *
 * 2. Cada item mostra, sob demanda, o trecho literal que pôs aquele lote naquela
 *    aba. A classificação é derivada por regra; sem a frase ao lado, a aba seria
 *    uma afirmação sem prova — e a seção 11 não admite isso.
 */

const CORES_CATEGORIA: Record<CategoriaBem, string> = {
  IMOVEL_URBANO: "selo--ok",
  IMOVEL_RURAL: "selo--atencao",
  IMOVEL_INDEFINIDO: "selo--neutro",
  MOVEL: "selo--serio",
  INDEFINIDO: "selo--desconhecido",
};

const ROTULO_EVENTO: Record<string, string> = {
  PRACA_PRIMEIRA: "1ª praça",
  PRACA_SEGUNDA: "2ª praça",
  PRACA_UNICA: "Praça única",
};

const DIAS_SEMANA = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];

function rotuloDoDia(iso: string) {
  const [ano, mes, dia] = iso.split("-").map(Number);
  const data = new Date(ano, mes - 1, dia);
  return `${DIAS_SEMANA[data.getDay()]}, ${String(dia).padStart(2, "0")}/${String(mes).padStart(2, "0")}/${ano}`;
}

function Procedencia({ item }: { item: ItemAgenda }) {
  const [aberto, setAberto] = useState(false);
  const provas = [
    item.evidencia_natureza && {
      rotulo: `Natureza (${Math.round(item.confianca_natureza * 100)}%)`,
      texto: item.evidencia_natureza,
      revisar: item.confianca_natureza < 0.7,
    },
    item.evidencia_zona && {
      rotulo: `Zona (${Math.round(item.confianca_zona * 100)}%)`,
      texto: item.evidencia_zona,
      revisar: item.confianca_zona < 0.7,
    },
    item.diario?.evidencia && {
      rotulo: `Detecção no diário (${Math.round(item.diario.confianca * 100)}%)`,
      texto: item.diario.evidencia,
      revisar: item.diario.revisao_necessaria,
    },
  ].filter(Boolean) as { rotulo: string; texto: string; revisar: boolean }[];

  if (!provas.length) return null;

  return (
    <div className="procedencia">
      <button
        type="button"
        className="botao botao--texto botao--pequeno"
        aria-expanded={aberto}
        onClick={() => setAberto((v) => !v)}
      >
        {aberto ? "Ocultar" : "Por que está nesta categoria?"}
      </button>
      {aberto && (
        <ul className="procedencia__provas">
          {provas.map((prova) => (
            <li key={prova.rotulo}>
              <span
                className={prova.revisar ? "confianca confianca--revisar" : "confianca"}
              >
                {prova.rotulo}
              </span>
              <q className="procedencia__trecho">{prova.texto}</q>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Item({ item }: { item: ItemAgenda }) {
  const hora = new Date(item.data_hora).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <li className="agenda-item">
      <div className="agenda-item__hora">
        <strong>{hora}</strong>
        <span>{ROTULO_EVENTO[item.tipo_evento] ?? item.tipo_evento}</span>
      </div>
      <div className="agenda-item__corpo">
        <div className="agenda-item__cabecalho">
          <Link to={`/lote/${item.lote_id}`}>{item.titulo}</Link>
          <span className={`selo ${CORES_CATEGORIA[item.categoria]}`}>
            {item.categoria_rotulo}
          </span>
          <span className="selo selo--neutro">
            {item.esfera === "FEDERAL" ? "Justiça Federal" : "Justiça Estadual"}
          </span>
          {item.estimado && <span className="etiqueta-estimado">data estimada</span>}
          {item.status_evento === "REMARCADO" && (
            <span className="etiqueta-remarcado">remarcado</span>
          )}
        </div>
        <p className="agenda-item__meta">
          {[item.cidade ?? item.comarca, item.uf].filter(Boolean).join("/")}
          {item.tribunal_sigla ? ` · ${item.tribunal_sigla}` : ""}
          {item.numero_processo ? ` · processo ${item.numero_processo}` : ""}
          {item.valor_minimo ? ` · lance mínimo ${emReais(item.valor_minimo)}` : ""}
        </p>
        {item.diario && (
          <p className="agenda-item__diario">
            Detectado em <strong>{item.diario.nome}</strong>
            {item.diario.publicado_em
              ? `, publicado em ${emData(item.diario.publicado_em)}`
              : ""}
            {item.diario.url && (
              <>
                {" — "}
                <a href={item.diario.url} target="_blank" rel="noreferrer">
                  ver publicação
                </a>
              </>
            )}
          </p>
        )}
        <Procedencia item={item} />
      </div>
    </li>
  );
}

function Publicacoes() {
  const [itens, setItens] = useState<PublicacaoDiario[]>([]);
  const [total, setTotal] = useState(0);
  const [todas, setTodas] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .publicacoes({ somente_detectadas: !todas, tamanho: 40 })
      .then((pagina) => {
        setItens(pagina.itens);
        setTotal(pagina.total);
      })
      .catch((e) => setErro(e.message));
  }, [todas]);

  if (erro) return <p className="erro">{erro}</p>;

  return (
    <section className="bloco bloco--largo">
      <header className="pagina__topo">
        <h2>Publicações lidas do Diário da Justiça</h2>
        <label className="caixa">
          <input
            type="checkbox"
            checked={todas}
            onChange={(e) => setTodas(e.target.checked)}
          />
          mostrar também as descartadas
        </label>
      </header>
      <p className="pagina__ajuda">
        {total} publicação(ões) nesta visão. As descartadas ficam acessíveis de
        propósito: é assim que se descobre que o limiar de detecção está alto demais
        e engolindo leilão de verdade.
      </p>
      {itens.length === 0 ? (
        <p className="vazio">
          Nenhuma publicação coletada ainda. Rode <code>radar diarios coletar</code>.
        </p>
      ) : (
        <div className="tabela-rolagem">
          <table className="tabela">
            <thead>
              <tr>
                <th scope="col">Publicado</th>
                <th scope="col">Diário</th>
                <th scope="col">Órgão</th>
                <th scope="col">Detecção</th>
                <th scope="col">Lote</th>
              </tr>
            </thead>
            <tbody>
              {itens.map((p) => (
                <tr key={p.id}>
                  <td>{emData(p.data_publicacao)}</td>
                  <td>
                    {p.diario_nome}
                    <br />
                    <span className="mono">
                      {p.esfera === "FEDERAL" ? "federal" : "estadual"}
                      {p.uf ? ` · ${p.uf}` : ""}
                    </span>
                  </td>
                  <td>{p.orgao ?? "—"}</td>
                  <td>
                    {p.detectado_como_leilao ? (
                      <span
                        className={
                          p.revisao_necessaria
                            ? "confianca confianca--revisar"
                            : "confianca"
                        }
                      >
                        leilão · {Math.round(p.confianca_deteccao * 100)}%
                        {p.revisao_necessaria ? " · conferir" : ""}
                      </span>
                    ) : (
                      <span className="selo selo--desconhecido">descartada</span>
                    )}
                    {p.evidencia && <q className="procedencia__trecho">{p.evidencia}</q>}
                  </td>
                  <td>
                    {p.lote_id ? (
                      <Link to={`/lote/${p.lote_id}`}>#{p.lote_id}</Link>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function Diarios() {
  const [agenda, setAgenda] = useState<Agenda | null>(null);
  const [uf, setUf] = useState<string[]>([]);
  const [categoria, setCategoria] = useState<CategoriaBem[]>([]);
  const [esfera, setEsfera] = useState<string[]>([]);
  const [somenteDiario, setSomenteDiario] = useState(false);
  const [dias, setDias] = useState(60);
  const [erro, setErro] = useState<string | null>(null);

  const filtros = useMemo(
    () => ({
      dias,
      uf: uf.length ? uf : undefined,
      categoria: categoria.length ? categoria : undefined,
      esfera: esfera.length ? esfera : undefined,
      somente_de_diario: somenteDiario || undefined,
    }),
    [dias, uf, categoria, esfera, somenteDiario],
  );

  useEffect(() => {
    api.agenda(filtros).then(setAgenda).catch((e) => setErro(e.message));
  }, [filtros]);

  const alternar = <T extends string>(
    valor: T,
    lista: T[],
    definir: (v: T[]) => void,
  ) => definir(lista.includes(valor) ? lista.filter((v) => v !== valor) : [...lista, valor]);

  if (erro) return <p className="erro">{erro}</p>;

  return (
    <section className="pagina">
      <header className="pagina__topo">
        <div>
          <h1>Leilões detectados no Diário da Justiça</h1>
          <p className="pagina__ajuda">
            Publicações dos diários das justiças estadual e federal, lidas
            automaticamente, em ordem cronológica e separadas por tipo de bem.
          </p>
        </div>
        {agenda && (
          <a className="botao botao--secundario" href={api.urlIcsAgenda(filtros)}>
            Baixar .ics desta agenda
          </a>
        )}
      </header>

      <div className="filtros">
        <div className="grupo">
          <span className="grupo__rotulo">Estado</span>
          {UFS.map((sigla) => (
            <button
              key={sigla}
              type="button"
              className={`pilula ${uf.includes(sigla) ? "esta-ativa" : ""}`}
              onClick={() => alternar(sigla, uf, setUf)}
            >
              {sigla}
            </button>
          ))}
        </div>
        <div className="grupo">
          <span className="grupo__rotulo">Esfera</span>
          {[
            ["ESTADUAL", "Estadual"],
            ["FEDERAL", "Federal"],
          ].map(([valor, rotulo]) => (
            <button
              key={valor}
              type="button"
              className={`pilula ${esfera.includes(valor) ? "esta-ativa" : ""}`}
              onClick={() => alternar(valor, esfera, setEsfera)}
            >
              {rotulo}
            </button>
          ))}
        </div>
        <div className="grupo">
          <span className="grupo__rotulo">Janela</span>
          {[15, 30, 60, 180].map((n) => (
            <button
              key={n}
              type="button"
              className={`pilula ${dias === n ? "esta-ativa" : ""}`}
              onClick={() => setDias(n)}
            >
              {n} dias
            </button>
          ))}
        </div>
        <div className="grupo">
          <button
            type="button"
            className={`pilula ${somenteDiario ? "esta-ativa" : ""}`}
            onClick={() => setSomenteDiario((v) => !v)}
          >
            Só o que veio do diário
          </button>
        </div>
      </div>

      {agenda && (
        <div className="grupo grupo--categorias">
          {agenda.categorias.map((c) => (
            <button
              key={c.chave}
              type="button"
              disabled={c.total === 0 && !categoria.includes(c.chave)}
              className={`pilula pilula--categoria ${
                categoria.includes(c.chave) ? "esta-ativa" : ""
              }`}
              onClick={() => alternar(c.chave, categoria, setCategoria)}
            >
              {c.rotulo} <span className="pilula__contagem">{c.total}</span>
            </button>
          ))}
        </div>
      )}

      {agenda && (
        <p className="pagina__ajuda">
          {agenda.total} leilão(ões) entre {emData(agenda.de)} e {emData(agenda.ate)} —{" "}
          {agenda.total_de_diario} detectado(s) em publicação de diário.
        </p>
      )}

      {agenda?.dias.length === 0 && (
        <p className="vazio">
          Nenhum leilão nesta janela com estes filtros. Amplie o período ou tire um
          filtro.
        </p>
      )}

      {agenda?.dias.map((dia) => (
        <section key={dia.data} className="bloco bloco--largo">
          <h2 className="agenda-dia">
            {rotuloDoDia(dia.data)}{" "}
            <span className="agenda-dia__total">
              {dia.total} {dia.total === 1 ? "leilão" : "leilões"}
            </span>
          </h2>
          <ul className="agenda-lista">
            {dia.itens.map((item) => (
              <Item key={`${item.lote_id}-${item.tipo_evento}`} item={item} />
            ))}
          </ul>
        </section>
      ))}

      {agenda && <p className="disclaimer">{agenda.disclaimer}</p>}

      <Publicacoes />
    </section>
  );
}
