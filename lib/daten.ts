// lib/daten.ts — EINZIGER Datenzugriff der App (Kontrakt-Schnittstelle).
// DATEN_MODUS=lokal  → liest/schreibt daten/*.json über fs (nur serverseitig)
// DATEN_MODUS=supabase → @supabase/supabase-js mit SERVICE_KEY (nur Server!)
// Default: lokal, wenn SUPABASE_URL fehlt.
//
// Multi-Tenant (Phase 1): Jede nutzerbezogene Funktion nimmt `userId` als
// ersten Parameter. Supabase-Modus: Videos leben als geteilter POOL (Tabelle
// `videos`, mandantenneutral), alles Nutzerspezifische (Status, Score, Verdict,
// Skripte, Feedback) in `video_zuordnung` — beim Lesen werden beide zur
// bisherigen Video-Form zusammengefügt, die UI bleibt unverändert.
// Lokal-Modus: `userId` wird ignoriert (Single-User-Fallback, flache JSONs).

import fs from "fs";
import fsp from "fs/promises";
import path from "path";
import { istAktuell } from "./format";
import type {
  AgentRun,
  AgentStatus,
  Claim,
  Einstellungen,
  Rezept,
  RezeptFilter,
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

/** Felder, die im Supabase-Modus in video_zuordnung leben (per User). */
const ZUORDNUNG_FELDER = new Set([
  "status",
  "score",
  "scores",
  "verdict",
  "thema_slug",
  "begruendung",
  "skripte",
  "feedback",
  "dublette_von",
]);

/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * video_zuordnung-Zeile (+ eingebettetes Pool-Video) → bisherige Video-Form.
 * Der neutrale Pool-Claim (aussage/kategorie) und das per-User-Verdict werden
 * zur gewohnten `claim`-Struktur zusammengefügt — UI-Kontrakt bleibt stabil.
 */
function zuordnungZuVideo(z: any): Video {
  const v = z.video || {};
  const poolClaim = v.claim || null;
  const verdict = z.verdict || null;
  const webcheck = v.webcheck || null;
  const claim: Claim | null =
    poolClaim || verdict
      ? {
          aussage: poolClaim?.aussage || verdict?.aussage || "",
          verdict: verdict?.verdict || poolClaim?.verdict || "strittig",
          konfidenz: verdict?.konfidenz ?? poolClaim?.konfidenz ?? 0,
          begruendung: verdict?.begruendung || poolClaim?.begruendung || "",
          thema: z.thema_slug || poolClaim?.thema || "",
          websuche: webcheck?.websuche ?? poolClaim?.websuche ?? null,
          quellen: webcheck?.quellen || poolClaim?.quellen || [],
        }
      : null;
  return {
    ...v,
    status: z.status,
    score: z.score || 0,
    scores: z.scores || { reichweite: 0, relevanz: 0, tauglichkeit: 0 },
    dublette_von: z.dublette_von || undefined,
    skripte: z.skripte || [],
    feedback: z.feedback || [],
    claim,
  } as Video;
}

/** Supabase-Rezept-Zeile → bisherige Rezept-Form (haken ↔ chris_haken). */
function zeileZuRezept(r: any): Rezept {
  return { ...r, chris_haken: r.chris_haken ?? r.haken ?? "" } as Rezept;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

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

/**
 * Dynamisches Ranking: das Feedback DES NUTZERS (themen_boost aus
 * Annehmen/Ablehnen/Vorschlägen) verschiebt die Reihenfolge SOFORT —
 * ±25 Punkte bei vollem Boost. Der gespeicherte Score bleibt unangetastet
 * (nachvollziehbar), nur die Sortierung reagiert live.
 */
async function feedbackSortierung(userId: string, videos: Video[]): Promise<Video[]> {
  let boost: Record<string, number> = {};
  try {
    boost = (await holeEinstellungen(userId)).gelernt.themen_boost || {};
  } catch {
    boost = {}; // ohne Einstellungen: kein Boost, aber Frische-Sortierung greift weiter
  }
  const dyn = (v: Video) =>
    (v.score || 0) + Math.round(25 * (boost[v.claim?.thema || ""] || 0));
  // Aktuelle Videos IMMER zuerst (Creator brauchen Frisches), innerhalb jeder
  // Frische-Gruppe nach dynamischem Score. Sonst versinken neue, noch view-arme
  // Videos unter alten Reichweiten-Klassikern.
  return [...videos].sort((a, b) => {
    const fa = istAktuell(a.veroeffentlicht) ? 1 : 0;
    const fb = istAktuell(b.veroeffentlicht) ? 1 : 0;
    if (fa !== fb) return fb - fa;
    return dyn(b) - dyn(a);
  });
}

export async function holeVideos(userId: string, filter?: VideoFilter): Promise<Video[]> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    let q = sb
      .from("video_zuordnung")
      .select("*, video:videos(*)")
      .eq("user_id", userId)
      .order("score", { ascending: false });
    if (filter?.status) {
      const stati = Array.isArray(filter.status) ? filter.status : [filter.status];
      q = q.in("status", stati);
    }
    const { data, error } = await q;
    if (error) throw new Error("Supabase-Fehler (video_zuordnung): " + error.message);
    // Plattform/Thema/Zeitraum nach dem Zusammenfügen filtern (kleine Mengen,
    // erspart fragile PostgREST-Filter über die eingebettete Tabelle).
    const videos = filterAnwenden(
      (data || []).map(zuordnungZuVideo),
      { ...filter, status: undefined }
    );
    return feedbackSortierung(userId, videos);
  }
  return feedbackSortierung(userId, filterAnwenden(liesJson<Video[]>("videos.json", []), filter));
}

