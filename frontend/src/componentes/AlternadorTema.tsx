import { useEffect, useState } from "react";

/**
 * Alternador de tema (seção 10: modo escuro).
 *
 * Três estados, não dois: claro, escuro e "seguir o sistema". Um toggle de dois
 * estados obriga quem usa o tema automático do sistema a escolher um lado.
 */

type Tema = "sistema" | "claro" | "escuro";
const CHAVE = "radar.tema";

function aplicar(tema: Tema) {
  const raiz = document.documentElement;
  if (tema === "sistema") raiz.removeAttribute("data-tema");
  else raiz.setAttribute("data-tema", tema);
}

export function AlternadorTema() {
  const [tema, setTema] = useState<Tema>(() => {
    try {
      return (localStorage.getItem(CHAVE) as Tema) ?? "sistema";
    } catch {
      return "sistema";
    }
  });

  useEffect(() => {
    aplicar(tema);
    try {
      localStorage.setItem(CHAVE, tema);
    } catch {
      /* navegação privada: o tema vale só nesta sessão */
    }
  }, [tema]);

  const opcoes: { valor: Tema; icone: string; rotulo: string }[] = [
    { valor: "claro", icone: "☀", rotulo: "Tema claro" },
    { valor: "escuro", icone: "☾", rotulo: "Tema escuro" },
    { valor: "sistema", icone: "◐", rotulo: "Seguir o sistema" },
  ];

  return (
    <div className="alternador-tema" role="group" aria-label="Tema da interface">
      {opcoes.map((opcao) => (
        <button
          key={opcao.valor}
          type="button"
          className={tema === opcao.valor ? "esta-ativo" : ""}
          onClick={() => setTema(opcao.valor)}
          aria-pressed={tema === opcao.valor}
          title={opcao.rotulo}
        >
          <span aria-hidden="true">{opcao.icone}</span>
          <span className="sr-apenas">{opcao.rotulo}</span>
        </button>
      ))}
    </div>
  );
}
