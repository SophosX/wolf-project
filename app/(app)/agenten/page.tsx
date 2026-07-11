// /agenten — Live-Ansicht des Radars: Vorschlag senden, Status & Ergebnisse
// in Echtzeit verfolgen (AgentenPanel pollt), Beobachtungsliste.
// Technische Fehler sind bewusst in "Technische Details" eingeklappt.

import VorschlagBox from "@/components/VorschlagBox";
import AgentenPanel from "@/components/AgentenPanel";
import PersonHinzufuegen from "@/components/PersonHinzufuegen";
import { aktuellerNutzer } from "@/lib/auth";
import { holeWatchlist } from "@/lib/watchlist";

export const dynamic = "force-dynamic";

export default async function AgentenSeite() {
  const nutzer = await aktuellerNutzer();
  const watchlist = await holeWatchlist(nutzer.userId);

  return (
    <>
      <VorschlagBox />

      <h1 className="abschnitt-titel" style={{ marginTop: 12 }}>
        Agenten-Status
      </h1>
      <AgentenPanel />

      {/* Watchlist */}
      <h2 className="abschnitt-titel">Beobachtungsliste</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 13.5 }}>
        Personen, deren neue Uploads die Agenten bei jedem Lauf prüfen.
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
          <p className="dim">
            Deine Beobachtungsliste ist leer — füge unten jemanden hinzu oder
            folge Personen im <a href="/personen">Personen-Tab</a>. Dein Radar
            schlägt dir außerdem automatisch Leute vor, deren Videos du öfter
            annimmst.
          </p>
        )}
      </div>
      <PersonHinzufuegen />
    </>
  );
}