export async function holeVideo(userId: string, id: string): Promise<Video | null> {
  const videos = await holeVideos(userId);
  return videos.find((v) => v.id === id) || null;
}

export async function aktualisiereVideo(
  userId: string,
  id: string,
  patch: Partial<Video>
): Promise<Video> {
  if (datenModus() === "supabase") {
    const zuordnungPatch: Record<string, unknown> = {};
    for (const [k, wert] of Object.entries(patch)) {
      if (!ZUORDNUNG_FELDER.has(k)) {
        throw new Error("aktualisiereVideo: Feld '" + k + "' ist nicht nutzerbezogen (Pool-Feld?)");
      }
      zuordnungPatch[k] = wert;
    }
    zuordnungPatch.aktualisiert_am = new Date().toISOString();
    const sb = await supabase();
    const { data, error } = await sb
      .from("video_zuordnung")
      .update(zuordnungPatch)
      .eq("user_id", userId)
      .eq("video_id", id)
      .select("*, video:videos(*)")
      .single();
    if (error) throw new Error("Supabase-Fehler (zuordnung update): " + error.message);
    return zuordnungZuVideo(data);
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

/** Läufe des Nutzers + globale Akquise-Läufe (user_id null). */
export async function holeAgentRuns(userId?: string): Promise<AgentRun[]> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    let q = sb
      .from("agent_runs")
      .select("*")
      .order("zeit", { ascending: false })
      .limit(100);
    if (userId) q = q.or("user_id.is.null,user_id.eq." + userId);
    const { data, error } = await q;
    if (error) throw new Error("Supabase-Fehler (agent_runs): " + error.message);
    return (data || []) as AgentRun[];
  }
  const runs = liesJson<AgentRun[]>("agent_runs.json", []);
  return [...runs].sort(
    (a, b) => new Date(b.zeit).getTime() - new Date(a.zeit).getTime()
  );
}

// ---------------------------------------------------------------------------
// Live-Status + "Jetzt suchen"
// Lokal: Status/Flag leben im Volume. Supabase: Auftrags-Queue (Tabelle
// auftraege) — ein Minuten-Worker im Scraper-Container claimt offene Aufträge.
// ---------------------------------------------------------------------------

const LAUF_ANFRAGE_PFAD = path.join(DATEN_DIR, ".lauf_anfrage");
/** Läufe, deren Status älter ist, gelten als verwaist (Absturz) — nicht "aktiv"
 *  zeigen. Kurz gewählt (15 min): ein regulärer youtube+tiktok-Lauf dauert
 *  wenige Minuten; ein "aktiv"-Status, der länger steht, ist abgestürzt und darf
 *  nicht stundenlang "Radar arbeitet" vortäuschen. */
const STATUS_STALE_MS = 15 * 60 * 1000;

