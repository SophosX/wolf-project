// lib/gemini.ts — Gemini-Client für On-Demand-Aufgaben (nur serverseitig!)
// - generiereSkripte: 3 Skript-Varianten im Chris-Ton (Stilguide + Playbook eingebettet)
// - faktencheck: ausführlicher Quellen-Check mit google_search-Grounding
// Direkt über die REST-API (keine SDK-Abhängigkeit), Modell: gemini-2.5-flash

import { ladeWissen } from "./wissen";
import type { Quelle, Skript, Video } from "./typen";

// Zwei Qualitätsstufen (User-Vorgabe: Faktencheck & Skripte auf hochwertigem Modell):
// - QUALITAET für Faktencheck + Skript-Generierung (Standard: gemini-2.5-pro)
// - SCHNELL als Fallback, wenn das Pro-Modell überlastet ist (503/429)
const MODELL_QUALITAET = process.env.RADAR_MODELL_QUALITAET || "gemini-2.5-pro";
const MODELL_SCHNELL = process.env.RADAR_MODELL_SCHNELL || "gemini-2.5-flash";
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
  temperatur = 0.8,
  modell: string = MODELL_QUALITAET
): Promise<GeminiAntwort> {
  const body: Record<string, unknown> = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: temperatur,
      maxOutputTokens: 16384,
      // Gemini 2.5 denkt sonst das ganze Token-Budget weg (MAX_TOKENS ohne Text)
      thinkingConfig: { thinkingBudget: 4096 },
    },
  };
  if (mitSuche) body.tools = [{ google_search: {} }];

  const res = await fetch(API_BASIS + "/" + modell + ":generateContent", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-goog-api-key": apiKey(),
    },
    body: JSON.stringify(body),
    // Pro-Modell + Grounding kann dauern
    signal: AbortSignal.timeout(180_000),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    // Pro-Modell überlastet/gedrosselt → einmalig aufs schnelle Modell ausweichen
    if ((res.status === 429 || res.status === 503) && modell !== MODELL_SCHNELL) {
      return rufeGemini(prompt, mitSuche, temperatur, MODELL_SCHNELL);
    }
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
// Faktencheck v2: mehrstufig — Behauptungen extrahieren, jede einzeln mit
// Websuche prüfen (parallel), konservativ synthetisieren.
// Arbeitsweise nach Chris' Faktenchecker-Briefing: externe Recherche PFLICHT,
// nur klare Fälle werden hart bewertet, Nuancen werden offen benannt,
// lieber eine echte Falschaussage übersehen als eine korrekte flaggen.
// ---------------------------------------------------------------------------

const MAX_BEHAUPTUNGEN = 4;

interface BehauptungsCheck {
  behauptung: string;
  urteil: "klar_falsch" | "stark_irrefuehrend" | "nuanciert" | "korrekt" | "unklar";
  konfidenz: number | null; // 0-100
  korrektur: string;
  begruendung: string;
  rechnung: string;
  belege: string[]; // vom Modell benannte Quellen inkl. „warum relevant" (ohne URL)
  quellen: Quelle[]; // echte Links aus dem Grounding (+ evtl. explizite URLs)
}

/** Strukturierter Gemini-Aufruf (responseSchema; ohne Suche — schließen sich aus). */
async function rufeGeminiJson<T>(
  prompt: string,
  schema: Record<string, unknown>,
  temperatur = 0.1,
  modell: string = MODELL_SCHNELL
): Promise<T> {
  const body = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: temperatur,
      maxOutputTokens: 8192,
      thinkingConfig: { thinkingBudget: 2048 },
      responseMimeType: "application/json",
      responseSchema: schema,
    },
  };
  const res = await fetch(API_BASIS + "/" + modell + ":generateContent", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": apiKey() },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(90_000),
  });
  if (!res.ok) {
    throw new Error("Gemini-API-Fehler (" + res.status + "): " + (await res.text().catch(() => "")).slice(0, 300));
  }
  const daten = await res.json();
  const text: string = (daten?.candidates?.[0]?.content?.parts || [])
    .map((p: { text?: string }) => p.text || "")
    .join("");
  return JSON.parse(text) as T;
}

