import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Glossario } from "../tipos";

/**
 * Onboarding em cards (seção 10).
 *
 * O conteúdo vem da API (/api/meta/glossario), não daqui: assim o texto
 * educativo e as referências legais moram num lugar só e podem ser revisados
 * por quem entende do assunto sem mexer no frontend.
 */
export function Onboarding() {
  const [glossario, setGlossario] = useState<Glossario | null>(null);
  const [passo, setPasso] = useState(0);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.glossario().then(setGlossario).catch((e) => setErro(e.message));
  }, []);

  if (erro) return <p className="erro">{erro}</p>;
  if (!glossario) return <div className="vazio">Carregando…</div>;

  const passos = glossario.passos;
  const atual = passos[passo];
  const progresso = ((passo + 1) / passos.length) * 100;

  return (
    <section className="pagina onboarding">
      <header className="pagina__topo">
        <div>
          <h1>Como funciona um leilão judicial</h1>
          <p className="pagina__ajuda">
            Dez passos, em linguagem direta. Cada um cita a norma de referência para
            você conferir — informar o que a lei diz é diferente de dizer o que vai
            acontecer no seu caso.
          </p>
        </div>
      </header>

      <div className="onboarding__progresso" aria-hidden="true">
        <span style={{ width: `${progresso}%` }} />
      </div>

      <div className="onboarding__cartao">
        <span className="onboarding__contador">
          Passo {passo + 1} de {passos.length}
        </span>
        <h2>{atual.titulo}</h2>
        <p className="onboarding__resumo">{atual.resumo}</p>
        <p className="onboarding__detalhe">{atual.detalhe}</p>
        {atual.atencao && (
          <p className="onboarding__atencao">
            <span className="selo__icone" aria-hidden="true">
              !
            </span>
            {atual.atencao}
          </p>
        )}

        <div className="onboarding__navegacao">
          <button
            type="button"
            className="botao botao--secundario"
            disabled={passo === 0}
            onClick={() => setPasso((p) => p - 1)}
          >
            Anterior
          </button>
          {passo < passos.length - 1 ? (
            <button
              type="button"
              className="botao botao--primario"
              onClick={() => setPasso((p) => p + 1)}
            >
              Próximo
            </button>
          ) : (
            <Link to="/" className="botao botao--primario">
              Ver os lotes disponíveis
            </Link>
          )}
        </div>
      </div>

      <nav className="onboarding__atalhos" aria-label="Ir para um passo">
        {passos.map((item, indice) => (
          <button
            key={item.chave}
            type="button"
            className={`pilula ${indice === passo ? "esta-ativa" : ""}`}
            onClick={() => setPasso(indice)}
            aria-current={indice === passo}
          >
            {item.titulo}
          </button>
        ))}
      </nav>

      <section className="bloco">
        <h2>Onde conferir</h2>
        <ul className="lista-simples">
          {glossario.referencias.map((referencia) => (
            <li key={referencia.titulo}>
              <a href={referencia.url} target="_blank" rel="noreferrer">
                {referencia.titulo}
              </a>{" "}
              — {referencia.descricao}
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