/** Live-Status des Scrapers; null wenn noch nie ein Lauf lief (oder Supabase-Modus). */
export async function holeAgentStatus(): Promise<AgentStatus | null> {
  if (datenModus() === "supabase") return null;
  const s = liesJson<AgentStatus | null>("agent_status.json", null);
  if (!s) return null;
  if (s.aktiv && Date.now() - new Date(s.gestartet).getTime() > STATUS_STALE_MS) {
    return { ...s, aktiv: false }; // verwaister Status nach hartem Absturz
  }
  return s;
}

/** Ist ein "Jetzt suchen" angefordert, aber noch nicht gestartet? */
export async function laufAngefragt(userId: string): Promise<boolean> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { count, error } = await sb
      .from("auftraege")
      .select("id", { count: "exact", head: true })
      .eq("user_id", userId)
      .eq("typ", "lauf")
      .in("status", ["offen", "laeuft"]);
    if (error) throw new Error("Supabase-Fehler (auftraege): " + error.message);
    return (count || 0) > 0;
  }
  return fs.existsSync(LAUF_ANFRAGE_PFAD);
}

/** "Jetzt suchen": Lokal Flag-Datei (Minuten-Cron), Supabase Auftrags-Queue. */
export async function fordereLaufAn(userId: string): Promise<void> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { error } = await sb
      .from("auftraege")
      .insert({ user_id: userId, typ: "lauf" });
    if (error) throw new Error("Supabase-Fehler (auftrag insert): " + error.message);
    return;
  }
  await fsp.writeFile(
    LAUF_ANFRAGE_PFAD,
    JSON.stringify({ angefragt: new Date().toISOString() })
  );
}

/** Service-Client für serverseitige Spezialfälle (Onboarding-Routen etc.).
 *  NUR server-seitig verwenden — Service-Key! Wirft im Lokal-Modus. */
export async function supabaseAdmin() {
  if (datenModus() !== "supabase") {
    throw new Error("supabaseAdmin nur im Supabase-Modus verfügbar");
  }
  return supabase();
}

/** profiles-Zeile eines Nutzers (Supabase); null im Lokal-Modus/unbekannt. */
export async function holeProfil(
  userId: string
): Promise<{ onboarding_status: string; plan: string; rolle: string; anzeige_name: string | null } | null> {
  if (datenModus() !== "supabase") return null;
  const sb = await supabase();
  const { data, error } = await sb
    .from("profiles")
    .select("onboarding_status, plan, rolle, anzeige_name")
    .eq("id", userId)
    .maybeSingle();
  if (error) throw new Error("Supabase-Fehler (profiles): " + error.message);
  return data;
}

/** radar_profile des Nutzers (Marke, Trigger-Liste, ...); null wenn nicht vorhanden. */
export async function holeRadarProfil(userId: string): Promise<Record<string, unknown> | null> {
  if (datenModus() !== "supabase") return null;
  const sb = await supabase();
  const { data, error } = await sb
    .from("radar_profile")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw new Error("Supabase-Fehler (radar_profile): " + error.message);
  return data;
}

/** Aktive Themen des Nutzers (Supabase); [] im Lokal-Modus. */
export async function holeThemen(
  userId: string
): Promise<{ slug: string; name: string; kerngewicht: number; keywords: string[]; aktiv: boolean }[]> {
  if (datenModus() !== "supabase") return [];
  const sb = await supabase();
  const { data, error } = await sb
    .from("themen")
    .select("slug, name, kerngewicht, keywords, aktiv")
    .eq("user_id", userId)
    .eq("aktiv", true)
    .order("kerngewicht", { ascending: false });
  if (error) throw new Error("Supabase-Fehler (themen): " + error.message);
  return data || [];
}

const LEERE_EINSTELLUNGEN: Einstellungen = {
  gelernt: { themen_boost: {}, notizen: [] },
  zuletzt_gelernt: null,
};

export async function holeEinstellungen(userId: string): Promise<Einstellungen> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { data, error } = await sb
      .from("einstellungen")
      .select("value")
      .eq("user_id", userId)
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
      rezept_notizen: e.gelernt?.rezept_notizen || [],
    },
    zuletzt_gelernt: e.zuletzt_gelernt || null,
  };
}

