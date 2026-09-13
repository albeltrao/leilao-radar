import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { CartaoLote } from "../componentes/CartaoLote";
import { emDataHora } from "../formatos";
import { useSessao } from "../sessao";
import type { Alerta } from "../tipos";

/** Conta: entrar/criar, alertas salvos e favoritos. */

export function Conta() {
  const { usuario, entrar, registrar, sair, listaFavoritos, favoritos, alternarFavorito } =
    useSessao();
  const [modo, setModo] = useState<"entrar" | "registrar">("entrar");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [nome, setNome] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [alertas, setAlertas] = useState<Alerta[]>([]);
  const [nomeAlerta, setNomeAlerta] = useState("");

  useEffect(() => {
    if (!usuario) return;
    api.alertas().then(setAlertas).catch(() => setAlertas([]));
  }, [usuario]);

  const enviar = async (evento: React.FormEvent) => {
    evento.preventDefault();
    setErro(null);
    try {
      if (modo === "entrar") await entrar(email, senha);
      else await registrar(email, senha, nome || undefined);
    } catch (e) {
      setErro((e as Error).message);
    }
  };

  const criarAlerta = async (evento: React.FormEvent) => {
    evento.preventDefault();
    setErro(null);
    try {
      const novo = await api.criarAlerta(nomeAlerta || "Meu alerta", {
        uf: ["AL", "SE", "PE"],
        desconto_minimo: 20,
      });
      setAlertas((atual) => [...atual, novo]);
      setNomeAlerta("");
    } catch (e) {
      setErro((e as Error).message);
    }
  };

  if (!usuario) {
    return (
      <section className="pagina pagina--estreita">
        <h1>{modo === "entrar" ? "Entrar" : "Criar conta"}</h1>
        <p className="pagina__ajuda">
          A conta serve para salvar filtros, receber alertas por e-mail e guardar
          favoritos. Navegar e consultar lotes não exige cadastro.
        </p>

        <form className="formulario" onSubmit={enviar}>
          {modo === "registrar" && (
            <label className="campo">
              <span>Nome (opcional)</span>
              <input value={nome} onChange={(e) => setNome(e.target.value)} />
            </label>
          )}
          <label className="campo">
            <span>E-mail</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </label>
          <label className="campo">
            <span>Senha</span>
            <input
              type="password"
              required
              minLength={8}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete={modo === "entrar" ? "current-password" : "new-password"}
            />
            {modo === "registrar" && (
              <small className="campo__ajuda">Pelo menos 8 caracteres.</small>
            )}
          </label>
          {erro && <p className="erro">{erro}</p>}
          <button type="submit" className="botao botao--primario">
            {modo === "entrar" ? "Entrar" : "Criar conta"}
          </button>
          <button
            type="button"
            className="botao botao--texto"
            onClick={() => {
              setModo(modo === "entrar" ? "registrar" : "entrar");
              setErro(null);
            }}
          >
            {modo === "entrar" ? "Não tenho conta" : "Já tenho conta"}
          </button>
        </form>
      </section>
    );
  }

  return (
    <section className="pagina">
      <header className="pagina__topo">
        <div>
          <h1>Olá, {usuario.nome ?? usuario.email}</h1>
          <p className="pagina__ajuda">Seus alertas e favoritos.</p>
        </div>
        <button type="button" className="botao botao--secundario" onClick={sair}>
          Sair
        </button>
      </header>

      <section className="bloco bloco--largo">
        <h2>Alertas por e-mail</h2>
        <p className="bloco__ajuda">
          Cada alerta é um filtro salvo. Quando um lote novo passa a casar com ele,
          você recebe um e-mail — e o mesmo lote nunca é avisado duas vezes.
        </p>
        <form className="formulario formulario--linha" onSubmit={criarAlerta}>
          <label className="campo">
            <span className="sr-apenas">Nome do alerta</span>
            <input
              placeholder="Ex.: imóveis com 20% de desconto em AL, SE e PE"
              value={nomeAlerta}
              onChange={(e) => setNomeAlerta(e.target.value)}
            />
          </label>
          <button type="submit" className="botao botao--primario">
            Criar alerta
          </button>
        </form>
        {erro && <p className="erro">{erro}</p>}

        {alertas.length === 0 ? (
          <p className="bloco__ajuda">Nenhum alerta salvo ainda.</p>
        ) : (
          <ul className="lista-alertas">
            {alertas.map((alerta) => (
              <li key={alerta.id}>
                <div>
                  <strong>{alerta.nome}</strong>
                  <span className="lista-alertas__criterios">
                    {JSON.stringify(alerta.criterios)}
                  </span>
                  <span className="lista-alertas__envio">
                    {alerta.ultimo_envio_em
                      ? `último envio em ${emDataHora(alerta.ultimo_envio_em)}`
                      : "ainda não disparado"}
                  </span>
                </div>
                <button
                  type="button"
                  className="botao botao--texto"
                  onClick={async () => {
                    await api.removerAlerta(alerta.id);
                    setAlertas((atual) => atual.filter((a) => a.id !== alerta.id));
                  }}
                >
                  Remover
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="bloco bloco--largo">
        <h2>Favoritos</h2>
        {listaFavoritos.length === 0 ? (
          <p className="bloco__ajuda">
            Nenhum favorito ainda. Marque a estrela em qualquer{" "}
            <Link to="/">lote da lista</Link>.
          </p>
        ) : (
          <div className="grade">
            {listaFavoritos.map((lote) => (
              <CartaoLote
                key={lote.id}
                lote={lote}
                favoritado={favoritos.has(lote.id)}
                aoFavoritar={(id) => alternarFavorito(id).then(() => undefined)}
              />
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
