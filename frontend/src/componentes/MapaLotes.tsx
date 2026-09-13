import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { GeoFeicao } from "../tipos";
import { emReais } from "../formatos";

/**
 * Mapa de oportunidades por município.
 *
 * Decisão explícita: não há camada de tiles. A geocodificação do pipeline é de
 * precisão MUNICIPAL — o ponto é o centroide da cidade, não o endereço do
 * imóvel. Desenhar um pino sobre uma rua sugeriria uma precisão que o dado não
 * tem, e a seção 11 pede o contrário: deixar clara a qualidade da informação.
 *
 * Então os lotes são agrupados por município, o raio cresce com a quantidade e
 * o rótulo é o nome da cidade. Quando a geocodificação por endereço for ligada
 * (radar.ingest.geocode.GeocodificadorNominatim), aí sim vale um basemap.
 */

const CORES_FAIXA: Record<string, string> = {
  ALTA: "var(--faixa-alta)",
  BOA: "var(--faixa-boa)",
  MODERADA: "var(--faixa-moderada)",
  BAIXA: "var(--faixa-baixa)",
};

interface Grupo {
  chave: string;
  cidade: string;
  uf: string;
  lat: number;
  lon: number;
  feicoes: GeoFeicao[];
  melhorFaixa: string;
}

