// Lern-Karte (Server-Komponente): "Was der Radar aus deinem Feedback gelernt hat"

import { holeEinstellungen } from "@/lib/daten";
import { relativeZeit } from "@/lib/format";
import { themaLabel } from "@/lib/typen";

export default async function LernKarte() {
  let notizen: string[] = [];
  let boosts: [string, number][] = [];
  let zuletzt: string | null = null;
  try {
    const e = await holeEinstellungen();
    notizen = e.gelernt.notizen || [];
    boosts = Object.entries(e.gelernt.themen_boost || {}).filter(
      ([, wert]) => Math.abs(wert) >= 0.05
    );
    zuletzt = e.zuletzt_gelernt;
  } catch (err) {
    console.error("[LernKarte] Einstellungen nicht ladbar:", err);
  }

  return (
    <details className="lernkarte">
      <summary>
        🧠 Was der Radar gelernt hat
        {zuletzt ? " · zuletzt " + relativeZeit(zuletzt) : ""}
      </summary>
      <div className="lernkarte-inhalt">
        {boosts.length > 0 && (
          <div className="boost-chips" style={{ marginBottom: 10 }}>
            {boosts
              .sort((a, b) => b[1] - a[1])
              .map(([slug, wert]) => (
                <span
                  key={slug}
                  className={"boost-chip " + (wert > 0 ? "plus" : "minus")}
                >
                  {themaLabel(slug)} {wert > 0 ? "▲" : "▼"}{" "}
                  {Math.round(Math.abs(wert) * 100)}%
                </span>
              ))}
          </div>
        )}
        {notizen.length > 0 ? (
          <ul>
            {notizen.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        ) : (
          <p style={{ color: "var(--text-dim)" }}>
            Noch nichts gelernt — nimm Videos an oder lehne sie ab, dann passt
            der Radar seine Gewichtung an.
          </p>
        )}
      </div>
    </details>
  );
}
