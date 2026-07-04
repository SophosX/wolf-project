// lib/vorschlaege.ts — Chris' Freitext-Vorschläge an den Radar (Server-only).
//
// Chris schreibt z.B. "Schau dir mal die Kreatin-Videos von Kanal X an" →
// Gemini leitet strukturiert ab: Suchqueries (fließen 7 Tage in die
// YouTube-Claim-Suche ein), Kanäle (landen auf der Beobachtungsliste),
// Themen-Boosts (heben das Ranking). Lokal: daten/vorschlaege.json;
// Supabase: einstellungen-Tabelle (keys "vorschlaege" / "extra_queries").

import fs from "fs";
import path from "path";
import {
  datenModus,
  holeEinstellungen,
  holeEinstellungsWert,
  speichereEinstellungen,
  speichereEinstellungsWert,
} from "./daten";

export interface VorschlagKanal {
  name: string;
  plattform: "youtube" | "tiktok" | "instagram" | "";
  handle: string;
}

export interface VorschlagAbleitung {
  queries: string[];
  kanaele: VorschlagKanal[];
  themen: string[]; // Slugs aus mythen_katalog.THEMEN
  notiz: string; // Ein Satz: wie der Radar den Vorschlag verstanden hat
}

export interface Vorschlag {
  text: string;
  zeit: string; // ISO
  ableitung: VorschlagAbleitung;
}

export interface ExtraQuery {
  query: string;
  bis: string; // ISO — solange läuft die Query in der Rotation mit
}

const DATEI = path.join(process.cwd(), "daten", "vorschlaege.json");
const MAX_VORSCHLAEGE = 25;
const MAX_EXTRA_QUERIES = 6;
const QUERY_LAUFZEIT_TAGE = 7;

/** Rezept-Vorschlag: Chris sagt dem Rezepte-Radar, wonach er suchen soll. */
export interface RezeptVorschlag {
  text: string;
  zeit: string; // ISO
  queries: string[]; // abgeleitete YouTube-Suchanfragen (7 Tage aktiv)
}

interface VorschlaegeDatei {
  vorschlaege: Vorschlag[];
  extra_queries: ExtraQuery[];
  rezept_vorschlaege?: RezeptVorschlag[];
  rezept_extra_queries?: ExtraQuery[];
}

function liesDatei(): VorschlaegeDatei {
  try {
    return JSON.parse(fs.readFileSync(DATEI, "utf-8")) as VorschlaegeDatei;
  } catch {
    return { vorschlaege: [], extra_queries: [] };
  }
}

function schreibeDatei(daten: VorschlaegeDatei): void {
  fs.mkdirSync(path.dirname(DATEI), { recursive: true });
  const tmp = DATEI + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(daten, null, 1), "utf-8");
  fs.renameSync(tmp, DATEI);
}

export async function holeVorschlaege(): Promise<Vorschlag[]> {
  if (datenModus() === "supabase") {
    return (await holeEinstellungsWert<Vorschlag[]>("vorschlaege", [])) || [];
  }
  return liesDatei().vorschlaege;
}

export async function holeExtraQueries(): Promise<ExtraQuery[]> {
  const alle =
    datenModus() === "supabase"
      ? (await holeEinstellungsWert<ExtraQuery[]>("extra_queries", [])) || []
      : liesDatei().extra_queries;
  const jetzt = new Date().toISOString();
  return alle.filter((q) => q.bis > jetzt);
}

