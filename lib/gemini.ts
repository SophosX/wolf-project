// lib/gemini.ts — Gemini-Client für On-Demand-Aufgaben (nur serverseitig!)
// - generiereSkripte: 3 Skript-Varianten im Chris-Ton (Stilguide + Playbook eingebettet)
// - faktencheck: ausführlicher Quellen-Check mit google_search-Grounding
// Direkt über die REST-API (keine SDK-Abhängigkeit), Modell: gemini-2.5-flash

import { ladeWissen } from "./wissen";
import type { Quelle, Skript, Video } from "./typen";

const MODELL = "gemini-2.5-flash";
const API_BASIS = "https://generativelanguage.googleapis.com/v1beta/models";

interface GeminiAntwort {
  text: string;
  quellen: Quelle[]; // aus Grounding-Metadaten (echte URLs)
}

function apiKey(): string {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error("GEMINI_API_KEY fehlt in der Umgebung (.env.local)");
  return key;
}

/** Ein Gemini-Aufruf; bei mitSuche=true mit google_search-Grounding. */
async function rufeGemini(
  prompt: string,
  mitSuche: boolean,
  temperatur = 0.8
): Promise<GeminiAntwort> {
  const body: Record<string, unknown> = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: temperatur,
      maxOutputTokens: 16384,
      // gemini-2.5-flash denkt sonst das ganze Token-Budget weg (MAX_TOKENS ohne Text)
      thinkingConfig: { thinkingBudget: 2048 },
    },
  };
  if (mitSuche) body.tools = [{ google_search: {} }];

  const res = await fetch(API_BASIS + "/" + MODELL + ":generateContent", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-goog-api-key": apiKey(),
    },
    body: JSON.stringify(body),
    // Skripte können dauern
    signal: AbortSignal.timeout(120_000),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      "Gemini-API-Fehler (" + res.status + "): " + detail.slice(0, 400)
    );
  }

  const daten = await res.json();
  const kandidat = daten?.candidates?.[0];
  const text: string = (kandidat?.content?.parts || [])
    .map((p: { text?: string }) => p.text || "")
    .join("");

  if (!text.trim()) {
    throw new Error(
      "Gemini lieferte keine Antwort (finishReason: " +
        (kandidat?.finishReason || "unbekannt") +
        ")"
    );
  }

  // Echte Quellen-URLs aus dem Grounding übernehmen
  const quellen: Quelle[] = [];
  const chunks = kandidat?.groundingMetadata?.groundingChunks || [];
  for (const chunk of chunks) {
    if (chunk?.web?.uri) {
      quellen.push({
        titel: chunk.web.title || chunk.web.uri,
        url: chunk.web.uri,
      });
    }
  }
  // Duplikate raus (Grounding liefert oft dieselbe Domain mehrfach), max. 10
  const gesehen = new Set<string>();
  const eindeutig = quellen
    .filter((q) => {
      const schluessel = q.titel || q.url;
      if (gesehen.has(schluessel)) return false;
      gesehen.add(schluessel);
      return true;
    })
    .slice(0, 10);

  return { text, quellen: eindeutig };
}

// ---------------------------------------------------------------------------
// Skript-Paket: 3 Varianten im Chris-Ton
// ---------------------------------------------------------------------------

function videoKontext(video: Video): string {
  if (!video.claim) {
    throw new Error("Video hat keinen analysierten Claim: " + video.id);
  }
  const teile = [
    "Plattform: " + video.plattform,
    "Titel: " + video.titel,
    "Kanal: " + video.kanal + (video.kanal_follower ? " (" + video.kanal_follower.toLocaleString("de-DE") + " Follower)" : ""),
    "Views: " + video.views.toLocaleString("de-DE"),
    "URL: " + video.url,
    "FALSCHAUSSAGE (wörtlich): »" + video.claim.aussage + "«",
    "Warum falsch: " + video.claim.begruendung,
    "Thema: " + video.claim.thema,
  ];
  if (video.caption) teile.push("Caption: " + video.caption.slice(0, 800));
  if (video.transkript) teile.push("Transkript (Auszug): " + video.transkript.slice(0, 2500));
  return teile.join("\n");
}

function feedbackKontext(video: Video): string {
  const relevant = (video.feedback || []).filter((f) => f.kommentar);
  if (relevant.length === 0) return "";
  return (
    "\n\nFEEDBACK VON CHRIS' TEAM ZU DIESEM VIDEO (unbedingt berücksichtigen):\n" +
    relevant.map((f) => "- [" + f.aktion + "] " + f.kommentar).join("\n")
  );
}

const SKRIPT_TRENNER = /===\s*VARIANTE\s*(\d)\s*\|\s*([a-z_]+)\s*===/gi;

