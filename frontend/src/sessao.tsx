import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, token as guardaToken } from "./api";
import type { LoteResumo, Usuario } from "./tipos";

/** Sessão do usuário e favoritos, compartilhados pela aplicação. */

interface Contexto {
  usuario: Usuario | null;
  carregando: boolean;
  favoritos: Set<number>;
  entrar: (email: string, senha: string) => Promise<void>;
  registrar: (email: string, senha: string, nome?: string) => Promise<void>;
  sair: () => void;
  alternarFavorito: (id: number) => Promise<boolean>;
  listaFavoritos: LoteResumo[];
  recarregarFavoritos: () => Promise<void>;
}

const ContextoSessao = createContext<Contexto | null>(null);

export function ProvedorSessao({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [listaFavoritos, setListaFavoritos] = useState<LoteResumo[]>([]);

  const recarregarFavoritos = useCallback(async () => {
    if (!guardaToken.ler()) {
      setListaFavoritos([]);
      return;
    }
    try {
      setListaFavoritos(await api.favoritos());
    } catch {
      setListaFavoritos([]);
    }
  }, []);

  useEffect(() => {
    let vivo = true;
    (async () => {
      if (!guardaToken.ler()) {
        setCarregando(false);
        return;
      }
      try {
        const atual = await api.eu();
        if (!vivo) return;
        setUsuario(atual);
        await recarregarFavoritos();
      } catch {
        guardaToken.limpar();
      } finally {
        if (vivo) setCarregando(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, [recarregarFavoritos]);

  const entrar = useCallback(
    async (email: string, senha: string) => {
      const resposta = await api.entrar(email, senha);
      guardaToken.gravar(resposta.token);
      setUsuario(resposta.usuario);
      await recarregarFavoritos();
    },
    [recarregarFavoritos],
  );

  const registrar = useCallback(
    async (email: string, senha: string, nome?: string) => {
      const resposta = await api.registrar(email, senha, nome);
      guardaToken.gravar(resposta.token);
      setUsuario(resposta.usuario);
    },
    [],
  );

  const sair = useCallback(() => {
    guardaToken.limpar();
    setUsuario(null);
    setListaFavoritos([]);
  }, []);

  const favoritos = useMemo(
    () => new Set(listaFavoritos.map((lote) => lote.id)),
    [listaFavoritos],
  );

  const alternarFavorito = useCallback(
    async (id: number) => {
      if (!usuario) throw new Error("entre na sua conta para salvar favoritos");
      const jaEra = favoritos.has(id);
      if (jaEra) await api.desfavoritar(id);
      else await api.favoritar(id);
      await recarregarFavoritos();
      return !jaEra;
    },
    [usuario, favoritos, recarregarFavoritos],
  );

  const valor = useMemo(
    () => ({
      usuario,
      carregando,
      favoritos,
      entrar,
      registrar,
      sair,
      alternarFavorito,
      listaFavoritos,
      recarregarFavoritos,
    }),
    [
      usuario,
      carregando,
      favoritos,
      entrar,
      registrar,
      sair,
      alternarFavorito,
      listaFavoritos,
      recarregarFavoritos,
    ],
  );

  return <ContextoSessao.Provider value={valor}>{children}</ContextoSessao.Provider>;
}

export function useSessao() {
  const contexto = useContext(ContextoSessao);
  if (!contexto) throw new Error("useSessao precisa estar dentro de ProvedorSessao");
  return contexto;
}
