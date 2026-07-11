// lib/personen.ts — Personen-Dashboard: Reaktions-Historie (Wissensbasis) + Watchlist-Folgen.
// Datenquellen: scraper/wissen/wissensbasis.json (aus Chris' 1.500 Videos extrahiert)
//               scraper/watchlist.json (= "gefolgte" Personen, von den Scrapern überwacht)
// Nur serverseitig verwenden (fs).

import { promises as fs } from "fs";
import path from "path";
import { datenModus, holeEinstellungsWert, holeRadarProfil, speichereEinstellungsWert, supabaseAdmin } from "./daten";
import type { TriggerEintrag } from "./typen";

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
  /** Lebende Trigger-Liste mit Stärke/Quelle (Supabase-Modus) — für Badges */
  trigger_details?: TriggerEintrag[];
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

/** Supabase-Modus: Personen aus watchlist_personen + EIGENE Reaktions-Bilanz
 *  (angenommene/gespeicherte Videos) + lebende Trigger-Liste aus radar_profile. */
async function holePersonenSupabase(userId: string): Promise<PersonenDaten> {
  const sb = await supabaseAdmin();
  const [{ data: wlRows }, profil, { data: zuordnungen }] = await Promise.all([
    sb.from("watchlist_personen").select("*").eq("user_id", userId),
    holeRadarProfil(userId),
    sb
      .from("video_zuordnung")
      .select("video_id, status, thema_slug, aktualisiert_am, video:videos(titel, kanal, kanal_id, views, veroeffentlicht)")
      .eq("user_id", userId)
      .in("status", ["angenommen", "gespeichert"]),
  ]);

  // Watchlist-Zeilen (eine je Plattform-Handle) zu Personen zusammenfassen
  const nachName = new Map<string, Person>();
  for (const w of wlRows || []) {
    const schluessel = normalisiert(String(w.name || ""));
    let p = nachName.get(schluessel);
    if (!p) {
      p = {
        name: String(w.name || "?"),
        typ: "influencer",
        handles: { youtube: null, instagram: null, tiktok: null },
        reaktionen: [...((w.reaktionen as Reaktion[]) || [])],
        themen: (w.interessen as string[]) || [],
        ton: "sachlich",
        prioritaet: Number(w.prioritaet) || 3,
        folgt: false,
      };
      nachName.set(schluessel, p);
    }
    const plattform = String(w.plattform || "") as keyof Person["handles"];
    if (plattform in p.handles && w.handle) p.handles[plattform] = String(w.handle);
    if (w.folgt) p.folgt = true;
  }

  // Eigene Reaktions-Bilanz: angenommene Videos den Personen zuordnen —
  // "Womit dich diese Person zuletzt getriggert hat". Unbekannte Kanäle
  // werden als neue (ungefolgte) Personen sichtbar.
  const themenZaehler = new Map<string, number>();
  let reaktionenGesamt = 0;
  let viewsGesamt = 0;
  /* eslint-disable @typescript-eslint/no-explicit-any */
  for (const z of (zuordnungen || []) as any[]) {
    const video = z.video || {};
    const kanal = String(video.kanal || "").trim();
    if (z.thema_slug) themenZaehler.set(z.thema_slug, (themenZaehler.get(z.thema_slug) || 0) + 1);
    reaktionenGesamt++;
    viewsGesamt += Number(video.views) || 0;
    if (!kanal) continue;
    const kanalNorm = normalisiert(kanal);
    let treffer: Person | undefined;
    for (const p of nachName.values()) {
      const kandidaten = [normalisiert(p.name), ...Object.values(p.handles).filter(Boolean).map((h) => normalisiert(String(h)))];
      if (kandidaten.some((k) => k && (kanalNorm.includes(k) || k.includes(kanalNorm)))) {
        treffer = p;
        break;
      }
    }
    if (!treffer) {
      treffer = {
        name: kanal,
        typ: "influencer",
        handles: { youtube: null, instagram: null, tiktok: null },
        reaktionen: [],
        themen: [],
        ton: "sachlich",
        prioritaet: 2,
        folgt: false,
      };
      nachName.set(kanalNorm, treffer);
    }
    if (!treffer.reaktionen.some((r) => r.video_id === z.video_id)) {
      treffer.reaktionen.push({
        video_id: z.video_id,
        titel: String(video.titel || ""),
        datum: String(z.aktualisiert_am || video.veroeffentlicht || ""),
        views: Number(video.views) || 0,
      });
    }
  }
  /* eslint-enable @typescript-eslint/no-explicit-any */

  const personen = [...nachName.values()].sort(
    (a, b) => b.prioritaet - a.prioritaet || b.reaktionen.length - a.reaktionen.length
  );
  const trigger = ((profil?.reaktions_ausloeser as TriggerEintrag[]) || [])
    .filter((t) => t?.trigger)
    .sort((a, b) => (b.staerke || 0) - (a.staerke || 0));

  return {
    stand: null,
    personen,
    reaktions_ausloeser: trigger.map((t) => t.trigger),
    trigger_details: trigger,
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

export async function holePersonen(userId: string): Promise<PersonenDaten> {
  if (datenModus() === "supabase") {
    return holePersonenSupabase(userId);
  }
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
  if (datenModus() === "supabase") {
    const sb = await supabaseAdmin();
    const eintraege = Object.entries(handles || {})
      .filter(([, h]) => h)
      .map(([plattform, handle]) => ({ plattform, handle: String(handle) }));
    if (eintraege.length === 0) eintraege.push({ plattform: "youtube", handle: name });
    for (const e of eintraege) {
      const { error } = await sb.from("watchlist_personen").upsert(
        {
          user_id: userId,
          name,
          plattform: e.plattform,
          handle: e.handle.replace(/^@/, ""),
          folgt: folgen,
          quelle: "manuell",
        },
        { onConflict: "user_id,plattform,handle" }
      );
      if (error) throw new Error("Supabase-Fehler (watchlist_personen): " + error.message);
    }
    // Entfolgen soll auch Namens-Treffer ohne exakten Handle erwischen
    if (!folgen) {
      await sb
        .from("watchlist_personen")
        .update({ folgt: false })
        .eq("user_id", userId)
        .ilike("name", name);
    }
    return;
  }
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
