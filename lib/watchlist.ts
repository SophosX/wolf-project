// Liest die Beobachtungsliste aus scraper/watchlist.json (read-only, nur Server).

import fs from "fs";
import path from "path";
import type { Video, WatchlistEintrag } from "./typen";

let cache: WatchlistEintrag[] | null = null;

export function holeWatchlist(): WatchlistEintrag[] {
  if (cache) return cache;
  try {
    const pfad = path.join(process.cwd(), "scraper", "watchlist.json");
    const roh = JSON.parse(fs.readFileSync(pfad, "utf-8"));
    cache = (roh.eintraege || []) as WatchlistEintrag[];
  } catch (e) {
    console.error("[watchlist] Konnte scraper/watchlist.json nicht lesen:", e);
    cache = [];
  }
  return cache;
}

/** Prüft, ob der Absender eines Videos auf der Beobachtungsliste steht. */
export function istAufWatchlist(video: Pick<Video, "kanal" | "kanal_id">): boolean {
  const kanalId = (video.kanal_id || "").toLowerCase().replace(/^@/, "");
  const kanalName = (video.kanal || "").toLowerCase();
  return holeWatchlist().some((e) => {
    const kandidaten = [e.youtube, e.tiktok, e.instagram]
      .filter(Boolean)
      .map((h) => String(h).toLowerCase().replace(/^@/, ""));
    if (kandidaten.includes(kanalId)) return true;
    const name = e.name.toLowerCase();
    return kanalName.length > 3 && (kanalName.includes(name) || name.includes(kanalName));
  });
}
