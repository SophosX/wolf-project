// Gemeinsame Server-Komponente für alle Karten-Seiten:
// Filter lesen → Videos laden → Watchlist-Flag anreichern → Liste rendern

import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeVideos } from "@/lib/daten";
import { istAufWatchlist } from "@/lib/watchlist";
import type { Plattform, Status } from "@/lib/typen";
import type { Seite, VideoAnzeige } from "./VideoKarte";
import FilterLeiste from "./FilterLeiste";
import SuchStatusLeiste from "./SuchStatusLeiste";
import VideoListe from "./VideoListe";

export interface SuchParams {
  plattform?: string;
  thema?: string;
  zeitraum?: string;
}

interface Props {
  status: Status | Status[];
  seite: Seite;
  searchParams: SuchParams;
  leerText: string;
}

export default async function ListenSeite({
  status,
  seite,
  searchParams,
  leerText,
}: Props) {
  const plattform = (searchParams.plattform || "") as Plattform | "";
  const thema = searchParams.thema || "";
  const zeitraum = searchParams.zeitraum || "";
  const zeitraumTage = parseInt(zeitraum, 10);

  let videos: VideoAnzeige[] = [];
  let themen: string[] = [];
  let ladefehler: string | null = null;

  try {
    const nutzer = await aktuellerNutzer();
    // Themen-Auswahl aus allen Videos dieses Status (unabhängig vom Thema-Filter)
    const basis = await holeVideos(nutzer.userId, { status });
    themen = [...new Set(basis.map((v) => v.claim?.thema).filter(Boolean))] as string[];

    const gefiltert = await holeVideos(nutzer.userId, {
      status,
      plattform: plattform || undefined,
      thema: thema || undefined,
      zeitraumTage: isNaN(zeitraumTage) ? undefined : zeitraumTage,
    });
    videos = gefiltert.map((v) => ({ ...v, beobachtung: istAufWatchlist(v) }));
  } catch (e) {
    console.error("[ListenSeite]", e);
    ladefehler = e instanceof Error ? e.message : "Daten konnten nicht geladen werden";
  }

  return (
    <>
      <FilterLeiste
        plattform={plattform}
        thema={thema}
        zeitraum={zeitraum}
        themen={themen}
      />
      {seite === "inbox" && <SuchStatusLeiste />}
      {ladefehler && <div className="hinweis-fehler">⚠ {ladefehler}</div>}
      {seite === "inbox" && videos.length === 0 && !ladefehler && datenModus() === "supabase" && (
        <div className="karte" style={{ padding: 16, marginBottom: 12 }}>
          <div className="abschnitt-titel">Dein Radar arbeitet für dich 🚀</div>
          <p>
            Eine leere Inbox heißt nicht, dass nichts passiert: Dein Radar
            durchsucht <b>automatisch alle paar Stunden</b> YouTube, TikTok und
            Instagram mit deinen Suchanfragen und prüft jeden Kandidaten gegen
            deine Positionen — nur echte Treffer landen hier. Die erste gut
            gefüllte Inbox wächst über die ersten 24–48 Stunden.
          </p>
          <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
            Tipp: Unter <a href="/agenten">Agenten</a> kannst du „Jetzt suchen“
            drücken, unter <a href="/einstellungen">Profil</a> deine Suchanfragen
            schärfen — und jedes Annehmen/Ablehnen macht dein Radar treffsicherer.
          </p>
        </div>
      )}
      <VideoListe videos={videos} seite={seite} leerText={leerText} />
    </>
  );
}
