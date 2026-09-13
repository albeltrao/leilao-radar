/**
 * UFs cobertas, num lugar só.
 *
 * Estavam fixas em quatro arquivos (cabeçalho, filtros, calendário e mapa).
 * Acrescentar a Bahia exigiria lembrar dos quatro, e esquecer um deixaria um
 * estado invisível justamente na tela onde o usuário vai procurá-lo.
 *
 * A fonte de verdade continua sendo o backend: a lista de filtros usa as
 * facetas de /api/meta/facetas quando elas chegam. Isto aqui é o que a tela
 * mostra antes da primeira resposta e onde não há faceta.
 */

export const UFS = ["AL", "BA", "PE", "SE"] as const;

export type Uf = (typeof UFS)[number];

export const NOME_UF: Record<Uf, string> = {
  AL: "Alagoas",
  BA: "Bahia",
  PE: "Pernambuco",
  SE: "Sergipe",
};

/** "Alagoas, Bahia, Pernambuco e Sergipe" */
export const REGIAO_POR_EXTENSO = UFS.map((uf) => NOME_UF[uf]).reduce(
  (texto, nome, i, todos) =>
    i === 0 ? nome : i === todos.length - 1 ? `${texto} e ${nome}` : `${texto}, ${nome}`,
  "",
);

/** "AL · BA · PE · SE" */
export const REGIAO_SIGLAS = UFS.join(" · ");
