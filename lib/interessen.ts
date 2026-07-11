// lib/interessen.ts — Interessen-Katalog fürs Onboarding (Label-Chips mit
// Starter-Packs). Quelle: scraper/interessen_katalog.json (EINE Quelle für
// App und Scraper; fs-Cache-Muster wie lib/wissen.ts).

import fs from "fs";
import path from "path";

export interface StarterThema {
  slug: string;
  name: string;
  kerngewicht: number;
  keywords: string[];
}
export interface StarterQuery {
  plattform: "youtube" | "tiktok" | "instagram";
  query: string;
}
export interface InteressenBereich {
  slug: string;
  label: string;
  emoji: string;
  themen: StarterThema[];
  queries: StarterQuery[];
  trigger: string[];
}

let cache: InteressenBereich[] | null = null;

export function interessenBereiche(): InteressenBereich[] {
  if (!cache) {
    const pfad = path.join(process.cwd(), "scraper", "interessen_katalog.json");
    try {
      const roh = JSON.parse(fs.readFileSync(pfad, "utf-8"));
      cache = (roh.bereiche || []) as InteressenBereich[];
    } catch (e) {
      console.error("[interessen] Katalog nicht lesbar:", e);
      cache = [];
    }
  }
  return cache;
}

/** Nur gültige Katalog-Slugs behalten. */
export function validiereLabels(labels: unknown): string[] {
  const gueltig = new Set(interessenBereiche().map((b) => b.slug));
  return (Array.isArray(labels) ? labels : [])
    .map((l) => String(l))
    .filter((l) => gueltig.has(l))
    .slice(0, 6);
}

/** Aggregiertes Starter-Pack für die gewählten Bereiche. */
export function starterPack(slugs: string[]): {
  themen: StarterThema[];
  queries: StarterQuery[];
  trigger: string[];
} {
  const bereiche = interessenBereiche().filter((b) => slugs.includes(b.slug));
  const themen: StarterThema[] = [];
  const queries: StarterQuery[] = [];
  const trigger: string[] = [];
  for (const b of bereiche) {
    themen.push(...b.themen);
    queries.push(...b.queries);
    trigger.push(...b.trigger);
  }
  return { themen, queries, trigger };
}
