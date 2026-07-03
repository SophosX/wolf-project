// lib/daten.ts — EINZIGER Datenzugriff der App (Kontrakt-Schnittstelle).
// DATEN_MODUS=lokal  → liest/schreibt daten/*.json über fs (nur serverseitig)
// DATEN_MODUS=supabase → @supabase/supabase-js mit SERVICE_KEY (nur Server!)
// Default: lokal, wenn SUPABASE_URL fehlt.

import fs from "fs";
import fsp from "fs/promises";
import path from "path";
import type {
  AgentRun,
  Einstellungen,
  Status,
  Video,
  VideoFilter,
} from "./typen";

const DATEN_DIR = path.join(process.cwd(), "daten");
const BEISPIEL_DIR = path.join(DATEN_DIR, "beispiel");
const LOCK_PFAD = path.join(DATEN_DIR, ".videos.lock");

export function datenModus(): "lokal" | "supabase" {
  const m = (process.env.DATEN_MODUS || "").toLowerCase();
  if (m === "supabase") return "supabase";
  if (m === "lokal") return "lokal";
  return process.env.SUPABASE_URL ? "supabase" : "lokal";
}

// ---------------------------------------------------------------------------
// Lokal-Modus: JSON-Dateien mit einfachem Write-Lock
// ---------------------------------------------------------------------------

/** Liest daten/<name>.json — Fallback auf daten/beispiel/<name>.json, wenn nicht vorhanden. */
function liesJson<T>(name: string, fallback: T): T {
  const echt = path.join(DATEN_DIR, name);
  const beispiel = path.join(BEISPIEL_DIR, name);
  for (const pfad of [echt, beispiel]) {
    try {
      if (fs.existsSync(pfad)) {
        return JSON.parse(fs.readFileSync(pfad, "utf-8")) as T;
      }
    } catch (e) {
      console.error("[daten] Fehler beim Lesen von " + pfad + ":", e);
    }
  }
  return fallback;
}

// In-Prozess-Warteschlange: Schreiboperationen laufen strikt nacheinander.
let schreibKette: Promise<unknown> = Promise.resolve();

/** Einfacher Write-Lock: Lock-Datei exklusiv anlegen, mit Retries (Scraper könnte parallel schreiben). */
async function mitLock<T>(fn: () => Promise<T>): Promise<T> {
  const aufgabe = schreibKette.then(async () => {
    let lockErhalten = false;
    for (let versuch = 0; versuch < 25; versuch++) {
      try {
        const fd = await fsp.open(LOCK_PFAD, "wx");
        await fd.close();
        lockErhalten = true;
        break;
      } catch {
        // Lock existiert — kurz warten. Verwaiste Locks (>10 s) aufräumen.
        try {
          const stat = await fsp.stat(LOCK_PFAD);
          if (Date.now() - stat.mtimeMs > 10_000) await fsp.unlink(LOCK_PFAD);
        } catch {}
        await new Promise((r) => setTimeout(r, 120));
      }
    }
    if (!lockErhalten) {
      throw new Error("Write-Lock auf daten/ nicht erhalten (Scraper aktiv?)");
    }
    try {
      return await fn();
    } finally {
      await fsp.unlink(LOCK_PFAD).catch(() => {});
    }
  });
  schreibKette = aufgabe.catch(() => {});
  return aufgabe as Promise<T>;
}

/** Atomar schreiben: erst Temp-Datei, dann rename. */
async function schreibeJson(name: string, daten: unknown): Promise<void> {
  await fsp.mkdir(DATEN_DIR, { recursive: true });
  const ziel = path.join(DATEN_DIR, name);
  const tmp = ziel + ".tmp";
  await fsp.writeFile(tmp, JSON.stringify(daten, null, 2), "utf-8");
  await fsp.rename(tmp, ziel);
}

/**
 * Stellt sicher, dass daten/videos.json existiert, bevor geschrieben wird.
 * Fehlt sie, werden die Beispiel-Fixtures als Startbestand übernommen
 * (die App darf im Lokal-Modus Feedback persistieren — Kontrakt).
 */
async function materialisiereVideos(): Promise<Video[]> {
  const echt = path.join(DATEN_DIR, "videos.json");
  if (fs.existsSync(echt)) {
    return JSON.parse(await fsp.readFile(echt, "utf-8")) as Video[];
  }
  const beispiel = liesJson<Video[]>("videos.json", []);
  await schreibeJson("videos.json", beispiel);
  return beispiel;
}

// ---------------------------------------------------------------------------
// Supabase-Modus (nur serverseitig, SERVICE_KEY!)
// ---------------------------------------------------------------------------

let supabaseClient: import("@supabase/supabase-js").SupabaseClient | null = null;

async function supabase() {
  if (!supabaseClient) {
    const { createClient } = await import("@supabase/supabase-js");
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
      throw new Error("SUPABASE_URL / SUPABASE_SERVICE_KEY fehlen in der Umgebung");
    }
    supabaseClient = createClient(url, key, { auth: { persistSession: false } });
  }
  return supabaseClient;
}

