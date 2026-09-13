import { useEffect, useState } from "react";
import { api } from "../api";
import { emDataHora } from "../formatos";
import type { FonteSaude } from "../tipos";

/**
 * Painel de saúde das fontes (seção 5).
 *
 * Existe por uma razão operacional concreta: o risco número 1 da seção 15 é um
 * site mudar de layout sem avisar. Uma fonte que passou a devolver zero itens
 * precisa aparecer para alguém, senão o produto envelhece em silêncio.
 */

const CORES_STATUS: Record<string, string> = {
  SUCESSO: "selo--ok",
  PARCIAL: "selo--atencao",
  FALHA: "selo--critico",
  BLOQUEADA: "selo--serio",
  EM_ANDAMENTO: "selo--neutro",
};

export function Fontes() {
  const [fontes, setFontes] = useState<FonteSaude[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.fontes().then(setFontes).catch((e) => setErro(e.message));
  }, []);

  if (erro) return <p className="erro">{erro}</p>;

  const naoValidadas = fontes.filter((f) => !f.validado_ao_vivo).length;
  const porTipo = new Map<string, FonteSaude[]>();
  for (const fonte of fontes) {
    (porTipo.get(fonte.tipo) ?? porTipo.set(fonte.tipo, []).get(fonte.tipo)!).push(fonte);
  }

  return (
    <section className="pagina">
      <header className="pagina__topo">
        <div>
          <h1>Saúde das fontes</h1>
          <p className="pagina__ajuda">
            De onde os dados vêm e quando cada fonte foi coletada com sucesso pela
            última vez.
          </p>
        </div>
      </header>

      {naoValidadas > 0 && (
        <p className="aviso aviso--destaque">
          <strong>{naoValidadas}</strong> de {fontes.length} conectores ainda não foram
          validados contra o site real. Eles ficam desligados na coleta automática até
          que alguém rode <code>radar fontes validar --fonte &lt;slug&gt;</code>, confira
          o que saiu e marque a fonte como validada.
        </p>
      )}

      {[...porTipo.entries()].map(([tipo, doTipo]) => (
        <section key={tipo} className="bloco bloco--largo">
          <h2>{tipo.replace("_", " ").toLowerCase()}</h2>
          <div className="tabela-rolagem">
            <table className="tabela">
              <thead>
                <tr>
                  <th scope="col">Fonte</th>
                  <th scope="col">UF</th>
                  <th scope="col">Validação</th>
                  <th scope="col">Última coleta</th>
                  <th scope="col">Status</th>
                  <th scope="col">Itens</th>
                  <th scope="col">Falhas (7d)</th>
                </tr>
              </thead>
              <tbody>
                {doTipo.map((fonte) => (
                  <tr key={fonte.slug}>
                    <th scope="row">
                      <a href={fonte.url_alvo} target="_blank" rel="noreferrer">
                        {fonte.nome}
                      </a>
                      <span className="tabela__sub">{fonte.descricao}</span>
                    </th>
                    <td>{fonte.uf ?? "—"}</td>
                    <td>
                      {fonte.validado_ao_vivo ? (
                        <span className="selo selo--ok">
                          <span className="selo__icone" aria-hidden="true">
                            ✓
                          </span>
                          <span className="selo__rotulo">validada</span>
                        </span>
                      ) : (
                        <span className="selo selo--atencao">
                          <span className="selo__icone" aria-hidden="true">
                            !
                          </span>
                          <span className="selo__rotulo">não validada</span>
                        </span>
                      )}
                    </td>
                    <td>{emDataHora(fonte.ultima_execucao_em)}</td>
                    <td>
                      {fonte.ultimo_status ? (
                        <span className={`selo ${CORES_STATUS[fonte.ultimo_status] ?? "selo--neutro"}`}>
                          <span className="selo__rotulo">
                            {fonte.ultimo_status.toLowerCase()}
                          </span>
                        </span>
                      ) : (
                        <span className="tabela__vazio">nunca coletada</span>
                      )}
                      {fonte.ultimo_erro && (
                        <span className="tabela__sub">{fonte.ultimo_erro}</span>
                      )}
                    </td>
                    <td className="mono">{fonte.itens_ultima_coleta ?? "—"}</td>
                    <td className="mono">{fonte.falhas_7d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </section>
  );
}
