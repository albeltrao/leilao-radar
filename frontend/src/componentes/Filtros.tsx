import type { Facetas, FiltroBusca } from "../tipos";
import { emReais } from "../formatos";
import { UFS } from "../ufs";

/**
 * Barra de filtros. Fica numa linha acima dos resultados, como manda a
 * orientação de interação: filtros agrupados, não espalhados pela página.
 *
 * As opções vêm de /api/meta/facetas — a UI não chuta quais cidades ou tipos
 * existem, ela pergunta. Filtro que oferece uma cidade sem nenhum lote é uma
 * promessa quebrada.
 */
export function Filtros({
  facetas,
  filtro,
  aoMudar,
  total,
}: {
  facetas: Facetas | null;
  filtro: FiltroBusca;
  aoMudar: (novo: FiltroBusca) => void;
  total: number;
}) {
  const alterar = (campo: keyof FiltroBusca, valor: unknown) =>
    aoMudar({ ...filtro, [campo]: valor, pagina: 1 });

  const alternarLista = (campo: "uf" | "tipo_bem", valor: string) => {
    const atual = new Set(filtro[campo] ?? []);
    atual.has(valor) ? atual.delete(valor) : atual.add(valor);
    alterar(campo, atual.size ? [...atual] : undefined);
  };

  const limpar = () => aoMudar({ ordenar: filtro.ordenar, tamanho: filtro.tamanho, pagina: 1 });
  const temFiltro =
    Boolean(filtro.uf?.length) ||
    Boolean(filtro.tipo_bem?.length) ||
    Boolean(filtro.q) ||
    filtro.desconto_minimo !== undefined ||
    filtro.valor_maximo !== undefined ||
    filtro.somente_desocupados ||
    filtro.sem_onus;

  return (
    <section className="filtros" aria-label="Filtros de busca">
      <div className="filtros__linha">
        <label className="campo campo--busca">
          <span className="sr-apenas">Buscar</span>
          <input
            type="search"
            placeholder="Buscar por bairro, cidade, processo, modelo…"
            value={filtro.q ?? ""}
            onChange={(e) => alterar("q", e.target.value || undefined)}
          />
        </label>

        <label className="campo">
          <span>Ordenar por</span>
          <select
            value={filtro.ordenar ?? "score"}
            onChange={(e) => alterar("ordenar", e.target.value)}
          >
            <option value="score">Melhor oportunidade</option>
            <option value="desconto">Maior desconto</option>
            <option value="praca">Praça mais próxima</option>
            <option value="valor">Menor lance</option>
            <option value="recente">Coletado há menos tempo</option>
          </select>
        </label>
      </div>

      <div className="filtros__linha filtros__linha--grupos">
        <fieldset className="grupo">
          <legend>Estado</legend>
          {(facetas?.ufs ?? [...UFS]).map((uf) => (
            <button
              key={uf}
              type="button"
              className={`pilula ${filtro.uf?.includes(uf) ? "esta-ativa" : ""}`}
              aria-pressed={filtro.uf?.includes(uf) ?? false}
              onClick={() => alternarLista("uf", uf)}
            >
              {uf}
            </button>
          ))}
        </fieldset>

        <fieldset className="grupo">
          <legend>Tipo de bem</legend>
          {(facetas?.tipos_bem ?? []).map((tipo) => (
            <button
              key={tipo.valor}
              type="button"
              className={`pilula ${filtro.tipo_bem?.includes(tipo.valor) ? "esta-ativa" : ""}`}
              aria-pressed={filtro.tipo_bem?.includes(tipo.valor) ?? false}
              onClick={() => alternarLista("tipo_bem", tipo.valor)}
            >
              {{ IMOVEL: "Imóveis", VEICULO: "Veículos", OUTRO: "Outros" }[tipo.valor] ??
                tipo.valor}
              <span className="pilula__contagem">{tipo.total}</span>
            </button>
          ))}
        </fieldset>

        <label className="campo campo--faixa">
          <span>
            Desconto mínimo
            {filtro.desconto_minimo ? `: ${filtro.desconto_minimo}%` : ""}
          </span>
          <input
            type="range"
            min={0}
            max={80}
            step={5}
            value={filtro.desconto_minimo ?? 0}
            onChange={(e) =>
              alterar("desconto_minimo", Number(e.target.value) || undefined)
            }
          />
        </label>

        <label className="campo campo--faixa">
          <span>
            Lance até{filtro.valor_maximo ? `: ${emReais(filtro.valor_maximo)}` : ""}
          </span>
          <input
            type="range"
            min={0}
            max={Number(facetas?.faixa_valores.maximo ?? 1_000_000)}
            step={10_000}
            value={filtro.valor_maximo ?? 0}
            onChange={(e) => alterar("valor_maximo", Number(e.target.value) || undefined)}
          />
        </label>
      </div>

      <div className="filtros__linha filtros__linha--fim">
        <label className="caixa">
          <input
            type="checkbox"
            checked={Boolean(filtro.somente_desocupados)}
            onChange={(e) => alterar("somente_desocupados", e.target.checked || undefined)}
          />
          Só desocupados
        </label>
        <label className="caixa">
          <input
            type="checkbox"
            checked={Boolean(filtro.sem_onus)}
            onChange={(e) => alterar("sem_onus", e.target.checked || undefined)}
          />
          Sem ônus registrado
        </label>

        <span className="filtros__resultado">
          {total} {total === 1 ? "lote encontrado" : "lotes encontrados"}
        </span>
        {temFiltro && (
          <button type="button" className="botao botao--texto" onClick={limpar}>
            Limpar filtros
          </button>
        )}
      </div>
    </section>
  );
}