/** Vorschlag + Ableitungen persistieren; wendet Themen-Boosts sofort an. */
export async function speichereVorschlag(vorschlag: Vorschlag): Promise<void> {
  const bis = new Date(Date.now() + QUERY_LAUFZEIT_TAGE * 86_400_000).toISOString();
  const neueQueries: ExtraQuery[] = (vorschlag.ableitung.queries || [])
    .map((q) => ({ query: q.trim(), bis }))
    .filter((q) => q.query.length > 3);

  if (datenModus() === "supabase") {
    const vorschlaege = [vorschlag, ...(await holeVorschlaege())].slice(0, MAX_VORSCHLAEGE);
    await speichereEinstellungsWert("vorschlaege", vorschlaege);
    const aktiv = await holeExtraQueries();
    const zusammen = [...neueQueries, ...aktiv]
      .filter((q, i, arr) => arr.findIndex((x) => x.query.toLowerCase() === q.query.toLowerCase()) === i)
      .slice(0, MAX_EXTRA_QUERIES);
    await speichereEinstellungsWert("extra_queries", zusammen);
  } else {
    const daten = liesDatei();
    daten.vorschlaege = [vorschlag, ...daten.vorschlaege].slice(0, MAX_VORSCHLAEGE);
    const jetzt = new Date().toISOString();
    daten.extra_queries = [...neueQueries, ...daten.extra_queries.filter((q) => q.bis > jetzt)]
      .filter((q, i, arr) => arr.findIndex((x) => x.query.toLowerCase() === q.query.toLowerCase()) === i)
      .slice(0, MAX_EXTRA_QUERIES);
    schreibeDatei(daten);
  }

  // Themen-Boosts sofort anwenden (gleicher Mechanismus wie Feedback-Lernen)
  await wendeThemenBoostsAn(vorschlag);
}

/** Vorschlag entfernen — nimmt auch seine abgeleiteten Suchqueries sofort aus
 *  der Rotation. (Abgeleitete Kanäle bleiben auf der Beobachtungsliste — dort
 *  sichtbar und separat entfernbar.) */
export async function loescheVorschlag(zeit: string): Promise<boolean> {
  const alle = await holeVorschlaege();
  const ziel = alle.find((v) => v.zeit === zeit);
  if (!ziel) return false;
  const zielQueries = new Set(
    (ziel.ableitung.queries || []).map((q) => q.trim().toLowerCase())
  );
  const rest = alle.filter((v) => v.zeit !== zeit);

  if (datenModus() === "supabase") {
    await speichereEinstellungsWert("vorschlaege", rest);
    const queries = (
      (await holeEinstellungsWert<ExtraQuery[]>("extra_queries", [])) || []
    ).filter((q) => !zielQueries.has(q.query.trim().toLowerCase()));
    await speichereEinstellungsWert("extra_queries", queries);
  } else {
    const daten = liesDatei();
    daten.vorschlaege = rest;
    daten.extra_queries = daten.extra_queries.filter(
      (q) => !zielQueries.has(q.query.trim().toLowerCase())
    );
    schreibeDatei(daten);
  }
  return true;
}

/** Wie lange die Suchqueries eines Vorschlags noch mitlaufen (ganze Tage; 0 = abgelaufen). */
export function queryRestTage(vorschlag: Vorschlag): number {
  const bis = new Date(vorschlag.zeit).getTime() + QUERY_LAUFZEIT_TAGE * 86_400_000;
  return Math.max(0, Math.ceil((bis - Date.now()) / 86_400_000));
}

// ---------------------------------------------------------------------------
// Rezept-Vorschläge (Rezepte-Radar) — gleicher Mechanismus, eigene Schlüssel
// ---------------------------------------------------------------------------

export async function holeRezeptVorschlaege(): Promise<RezeptVorschlag[]> {
  if (datenModus() === "supabase") {
    return (await holeEinstellungsWert<RezeptVorschlag[]>("rezept_vorschlaege", [])) || [];
  }
  return liesDatei().rezept_vorschlaege || [];
}

