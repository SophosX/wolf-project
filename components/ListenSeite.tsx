// Gemeinsame Server-Komponente für alle Karten-Seiten:
// Filter lesen → Videos laden → Watchlist-Flag anreichern → Liste rendern

import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeVideos } from "@/lib/daten";
import { holeWatchlist, istAufWatchlistIn } from "@/lib/watchlist";
import type { Plattform, Status } from "@/lib/typen";
import type { Seite, VideoAnzeige } from "./VideoKarte";
import FilterLeiste from "./FilterLeiste";
import InboxDiagnose from "./InboxDiagnose";
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
    const watchlist = await holeWatchlist(nutzer.userId);
    videos = gefiltert.map((v) => ({ ...v, beobachtung: istAufWatchlistIn(watchlist, v) }));
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
      {/* Diagnose: bei leerer/duenner Inbox sieht der Nutzer WARUM und was er
          tun kann (breiter suchen / schaerfen / Interessen) — nie ein stummes Leer. */}
      {seite === "inbox" && !ladefehler && datenModus() === "supabase" && videos.length < 3 &&
        !plattform && !thema && !zeitraum && (
        <InboxDiagnose inboxAnzahl={videos.length} />
      )}
      <VideoListe videos={videos} seite={seite} leerText={leerText} />
    </>
  );
}