/** Stufe 1: alle konkreten, überprüfbaren Behauptungen aus dem Video ziehen. */
async function extrahiereBehauptungen(video: Video): Promise<string[]> {
  const kern = video.claim?.aussage?.trim() || "";
  const material = [
    "Titel: " + video.titel,
    video.caption ? "Caption: " + video.caption.slice(0, 1200) : "",
    video.transkript ? "Transkript: " + video.transkript.slice(0, 6000) : "(kein Transkript vorhanden)",
  ].filter(Boolean).join("\n");

  try {
    const daten = await rufeGeminiJson<{ behauptungen: string[] }>(
      [
        "Extrahiere aus diesem Social-Media-Video die konkreten, ÜBERPRÜFBAREN Sachbehauptungen",
        "zu Ernährung/Fitness/Gesundheit (keine Meinungen, keine Werbung, keine Erfahrungsberichte).",
        "Jede Behauptung als eigenständiger, aus sich heraus verständlicher Satz (dekontextualisiert),",
        "möglichst nah am Wortlaut. Maximal " + (MAX_BEHAUPTUNGEN - 1) + " weitere Behauptungen",
        kern ? "ZUSÄTZLICH zu dieser bereits bekannten Kernbehauptung (weder wiederholen noch\nbloße Teilstücke davon erneut aufführen):\n»" + kern + "«" : ".",
        "Nur INHALTLICH EIGENSTÄNDIGE Behauptungen, die im Material wirklich vorkommen.",
        "Wenn es keine weiteren gibt: leere Liste.",
        "",
        "MATERIAL:",
        material,
      ].join("\n"),
      {
        type: "OBJECT",
        properties: {
          behauptungen: { type: "ARRAY", items: { type: "STRING" } },
        },
        required: ["behauptungen"],
      }
    );
    const weitere = (daten.behauptungen || [])
      .map((b) => (b || "").trim())
      .filter((b) => b.length > 10 && b.toLowerCase() !== kern.toLowerCase());
    return [kern, ...weitere].filter(Boolean).slice(0, MAX_BEHAUPTUNGEN);
  } catch (e) {
    console.error("[faktencheck] Behauptungs-Extraktion fehlgeschlagen:", e);
    return kern ? [kern] : [];
  }
}

const CHECK_REGELN = [
  "Du bist ein präziser, wissenschaftlich arbeitender Faktenchecker mit Spezialisierung auf",
  "Ernährung, Fitness und Gesundheit. Prüfe die Behauptung GRÜNDLICH mit der Google-Suche,",
  "bevor du urteilst — verlasse dich NICHT nur auf dein internes Wissen. Suche gezielt nach",
  "seriösen Quellen: EFSA, DGE, BfR, WHO, Cochrane Reviews, Metaanalysen, Positionspapiere",
  "von Fachgesellschaften. Primärquellen schlagen Presseartikel.",
  "",
  "BEWERTUNGSREGELN (streng konservativ):",
  "- klar_falsch: NUR wenn die Behauptung wissenschaftlich eindeutig widerlegt ist.",
  "- stark_irrefuehrend: technisch nicht ganz falsch, aber die vermittelte Botschaft führt",
  "  Zuschauer klar in die Irre (z. B. wahrer Einzelfakt, irreführende Verallgemeinerung).",
  "- nuanciert: Evidenz gemischt oder kontextabhängig ('kann sein, muss aber nicht') — das",
  "  sagst du DIREKT und ehrlich, ohne künstliche Eindeutigkeit.",
  "- korrekt: wissenschaftlich haltbar.",
  "- Lieber eine echte Falschaussage übersehen als eine korrekte oder nuancierte Aussage",
  "  fälschlich als falsch markieren. 'Nicht belegt' ist NICHT 'widerlegt'.",
  "- Hängt die Behauptung von einem aktuellen Ereignis ab (neue Studie, Behörden-Meldung),",
  "  prüfe per Suche, ob das Ereignis real ist und was die Quelle wirklich sagt.",
].join("\n");

/** Stufe 2: eine Behauptung mit Websuche prüfen (Format-Parsing statt Schema — Grounding und Schema schließen sich aus). */
async function pruefeBehauptung(behauptung: string, kontext: string): Promise<BehauptungsCheck> {
  const prompt = [
    CHECK_REGELN,
    "",
    "ZU PRÜFENDE BEHAUPTUNG: »" + behauptung + "«",
    "KONTEXT: " + kontext,
    "",
    "Antworte auf Deutsch EXAKT in diesem Format (Labels genau so, keine Extra-Abschnitte):",
    "URTEIL: klar_falsch | stark_irrefuehrend | nuanciert | korrekt",
    "KONFIDENZ: <Zahl 0-100>",
    "KORREKTUR: <1-3 Sätze, die Chris wörtlich in einem Richtigstellungs-Video sagen könnte;",
    "bei 'korrekt' stattdessen, was daran stimmt>",
    "BEGRUENDUNG: <kompakt, mit konkreten Zahlen/Dosen/Endpunkten aus der Evidenz>",
    "RECHNUNG: <eine nachrechenbare Dreisatz-Zahl fürs Video, oder '-'>",
    "QUELLEN:",
    "- <Name der Quelle, Jahr> — <halber Satz: warum diese Quelle relevant/vertrauenswürdig ist>",
    "(2-4 Quellen, die stärksten zuerst. Nenne Quellen beim NAMEN — z. B. 'EFSA-Neubewertung",
    "Aspartam 2023' oder 'Cochrane Review Süßstoffe 2020'. KEINE URLs schreiben und keinesfalls",
    "URLs erfinden — die Links kommen automatisch aus deiner Suche.)",
  ].join("\n");

  const antwort = await rufeGemini(prompt, true, 0.2);
  return parseBehauptungsCheck(behauptung, antwort.text, antwort.quellen);
}