export async function speichereRezeptVorschlag(vorschlag: RezeptVorschlag): Promise<void> {
  const bis = new Date(Date.now() + QUERY_LAUFZEIT_TAGE * 86_400_000).toISOString();
  const neueQueries: ExtraQuery[] = (vorschlag.queries || [])
    .map((q) => ({ query: q.trim(), bis }))
    .filter((q) => q.query.length > 3);
  const jetzt = new Date().toISOString();

  if (datenModus() === "supabase") {
    const alle = [vorschlag, ...(await holeRezeptVorschlaege())].slice(0, MAX_VORSCHLAEGE);
    await speichereEinstellungsWert("rezept_vorschlaege", alle);
    const aktiv = (
      (await holeEinstellungsWert<ExtraQuery[]>("rezept_extra_queries", [])) || []
    ).filter((q) => q.bis > jetzt);
    const zusammen = [...neueQueries, ...aktiv]
      .filter((q, i, arr) => arr.findIndex((x) => x.query.toLowerCase() === q.query.toLowerCase()) === i)
      .slice(0, MAX_EXTRA_QUERIES);
    await speichereEinstellungsWert("rezept_extra_queries", zusammen);
  } else {
    const daten = liesDatei();
    daten.rezept_vorschlaege = [vorschlag, ...(daten.rezept_vorschlaege || [])].slice(0, MAX_VORSCHLAEGE);
    daten.rezept_extra_queries = [
      ...neueQueries,
      ...(daten.rezept_extra_queries || []).filter((q) => q.bis > jetzt),
    ]
      .filter((q, i, arr) => arr.findIndex((x) => x.query.toLowerCase() === q.query.toLowerCase()) === i)
      .slice(0, MAX_EXTRA_QUERIES);
    schreibeDatei(daten);
  }
}

export async function loescheRezeptVorschlag(zeit: string): Promise<boolean> {
  const alle = await holeRezeptVorschlaege();
  const ziel = alle.find((v) => v.zeit === zeit);
  if (!ziel) return false;
  const zielQueries = new Set((ziel.queries || []).map((q) => q.trim().toLowerCase()));
  const rest = alle.filter((v) => v.zeit !== zeit);

  if (datenModus() === "supabase") {
    await speichereEinstellungsWert("rezept_vorschlaege", rest);
    const queries = (
      (await holeEinstellungsWert<ExtraQuery[]>("rezept_extra_queries", [])) || []
    ).filter((q) => !zielQueries.has(q.query.trim().toLowerCase()));
    await speichereEinstellungsWert("rezept_extra_queries", queries);
  } else {
    const daten = liesDatei();
    daten.rezept_vorschlaege = rest;
    daten.rezept_extra_queries = (daten.rezept_extra_queries || []).filter(
      (q) => !zielQueries.has(q.query.trim().toLowerCase())
    );
    schreibeDatei(daten);
  }
  return true;
}

/** Rest-Laufzeit der Rezept-Suchqueries (ganze Tage; 0 = abgelaufen). */
export function rezeptQueryRestTage(vorschlag: RezeptVorschlag): number {
  const bis = new Date(vorschlag.zeit).getTime() + QUERY_LAUFZEIT_TAGE * 86_400_000;
  return Math.max(0, Math.ceil((bis - Date.now()) / 86_400_000));
}

async function wendeThemenBoostsAn(vorschlag: Vorschlag): Promise<void> {
  const themen = vorschlag.ableitung.themen || [];
  if (themen.length > 0) {
    const einstellungen = await holeEinstellungen();
    for (const slug of themen) {
      const alt = einstellungen.gelernt.themen_boost[slug] || 0;
      einstellungen.gelernt.themen_boost[slug] = Math.min(1, Math.round((alt + 0.2) * 100) / 100);
    }
    einstellungen.gelernt.notizen = [
      "Vorschlag von Chris: „" + vorschlag.text.slice(0, 80) + "“ → " + vorschlag.ableitung.notiz,
      ...einstellungen.gelernt.notizen,
    ].slice(0, 15);
    einstellungen.zuletzt_gelernt = new Date().toISOString();
    await speichereEinstellungen(einstellungen);
  }
}
