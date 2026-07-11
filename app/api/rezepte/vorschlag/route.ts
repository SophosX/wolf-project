// POST   /api/rezepte/vorschlag {text} — Chris sagt dem Rezepte-Radar, wonach
//        er suchen soll ("Suche High-Protein Frühstücksrezepte"). Gemini leitet
//        1-3 YouTube-Suchanfragen ab (Fallback: der Text selbst); sie laufen
//        7 Tage in der täglichen Rezept-Suche mit.
// GET    /api/rezepte/vorschlag — bisherige Rezept-Vorschläge.
// DELETE /api/rezepte/vorschlag {zeit} — Vorschlag entfernen, Suche stoppt sofort.

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { creatorBeschreibung } from "@/lib/profiltext";
import { rufeGeminiJson } from "@/lib/gemini";
import {
  holeRezeptVorschlaege,
  loescheRezeptVorschlag,
  speichereRezeptVorschlag,
  type RezeptVorschlag,
} from "@/lib/vorschlaege";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function GET() {
  try {
    const nutzer = await aktuellerNutzer();
    return NextResponse.json({ vorschlaege: await holeRezeptVorschlaege(nutzer.userId) });
  } catch (e) {
    console.error("[api/rezepte/vorschlag GET]", e);
    return NextResponse.json({ vorschlaege: [] });
  }
}

export async function POST(req: NextRequest) {
  try {
    const { text } = (await req.json()) || {};
    const eingabe = String(text || "").trim();
    if (eingabe.length < 5) {
      return NextResponse.json(
        { fehler: "Bitte kurz beschreiben, welche Rezepte der Radar suchen soll." },
        { status: 400 }
      );
    }

    // Gemini formt Suchanfragen; wenn das schiefgeht, suchen wir mit dem Text selbst
    const nutzerFruh = await aktuellerNutzer();
    const creator = await creatorBeschreibung(nutzerFruh.userId);
    let queries: string[] = [];
    try {
      const ableitung = await rufeGeminiJson<{ queries: string[] }>(
        [
          creator + " sagt seinem Rezepte-Radar, welche Rezepte",
          "er auf YouTube suchen soll. Leite 1-3 kurze deutsche YouTube-Suchanfragen ab,",
          "so wie echte Nutzer suchen (z. B. 'high protein frühstück rezept').",
          "",
          "WUNSCH: »" + eingabe.slice(0, 300) + "«",
        ].join("\n"),
        {
          type: "OBJECT",
          properties: { queries: { type: "ARRAY", items: { type: "STRING" } } },
          required: ["queries"],
        },
        0.2
      );
      queries = (ableitung.queries || []).map((q) => q.trim()).filter((q) => q.length > 3).slice(0, 3);
    } catch (e) {
      console.error("[api/rezepte/vorschlag] Gemini-Ableitung fehlgeschlagen, nutze Rohtext:", e);
    }
    if (queries.length === 0) queries = [eingabe.slice(0, 80)];

    const vorschlag: RezeptVorschlag = {
      text: eingabe,
      zeit: new Date().toISOString(),
      queries,
    };
    await speichereRezeptVorschlag(nutzerFruh.userId, vorschlag);
    return NextResponse.json({ ok: true, vorschlag });
  } catch (e) {
    console.error("[api/rezepte/vorschlag POST]", e);
    return NextResponse.json(
      { fehler: "Vorschlag konnte nicht gespeichert werden" },
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
    const geloescht = await loescheRezeptVorschlag(nutzer.userId, String(zeit));
    if (!geloescht) {
      return NextResponse.json({ fehler: "Vorschlag nicht gefunden" }, { status: 404 });
    }
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/rezepte/vorschlag DELETE]", e);
    return NextResponse.json(
      { fehler: "Vorschlag konnte nicht entfernt werden" },
      { status: 500 }
    );
  }
}
