import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { CartaoLote } from "../componentes/CartaoLote";
import { Confete, useConfete } from "../componentes/Confete";
import { Filtros } from "../componentes/Filtros";
import { emReais } from "../formatos";
import { useSessao } from "../sessao";
import type { Facetas, FiltroBusca, PaginaLotes } from "../tipos";

/** Painel principal: filtros, resumo e a grade de cartões. */

const CHAVE_COMPARACAO = "radar.comparar";

function lerComparacao(): number[] {
  try {
    return JSON.parse(sessionStorage.getItem(CHAVE_COMPARACAO) ?? "[]");
  } catch {
    return [];
  }
}

export function Painel() {
  const [params, setParams] = useSearchParams();
  const { usuario, favoritos, alternarFavorito } = useSessao();
  const { ativo: confeteAtivo, comemorar } = useConfete();

  const [pagina, setPagina] = useState<PaginaLotes | null>(null);
  const [facetas, setFacetas] = useState<Facetas | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [comparacao, setComparacao] = useState<number[]>(lerComparacao);

  const filtro = useMemo<FiltroBusca>(() => {
    const numero = (chave: string) => {
      const valor = params.get(chave);
      return valor ? Number(valor) : undefined;
    };
    return {
      q: params.get("q") ?? undefined,
      uf: params.getAll("uf").length ? params.getAll("uf") : undefined,
      tipo_bem: params.getAll("tipo_bem").length ? params.getAll("tipo_bem") : undefined,
      desconto_minimo: numero("desconto_minimo"),
      valor_maximo: numero("valor_maximo"),
      somente_desocupados: params.get("somente_desocupados") === "true" || undefined,
      sem_onus: params.get("sem_onus") === "true" || undefined,
      ordenar: params.get("ordenar") ?? "score",
      pagina: numero("pagina") ?? 1,
      tamanho: 24,
    };
  }, [params]);

  const aplicar = useCallback(
    (novo: FiltroBusca) => {
      const proximos = new URLSearchParams();
      for (const [chave, valor] of Object.entries(novo)) {
        if (valor === undefined || valor === null || valor === "" || valor === false) continue;
        if (Array.isArray(valor)) valor.forEach((v) => proximos.append(chave, String(v)));
        else proximos.set(chave, String(valor));
      }
      proximos.delete("tamanho");
      setParams(proximos, { replace: true });
    },
    [setParams],
  );

  useEffect(() => {
    api.facetas().then(setFacetas).catch(() => setFacetas(null));
  }, []);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    api
      .lotes(filtro)
      .then((dados) => vivo && setPagina(dados))
      .catch((e) => vivo && setErro(e.message))
      .finally(() => vivo && setCarregando(false));
    return () => {
      vivo = false;
    };
  }, [filtro]);

  const alternarComparacao = (id: number) => {
    setComparacao((atual) => {
      const proximo = atual.includes(id)
        ? atual.filter((x) => x !== id)
        : [...atual, id].slice(-3);
      try {
        sessionStorage.setItem(CHAVE_COMPARACAO, JSON.stringify(proximo));
      } catch {
        /* sem storage: a seleção vale só enquanto a página estiver aberta */
      }
      return proximo;
    });
  };

  const favoritar = async (id: number) => {
    try {
      const virouFavorito = await alternarFavorito(id);
      if (virouFavorito) comemorar();
    } catch (e) {
      setErro((e as Error).message);
    }
  };

  const destaque = pagina?.itens[0];

  return (
    <>
      <Confete ativo={confeteAtivo} />

      <section className="abertura">
        <div className="abertura__texto">
          <h1>
            Leilões judiciais de <span className="realce">Alagoas, Sergipe e Pernambuco</span>
          </h1>
          <p>
            Editais lidos, valores comparados com referência de mercado e praças no
            calendário. Cada número mostra de onde veio.
          </p>
          <div className="abertura__acoes">
            <Link to="/como-funciona" className="botao botao--primario">
              Nunca participei de um leilão
            </Link>
            <Link to="/calendario" className="botao botao--secundario">
              Ver o calendário de praças
            </Link>
          </div>
        </div>

        {destaque && (
          <aside className="abertura__destaque" aria-label="Lote em destaque">
            <span className="abertura__etiqueta">Melhor oportunidade agora</span>
            <Link to={`/lote/${destaque.id}`} className="abertura__titulo">
              {destaque.titulo}
            </Link>
            <div className="abertura__numeros">
              <div>
                <span className="abertura__rotulo">Lance mínimo</span>
                <strong>
                  {emReais(destaque.valor_minimo_segunda ?? destaque.valor_minimo_primeira)}
                </strong>
              </div>
              <div>
                <span className="abertura__rotulo">Score</span>
                <strong>{destaque.score ? destaque.score.total.toFixed(0) : "—"}/100</strong>
              </div>
            </div>
          </aside>
        )}
      </section>

      <Filtros
        facetas={facetas}
        filtro={filtro}
        aoMudar={aplicar}
        total={pagina?.total ?? 0}
      />

      {comparacao.length > 0 && (
        <div className="barra-comparacao" role="status">
          <span>
            {comparacao.length} {comparacao.length === 1 ? "lote" : "lotes"} para comparar
          </span>
          <Link
            to={`/comparar?ids=${comparacao.join(",")}`}
            className="botao botao--primario botao--pequeno"
            aria-disabled={comparacao.length < 2}
          >
            Comparar lado a lado
          </Link>
          <button
            type="button"
            className="botao botao--texto"
            onClick={() => {
              setComparacao([]);
              try {
                sessionStorage.removeItem(CHAVE_COMPARACAO);
              } catch {
                /* nada a limpar */
              }
            }}
          >
            Limpar
          </button>
        </div>
      )}

      {erro && <p className="erro">Não consegui carregar os lotes: {erro}</p>}

      {carregando ? (
        <div className="grade">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="cartao cartao--esqueleto" aria-hidden="true" />
          ))}
        </div>
      ) : pagina && pagina.itens.length > 0 ? (
        <>
          <div className="grade">
            {pagina.itens.map((lote) => (
              <CartaoLote
                key={lote.id}
                lote={lote}
                selecionado={comparacao.includes(lote.id)}
                aoAlternarSelecao={alternarComparacao}
                favoritado={favoritos.has(lote.id)}
                aoFavoritar={usuario ? favoritar : undefined}
              />
            ))}
          </div>

          {pagina.paginas > 1 && (
            <nav className="paginacao" aria-label="Paginação">
              <button
                type="button"
                className="botao botao--secundario"
                disabled={pagina.pagina <= 1}
                onClick={() => aplicar({ ...filtro, pagina: pagina.pagina - 1 })}
              >
                Anterior
              </button>
              <span>
                Página {pagina.pagina} de {pagina.paginas}
              </span>
              <button
                type="button"
                className="botao botao--secundario"
                disabled={pagina.pagina >= pagina.paginas}
                onClick={() => aplicar({ ...filtro, pagina: pagina.pagina + 1 })}
              >
                Próxima
              </button>
            </nav>
          )}
        </>
      ) : (
        <div className="vazio">
          <h2>Nenhum lote com esses filtros</h2>
          <p>
            Tente ampliar a faixa de valor, tirar o desconto mínimo ou incluir outro
            estado. Também pode ser que a coleta ainda não tenha rodado.
          </p>
        </div>
      )}
    </>
  );
}