/** Generischer Einstellungs-Wert (z.B. key "watchlist") — Supabase: einstellungen-Tabelle. */
export async function holeEinstellungsWert<T>(
  userId: string,
  key: string,
  fallback: T
): Promise<T | null> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { data, error } = await sb
      .from("einstellungen")
      .select("value")
      .eq("user_id", userId)
      .eq("key", key)
      .maybeSingle();
    if (error) throw new Error("Supabase-Fehler (" + key + "): " + error.message);
    return (data?.value as T) ?? fallback;
  }
  return fallback; // Lokal-Modus: Aufrufer nutzt seine Datei-Quelle
}

export async function speichereEinstellungsWert(
  userId: string,
  key: string,
  value: unknown
): Promise<void> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { error } = await sb
      .from("einstellungen")
      .upsert(
        { user_id: userId, key, value, aktualisiert_am: new Date().toISOString() },
        { onConflict: "user_id,key" }
      );
    if (error) throw new Error("Supabase-Fehler (" + key + " upsert): " + error.message);
    return;
  }
  throw new Error("speichereEinstellungsWert ist nur im Supabase-Modus verfügbar");
}

export async function speichereEinstellungen(userId: string, e: Einstellungen): Promise<void> {
  if (datenModus() === "supabase") {
    await speichereEinstellungsWert(userId, "einstellungen", e);
    return;
  }
  await mitLock(() => schreibeJson("einstellungen.json", e));
}

// ---------------------------------------------------------------------------
// Rezepte-Radar (lokal: daten/rezepte.json — geschrieben vom scraper/rezepte_agent.py)
// ---------------------------------------------------------------------------

function rezeptFilterAnwenden(rezepte: Rezept[], filter?: RezeptFilter): Rezept[] {
  let liste = rezepte;
  if (filter?.status) {
    const stati = Array.isArray(filter.status) ? filter.status : [filter.status];
    liste = liste.filter((r) => stati.includes(r.status));
  }
  if (filter?.kategorie) liste = liste.filter((r) => r.kategorie === filter.kategorie);
  return [...liste].sort((a, b) => (b.score || 0) - (a.score || 0));
}

export async function holeRezepte(userId: string, filter?: RezeptFilter): Promise<Rezept[]> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    let q = sb
      .from("rezepte")
      .select("*")
      .eq("user_id", userId)
      .order("score", { ascending: false });
    if (filter?.status) {
      const stati = Array.isArray(filter.status) ? filter.status : [filter.status];
      q = q.in("status", stati);
    }
    if (filter?.kategorie) q = q.eq("kategorie", filter.kategorie);
    const { data, error } = await q;
    if (error) throw new Error("Supabase-Fehler (rezepte): " + error.message);
    return (data || []).map(zeileZuRezept);
  }
  return rezeptFilterAnwenden(liesJson<Rezept[]>("rezepte.json", []), filter);
}

export async function holeRezept(userId: string, id: string): Promise<Rezept | null> {
  const rezepte = await holeRezepte(userId);
  return rezepte.find((r) => r.id === id) || null;
}

export async function aktualisiereRezept(
  userId: string,
  id: string,
  patch: Partial<Rezept>
): Promise<Rezept> {
  if (datenModus() === "supabase") {
    const sb = await supabase();
    const { data, error } = await sb
      .from("rezepte")
      .update(patch)
      .eq("user_id", userId)
      .eq("id", id)
      .select()
      .single();
    if (error) throw new Error("Supabase-Fehler (rezept update): " + error.message);
    return zeileZuRezept(data);
  }
  return mitLock(async () => {
    const rezepte = liesJson<Rezept[]>("rezepte.json", []);
    const idx = rezepte.findIndex((r) => r.id === id);
    if (idx < 0) throw new Error("Rezept nicht gefunden: " + id);
    rezepte[idx] = { ...rezepte[idx], ...patch };
    await schreibeJson("rezepte.json", rezepte);
    return rezepte[idx];
  });
}

/** Anzahl offener Rezept-Vorschläge (für den Kopfleisten-Tab). */
export async function zaehleRezeptVorschlaege(userId: string): Promise<number> {
  const rezepte = await holeRezepte(userId, { status: "vorschlag" });
  return rezepte.length;
}

/** Zähler je Status für die Kopfleisten-Tabs. */
export async function zaehleStatus(userId: string): Promise<Record<Status, number>> {
  const videos = await holeVideos(userId);
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
