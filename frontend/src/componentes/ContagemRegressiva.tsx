import { useEffect, useState } from "react";
import { emDataHora, tempoRestante } from "../formatos";

/**
 * Contagem regressiva até a praça (seção 10).
 *
 * Atualiza a cada 30 s — não a cada segundo. Um relógio que pisca a cada
 * segundo em 24 cartões chama mais atenção do que o conteúdo e só gasta
 * bateria em celular, que é onde a maior parte da audiência vai acessar.
 */
export function ContagemRegressiva({
  data,
  ordem,
  estimado = false,
}: {
  data: string | null;
  ordem?: number | null;
  estimado?: boolean;
}) {
  const [agora, setAgora] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setAgora(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const { texto, urgencia } = tempoRestante(data, agora);
  const rotuloPraca = ordem ? `${ordem}ª praça` : "Praça";

  return (
    <div className={`contagem contagem--${urgencia}`}>
      <span className="contagem__praca">{rotuloPraca}</span>
      <time className="contagem__data" dateTime={data ?? undefined}>
        {emDataHora(data)}
      </time>
      <span className="contagem__resta">
        {texto}
        {estimado && (
          <span className="contagem__estimado" title="Data inferida, não declarada no edital">
            {" "}
            · estimada
          </span>
        )}
      </span>
    </div>
  );
}
