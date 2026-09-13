import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ContagemRegressiva } from "../componentes/ContagemRegressiva";
import { SeloRisco } from "../componentes/SeloRisco";
import { TermometroScore } from "../componentes/TermometroScore";
import {
  emArea,
  emData,
  emDataHora,
  emPercentual,
  emReais,
  humanizar,
  rotuloFonte,
  rotuloTipoBem,
} from "../formatos";
import type { Campo, LoteDetalhe as TipoLote, Simulacao } from "../tipos";

/**
 * Detalhe do lote.
 *
 * É aqui que a promessa da seção 11 se cumpre ou não: todo dado derivado aparece
 * com a sua procedência. Campo extraído mostra confiança e o trecho literal do
 * edital; comparação de mercado mostra metodologia, data da fonte e ressalvas;
 * o score abre em cinco componentes explicados.
 */

const ROTULO_CAMPO: Record<string, string> = {
  valor_avaliacao: "Valor de avaliação",
  valor_minimo_praca_1: "Lance mínimo da 1ª praça",
  valor_minimo_praca_2: "Lance mínimo da 2ª praça",
  percentual_minimo_segunda_praca: "Percentual mínimo da 2ª praça",
  comissao_leiloeiro: "Comissão do leiloeiro",
  data_praca_1: "Data da 1ª praça",
  data_praca_2: "Data da 2ª praça",
  numero_processo: "Número do processo",
  comarca: "Comarca",
  vara: "Vara",
  leiloeiro_nome: "Leiloeiro",
  leiloeiro_matricula: "Matrícula do leiloeiro",
  matricula_imovel: "Matrícula do imóvel",
  cartorio: "Cartório",
  area_total_m2: "Área total",
  area_privativa_m2: "Área privativa",
  ocupado: "Imóvel ocupado",
  onus: "Ônus registrados",
  debitos_mencionados: "Débitos mencionados",
  edital_invoca_sub_rogacao_no_preco: "Edital invoca sub-rogação no preço",
  edital_atribui_debitos_ao_arrematante: "Edital atribui débitos ao arrematante",
  formas_pagamento: "Formas de pagamento",
  condicao_veiculo: "Condição do veículo",
};

function valorLegivel(campo: Campo): string {
  if (campo.valor === null || campo.valor === undefined) return "—";
  if (typeof campo.valor === "boolean") return campo.valor ? "sim" : "não";
  if (campo.nome.startsWith("data_")) return emDataHora(String(campo.valor));
  if (campo.nome.includes("valor_") || campo.nome.startsWith("debito_"))
    return emReais(String(campo.valor), true);
  if (campo.nome.includes("percentual") || campo.nome === "comissao_leiloeiro")
    return emPercentual(String(campo.valor));
  if (campo.nome.startsWith("area_")) return emArea(String(campo.valor));
  return String(campo.valor);
}

function Confianca({ campo }: { campo: Campo }) {
  const porcento = Math.round(campo.confianca * 100);
  return (
    <span
      className={`confianca ${campo.revisao_necessaria ? "confianca--revisar" : ""}`}
      title={`Extraído por ${campo.metodo.toLowerCase()}`}
    >
      <span className="confianca__barra" aria-hidden="true">
        <span style={{ width: `${porcento}%` }} />
      </span>
      {porcento}%
      {campo.revisao_necessaria && <strong> · confira no edital</strong>}
    </span>
  );
}