/** Generiert 3 Skript-Varianten (mit Grounding für echte Quellen). */
export async function generiereSkripte(video: Video): Promise<Skript[]> {
  const wissen = ladeWissen();
  const prompt = [
    "Du bist der Skript-Autor von Christian Wolf (deutscher Fitness-Creator, 'Wolf Radar').",
    "Schreibe 3 Reaktions-Skript-Varianten (je 45-90 Sekunden Sprechzeit, Deutsch) auf das unten beschriebene Video mit einer klaren Ernährungs-Falschaussage.",
    "",
    "HALTE DICH STRIKT AN DIESEN STILGUIDE:",
    "<stilguide>",
    wissen.stilguide,
    "</stilguide>",
    "",
    "UND AN DIESES REAKTIONS-PLAYBOOK (Struktur, Hook-Typen, Quellen-Handwerk, Eskalationsregeln):",
    "<playbook>",
    wissen.playbook,
    "</playbook>",
    "",
    "DAS ZIEL-VIDEO:",
    videoKontext(video),
    feedbackKontext(video),
    "",
    "Suche aktuelle, seriöse Belege (Metaanalysen, EFSA, DGE, BfR) für die Widerlegung und baue konkrete Zahlen ein (nachrechenbar, Dreisatz-tauglich).",
    "",
    "AUSGABEFORMAT (exakt einhalten, keine weiteren Überschriften davor/danach):",
    "=== VARIANTE 1 | o_ton_konter ===",
    "(Markdown: **Hook**, **Kontext**, **Widerlegung** mit Zahlen, **Fairness-Anker**, **Was heißt das für dich**, **Schluss/CTA**)",
    "=== VARIANTE 2 | frage_hook ===",
    "(gleiche Struktur, anderer Einstieg)",
    "=== VARIANTE 3 | empoerungs_hook ===",
    "(gleiche Struktur, anderer Einstieg)",
    "=== QUELLEN ===",
    "- Titel der Quelle | https://…  (eine pro Zeile)",
  ].join("\n");

  const antwort = await rufeGemini(prompt, true);
  return parseSkripte(antwort.text, antwort.quellen);
}

/** Zerlegt die Gemini-Antwort in 3 Skripte + Quellen. Exportiert für Tests. */
export function parseSkripte(text: string, groundingQuellen: Quelle[]): Skript[] {
  // Quellen-Block abtrennen
  let quellenBlock = "";
  const qIdx = text.search(/===\s*QUELLEN\s*===/i);
  let skriptText = text;
  if (qIdx >= 0) {
    quellenBlock = text.slice(qIdx).replace(/===\s*QUELLEN\s*===/i, "");
    skriptText = text.slice(0, qIdx);
  }

  // Quellen: Grounding zuerst (echte URLs), dann aus dem Textblock ergänzen
  const quellen: Quelle[] = [...groundingQuellen];
  for (const zeile of quellenBlock.split("\n")) {
    const m = zeile.match(/^\s*[-*]\s*(.+?)\s*\|\s*(https?:\/\/\S+)/);
    if (m && !quellen.some((q) => q.url === m[2])) {
      quellen.push({ titel: m[1], url: m[2] });
    }
  }

  const skripte: Skript[] = [];
  const treffer = [...skriptText.matchAll(SKRIPT_TRENNER)];
  for (let i = 0; i < treffer.length; i++) {
    const start = (treffer[i].index || 0) + treffer[i][0].length;
    const ende = i + 1 < treffer.length ? treffer[i + 1].index : skriptText.length;
    const inhalt = skriptText.slice(start, ende).trim();
    if (!inhalt) continue;
    skripte.push({
      variante: parseInt(treffer[i][1], 10),
      hook_typ: treffer[i][2].toLowerCase(),
      inhalt_md: inhalt,
      quellen,
    });
  }

  if (skripte.length === 0) {
    throw new Error(
      "Skript-Antwort konnte nicht geparst werden (kein '=== VARIANTE n | typ ===' gefunden). Anfang der Antwort: " +
        text.slice(0, 200)
    );
  }
  return skripte;
}

// ---------------------------------------------------------------------------
// Faktencheck: ausführlicher Quellen-Check mit Grounding
// ---------------------------------------------------------------------------

export async function faktencheck(
  video: Video
): Promise<{ inhalt_md: string; quellen: Quelle[] }> {
  if (!video.claim) {
    throw new Error("Video hat keinen analysierten Claim: " + video.id);
  }
  const prompt = [
    "Du bist wissenschaftlicher Faktenchecker für einen deutschen Fitness-Creator.",
    "Prüfe die folgende Aussage aus einem Social-Media-Video gründlich mit aktueller Websuche.",
    "",
    "AUSSAGE (wörtlich): »" + video.claim.aussage + "«",
    "Kontext: Video '" + video.titel + "' von " + video.kanal + " (" + video.plattform + ")",
    video.transkript ? "Transkript-Auszug: " + video.transkript.slice(0, 1500) : "",
    "",
    "Antworte auf Deutsch als Markdown mit GENAU diesen Abschnitten:",
    "## Urteil",
    "(Ein Satz: klar falsch / strittig / korrekt — plus Konfidenz in %)",
    "## Was die Evidenz sagt",
    "(Metaanalysen, Behördenpositionen: EFSA, DGE, BfR, WHO — mit konkreten Zahlen, Dosen, Endpunkten)",
    "## Die stärksten Belege im Detail",
    "(2-4 Belege mit Studientyp, Größe, Ergebnis)",
    "## Was am Claim eventuell dran ist",
    "(Fairness: welcher wahre Kern könnte missverstanden worden sein)",
    "## Nachrechenbare Zahl für Chris",
    "(eine Dreisatz-taugliche Rechnung fürs Video)",
    "",
    "Keine erfundenen Studien. Wenn die Evidenz strittig ist, sage das klar.",
  ].join("\n");

  const antwort = await rufeGemini(prompt, true, 0.3);
  return { inhalt_md: antwort.text.trim(), quellen: antwort.quellen };
}
