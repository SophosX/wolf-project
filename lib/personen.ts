// lib/personen.ts — Personen-Dashboard: Reaktions-Historie (Wissensbasis) + Watchlist-Folgen.
// Datenquellen: scraper/wissen/wissensbasis.json (aus Chris' 1.500 Videos extrahiert)
//               scraper/watchlist.json (= "gefolgte" Personen, von den Scrapern überwacht)
// Nur serverseitig verwenden (fs).

import { promises as fs } from "fs";
import path from "path";
import { datenModus, holeEinstellungsWert, speichereEinstellungsWert } from "./daten";

const REPO = process.cwd();
const WISSENSBASIS_PFAD = path.join(REPO, "scraper", "wissen", "wissensbasis.json");
const WATCHLIST_PFAD = path.join(REPO, "scraper", "watchlist.json");

type WatchlistDatei = { [k: string]: unknown; eintraege?: Record<string, unknown>[] };

/** Watchlist laden: Supabase-Modus = DB (Quelle der Wahrheit, Datei nur Seed), sonst Datei. */
async function ladeWatchlist(userId: string): Promise<WatchlistDatei> {
  const datei = await ladeJsonDatei<WatchlistDatei>(WATCHLIST_PFAD, {});
  if (datenModus() === "supabase") {
    const db = await holeEinstellungsWert<WatchlistDatei | null>(userId, "watchlist", null);
    if (db?.eintraege) return db;
    // DB noch leer → mit Datei-Seed initialisieren
    if (datei.eintraege) await speichereEinstellungsWert(userId, "watchlist", datei);
    return datei;
  }
  return datei;
}

async function speichereWatchlist(userId: string, wl: WatchlistDatei): Promise<void> {
  if (datenModus() === "supabase") {
    await speichereEinstellungsWert(userId, "watchlist", wl);
    return;
  }
  const tmp = WATCHLIST_PFAD + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(wl, null, 2), "utf-8");
  await fs.rename(tmp, WATCHLIST_PFAD);
}

export interface Reaktion {
  video_id: string;
  titel: string;
  datum: string;
  views: number;
}

export interface Person {
  name: string;
  typ: string;
  handles: { youtube: string | null; instagram: string | null; tiktok: string | null };
  reaktionen: Reaktion[];
  themen: string[];
  ton: string;
  prioritaet: number;
  folgt: boolean; // steht auf der Watchlist → Scraper überwachen die Person
}

export interface PersonenDaten {
  stand: string | null;
  personen: Person[];
  reaktions_ausloeser: string[];
  statistik: {
    reaktionen_gesamt: number;
    personen_gesamt: number;
    gefolgt: number;
    top_themen: { thema: string; anzahl: number }[];
    views_durch_reaktionen: number;
  };
}

async function ladeJsonDatei<T>(pfad: string, fallback: T): Promise<T> {
  try {
    return JSON.parse(await fs.readFile(pfad, "utf-8")) as T;
  } catch {
    return fallback;
  }
}

function normalisiert(name: string): string {
  // Namens-Kern: Klammer-Zusätze ignorieren ("Coach Aaron (NNG)" == "Coach Aaron (Rohgang)")
  return name.split("(")[0].toLowerCase().replace(/[^a-zäöüß]/g, "");
}

export async function holePersonen(userId: string): Promise<PersonenDaten> {
  const wb = await ladeJsonDatei<Record<string, unknown>>(WISSENSBASIS_PFAD, {});
  const wl = await ladeWatchlist(userId);
  const gefolgt = new Set(
    (wl.eintraege || []).map((e) => normalisiert(String(e.name || "")))
  );

  const roh = (wb.personen as Omit<Person, "folgt">[] | undefined) || [];
  const personen: Person[] = roh
    .map((p) => ({ ...p, folgt: gefolgt.has(normalisiert(p.name)) }))
    .sort((a, b) => b.prioritaet - a.prioritaet || b.reaktionen.length - a.reaktionen.length);

  // Watchlist-Einträge ohne Reaktions-Historie trotzdem zeigen (manuell gefolgt)
  const bekannt = new Set(personen.map((p) => normalisiert(p.name)));
  for (const e of wl.eintraege || []) {
    const eName = String(e.name || "");
    if (eName && !bekannt.has(normalisiert(eName))) {
      const eintrag = e as Record<string, string | null>;
      personen.push({
        name: eName,
        typ: "influencer",
        handles: {
          youtube: eintrag.youtube ?? null,
          instagram: eintrag.instagram ?? null,
          tiktok: eintrag.tiktok ?? null,
        },
        reaktionen: [],
        themen: [],
        ton: "sachlich",
        prioritaet: 3,
        folgt: true,
      });
    }
  }

  const themenZaehler = new Map<string, number>();
  let reaktionenGesamt = 0;
  let viewsGesamt = 0;
  for (const p of personen) {
    reaktionenGesamt += p.reaktionen.length;
    for (const r of p.reaktionen) viewsGesamt += r.views || 0;
    for (const t of p.themen) themenZaehler.set(t, (themenZaehler.get(t) || 0) + 1);
  }

  return {
    stand: (wb.stand as string) || null,
    personen,
    reaktions_ausloeser: (wb.reaktions_ausloeser as string[]) || [],
    statistik: {
      reaktionen_gesamt: reaktionenGesamt,
      personen_gesamt: personen.length,
      gefolgt: personen.filter((p) => p.folgt).length,
      top_themen: [...themenZaehler.entries()]
        .map(([thema, anzahl]) => ({ thema, anzahl }))
        .sort((a, b) => b.anzahl - a.anzahl)
        .slice(0, 6),
      views_durch_reaktionen: viewsGesamt,
    },
  };
}

/** Folgen/Entfolgen = Person auf die Scraper-Watchlist setzen/entfernen. */
export async function setzeFolgen(
  userId: string,
  name: string,
  folgen: boolean,
  handles?: { youtube?: string | null; instagram?: string | null; tiktok?: string | null }
): Promise<void> {
  const wl = await ladeWatchlist(userId);
  const eintraege = (wl.eintraege || []) as Record<string, unknown>[];
  const ziel = normalisiert(name);
  const ohne = eintraege.filter((e) => normalisiert(String(e.name || "")) !== ziel);

  if (folgen) {
    ohne.push({
      name,
      youtube: handles?.youtube ?? null,
      tiktok: handles?.tiktok ?? null,
      instagram: handles?.instagram ?? null,
      notiz: "Über das Personen-Dashboard gefolgt (" + new Date().toISOString().slice(0, 10) + ")",
    });
  }
  wl.eintraege = ohne;
  await speichereWatchlist(userId, wl);
}
