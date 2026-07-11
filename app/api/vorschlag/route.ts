// POST   /api/vorschlag {text} — Chris' Freitext-Vorschlag an den Radar.
//        Gemini leitet strukturiert ab (Suchqueries, Kanäle, Themen), die Ableitungen
//        fließen sofort in den Suchalgorithmus: Queries in die YouTube-Rotation (7 Tage),
//        Kanäle auf die Beobachtungsliste, Themen-Boosts ins Ranking.
// GET    /api/vorschlag — bisherige Vorschläge mit Ableitungen.
// DELETE /api/vorschlag {zeit} — Vorschlag entfernen; seine Suchqueries stoppen sofort.

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { rufeGeminiJson } from "@/lib/gemini";
import { setzeFolgen } from "@/lib/personen";
import {
  holeVorschlaege,
  loescheVorschlag,
  speichereVorschlag,
  type Vorschlag,
  type VorschlagAbleitung,
  type VorschlagKanal,
} from "@/lib/vorschlaege";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

// Themen-Slugs aus scraper/mythen_katalog.py (fürs Ableitungs-Schema)
const THEMEN_SLUGS = [
  "suessstoffe", "kaloriendefizit", "stoffwechsel_mythen", "fruehstuecksmythos",
  "kohlenhydrate_abends", "honig_datteln_zucker", "detox_kuren", "protein_niere",
  "protein_allgemein", "abnehm_wundermittel", "crash_diaeten", "fasten_magie",
  "clean_eating_chemie", "light_produkte", "saefte_fluessige_kalorien",
  "vollkorn_dogma", "training_fettabbau_mythen", "abnehmspritze",
  "mahlzeiten_regeln", "uebergewicht_disziplin",
];

export async function GET() {
  try {
    const nutzer = await aktuellerNutzer();
    return NextResponse.json({ vorschlaege: await holeVorschlaege(nutzer.userId) });
  } catch (e) {
    console.error("[api/vorschlag GET]", e);
    return NextResponse.json({ vorschlaege: [] });
  }
}

export async function POST(req: NextRequest) {
  try {
    const nutzer = await aktuellerNutzer();
    const { text } = (await req.json()) || {};
    const eingabe = String(text || "").trim();
    if (eingabe.length < 5) {
      return NextResponse.json({ fehler: "Bitte einen Vorschlag mit etwas Kontext schreiben." }, { status: 400 });
    }

    const ableitung = await rufeGeminiJson<VorschlagAbleitung>(
      [
        "Christian Wolf (Fitness-Creator, stellt Ernährungs-Falschinfos richtig) gibt seinem",
        "Falschinfo-Radar einen Vorschlag. Leite daraus ab, wie der Suchalgorithmus angepasst wird.",
        "",
        "VORSCHLAG: »" + eingabe.slice(0, 600) + "«",
        "",
        "Leite NUR ab, was der Vorschlag wirklich hergibt (leere Listen sind völlig ok):",
        "- queries: 0-3 deutsche YouTube-Suchanfragen im Claim-Stil (so wie die Falschbehauptung",
        "  klingt, z. B. 'Kreatin schädlich Nieren'). Nur wenn der Vorschlag ein Thema/Claim nennt.",
        "- kanaele: 0-2 Kanäle/Personen, die er beobachten will — NUR wenn explizit genannt.",
        "  handle nur angeben, wenn es im Vorschlag steht oder zweifelsfrei bekannt ist, sonst ''.",
        "- themen: 0-3 passende Themen-Slugs aus der Liste (nur bei klarem Themenbezug).",
        "- notiz: EIN Satz auf Deutsch, wie der Radar den Vorschlag verstanden hat und was er nun tut.",
      ].join("\n"),
      {
        type: "OBJECT",
        properties: {
          queries: { type: "ARRAY", items: { type: "STRING" } },
          kanaele: {
            type: "ARRAY",
            items: {
              type: "OBJECT",
              properties: {
                name: { type: "STRING" },
                plattform: { type: "STRING", enum: ["youtube", "tiktok", "instagram", "unbekannt"] },
                handle: { type: "STRING" },
              },
              required: ["name", "plattform", "handle"],
            },
          },
          themen: { type: "ARRAY", items: { type: "STRING", enum: THEMEN_SLUGS } },
          notiz: { type: "STRING" },
        },
        required: ["queries", "kanaele", "themen", "notiz"],
      },
      0.2
    );

    // Härten: Limits einziehen, "unbekannt"-Plattform neutralisieren
    ableitung.queries = (ableitung.queries || []).slice(0, 3);
    ableitung.kanaele = (ableitung.kanaele || []).slice(0, 2).map((k) => ({
      ...k,
      plattform: ((k.plattform as string) === "unbekannt" ? "" : k.plattform) as VorschlagKanal["plattform"],
    }));
    ableitung.themen = (ableitung.themen || []).filter((t) => THEMEN_SLUGS.includes(t)).slice(0, 3);

    const vorschlag: Vorschlag = { text: eingabe, zeit: new Date().toISOString(), ableitung };
    await speichereVorschlag(nutzer.userId, vorschlag);

    // Kanäle auf die Beobachtungsliste (gleicher Weg wie das Personen-Dashboard)
    for (const kanal of ableitung.kanaele) {
      if (!kanal.name) continue;
      try {
        const handles: Record<string, string> = {};
        if (kanal.handle && kanal.plattform) handles[kanal.plattform] = kanal.handle.replace(/^@/, "");
        await setzeFolgen(nutzer.userId, kanal.name, true, handles);
      } catch (e) {
        console.error("[api/vorschlag] Watchlist-Update fehlgeschlagen:", e);
      }
    }

    return NextResponse.json({ ok: true, vorschlag });
  } catch (e) {
    console.error("[api/vorschlag POST]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Vorschlag konnte nicht verarbeitet werden" },
      { status: 500 }
    );
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const { zeit } = (await req.json()) || {};
    if (!zeit) {
      return NextResponse.json({ fehler: "zeit erforderlich" }, { status: 400 });
    }
    const nutzer = await aktuellerNutzer();
    const geloescht = await loescheVorschlag(nutzer.userId, String(zeit));
    if (!geloescht) {
      return NextResponse.json({ fehler: "Vorschlag nicht gefunden" }, { status: 404 });
    }
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/vorschlag DELETE]", e);
    return NextResponse.json(
      { fehler: "Vorschlag konnte nicht entfernt werden" },
      { status: 500 }
    );
  }
}