/** Parst die Format-Antwort einer Behauptungs-Prüfung. Exportiert für Tests. */
export function parseBehauptungsCheck(
  behauptung: string,
  text: string,
  groundingQuellen: Quelle[]
): BehauptungsCheck {
  const abschnitt = (label: string): string => {
    const m = text.match(
      new RegExp("^\\s*\\**" + label + "\\**\\s*:\\s*([\\s\\S]*?)(?=^\\s*\\**(?:URTEIL|KONFIDENZ|KORREKTUR|BEGRUENDUNG|RECHNUNG|QUELLEN)\\**\\s*:|$)", "mi")
    );
    return (m?.[1] || "").trim();
  };

  // Urteil robust normalisieren: Umlaute (Modell schreibt gern „irreführend"),
  // Leerzeichen statt Unterstrich („klar falsch"), Markdown-Reste
  const urteilRoh = abschnitt("URTEIL")
    .toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .replace(/[^a-z_ ]/g, " ")
    .trim();
  const urteilKandidaten = [
    urteilRoh.split(/\s+/)[0],
    urteilRoh.split(/\s+/).slice(0, 2).join("_"),
  ];
  const gueltig = ["klar_falsch", "stark_irrefuehrend", "nuanciert", "korrekt"] as const;
  const urteil = (gueltig.find((g) => urteilKandidaten.includes(g)) ||
    "unklar") as BehauptungsCheck["urteil"];

  const konfidenzRoh = parseInt(abschnitt("KONFIDENZ").match(/\d+/)?.[0] || "", 10);
  const konfidenz = Number.isFinite(konfidenzRoh) ? Math.max(0, Math.min(100, konfidenzRoh)) : null;

  // Quellen-Block: benannte Belege (ohne URL) und explizite URLs trennen.
  // URLs erfindet das Modell bei Grounding gern — nur nehmen, wenn wirklich genannt;
  // die verlässlichen Links kommen aus den Grounding-Metadaten.
  const belege: string[] = [];
  const quellen: Quelle[] = [];
  for (const zeile of abschnitt("QUELLEN").split("\n")) {
    const inhalt = zeile.replace(/^\s*[-*]\s*/, "").trim();
    if (!inhalt) continue;
    const mitUrl = inhalt.match(/^(.*?)\s*\|?\s*(https?:\/\/\S+)\s*(?:\|\s*(.+))?$/);
    if (mitUrl) {
      if (!quellen.some((q) => q.url === mitUrl[2])) {
        quellen.push({
          titel: (mitUrl[3] ? mitUrl[1] + " — " + mitUrl[3].trim() : mitUrl[1]) || mitUrl[2],
          url: mitUrl[2],
        });
      }
    } else if (belege.length < 4) {
      belege.push(inhalt);
    }
  }
  for (const q of groundingQuellen) {
    if (quellen.length >= 5) break;
    if (!quellen.some((v) => v.url === q.url)) quellen.push(q);
  }

  const rechnungRoh = abschnitt("RECHNUNG");
  return {
    behauptung,
    urteil,
    konfidenz,
    korrektur: abschnitt("KORREKTUR"),
    begruendung: abschnitt("BEGRUENDUNG"),
    rechnung: /^[-–—]?$/.test(rechnungRoh) ? "" : rechnungRoh,
    belege,
    quellen,
  };
}

const URTEIL_ANZEIGE: Record<BehauptungsCheck["urteil"], string> = {
  klar_falsch: "❌ Klar falsch",
  stark_irrefuehrend: "⚠️ Stark irreführend",
  nuanciert: "🟡 Nuanciert — Evidenz gemischt",
  korrekt: "✅ Korrekt",
  unklar: "❓ Nicht abschließend prüfbar",
};

