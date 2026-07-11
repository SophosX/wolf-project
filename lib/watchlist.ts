// Beobachtungsliste — USER-SCOPED.
// Supabase-Modus: watchlist_personen des Nutzers (folgt=true), Zeilen je
// Plattform-Handle zu einem Eintrag pro Name gruppiert.
// Lokal-Modus: scraper/watchlist.json (Christian-Dev, wie bisher).

import fs from "fs";
import path from "path";
import { datenModus, supabaseAdmin } from "./daten";
import type { Video, WatchlistEintrag } from "./typen";

let dateiCache: WatchlistEintrag[] | null = null;

function holeWatchlistDatei(): WatchlistEintrag[] {
  if (dateiCache) return dateiCache;
  try {
    const pfad = path.join(process.cwd(), "scraper", "watchlist.json");
    const roh = JSON.parse(fs.readFileSync(pfad, "utf-8"));
    dateiCache = (roh.eintraege || []) as WatchlistEintrag[];
  } catch (e) {
    console.error("[watchlist] Konnte scraper/watchlist.json nicht lesen:", e);
    dateiCache = [];
  }
  return dateiCache;
}

export async function holeWatchlist(userId: string): Promise<WatchlistEintrag[]> {
  if (datenModus() !== "supabase") return holeWatchlistDatei();
  try {
    const sb = await supabaseAdmin();
    const { data, error } = await sb
      .from("watchlist_personen")
      .select("name, plattform, handle, notizen")
      .eq("user_id", userId)
      .eq("folgt", true);
    if (error) throw new Error(error.message);
    const nachName = new Map<string, WatchlistEintrag>();
    for (const z of data || []) {
      const eintrag =
        nachName.get(z.name) ||
        ({ name: z.name, youtube: null, tiktok: null, instagram: null,
           notiz: z.notizen || undefined } as WatchlistEintrag);
      if (z.plattform === "youtube") eintrag.youtube = z.handle;
      if (z.plattform === "tiktok") eintrag.tiktok = z.handle;
      if (z.plattform === "instagram") eintrag.instagram = z.handle;
      nachName.set(z.name, eintrag);
    }
    return [...nachName.values()];
  } catch (e) {
    console.error("[watchlist] watchlist_personen nicht ladbar:", e);
    return [];
  }
}

/** Prüft gegen eine VORAB geladene Liste (sync — für Karten-Badges in Schleifen). */
export function istAufWatchlistIn(
  eintraege: WatchlistEintrag[],
  video: Pick<Video, "kanal" | "kanal_id">
): boolean {
  const kanalId = (video.kanal_id || "").toLowerCase().replace(/^@/, "");
  const kanalName = (video.kanal || "").toLowerCase();
  return eintraege.some((e) => {
    const kandidaten = [e.youtube, e.tiktok, e.instagram]
      .filter(Boolean)
      .map((h) => String(h).toLowerCase().replace(/^@/, ""));
    if (kandidaten.includes(kanalId)) return true;
    const name = e.name.toLowerCase();
    return kanalName.length > 3 && (kanalName.includes(name) || name.includes(kanalName));
  });
}
