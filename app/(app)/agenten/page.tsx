// /agenten — Status-Panel: letzte Läufe, Funde je Quelle, Fehler ROT sichtbar, Watchlist

import { holeAgentRuns } from "@/lib/daten";
import { formatDatum, relativeZeit } from "@/lib/format";
import { holeWatchlist } from "@/lib/watchlist";
import VorschlagBox from "@/components/VorschlagBox";
import type { AgentRun } from "@/lib/typen";

export const dynamic = "force-dynamic";

const QUELLEN_LABEL: Record<string, string> = {
  youtube_claim_suche: "YouTube · Claim-Suche",
  youtube_watchlist: "YouTube · Watchlist",
  tiktok_watchlist: "TikTok · Watchlist",
  tiktok_discovery: "TikTok · Discovery",
  instagram_watchlist: "Instagram · Watchlist",
};

function quelleLabel(q: string): string {
  return QUELLEN_LABEL[q] || q;
}

export default async function AgentenSeite() {
  let runs: AgentRun[] = [];
  let ladefehler: string | null = null;
  try {
    runs = await holeAgentRuns();
  } catch (e) {
    console.error("[agenten]", e);
    ladefehler = e instanceof Error ? e.message : "agent_runs nicht ladbar";
  }
  const watchlist = holeWatchlist();

  // Letzter Lauf je Quelle (runs sind zeit desc sortiert)
  const jeQuelle = new Map<string, AgentRun>();
  for (const r of runs) {
    if (!jeQuelle.has(r.quelle)) jeQuelle.set(r.quelle, r);
  }
  const fehlerGesamt = runs.reduce((s, r) => s + (r.fehler || []).length, 0);

  return (
    <>
      <VorschlagBox />
      <h1 className="abschnitt-titel" style={{ marginTop: 12 }}>
        Agenten-Status
      </h1>
      <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
        {runs.length > 0 ? (
          <>
            Letzter Lauf {relativeZeit(runs[0].zeit)} · {runs.length} Läufe
            protokolliert ·{" "}
            <span style={{ color: fehlerGesamt > 0 ? "var(--rot)" : "var(--gruen)" }}>
              {fehlerGesamt > 0 ? fehlerGesamt + " Fehler insgesamt" : "keine Fehler"}
            </span>
          </>
        ) : (
          "Noch keine Läufe protokolliert — der Scraper hat noch nicht geschrieben."
        )}
      </p>

      {ladefehler && <div className="hinweis-fehler">⚠ {ladefehler}</div>}

      {/* Funde je Quelle */}
      <div className="agenten-gitter">
        {[...jeQuelle.entries()].map(([quelle, run]) => {
          const fehler = run.fehler || [];
          return (
            <div
              key={quelle}
              className={"agent-kachel" + (fehler.length > 0 ? " fehlerhaft" : "")}
            >
              <h3>{quelleLabel(quelle)}</h3>
              <div className="gross-zahl">{run.geflaggt}</div>
              <div className="dim">
                geflaggt · {run.gefunden} gefunden · {run.neu} neu ·{" "}
                {run.analysiert} analysiert
              </div>
              <div className="dim" style={{ marginTop: 6 }}>
                {relativeZeit(run.zeit)} · {run.dauer_s}s
              </div>
              {fehler.length > 0 && (
                <div className="fehler-zelle" style={{ marginTop: 8, color: "var(--rot)" }}>
                  {fehler.map((f, i) => (
                    <div key={i}>⚠ {f}</div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Letzte Läufe */}
      {runs.length > 0 && (
        <>
          <h2 className="abschnitt-titel">Letzte Läufe</h2>
          <div className="tabellen-scroll">
            <table className="lauf-tabelle">
              <thead>
                <tr>
                  <th>Zeit</th>
                  <th>Quelle</th>
                  <th>Gefunden</th>
                  <th>Neu</th>
                  <th>Analysiert</th>
                  <th>Geflaggt</th>
                  <th>Dauer</th>
                  <th>Fehler</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 30).map((r, i) => (
                  <tr key={i}>
                    <td title={formatDatum(r.zeit)}>{relativeZeit(r.zeit)}</td>
                    <td>{quelleLabel(r.quelle)}</td>
                    <td>{r.gefunden}</td>
                    <td>{r.neu}</td>
                    <td>{r.analysiert}</td>
                    <td>{r.geflaggt}</td>
                    <td>{r.dauer_s}s</td>
                    <td className="fehler-zelle">
                      {(r.fehler || []).length === 0
                        ? "—"
                        : (r.fehler || []).map((f, j) => <div key={j}>⚠ {f}</div>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Watchlist */}
      <h2 className="abschnitt-titel">⚠ Beobachtungsliste</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 13.5 }}>
        Personen, deren neue Uploads die Agenten bei jedem Lauf prüfen
        (scraper/watchlist.json).
      </p>
      <div className="watchlist-liste">
        {watchlist.map((e) => (
          <div key={e.name} className="watchlist-eintrag">
            <b>{e.name}</b>
            <div className="dim">
              {[
                e.youtube ? "YouTube: " + e.youtube : null,
                e.tiktok ? "TikTok: @" + e.tiktok : null,
                e.instagram ? "Instagram: @" + e.instagram : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
            {e.notiz && <div className="dim">{e.notiz}</div>}
          </div>
        ))}
        {watchlist.length === 0 && (
          <div className="hinweis-fehler">
            ⚠ Watchlist konnte nicht geladen werden (scraper/watchlist.json fehlt?)
          </div>
        )}
      </div>
    </>
  );
}
