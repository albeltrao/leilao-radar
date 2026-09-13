import { useEffect, useState } from "react";

/**
 * Confete sutil ao salvar o primeiro favorito (seção 10: tom lúdico).
 *
 * Duas contenções deliberadas: dispara UMA vez na vida do usuário (o segundo
 * favorito não merece festa) e respeita `prefers-reduced-motion`, porque
 * animação fora de controle é barreira de acessibilidade, não charme.
 */

const CHAVE = "radar.confete-visto";
const CORES = ["var(--faixa-alta)", "var(--faixa-boa)", "var(--faixa-moderada)", "var(--marca)"];

export function useConfete() {
  const [ativo, setAtivo] = useState(false);

  const comemorar = () => {
    try {
      if (localStorage.getItem(CHAVE)) return;
      localStorage.setItem(CHAVE, "1");
    } catch {
      /* sem storage: comemora uma vez por sessão mesmo */
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setAtivo(true);
  };

  useEffect(() => {
    if (!ativo) return;
    const id = setTimeout(() => setAtivo(false), 1800);
    return () => clearTimeout(id);
  }, [ativo]);

  return { ativo, comemorar };
}

export function Confete({ ativo }: { ativo: boolean }) {
  if (!ativo) return null;
  const pedacos = Array.from({ length: 26 }, (_, i) => i);
  return (
    <div className="confete" aria-hidden="true">
      {pedacos.map((i) => (
        <span
          key={i}
          className="confete__pedaco"
          style={{
            left: `${(i * 37) % 100}%`,
            background: CORES[i % CORES.length],
            animationDelay: `${(i % 7) * 60}ms`,
            transform: `rotate(${(i * 47) % 360}deg)`,
          }}
        />
      ))}
    </div>
  );
}
