/** Tipos espelhando os schemas da API (backend/src/radar/api/schemas.py). */

export type TipoBem = "IMOVEL" | "VEICULO" | "OUTRO";
export type Faixa = "ALTA" | "BOA" | "MODERADA" | "BAIXA" | "INDEFINIDA";

export interface ComponenteScore {
  chave: string;
  rotulo: string;
  pontos: number;
  maximo: number;
  explicacao: string;
}

export interface Score {
  total: number;
  faixa: Faixa;
  componentes: ComponenteScore[];
  desconto_destaque: number | null;
  fonte_destaque: string | null;
  versao: string;
  calculado_em: string;
}

export interface Leiloeiro {
  id: number;
  nome: string;
  matricula: string | null;
  junta: string | null;
  uf: string;
  status: string;
  site_url: string | null;
  credenciamentos: Record<string, boolean> | null;
}

export interface LoteResumo {
  id: number;
  titulo: string;
  tipo_bem: TipoBem;
  status: string;
  numero_lote: string | null;
  numero_processo: string | null;
  valor_avaliacao: string | null;
  valor_minimo_primeira: string | null;
  valor_minimo_segunda: string | null;
  cidade: string | null;
  bairro: string | null;
  uf: string | null;
  latitude: number | null;
  longitude: number | null;
  geocodificacao_precisao: string | null;
  ocupado: boolean | null;
  onus: string[] | null;
  condicao_veiculo: string[] | null;
  fotos: string[] | null;
  fonte_slug: string;
  fonte_url: string | null;
  atualizado_em: string;
  score: Score | null;
  proxima_praca: string | null;
  proxima_praca_ordem: number | null;
  leiloeiro: Leiloeiro | null;
}

export interface Campo {
  nome: string;
  valor: string | number | boolean | null;
  confianca: number;
  metodo: string;
  evidencia: string | null;
  revisao_necessaria: boolean;
}

export interface Analise {
  fonte: string;
  valor_referencia: string | null;
  valor_comparado: string | null;
  praca_base: number | null;
  desconto_percentual: string | null;
  data_referencia_fonte: string | null;
  metodologia: string;
  fonte_url: string | null;
  avisos: string[] | null;
  confianca: number;
  calculado_em: string;
}

export interface Evento {
  id: number;
  lote_id: number;
  tipo: string;
  titulo: string;
  data_hora: string;
  status: string;
  estimado: boolean;
  lembretes_horas: number[] | null;
}

export interface Praca {
  ordem: number;
  data_hora: string | null;
  percentual_minimo: string | null;
  status: string;
}

export interface Documento {
  id: number;
  tipo: string;
  url: string | null;
  paginas: number | null;
  origem_texto: string | null;
  extraido_em: string | null;
  erro_extracao: string | null;
}

export interface LoteDetalhe extends LoteResumo {
  descricao: string | null;
  endereco: string | null;
  cep: string | null;
  matricula: string | null;
  cartorio: string | null;
  area_total_m2: string | null;
  area_privativa_m2: string | null;
  quartos: number | null;
  vagas: number | null;
  marca: string | null;
  modelo: string | null;
  ano_fabricacao: number | null;
  ano_modelo: number | null;
  combustivel: string | null;
  placa_parcial: string | null;
  comissao_leiloeiro_percentual: string | null;
  formas_pagamento: string[] | null;
  debitos: { tipo: string; valor: number | null }[] | null;
  fontes_secundarias: { fonte: string; url: string }[] | null;
  coletado_em: string;
  visto_por_ultimo_em: string;
  pracas: Praca[];
  eventos: Evento[];
  documentos: Documento[];
  campos: Campo[];
  analises: Analise[];
  disclaimer: string;
}

export interface PaginaLotes {
  itens: LoteResumo[];
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
}

export interface Simulacao {
  lance_base: string | null;
  custo_total_estimado: string | null;
  detalhes: string[];
  aviso: string;
}

export interface FonteSaude {
  slug: string;
  nome: string;
  tipo: string;
  uf: string | null;
  url_alvo: string;
  periodicidade_horas: number;
  validado_ao_vivo: boolean;
  descricao: string;
  ultima_execucao_em: string | null;
  ultimo_status: string | null;
  ultimo_erro: string | null;
  itens_ultima_coleta: number | null;
  duracao_ultima_s: number | null;
  execucoes_7d: number;
  falhas_7d: number;
}

export interface Facetas {
  ufs: string[];
  cidades: { uf: string; cidade: string; total: number }[];
  tipos_bem: { valor: string; total: number }[];
  status: { valor: string; total: number }[];
  leiloeiros: Leiloeiro[];
  faixa_valores: { minimo: string | null; maximo: string | null };
}

export interface PassoGlossario {
  chave: string;
  titulo: string;
  resumo: string;
  detalhe: string;
  atencao: string | null;
}

export interface Glossario {
  passos: PassoGlossario[];
  referencias: { titulo: string; descricao: string; url: string }[];
}

export interface Usuario {
  id: number;
  email: string;
  nome: string | null;
}

export interface Alerta {
  id: number;
  nome: string;
  criterios: Record<string, unknown>;
  canal: string;
  ativo: boolean;
  ultimo_envio_em: string | null;
  criado_em: string;
}

export interface FiltroBusca {
  uf?: string[];
  cidade?: string[];
  tipo_bem?: string[];
  status?: string[];
  valor_minimo?: number;
  valor_maximo?: number;
  desconto_minimo?: number;
  score_minimo?: number;
  dias_ate_praca_max?: number;
  somente_desocupados?: boolean;
  sem_onus?: boolean;
  q?: string;
  ordenar?: string;
  pagina?: number;
  tamanho?: number;
}

export interface GeoFeicao {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    id: number;
    titulo: string;
    cidade: string | null;
    uf: string | null;
    tipo_bem: TipoBem;
    valor_minimo: number;
    score: number | null;
    faixa: Faixa | null;
    desconto: number | null;
    proxima_praca: string | null;
    proxima_praca_ordem: number | null;
    precisao: string | null;
  };
}