// ---------------------------------------------------------------------------
// Öffentliche Schnittstelle (Kontrakt)
// ---------------------------------------------------------------------------

function filterAnwenden(videos: Video[], filter?: VideoFilter): Video[] {
  let liste = videos;
  if (filter?.status) {
    const stati = Array.isArray(filter.status) ? filter.status : [filter.status];
    liste = liste.filter((v) => stati.includes(v.status));
  }
  if (filter?.plattform) liste = liste.filter((v) => v.plattform === filter.plattform);
  if (filter?.thema) liste = liste.filter((v) => v.claim?.thema === filter.thema);
  if (filter?.zeitraumTage) {
    const grenze = Date.now() - filter.zeitraumTage * 86_400_000;
    liste = liste.filter((v) => new Date(v.veroeffentlicht).getTime() >= grenze);
  }
  return [...liste].sort((a, b) => (b.score || 0) - (a.score || 0));
}

export async function holeVideos(filter?: VideoFilter): Promise<Video[]> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    let q = sb.from("videos").select("*").order("score", { ascending: false });
    if (filter?.status) {
      const stati = Array.isArray(filter.status) ? filter.status : [filter.status];
      q = q.in("status", stati);
    }
    if (filter?.plattform) q = q.eq("plattform", filter.plattform);
    if (filter?.thema) q = q.eq("claim->>thema", filter.thema);
    if (filter?.zeitraumTage) {
      const grenze = new Date(Date.now() - filter.zeitraumTage * 86_400_000).toISOString();
      q = q.gte("veroeffentlicht", grenze);
    }
    const { data, error } = await q;
    if (error) throw new Error("Supabase-Fehler (videos): " + error.message);
    return (data || []) as Video[];
  }
  return filterAnwenden(liesJson<Video[]>("videos.json", []), filter);
}

export async function holeVideo(id: string): Promise<Video | null> {
  const videos = await holeVideos();
  return videos.find((v) => v.id === id) || null;
}

export async function aktualisiereVideo(
  id: string,
  patch: Partial<Video>
): Promise<Video> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { data, error } = await sb
      .from("videos")
      .update(patch)
      .eq("id", id)
      .select()
      .single();
    if (error) throw new Error("Supabase-Fehler (update): " + error.message);
    return data as Video;
  }
  return mitLock(async () => {
    const videos = await materialisiereVideos();
    const idx = videos.findIndex((v) => v.id === id);
    if (idx < 0) throw new Error("Video nicht gefunden: " + id);
    videos[idx] = { ...videos[idx], ...patch };
    await schreibeJson("videos.json", videos);
    return videos[idx];
  });
}

export async function holeAgentRuns(): Promise<AgentRun[]> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { data, error } = await sb
      .from("agent_runs")
      .select("*")
      .order("zeit", { ascending: false })
      .limit(100);
    if (error) throw new Error("Supabase-Fehler (agent_runs): " + error.message);
    return (data || []) as AgentRun[];
  }
  const runs = liesJson<AgentRun[]>("agent_runs.json", []);
  return [...runs].sort(
    (a, b) => new Date(b.zeit).getTime() - new Date(a.zeit).getTime()
  );
}

const LEERE_EINSTELLUNGEN: Einstellungen = {
  gelernt: { themen_boost: {}, notizen: [] },
  zuletzt_gelernt: null,
};

export async function holeEinstellungen(): Promise<Einstellungen> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { data, error } = await sb
      .from("einstellungen")
      .select("value")
      .eq("key", "einstellungen")
      .maybeSingle();
    if (error) throw new Error("Supabase-Fehler (einstellungen): " + error.message);
    return (data?.value as Einstellungen) || LEERE_EINSTELLUNGEN;
  }
  const e = liesJson<Einstellungen>("einstellungen.json", LEERE_EINSTELLUNGEN);
  // Defensive Defaults, falls Datei unvollständig
  return {
    gelernt: {
      themen_boost: e.gelernt?.themen_boost || {},
      notizen: e.gelernt?.notizen || [],
    },
    zuletzt_gelernt: e.zuletzt_gelernt || null,
  };
}

export async function speichereEinstellungen(e: Einstellungen): Promise<void> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { error } = await sb
      .from("einstellungen")
      .upsert({ key: "einstellungen", value: e });
    if (error) throw new Error("Supabase-Fehler (einstellungen upsert): " + error.message);
    return;
  }
  await mitLock(() => schreibeJson("einstellungen.json", e));
}

/** Zähler je Status für die Kopfleisten-Tabs. */
export async function zaehleStatus(): Promise<Record<Status, number>> {
  const videos = await holeVideos();
  const zaehler: Record<Status, number> = {
    inbox: 0,
    angenommen: 0,
    abgelehnt: 0,
    gespeichert: 0,
    strittig: 0,
    archiv: 0,
  };
  for (const v of videos) {
    if (zaehler[v.status] !== undefined) zaehler[v.status]++;
  }
  return zaehler;
}
