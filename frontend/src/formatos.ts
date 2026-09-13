/** Formatação pt-BR. Um lugar só, para a mesma moeda não sair de dois jeitos. */

const MOEDA = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});
const MOEDA_EXATA = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const DATA = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "America/Maceio",
});
const DATA_HORA = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "America/Maceio",
});

export const emReais = (valor: string | number | null | undefined, exato = false) => {
  if (valor === null || valor === undefined || valor === "") return "não informado";
  const numero = typeof valor === "string" ? Number(valor) : valor;
  if (!Number.isFinite(numero)) return "não informado";
  return (exato ? MOEDA_EXATA : MOEDA).format(numero);
};

export const emData = (iso: string | null | undefined) =>
  iso ? DATA.format(new Date(iso)) : "—";

export const emDataHora = (iso: string | null | undefined) =>
  iso ? DATA_HORA.format(new Date(iso)) : "—";

export const emPercentual = (valor: string | number | null | undefined, casas = 1) => {
  if (valor === null || valor === undefined || valor === "") return "—";
  const numero = typeof valor === "string" ? Number(valor) : valor;
  if (!Number.isFinite(numero)) return "—";
  return `${numero.toFixed(casas).replace(".", ",")}%`;
};

export const emArea = (valor: string | number | null | undefined) => {
  if (valor === null || valor === undefined || valor === "") return "—";
  const numero = typeof valor === "string" ? Number(valor) : valor;
  return `${numero.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} m²`;
};

/** "faltam 3 dias", "em 4 horas", "encerrada há 2 dias". */
export function tempoRestante(iso: string | null | undefined, agora = new Date()) {
  if (!iso) return { texto: "sem data de praça", urgencia: "nenhuma" as const, ms: 0 };
  const alvo = new Date(iso).getTime();
  const ms = alvo - agora.getTime();
  const passou = ms < 0;
  const abs = Math.abs(ms);
  const minutos = Math.floor(abs / 60000);
  const horas = Math.floor(minutos / 60);
  const dias = Math.floor(horas / 24);

  let quantidade: string;
  if (dias >= 2) quantidade = `${dias} dias`;
  else if (horas >= 2) quantidade = `${horas} horas`;
  else if (minutos >= 2) quantidade = `${minutos} minutos`;
  else quantidade = "menos de 1 minuto";

  const urgencia = passou
    ? ("encerrada" as const)
    : dias <= 1
      ? ("alta" as const)
      : dias <= 7
        ? ("media" as const)
        : ("baixa" as const);

  return {
    texto: passou ? `encerrada há ${quantidade}` : `faltam ${quantidade}`,
    urgencia,
    ms,
  };
}

export const rotuloTipoBem = (tipo: string) =>
  ({ IMOVEL: "Imóvel", VEICULO: "Veículo", OUTRO: "Outro" })[tipo] ?? tipo;

export const rotuloFonte = (fonte: string) =>
  ({
    FIPE: "Tabela FIPE",
    FIPEZAP: "Índice FipeZap",
    LAUDO_JUDICIAL: "Laudo judicial",
    COMPARAVEIS: "Anúncios comparáveis",
  })[fonte] ?? fonte;

export const humanizar = (texto: string) =>
  texto.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