export function MapaLotes({ feicoes }: { feicoes: GeoFeicao[] }) {
  const [selecionado, setSelecionado] = useState<string | null>(null);

  const grupos = useMemo<Grupo[]>(() => {
    const mapa = new Map<string, Grupo>();
    for (const feicao of feicoes) {
      const { cidade, uf } = feicao.properties;
      const chave = `${uf}/${cidade}`;
      const [lon, lat] = feicao.geometry.coordinates;
      const atual = mapa.get(chave);
      if (atual) {
        atual.feicoes.push(feicao);
      } else {
        mapa.set(chave, {
          chave,
          cidade: cidade ?? "—",
          uf: uf ?? "—",
          lat,
          lon,
          feicoes: [feicao],
          melhorFaixa: "BAIXA",
        });
      }
    }
    const ordem = ["BAIXA", "MODERADA", "BOA", "ALTA"];
    for (const grupo of mapa.values()) {
      grupo.melhorFaixa = grupo.feicoes.reduce((melhor, f) => {
        const faixa = f.properties.faixa ?? "BAIXA";
        return ordem.indexOf(faixa) > ordem.indexOf(melhor) ? faixa : melhor;
      }, "BAIXA");
    }
    return [...mapa.values()];
  }, [feicoes]);

  if (grupos.length === 0) {
    return <p className="vazio">Nenhum lote geocodificado para desenhar no mapa.</p>;
  }

  // Projeção equirretangular simples sobre o retângulo que contém os pontos.
  // Na latitude do Nordeste a distorção é irrelevante para posicionar cidades.
  const margem = 0.8;
  const lats = grupos.map((g) => g.lat);
  const lons = grupos.map((g) => g.lon);
  const minLat = Math.min(...lats) - margem;
  const maxLat = Math.max(...lats) + margem;
  const minLon = Math.min(...lons) - margem;
  const maxLon = Math.max(...lons) + margem;
  const largura = 900;
  // Teto de altura: com poucos municípios a proporção geográfica real vira uma
  // faixa vertical quase vazia. Melhor comprimir a escala do que mostrar tela
  // em branco — a leitura aqui é "onde há lotes", não distância exata.
  const altura = Math.min(
    620,
    Math.max(420, (largura * (maxLat - minLat)) / Math.max(maxLon - minLon, 0.001)),
  );

  const x = (lon: number) => ((lon - minLon) / (maxLon - minLon)) * largura;
  const y = (lat: number) => altura - ((lat - minLat) / (maxLat - minLat)) * altura;
  const raio = (n: number) => 10 + Math.min(22, Math.sqrt(n) * 7);

  // Municípios vizinhos (Recife e Olinda ficam a ~10 km) colidem o rótulo nesta
  // escala. Quem colide com um vizinho já posicionado vai com o rótulo ACIMA do
  // círculo, em vez de abaixo — resolve o caso real sem motor de layout.
  const posicoes: { x: number; y: number }[] = [];
  const rotuloAcima = new Set<string>();
  for (const grupo of grupos) {
    const px = x(grupo.lon);
    const py = y(grupo.lat) + raio(grupo.feicoes.length) + 16;
    if (posicoes.some((p) => Math.abs(p.x - px) < 80 && Math.abs(p.y - py) < 16)) {
      rotuloAcima.add(grupo.chave);
    } else {
      posicoes.push({ x: px, y: py });
    }
  }

  const grupoAtivo = grupos.find((g) => g.chave === selecionado) ?? null;

  return (
    <div className="mapa">
      <div className="mapa__tela">
        <svg
          viewBox={`0 0 ${largura} ${altura}`}
          className="mapa__svg"
          role="img"
          aria-label="Lotes por município em Alagoas, Sergipe e Pernambuco"
        >
          <defs>
            <pattern id="grade" width="60" height="60" patternUnits="userSpaceOnUse">
              <path
                d="M 60 0 L 0 0 0 60"
                fill="none"
                stroke="var(--borda)"
                strokeWidth="1"
              />
            </pattern>
          </defs>
          <rect width={largura} height={altura} fill="url(#grade)" />

          {grupos.map((grupo) => {
            const ativo = grupo.chave === selecionado;
            return (
              <g
                key={grupo.chave}
                className={`mapa__ponto ${ativo ? "esta-ativo" : ""}`}
                onClick={() => setSelecionado(ativo ? null : grupo.chave)}
                tabIndex={0}
                role="button"
                aria-label={`${grupo.cidade}, ${grupo.uf}: ${grupo.feicoes.length} lotes`}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelecionado(ativo ? null : grupo.chave);
                  }
                }}
              >
                <circle
                  cx={x(grupo.lon)}
                  cy={y(grupo.lat)}
                  r={raio(grupo.feicoes.length)}
                  fill={CORES_FAIXA[grupo.melhorFaixa]}
                  fillOpacity={ativo ? 0.95 : 0.7}
                  stroke="var(--superficie)"
                  strokeWidth="2"
                />
                <text
                  x={x(grupo.lon)}
                  y={y(grupo.lat) + 4}
                  textAnchor="middle"
                  className="mapa__contagem"
                >
                  {grupo.feicoes.length}
                </text>
                <text
                  x={x(grupo.lon)}
                  y={
                    rotuloAcima.has(grupo.chave)
                      ? y(grupo.lat) - raio(grupo.feicoes.length) - 8
                      : y(grupo.lat) + raio(grupo.feicoes.length) + 16
                  }
                  textAnchor="middle"
                  className="mapa__rotulo"
                >
                  {grupo.cidade}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <aside className="mapa__painel">
        {grupoAtivo ? (
          <>
            <h3>
              {grupoAtivo.cidade}/{grupoAtivo.uf}
            </h3>
            <p className="mapa__precisao">
              Posição no centroide do município — não é o endereço do bem.
            </p>
            <ul className="mapa__lista">
              {grupoAtivo.feicoes.map((f) => (
                <li key={f.properties.id}>
                  <Link to={`/lote/${f.properties.id}`}>{f.properties.titulo}</Link>
                  <span className="mapa__valor">
                    {emReais(f.properties.valor_minimo)}
                    {f.properties.desconto ? ` · ${f.properties.desconto.toFixed(0)}% off` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <>
            <h3>Clique em um município</h3>
            <p className="mapa__precisao">
              O tamanho do círculo é a quantidade de lotes; a cor é a melhor faixa
              de oportunidade do município.
            </p>
            <ul className="mapa__legenda">
              {["ALTA", "BOA", "MODERADA", "BAIXA"].map((faixa) => (
                <li key={faixa}>
                  <span
                    className="mapa__amostra"
                    style={{ background: CORES_FAIXA[faixa] }}
                    aria-hidden="true"
                  />
                  {faixa.charAt(0) + faixa.slice(1).toLowerCase()}
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}
