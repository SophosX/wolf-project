// lib/narrativ.ts — Narrativ-Retrieval (RAG über Chris' eigene Videos), Server-only.
// Liest scraper/wissen/narrativ_index.json (gebaut von scraper/narrativ_index_bauen.py),
// embeddet die Anfrage via Gemini und liefert die passendsten O-Ton-Passagen.
// Fail-safe: bei fehlendem Index oder API-Fehlern kommt "" zurück — Aufrufer laufen weiter.

import fs from "fs";
import path from "path";

interface NarrativChunk {
  text: string;
  quelle: string;
  reaktion: boolean;
  vektor: number[];
}

interface NarrativIndex {
  modell: string;
  dim: number;
  chunks: NarrativChunk[];
}

const INDEX_PFAD = path.join(process.cwd(), "scraper", "wissen", "narrativ_index.json");
const EMBED_MODELL = "gemini-embedding-001";
const MIN_AEHNLICHKEIT = 0.55;
const MAX_PASSAGE_ZEICHEN = 550;

let indexCache: NarrativIndex | null | undefined;

function ladeIndex(): NarrativIndex | null {
  if (indexCache !== undefined) return indexCache;
  try {
    indexCache = JSON.parse(fs.readFileSync(INDEX_PFAD, "utf-8")) as NarrativIndex;
  } catch {
    console.warn("[narrativ] Index nicht ladbar — O-Ton-Retrieval aus.");
    indexCache = null;
  }
  return indexCache;
}

async function embedQuery(text: string, dim: number): Promise<number[]> {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error("GEMINI_API_KEY fehlt");
  const res = await fetch(
    "https://generativelanguage.googleapis.com/v1beta/models/" + EMBED_MODELL + ":embedContent",
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify({
        model: "models/" + EMBED_MODELL,
        content: { parts: [{ text: text.slice(0, 1500) }] },
        taskType: "RETRIEVAL_QUERY",
        outputDimensionality: dim,
      }),
      signal: AbortSignal.timeout(20_000),
    }
  );
  if (!res.ok) throw new Error("Embedding-Fehler " + res.status);
  const daten = await res.json();
  return daten?.embedding?.values || [];
}

function cosinus(a: number[], b: number[]): number {
  let skalar = 0, na = 0, nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    skalar += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  const norm = Math.sqrt(na) * Math.sqrt(nb);
  return norm ? skalar / norm : 0;
}

/** Formatierter Prompt-Block mit Chris' O-Tönen zum Thema — "" wenn nichts passt. */
export async function chrisOTonBlock(text: string, k = 3): Promise<string> {
  const index = ladeIndex();
  if (!index?.chunks?.length || !text) return "";
  let anfrage: number[];
  try {
    anfrage = await embedQuery(text, index.dim || 512);
  } catch (e) {
    console.warn("[narrativ] Query-Embedding fehlgeschlagen:", e);
    return "";
  }
  if (!anfrage.length) return "";

  const bewertet = index.chunks
    .map((c) => ({
      c,
      score: cosinus(anfrage, c.vektor) + (c.reaktion ? 0.03 : 0),
    }))
    .sort((x, y) => y.score - x.score)
    .filter((e) => e.score >= MIN_AEHNLICHKEIT)
    .slice(0, k);

  if (bewertet.length === 0) return "";
  const zeilen = ["SO SPRICHT CHRIS ÜBER DAS THEMA (O-Ton aus seinen Videos):"];
  for (const { c } of bewertet) {
    const marker = c.reaktion ? " [aus einem seiner Richtigstellungs-Videos]" : "";
    zeilen.push("- »" + c.text.slice(0, MAX_PASSAGE_ZEICHEN) + "« (Video: " + c.quelle + marker + ")");
  }
  zeilen.push("(Übernimm Haltung und typische Formulierungen, zitiere dich nicht wörtlich selbst.)");
  return zeilen.join("\n");
}
