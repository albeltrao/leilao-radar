/** Cliente HTTP da API. Um lugar só para token, erro e montagem de query. */

import type {
  Alerta,
  Facetas,
  FiltroBusca,
  FonteSaude,
  GeoFeicao,
  Glossario,
  LoteDetalhe,
  LoteResumo,
  PaginaLotes,
  Simulacao,
  Usuario,
} from "./tipos";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const CHAVE_TOKEN = "radar.token";

export class ErroApi extends Error {
  constructor(
    public status: number,
    mensagem: string,
  ) {
    super(mensagem);
  }
}

export const token = {
  ler: () => {
    try {
      return localStorage.getItem(CHAVE_TOKEN);
    } catch {
      return null;
    }
  },
  gravar: (valor: string) => {
    try {
      localStorage.setItem(CHAVE_TOKEN, valor);
    } catch {
      /* navegação privada: a sessão vive só nesta aba */
    }
  },
  limpar: () => {
    try {
      localStorage.removeItem(CHAVE_TOKEN);
    } catch {
      /* idem */
    }
  },
};

function montarQuery(filtros: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor === undefined || valor === null || valor === "") continue;
    if (Array.isArray(valor)) {
      for (const item of valor) params.append(chave, String(item));
    } else if (typeof valor === "boolean") {
      if (valor) params.append(chave, "true");
    } else {
      params.append(chave, String(valor));
    }
  }
  const texto = params.toString();
  return texto ? `?${texto}` : "";
}

async function pedir<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const cabecalhos = new Headers(opcoes.headers);
  cabecalhos.set("Accept", "application/json");
  if (opcoes.body) cabecalhos.set("Content-Type", "application/json");
  const atual = token.ler();
  if (atual) cabecalhos.set("Authorization", `Bearer ${atual}`);

  const resposta = await fetch(`${BASE}${caminho}`, { ...opcoes, headers: cabecalhos });
  if (resposta.status === 204) return undefined as T;
  if (!resposta.ok) {
    let detalhe = `HTTP ${resposta.status}`;
    try {
      const corpo = await resposta.json();
      if (corpo?.detail) {
        detalhe =
          typeof corpo.detail === "string"
            ? corpo.detail
            : (corpo.detail[0]?.msg ?? detalhe);
      }
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new ErroApi(resposta.status, detalhe);
  }
  return (await resposta.json()) as T;
}

export const api = {
  saude: () => pedir<{ status: string; lotes: number; leiloeiros: number }>("/saude"),

  lotes: (filtros: FiltroBusca = {}) =>
    pedir<PaginaLotes>(`/lotes${montarQuery(filtros as Record<string, unknown>)}`),
  lote: (id: number) => pedir<LoteDetalhe>(`/lotes/${id}`),
  comparar: (ids: number[]) =>
    pedir<LoteDetalhe[]>(`/lotes/comparar?ids=${ids.join(",")}`),
  simulacao: (id: number, lance?: number) =>
    pedir<Simulacao>(`/lotes/${id}/simulacao${montarQuery({ lance })}`),
  historico: (id: number) =>
    pedir<
      {
        data_hora_anterior: string | null;
        data_hora_nova: string | null;
        status_anterior: string | null;
        status_novo: string | null;
        motivo: string | null;
        registrado_em: string;
      }[]
    >(`/lotes/${id}/historico`),

  geo: (filtros: { uf?: string[]; tipo_bem?: string[] } = {}) =>
    pedir<{ type: string; features: GeoFeicao[] }>(`/geo/lotes${montarQuery(filtros)}`),

  calendario: (filtros: Record<string, unknown> = {}) =>
    pedir<import("./tipos").Evento[]>(`/calendario${montarQuery(filtros)}`),
  urlIcsCalendario: (filtros: Record<string, unknown> = {}) =>
    `${BASE}/calendario.ics${montarQuery(filtros)}`,
  urlIcsLote: (id: number) => `${BASE}/lotes/${id}/calendario.ics`,

  fontes: () => pedir<FonteSaude[]>("/fontes"),
  facetas: () => pedir<Facetas>("/meta/facetas"),
  glossario: () => pedir<Glossario>("/meta/glossario"),
  leiloeiros: () => pedir<import("./tipos").Leiloeiro[]>("/leiloeiros"),

  registrar: (email: string, senha: string, nome?: string) =>
    pedir<{ token: string; usuario: Usuario }>("/auth/registrar", {
      method: "POST",
      body: JSON.stringify({ email, senha, nome }),
    }),
  entrar: (email: string, senha: string) =>
    pedir<{ token: string; usuario: Usuario }>("/auth/entrar", {
      method: "POST",
      body: JSON.stringify({ email, senha }),
    }),
  eu: () => pedir<Usuario>("/auth/eu"),

  alertas: () => pedir<Alerta[]>("/alertas"),
  criarAlerta: (nome: string, criterios: Record<string, unknown>) =>
    pedir<Alerta>("/alertas", {
      method: "POST",
      body: JSON.stringify({ nome, criterios, canal: "EMAIL", ativo: true }),
    }),
  removerAlerta: (id: number) => pedir<void>(`/alertas/${id}`, { method: "DELETE" }),
  previaAlerta: (id: number) => pedir<PaginaLotes>(`/alertas/${id}/previa`),

  favoritos: () => pedir<LoteResumo[]>("/favoritos"),
  favoritar: (id: number) => pedir<unknown>(`/favoritos/${id}`, { method: "POST" }),
  desfavoritar: (id: number) => pedir<void>(`/favoritos/${id}`, { method: "DELETE" }),
};
