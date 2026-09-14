import { NavLink, Route, Routes } from "react-router-dom";
import { AlternadorTema } from "./componentes/AlternadorTema";
import { ProvedorSessao, useSessao } from "./sessao";
import { Painel } from "./paginas/Painel";
import { DetalheLote } from "./paginas/DetalheLote";
import { Calendario } from "./paginas/Calendario";
import { Diarios } from "./paginas/Diarios";
import { PaginaMapa } from "./paginas/PaginaMapa";
import { Comparar } from "./paginas/Comparar";
import { Onboarding } from "./paginas/Onboarding";
import { Fontes } from "./paginas/Fontes";
import { Conta } from "./paginas/Conta";
import { REGIAO_POR_EXTENSO, REGIAO_SIGLAS } from "./ufs";

const LINKS = [
  { para: "/", rotulo: "Lotes", fim: true },
  { para: "/calendario", rotulo: "Calendário" },
  { para: "/diarios", rotulo: "Diários" },
  { para: "/mapa", rotulo: "Mapa" },
  { para: "/comparar", rotulo: "Comparar" },
  { para: "/como-funciona", rotulo: "Como funciona" },
  { para: "/fontes", rotulo: "Fontes" },
];

function Cabecalho() {
  const { usuario } = useSessao();
  return (
    <header className="topo">
      <div className="topo__interno">
        <NavLink to="/" className="marca">
          <span className="marca__icone" aria-hidden="true">
            🔨
          </span>
          <span className="marca__texto">
            Radar<strong>Leilão</strong>
          </span>
          <span className="marca__regiao">{REGIAO_SIGLAS}</span>
        </NavLink>

        <nav className="navegacao" aria-label="Seções">
          {LINKS.map((link) => (
            <NavLink
              key={link.para}
              to={link.para}
              end={link.fim}
              className={({ isActive }) => (isActive ? "esta-ativo" : "")}
            >
              {link.rotulo}
            </NavLink>
          ))}
        </nav>

        <div className="topo__acoes">
          <AlternadorTema />
          <NavLink to="/conta" className="botao botao--primario botao--pequeno">
            {usuario ? (usuario.nome ?? usuario.email.split("@")[0]) : "Entrar"}
          </NavLink>
        </div>
      </div>
    </header>
  );
}

function Rodape() {
  return (
    <footer className="rodape">
      <div className="rodape__interno">
        <p className="rodape__aviso">
          O Radar Leilão organiza e enriquece informação pública de leilões judiciais.
          Ele <strong>não</strong> presta assessoria jurídica nem recomendação de
          investimento. Informações extraídas automaticamente do edital oficial:
          consulte o documento original e um advogado antes de participar do leilão.
        </p>
        <p className="rodape__fontes">
          Fontes: Diário de Justiça Eletrônico Nacional (justiças estadual e
          federal), tribunais de justiça e juntas comerciais de {REGIAO_POR_EXTENSO},
          DataJud/CNJ, Tabela FIPE e índice FipeZap. Cada dado exibido traz a sua
          origem e a data da coleta.
        </p>
      </div>
    </footer>
  );
}

export function App() {
  return (
    <ProvedorSessao>
      <a className="pular" href="#conteudo">
        Pular para o conteúdo
      </a>
      <Cabecalho />
      <main id="conteudo" className="conteudo">
        <Routes>
          <Route path="/" element={<Painel />} />
          <Route path="/lote/:id" element={<DetalheLote />} />
          <Route path="/calendario" element={<Calendario />} />
          <Route path="/diarios" element={<Diarios />} />
          <Route path="/mapa" element={<PaginaMapa />} />
          <Route path="/comparar" element={<Comparar />} />
          <Route path="/como-funciona" element={<Onboarding />} />
          <Route path="/fontes" element={<Fontes />} />
          <Route path="/conta" element={<Conta />} />
          <Route
            path="*"
            element={
              <div className="vazio">
                <h2>Página não encontrada</h2>
                <NavLink to="/">Voltar para a lista de lotes</NavLink>
              </div>
            }
          />
        </Routes>
      </main>
      <Rodape />
    </ProvedorSessao>
  );
}
