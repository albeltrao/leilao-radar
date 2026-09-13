import { Link } from "react-router-dom";
import type { LoteResumo } from "../tipos";
import { emReais, rotuloTipoBem } from "../formatos";
import { ContagemRegressiva } from "./ContagemRegressiva";
import { SeloRisco } from "./SeloRisco";
import { TermometroScore } from "./TermometroScore";

/** Cartão de lote — a unidade central de navegação (seção 10). */

const ICONE_TIPO: Record<string, string> = {
  IMOVEL: "🏠",
  VEICULO: "🚗",
  OUTRO: "📦",
};

export function CartaoLote({
  lote,
  selecionado,
  aoAlternarSelecao,
  favoritado,
  aoFavoritar,
}: {
  lote: LoteResumo;
  selecionado?: boolean;
  aoAlternarSelecao?: (id: number) => void;
  favoritado?: boolean;
  aoFavoritar?: (id: number) => void;
}) {
  const lanceAtual = lote.valor_minimo_segunda ?? lote.valor_minimo_primeira;
  const foto = lote.fotos?.[0];

  return (
    <article className={`cartao ${selecionado ? "cartao--selecionado" : ""}`}>
      <div className="cartao__midia">
        {foto ? (
          <img src={foto} alt="" loading="lazy" className="cartao__foto" />
        ) : (
          <div className="cartao__sem-foto" aria-hidden="true">
            <span>{ICONE_TIPO[lote.tipo_bem] ?? "📦"}</span>
          </div>
        )}
        <span className="cartao__tipo">
          <span aria-hidden="true">{ICONE_TIPO[lote.tipo_bem] ?? "📦"}</span>
          {rotuloTipoBem(lote.tipo_bem)}
        </span>
        {aoFavoritar && (
          <button
            type="button"
            className={`cartao__favorito ${favoritado ? "esta-ativo" : ""}`}
            onClick={() => aoFavoritar(lote.id)}
            aria-pressed={favoritado}
            aria-label={favoritado ? "Remover dos favoritos" : "Salvar nos favoritos"}
          >
            {favoritado ? "★" : "☆"}
          </button>
        )}
      </div>

      <div className="cartao__corpo">
        <h3 className="cartao__titulo">
          <Link to={`/lote/${lote.id}`}>{lote.titulo}</Link>
        </h3>
        <p className="cartao__local">
          {[lote.bairro, lote.cidade, lote.uf].filter(Boolean).join(", ") ||
            "Localização não informada"}
        </p>

        <dl className="cartao__valores">
          <div>
            <dt>Lance mínimo</dt>
            <dd className="cartao__lance">{emReais(lanceAtual)}</dd>
          </div>
          <div>
            <dt>Avaliação</dt>
            <dd>{emReais(lote.valor_avaliacao)}</dd>
          </div>
        </dl>

        <ContagemRegressiva
          data={lote.proxima_praca}
          ordem={lote.proxima_praca_ordem}
        />

        <div className="cartao__selos">
          <SeloRisco lote={lote} />
          {lote.status !== "ABERTO" && (
            <span className="selo selo--neutro">
              <span className="selo__icone" aria-hidden="true">
                ◼
              </span>
              <span className="selo__rotulo">{lote.status.toLowerCase()}</span>
            </span>
          )}
        </div>

        <TermometroScore score={lote.score} compacto />

        {aoAlternarSelecao && (
          <label className="cartao__comparar">
            <input
              type="checkbox"
              checked={Boolean(selecionado)}
              onChange={() => aoAlternarSelecao(lote.id)}
            />
            Comparar
          </label>
        )}
      </div>
    </article>
  );
}
