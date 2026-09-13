import type { LoteResumo } from "../tipos";
import { humanizar } from "../formatos";

/**
 * Selo de risco documental (seção 10).
 *
 * A seção 10 é explícita: "nunca só vermelho/verde puros por acessibilidade —
 * usar também ícone/forma, não somente cor". Por isso cada nível tem ícone
 * próprio E rótulo textual; a cor é o terceiro canal, não o único.
 *
 * O motivo do nível fica no `title` e na lista expandida do detalhe — um selo
 * vermelho sem explicação não ajuda ninguém a decidir.
 */

type Nivel = "ok" | "atencao" | "serio" | "critico" | "desconhecido";

const APARENCIA: Record<Nivel, { icone: string; rotulo: string; classe: string }> = {
  ok: { icone: "✓", rotulo: "Risco baixo", classe: "selo--ok" },
  atencao: { icone: "!", rotulo: "Atenção", classe: "selo--atencao" },
  serio: { icone: "▲", rotulo: "Risco relevante", classe: "selo--serio" },
  critico: { icone: "✕", rotulo: "Risco alto", classe: "selo--critico" },
  desconhecido: { icone: "?", rotulo: "Não avaliado", classe: "selo--desconhecido" },
};

export function avaliarRisco(lote: LoteResumo): { nivel: Nivel; motivos: string[] } {
  const motivos: string[] = [];
  let peso = 0;

  if (lote.ocupado === true) {
    motivos.push("imóvel ocupado — a desocupação pode exigir ação judicial");
    peso += 3;
  } else if (lote.ocupado === null && lote.tipo_bem === "IMOVEL") {
    motivos.push("o edital não informa se o imóvel está ocupado");
    peso += 1;
  }

  for (const onus of lote.onus ?? []) {
    motivos.push(`ônus registrado: ${humanizar(onus)}`);
    peso += ["hipoteca", "alienacao_fiduciaria", "usufruto"].includes(onus) ? 2 : 1;
  }

  for (const condicao of lote.condicao_veiculo ?? []) {
    motivos.push(`veículo ${humanizar(condicao).toLowerCase()}`);
    peso += ["sucata", "sem_documento"].includes(condicao) ? 3 : 1;
  }

  if (motivos.length === 0) {
    return {
      nivel: "ok",
      motivos: [
        "Nada foi encontrado no que analisamos. Isso não garante que não exista — confirme na matrícula atualizada.",
      ],
    };
  }
  const nivel: Nivel = peso >= 5 ? "critico" : peso >= 3 ? "serio" : "atencao";
  return { nivel, motivos };
}

export function SeloRisco({
  lote,
  detalhado = false,
}: {
  lote: LoteResumo;
  detalhado?: boolean;
}) {
  const { nivel, motivos } = avaliarRisco(lote);
  const aparencia = APARENCIA[nivel];

  return (
    <div className={detalhado ? "selo-bloco" : undefined}>
      <span
        className={`selo ${aparencia.classe}`}
        title={motivos.join(" · ")}
        role="status"
      >
        <span className="selo__icone" aria-hidden="true">
          {aparencia.icone}
        </span>
        <span className="selo__rotulo">{aparencia.rotulo}</span>
      </span>
      {detalhado && (
        <ul className="selo-bloco__motivos">
          {motivos.map((motivo) => (
            <li key={motivo}>{motivo}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