/** Stufe 3: Checks zu einem Bericht synthetisieren (deterministisch, kein LLM). */
export function baueFaktencheckBericht(checks: BehauptungsCheck[]): {
  inhalt_md: string;
  quellen: Quelle[];
} {
  const zaehle = (u: BehauptungsCheck["urteil"]) => checks.filter((c) => c.urteil === u).length;
  const falsch = zaehle("klar_falsch");
  const irref = zaehle("stark_irrefuehrend");

  let gesamt: string;
  if (falsch > 0) {
    gesamt = falsch + " von " + checks.length + " geprüften Behauptungen ist/sind **klar falsch**" +
      (irref ? ", " + irref + " weitere stark irreführend" : "") + " — Reaktion lohnt sich.";
  } else if (irref > 0) {
    gesamt = "Keine Behauptung ist klar falsch, aber " + irref + " von " + checks.length +
      " ist/sind **stark irreführend** — Reaktion möglich, Framing beachten.";
  } else if (zaehle("nuanciert") > 0) {
    gesamt = "Die Evidenz ist hier **gemischt/nuanciert** — keine klare Falschaussage. " +
      "Vorsicht mit einer harten Richtigstellung.";
  } else if (zaehle("korrekt") === checks.length) {
    gesamt = "Alle geprüften Behauptungen sind **wissenschaftlich haltbar** — keine Grundlage für eine Richtigstellung.";
  } else {
    gesamt = "Die Prüfung war **nicht abschließend möglich** — bitte Behauptungen manuell prüfen.";
  }

  const teile: string[] = ["## Gesamturteil", gesamt];

  checks.forEach((c, i) => {
    teile.push("");
    teile.push("## Behauptung " + (i + 1) + ": »" + c.behauptung + "«");
    teile.push("**Urteil:** " + URTEIL_ANZEIGE[c.urteil] +
      (c.konfidenz !== null ? " (Konfidenz " + c.konfidenz + " %)" : ""));
    if (c.korrektur) teile.push("\n**Korrektur fürs Video:** " + c.korrektur);
    if (c.begruendung) teile.push("\n**Was die Evidenz sagt:** " + c.begruendung);
    if (c.belege.length > 0) {
      teile.push("\n**Belege & warum sie zählen:**");
      for (const b of c.belege) teile.push("- " + b);
    }
    if (c.quellen.length > 0) {
      teile.push("\n**Links (aus der Recherche):**");
      for (const q of c.quellen.slice(0, 4)) {
        teile.push("- [" + q.titel + "](" + q.url + ")");
      }
    }
  });

  const rechnungen = checks.map((c) => c.rechnung).filter(Boolean);
  if (rechnungen.length > 0) {
    teile.push("");
    teile.push("## Nachrechenbare Zahl für Chris");
    for (const r of rechnungen.slice(0, 2)) teile.push("- " + r);
  }

  // Quellen global dedupen (für die Link-Liste unter dem Bericht)
  const alle: Quelle[] = [];
  for (const c of checks) {
    for (const q of c.quellen) {
      if (!alle.some((v) => v.url === q.url)) alle.push(q);
    }
  }
  return { inhalt_md: teile.join("\n"), quellen: alle.slice(0, 12) };
}

export async function faktencheck(
  video: Video
): Promise<{ inhalt_md: string; quellen: Quelle[] }> {
  if (!video.claim) {
    throw new Error("Video hat keinen analysierten Claim: " + video.id);
  }
  const kontext = "Video '" + video.titel + "' von " + video.kanal + " (" + video.plattform +
    ", " + video.views.toLocaleString("de-DE") + " Views)" +
    (video.transkript ? "; Transkript liegt vor" : "; kein Transkript — nur Titel/Caption");

  const behauptungen = await extrahiereBehauptungen(video);
  if (behauptungen.length === 0) {
    throw new Error("Keine prüfbare Behauptung gefunden für " + video.id);
  }

  // Alle Behauptungen parallel prüfen; einzelne Ausfälle brechen den Bericht nicht
  const ergebnisse = await Promise.allSettled(
    behauptungen.map((b) => pruefeBehauptung(b, kontext))
  );
  const checks: BehauptungsCheck[] = ergebnisse.map((r, i) =>
    r.status === "fulfilled"
      ? r.value
      : {
          behauptung: behauptungen[i],
          urteil: "unklar" as const,
          konfidenz: null,
          korrektur: "",
          begruendung: "Prüfung fehlgeschlagen (" +
            (r.reason instanceof Error ? r.reason.message : "unbekannter Fehler") +
            ") — bitte erneut versuchen.",
          rechnung: "",
          belege: [],
          quellen: [],
        }
  );
  if (checks.every((c) => c.urteil === "unklar" && !c.quellen.length)) {
    throw new Error("Faktencheck fehlgeschlagen: keine der Prüfungen lieferte ein Ergebnis.");
  }
  return baueFaktencheckBericht(checks);
}
