import { useEffect, useState } from "react";
import { api } from "../api";
import { MapaLotes } from "../componentes/MapaLotes";
import type { GeoFeicao } from "../tipos";

export function PaginaMapa() {
  const [feicoes, setFeicoes] = useState<GeoFeicao[]>([]);
  const [uf, setUf] = useState<string[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .geo({ uf: uf.length ? uf : undefined })
      .then((dados) => setFeicoes(dados.features))
      .catch((e) => setErro(e.message));
  }, [uf]);

  return (
    <section className="pagina">
      <header className="pagina__topo">
        <div>
          <h1>Mapa de oportunidades</h1>
          <p className="pagina__ajuda">
            Lotes agrupados por município. A geocodificação atual é de precisão
            municipal — o ponto é o centro da cidade, não o endereço do bem.
          </p>
        </div>
      </header>

      <fieldset className="grupo">
        <legend>Estado</legend>
        {["AL", "SE", "PE"].map((sigla) => (
          <button
            key={sigla}
            type="button"
            className={`pilula ${uf.includes(sigla) ? "esta-ativa" : ""}`}
            aria-pressed={uf.includes(sigla)}
            onClick={() =>
              setUf((atual) =>
                atual.includes(sigla)
                  ? atual.filter((x) => x !== sigla)
                  : [...atual, sigla],
              )
            }
          >
            {sigla}
          </button>
        ))}
      </fieldset>

      {erro ? <p className="erro">{erro}</p> : <MapaLotes feicoes={feicoes} />}
    </section>
  );
}
