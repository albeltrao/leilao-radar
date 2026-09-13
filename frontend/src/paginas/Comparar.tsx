import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { SeloRisco } from "../componentes/SeloRisco";
import { emArea, emDataHora, emPercentual, emReais, rotuloFonte } from "../formatos";
import type { LoteDetalhe } from "../tipos";

/** Modo comparação: 2 a 3 lotes lado a lado (seção 10). */

export function Comparar() {
  const [params] = useSearchParams();
  const [lotes, setLotes] = useState<LoteDetalhe[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  const ids = (params.get("ids") ?? "")
    .split(",")
    .map((x) => Number(x))
    .filter(Boolean);

  useEffect(() => {
    if (ids.length < 2) return;
    api.comparar(ids).then(setLotes).catch((e) => setErro(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  if (ids.length < 2) {
    return (
      <div className="vazio">
        <h2>Escolha ao menos dois lotes</h2>
        <p>
          Marque “Comparar” em dois ou três cartões na <Link to="/">lista de lotes</Link> e
          volte aqui.
        </p>
      </div>
    );
  }
  if (erro) return <p className="erro">{erro}</p>;
  if (lotes.length === 0) return <div className="vazio">Carregando…</div>;

  const linhas: { rotulo: string; valor: (lote: LoteDetalhe) => React.ReactNode }[] = [
    { rotulo: "Score", valor: (l) => (l.score ? `${l.score.total.toFixed(0)}/100` : "—") },
    {
      rotulo: "Desconto estimado",
      valor: (l) => emPercentual(l.score?.desconto_destaque ?? null, 0),
    },
    {
      rotulo: "Referência usada",
      valor: (l) => (l.score?.fonte_destaque ? rotuloFonte(l.score.fonte_destaque) : "—"),
    },
    { rotulo: "Lance mínimo", valor: (l) => emReais(l.valor_minimo_segunda ?? l.valor_minimo_primeira, true) },
    { rotulo: "Avaliação", valor: (l) => emReais(l.valor_avaliacao, true) },
    { rotulo: "Comissão", valor: (l) => emPercentual(l.comissao_leiloeiro_percentual) },
    { rotulo: "Próxima praça", valor: (l) => emDataHora(l.proxima_praca) },
    { rotulo: "Cidade", valor: (l) => [l.bairro, l.cidade, l.uf].filter(Boolean).join(", ") },
    { rotulo: "Área", valor: (l) => emArea(l.area_privativa_m2 ?? l.area_total_m2) },
    {
      rotulo: "Ocupação",
      valor: (l) =>
        l.ocupado === null ? "não informada" : l.ocupado ? "ocupado" : "desocupado",
    },
    { rotulo: "Ônus", valor: (l) => (l.onus ?? []).join(", ") || "nenhum encontrado" },
    { rotulo: "Risco", valor: (l) => <SeloRisco lote={l} /> },
    {
      rotulo: "Campos confirmados",
      valor: (l) => `${l.campos.filter((c) => !c.revisao_necessaria).length} de ${l.campos.length}`,
    },
  ];

  return (
    <section className="pagina">
      <header className="pagina__topo">
        <div>
          <h1>Comparação</h1>
          <p className="pagina__ajuda">
            Mesmos critérios, lado a lado. Os valores de desconto vêm da mesma
            metodologia em todos — confira a fonte em cada lote.
          </p>
        </div>
      </header>

      <div className="tabela-rolagem">
        <table className="comparacao">
          <thead>
            <tr>
              <th scope="col">Critério</th>
              {lotes.map((lote) => (
                <th key={lote.id} scope="col">
                  <Link to={`/lote/${lote.id}`}>{lote.titulo}</Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {linhas.map((linha) => (
              <tr key={linha.rotulo}>
                <th scope="row">{linha.rotulo}</th>
                {lotes.map((lote) => (
                  <td key={lote.id}>{linha.valor(lote)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="disclaimer">{lotes[0]?.disclaimer}</p>
    </section>
  );
}
