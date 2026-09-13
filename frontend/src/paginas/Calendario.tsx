import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { emDataHora } from "../formatos";
import type { Evento } from "../tipos";

/** Calendário consolidado de praças e prazos (seção 9). */

const ROTULO_TIPO: Record<string, string> = {
  PRACA_PRIMEIRA: "1ª praça",
  PRACA_SEGUNDA: "2ª praça",
  PRACA_UNICA: "Praça única",
  PRAZO_HABILITACAO: "Prazo de habilitação",
  PRAZO_CAUCAO: "Prazo de caução",
  PRAZO_IMPUGNACAO: "Prazo de impugnação",
  VISITACAO: "Visitação",
};

const MESES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

export function Calendario() {
  const [eventos, setEventos] = useState<Evento[]>([]);
  const [uf, setUf] = useState<string[]>([]);
  const [visao, setVisao] = useState<"lista" | "mes">("lista");
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const de = new Date().toISOString();
    api
      .calendario({ de, uf: uf.length ? uf : undefined })
      .then(setEventos)
      .catch((e) => setErro(e.message));
  }, [uf]);

  const porMes = useMemo(() => {
    const mapa = new Map<string, Evento[]>();
    for (const evento of eventos) {
      const data = new Date(evento.data_hora);
      const chave = `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}`;
      (mapa.get(chave) ?? mapa.set(chave, []).get(chave)!).push(evento);
    }
    return [...mapa.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [eventos]);

  const alternarUf = (valor: string) =>
    setUf((atual) =>
      atual.includes(valor) ? atual.filter((x) => x !== valor) : [...atual, valor],
    );

  return (
    <section className="pagina">
      <header className="pagina__topo">
        <div>
          <h1>Calendário de praças</h1>
          <p className="pagina__ajuda">
            Praças e prazos de todos os lotes monitorados. Remarcações ficam
            registradas: o evento atualiza em vez de duplicar na sua agenda.
          </p>
        </div>
        <a
          className="botao botao--primario"
          href={api.urlIcsCalendario({ uf: uf.length ? uf : undefined })}
        >
          Assinar calendário (.ics)
        </a>
      </header>

      <div className="filtros__linha filtros__linha--grupos">
        <fieldset className="grupo">
          <legend>Estado</legend>
          {["AL", "SE", "PE"].map((sigla) => (
            <button
              key={sigla}
              type="button"
              className={`pilula ${uf.includes(sigla) ? "esta-ativa" : ""}`}
              aria-pressed={uf.includes(sigla)}
              onClick={() => alternarUf(sigla)}
            >
              {sigla}
            </button>
          ))}
        </fieldset>
        <fieldset className="grupo">
          <legend>Visualização</legend>
          <button
            type="button"
            className={`pilula ${visao === "lista" ? "esta-ativa" : ""}`}
            onClick={() => setVisao("lista")}
          >
            Lista cronológica
          </button>
          <button
            type="button"
            className={`pilula ${visao === "mes" ? "esta-ativa" : ""}`}
            onClick={() => setVisao("mes")}
          >
            Por mês
          </button>
        </fieldset>
      </div>

      {erro && <p className="erro">{erro}</p>}
      {eventos.length === 0 && !erro && (
        <p className="vazio">Nenhum evento futuro para esses filtros.</p>
      )}

      {visao === "lista" ? (
        <ol className="linha-tempo">
          {eventos.map((evento) => (
            <li key={evento.id} className={`linha-tempo__item tipo--${evento.tipo}`}>
              <time className="linha-tempo__data" dateTime={evento.data_hora}>
                {emDataHora(evento.data_hora)}
              </time>
              <div className="linha-tempo__corpo">
                <span className="linha-tempo__tipo">
                  {ROTULO_TIPO[evento.tipo] ?? evento.tipo}
                  {evento.estimado && (
                    <span className="etiqueta-estimado" title="Data inferida pelo sistema">
                      estimada
                    </span>
                  )}
                  {evento.status === "REMARCADO" && (
                    <span className="etiqueta-remarcado">remarcada</span>
                  )}
                </span>
                <Link to={`/lote/${evento.lote_id}`}>{evento.titulo}</Link>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="meses">
          {porMes.map(([chave, doMes]) => {
            const [ano, mes] = chave.split("-");
            return (
              <section key={chave} className="mes">
                <h2>
                  {MESES[Number(mes) - 1]} de {ano}
                </h2>
                <ul className="mes__eventos">
                  {doMes.map((evento) => (
                    <li key={evento.id}>
                      <span className="mes__dia">
                        {new Date(evento.data_hora).getDate()}
                      </span>
                      <Link to={`/lote/${evento.lote_id}`}>
                        {ROTULO_TIPO[evento.tipo] ?? evento.tipo} — {evento.titulo}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}