export function DetalheLote() {
  const { id } = useParams();
  const [lote, setLote] = useState<TipoLote | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [simulacao, setSimulacao] = useState<Simulacao | null>(null);
  const [lance, setLance] = useState<string>("");
  const [campoAberto, setCampoAberto] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let vivo = true;
    api
      .lote(Number(id))
      .then((dados) => {
        if (!vivo) return;
        setLote(dados);
        setLance(String(dados.valor_minimo_segunda ?? dados.valor_minimo_primeira ?? ""));
      })
      .catch((e) => vivo && setErro(e.message));
    return () => {
      vivo = false;
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const numero = Number(lance);
    if (!Number.isFinite(numero) || numero <= 0) return;
    const timer = setTimeout(() => {
      api.simulacao(Number(id), numero).then(setSimulacao).catch(() => setSimulacao(null));
    }, 350);
    return () => clearTimeout(timer);
  }, [id, lance]);

  const camposOrdenados = useMemo(() => {
    if (!lote) return [];
    return [...lote.campos].sort((a, b) => {
      if (a.revisao_necessaria !== b.revisao_necessaria) return a.revisao_necessaria ? 1 : -1;
      return (ROTULO_CAMPO[a.nome] ?? a.nome).localeCompare(ROTULO_CAMPO[b.nome] ?? b.nome);
    });
  }, [lote]);

  if (erro) return <p className="erro">Não consegui abrir este lote: {erro}</p>;
  if (!lote) return <div className="vazio">Carregando…</div>;

  const paraRevisar = lote.campos.filter((c) => c.revisao_necessaria).length;

  return (
    <article className="detalhe">
      <nav className="migalhas">
        <Link to="/">Lotes</Link> <span aria-hidden="true">›</span>{" "}
        <span>{rotuloTipoBem(lote.tipo_bem)}</span>
      </nav>

      <header className="detalhe__topo">
        <div>
          <h1>{lote.titulo}</h1>
          <p className="detalhe__local">
            {[lote.endereco, lote.bairro, lote.cidade, lote.uf].filter(Boolean).join(", ")}
            {lote.geocodificacao_precisao === "MUNICIPIO" && (
              <span className="detalhe__precisao">
                {" "}
                · posição no mapa é do município, não do endereço
              </span>
            )}
          </p>
          <div className="detalhe__selos">
            <SeloRisco lote={lote} />
            <span className="selo selo--neutro">
              <span className="selo__icone" aria-hidden="true">
                ◼
              </span>
              <span className="selo__rotulo">{lote.status.toLowerCase()}</span>
            </span>
          </div>
        </div>
        <TermometroScore score={lote.score} />
      </header>

      <p className="disclaimer">{lote.disclaimer}</p>

      <div className="detalhe__grade">
        <section className="bloco">
          <h2>Valores e praças</h2>
          <dl className="lista-dados">
            <div>
              <dt>Avaliação judicial</dt>
              <dd>{emReais(lote.valor_avaliacao, true)}</dd>
            </div>
            <div>
              <dt>Lance mínimo da 1ª praça</dt>
              <dd>{emReais(lote.valor_minimo_primeira, true)}</dd>
            </div>
            <div>
              <dt>Lance mínimo da 2ª praça</dt>
              <dd>{emReais(lote.valor_minimo_segunda, true)}</dd>
            </div>
            <div>
              <dt>Comissão do leiloeiro</dt>
              <dd>{emPercentual(lote.comissao_leiloeiro_percentual)}</dd>
            </div>
          </dl>

          <div className="pracas">
            {lote.eventos
              .filter((e) => e.tipo.startsWith("PRACA"))
              .map((evento) => (
                <ContagemRegressiva
                  key={evento.id}
                  data={evento.data_hora}
                  ordem={evento.tipo === "PRACA_SEGUNDA" ? 2 : 1}
                  estimado={evento.estimado}
                />
              ))}
          </div>

          <a className="botao botao--secundario" href={api.urlIcsLote(lote.id)}>
            Adicionar ao meu calendário (.ics)
          </a>
        </section>

        <section className="bloco">
          <h2>Simulador de custo</h2>
          <p className="bloco__ajuda">
            O lance não é o custo. Some comissão e os débitos que o edital atribui a
            quem arremata.
          </p>
          <label className="campo">
            <span>Seu lance</span>
            <input
              type="number"
              min={0}
              step={1000}
              value={lance}
              onChange={(e) => setLance(e.target.value)}
            />
          </label>
          {simulacao && (
            <>
              <p className="simulacao__total">
                <span>Custo estimado</span>
                <strong>{emReais(simulacao.custo_total_estimado, true)}</strong>
              </p>
              <ul className="simulacao__detalhes">
                {simulacao.detalhes.map((detalhe) => (
                  <li key={detalhe}>{detalhe}</li>
                ))}
              </ul>
              <p className="aviso">{simulacao.aviso}</p>
            </>
          )}
        </section>

        <section className="bloco bloco--largo">
          <h2>Comparação com o mercado</h2>
          {lote.analises.length === 0 ? (
            <p className="bloco__ajuda">
              Sem referência de mercado para este lote. Compare manualmente com bens
              semelhantes antes de decidir.
            </p>
          ) : (
            <div className="analises">
              {lote.analises.map((analise) => (
                <article key={analise.fonte} className="analise">
                  <header>
                    <h3>{rotuloFonte(analise.fonte)}</h3>
                    <span
                      className={`analise__desconto ${
                        Number(analise.desconto_percentual) > 0 ? "" : "esta-negativo"
                      }`}
                    >
                      {emPercentual(analise.desconto_percentual)}
                    </span>
                  </header>
                  <dl className="lista-dados lista-dados--compacta">
                    <div>
                      <dt>Referência</dt>
                      <dd>{emReais(analise.valor_referencia, true)}</dd>
                    </div>
                    <div>
                      <dt>Comparado a</dt>
                      <dd>{emReais(analise.valor_comparado, true)}</dd>
                    </div>
                    <div>
                      <dt>Data da fonte</dt>
                      <dd>{emData(analise.data_referencia_fonte)}</dd>
                    </div>
                    <div>
                      <dt>Confiança</dt>
                      <dd>{Math.round(analise.confianca * 100)}%</dd>
                    </div>
                  </dl>
                  <p className="analise__metodologia">{analise.metodologia}</p>
                  {(analise.avisos ?? []).map((aviso) => (
                    <p key={aviso} className="aviso">
                      {aviso}
                    </p>
                  ))}
                  {analise.fonte_url && (
                    <a href={analise.fonte_url} target="_blank" rel="noreferrer">
                      Ver a fonte
                    </a>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="bloco bloco--largo">
          <h2>
            O que lemos no edital
            <span className="bloco__contagem">
              {lote.campos.length} campos
              {paraRevisar > 0 && ` · ${paraRevisar} para conferir`}
            </span>
          </h2>
          <p className="bloco__ajuda">
            Cada campo foi extraído automaticamente e traz o trecho do documento que
            o sustenta. Clique para ver a evidência. Nada aqui substitui a leitura do
            edital original.
          </p>
          {camposOrdenados.length === 0 ? (
            <p className="bloco__ajuda">
              Nenhum edital foi analisado ainda para este lote.
            </p>
          ) : (
            <ul className="campos">
              {camposOrdenados.map((campo) => (
                <li
                  key={campo.nome}
                  className={campo.revisao_necessaria ? "campo-item esta-incerto" : "campo-item"}
                >
                  <button
                    type="button"
                    className="campo-item__topo"
                    onClick={() =>
                      setCampoAberto(campoAberto === campo.nome ? null : campo.nome)
                    }
                    aria-expanded={campoAberto === campo.nome}
                  >
                    <span className="campo-item__nome">
                      {ROTULO_CAMPO[campo.nome] ?? humanizar(campo.nome)}
                    </span>
                    <span className="campo-item__valor">{valorLegivel(campo)}</span>
                    <Confianca campo={campo} />
                  </button>
                  {campoAberto === campo.nome && campo.evidencia && (
                    <blockquote className="campo-item__evidencia">
                      <span className="campo-item__origem">Trecho do documento:</span>
                      {campo.evidencia}
                    </blockquote>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="bloco">
          <h2>Ficha do bem</h2>
          <dl className="lista-dados">
            {lote.tipo_bem === "IMOVEL" ? (
              <>
                <div>
                  <dt>Área total</dt>
                  <dd>{emArea(lote.area_total_m2)}</dd>
                </div>
                <div>
                  <dt>Área privativa</dt>
                  <dd>{emArea(lote.area_privativa_m2)}</dd>
                </div>
                <div>
                  <dt>Matrícula</dt>
                  <dd>{lote.matricula ?? "—"}</dd>
                </div>
                <div>
                  <dt>Cartório</dt>
                  <dd>{lote.cartorio ?? "—"}</dd>
                </div>
                <div>
                  <dt>Ocupação</dt>
                  <dd>
                    {lote.ocupado === null
                      ? "não informada"
                      : lote.ocupado
                        ? "ocupado"
                        : "desocupado"}
                  </dd>
                </div>
              </>
            ) : (
              <>
                <div>
                  <dt>Marca e modelo</dt>
                  <dd>{[lote.marca, lote.modelo].filter(Boolean).join(" ") || "—"}</dd>
                </div>
                <div>
                  <dt>Ano</dt>
                  <dd>
                    {lote.ano_fabricacao ?? "—"}/{lote.ano_modelo ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>Placa</dt>
                  <dd>{lote.placa_parcial ?? "—"}</dd>
                </div>
                <div>
                  <dt>Condição</dt>
                  <dd>
                    {(lote.condicao_veiculo ?? []).map(humanizar).join(", ") || "—"}
                  </dd>
                </div>
              </>
            )}
            <div>
              <dt>Processo</dt>
              <dd className="mono">{lote.numero_processo ?? "—"}</dd>
            </div>
            <div>
              <dt>Leiloeiro</dt>
              <dd>
                {lote.leiloeiro ? (
                  <>
                    {lote.leiloeiro.nome}
                    {lote.leiloeiro.matricula && (
                      <span className="detalhe__credencial">
                        {" "}
                        · matrícula {lote.leiloeiro.matricula}
                        {lote.leiloeiro.junta && ` (${lote.leiloeiro.junta})`}
                      </span>
                    )}
                  </>
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
        </section>

        <section className="bloco">
          <h2>Riscos e pendências</h2>
          <SeloRisco lote={lote} detalhado />
          {(lote.debitos ?? []).length > 0 && (
            <>
              <h3 className="bloco__sub">Débitos citados no edital</h3>
              <ul className="lista-simples">
                {(lote.debitos ?? []).map((debito) => (
                  <li key={debito.tipo}>
                    {humanizar(debito.tipo)}:{" "}
                    {debito.valor ? emReais(debito.valor, true) : "valor não informado"}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="aviso">
            O Radar relata o que o edital diz sobre dívidas e ônus, com o trecho
            citado. Ele não diz o que você vai pagar — essa leitura é do seu advogado.
          </p>
        </section>

        <section className="bloco bloco--largo">
          <h2>Procedência</h2>
          <dl className="lista-dados">
            <div>
              <dt>Fonte</dt>
              <dd>
                {lote.fonte_url ? (
                  <a href={lote.fonte_url} target="_blank" rel="noreferrer">
                    {lote.fonte_slug}
                  </a>
                ) : (
                  lote.fonte_slug
                )}
              </dd>
            </div>
            <div>
              <dt>Coletado em</dt>
              <dd>{emDataHora(lote.coletado_em)}</dd>
            </div>
            <div>
              <dt>Visto por último</dt>
              <dd>{emDataHora(lote.visto_por_ultimo_em)}</dd>
            </div>
            <div>
              <dt>Documentos</dt>
              <dd>
                {lote.documentos.length === 0
                  ? "nenhum"
                  : lote.documentos.map((documento) => (
                      <a
                        key={documento.id}
                        href={documento.url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="documento"
                      >
                        {documento.tipo.toLowerCase()}
                        {documento.paginas ? ` (${documento.paginas} p.)` : ""}
                      </a>
                    ))}
              </dd>
            </div>
          </dl>
          {(lote.fontes_secundarias ?? []).length > 0 && (
            <p className="bloco__ajuda">
              Este lote também foi encontrado em:{" "}
              {(lote.fontes_secundarias ?? []).map((f) => f.fonte).join(", ")}.
            </p>
          )}
        </section>
      </div>
    </article>
  );
}
