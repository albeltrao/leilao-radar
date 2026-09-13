import { useId, useState } from "react";
import type { Score } from "../tipos";
import { emPercentual } from "../formatos";

/**
 * Termômetro de oportunidade (seção 8).
 *
 * A regra que dita o desenho: "nunca apenas um número sem explicação". O
 * número existe, mas o detalhamento por componente vem junto — expandido no
 * detalhe do lote e sob foco/hover no cartão. É acessível por teclado porque
 * um tooltip que só abre no mouse deixa metade da explicação inalcançável.
 */

const FAIXAS: Record<string, { cor: string; rotulo: string }> = {
  ALTA: { cor: "var(--faixa-alta)", rotulo: "Oportunidade alta" },
  BOA: { cor: "var(--faixa-boa)", rotulo: "Oportunidade boa" },
  MODERADA: { cor: "var(--faixa-moderada)", rotulo: "Oportunidade moderada" },
  BAIXA: { cor: "var(--faixa-baixa)", rotulo: "Oportunidade baixa" },
  INDEFINIDA: { cor: "var(--borda-forte)", rotulo: "Sem score calculado" },
};

export function TermometroScore({
  score,
  compacto = false,
}: {
  score: Score | null;
  compacto?: boolean;
}) {
  const [aberto, setAberto] = useState(false);
  const idPainel = useId();

  if (!score) {
    return (
      <span className="termometro termometro--vazio" title="Score ainda não calculado">
        <span className="termometro__vazio-texto">sem score</span>
      </span>
    );
  }

  const faixa = FAIXAS[score.faixa] ?? FAIXAS.INDEFINIDA;
  const largura = Math.max(2, Math.min(100, score.total));

  return (
    <div
      className={`termometro ${compacto ? "termometro--compacto" : ""}`}
      onMouseEnter={() => setAberto(true)}
      onMouseLeave={() => setAberto(false)}
    >
      <button
        type="button"
        className="termometro__gatilho"
        aria-expanded={aberto}
        aria-controls={idPainel}
        onClick={() => setAberto((v) => !v)}
        onFocus={() => setAberto(true)}
        onBlur={() => setAberto(false)}
      >
        <span className="termometro__numero" style={{ color: faixa.cor }}>
          {score.total.toFixed(0)}
          <span className="termometro__de">/100</span>
        </span>
        <span className="termometro__trilho" aria-hidden="true">
          <span
            className="termometro__preenchimento"
            style={{ width: `${largura}%`, background: faixa.cor }}
          />
        </span>
        <span className="termometro__faixa">{faixa.rotulo}</span>
        {score.desconto_destaque !== null && score.desconto_destaque > 0 && (
          <span className="termometro__desconto">
            {emPercentual(score.desconto_destaque, 0)} abaixo da referência
          </span>
        )}
      </button>

      <div
        id={idPainel}
        role="region"
        aria-label="Como este score foi calculado"
        className={`termometro__painel ${aberto ? "esta-aberto" : ""}`}
      >
        <p className="termometro__intro">
          O score soma cinco componentes. Passe o olho no porquê de cada um:
        </p>
        <ul className="termometro__lista">
          {score.componentes.map((componente) => (
            <li key={componente.chave} className="componente">
              <div className="componente__topo">
                <span className="componente__rotulo">{componente.rotulo}</span>
                <span className="componente__pontos">
                  {componente.pontos.toFixed(1)}
                  <span className="componente__max">/{componente.maximo}</span>
                </span>
              </div>
              <span className="componente__trilho" aria-hidden="true">
                <span
                  className="componente__preenchimento"
                  style={{
                    width: `${(componente.pontos / componente.maximo) * 100}%`,
                  }}
                />
              </span>
              <p className="componente__explicacao">{componente.explicacao}</p>
            </li>
          ))}
        </ul>
        <p className="termometro__rodape">
          Score versão {score.versao}. É um ranqueamento informativo, não uma
          recomendação de investimento.
        </p>
      </div>
    </div>
  );
}
