// GET  /api/rezepte?status=&kategorie= → {rezepte:[...]} (score desc)
// POST /api/rezepte {rezept_id, aktion, kommentar?}
//   → aktualisiert status + feedback in daten/rezepte.json;
//     Kommentare fließen als Liste in einstellungen.gelernt.rezept_notizen
//     (Muster: /api/feedback + lib/lernen.ts)

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import {
  aktualisiereRezept,
  holeEinstellungen,
  holeRezept,
  holeRezepte,
  speichereEinstellungen,
} from "@/lib/daten";
import type { Rezept, RezeptStatus } from "@/lib/typen";

export const dynamic = "force-dynamic";

const MAX_REZEPT_NOTIZEN = 20;

// aktion → neuer Status ("kommentar" ändert den Status nicht)
const STATUS_MAP: Record<string, RezeptStatus | null> = {
  gemerkt: "gemerkt",
  verworfen: "verworfen",
  vorschlag: "vorschlag", // rückgängig machen
  kommentar: null,
};

export async function GET(req: NextRequest) {
  try {
    const p = req.nextUrl.searchParams;
    const status = (p.get("status") || undefined) as RezeptStatus | undefined;
    const kategorie = p.get("kategorie") || undefined;
    const nutzer = await aktuellerNutzer();
    const rezepte = await holeRezepte(nutzer.userId, { status, kategorie });
    return NextResponse.json({ rezepte });
  } catch (e) {
    console.error("[api/rezepte GET]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}

/** Kommentar in einstellungen.gelernt.rezept_notizen anhängen (simple Liste). */
async function merkeRezeptNotiz(userId: string, rezept: Rezept, aktion: string, kommentar: string) {
  const einstellungen = await holeEinstellungen(userId);
  const notiz =
    "[" + aktion + "] „" + rezept.titel.slice(0, 60) + "“: „" + kommentar + "“";
  einstellungen.gelernt.rezept_notizen = [
    notiz,
    ...(einstellungen.gelernt.rezept_notizen || []),
  ].slice(0, MAX_REZEPT_NOTIZEN);
  einstellungen.zuletzt_gelernt = new Date().toISOString();
  await speichereEinstellungen(userId, einstellungen);
}

export async function POST(req: NextRequest) {
  try {
    const nutzer = await aktuellerNutzer();
    const body = await req.json();
    const { rezept_id, aktion, kommentar } = body || {};

    if (!rezept_id || !aktion || !(aktion in STATUS_MAP)) {
      return NextResponse.json(
        { fehler: "rezept_id und gültige aktion (gemerkt|verworfen|vorschlag|kommentar) erforderlich" },
        { status: 400 }
      );
    }

    const rezept = await holeRezept(nutzer.userId, rezept_id);
    if (!rezept) {
      return NextResponse.json(
        { fehler: "Rezept nicht gefunden: " + rezept_id },
        { status: 404 }
      );
    }

    const eintrag = {
      aktion,
      ...(kommentar ? { kommentar: String(kommentar).slice(0, 500) } : {}),
      zeit: new Date().toISOString(),
    };

    const neuerStatus = STATUS_MAP[aktion];
    const patch: Partial<Rezept> = {
      feedback: [...(rezept.feedback || []), eintrag],
    };
    if (neuerStatus) patch.status = neuerStatus;

    const aktualisiert = await aktualisiereRezept(nutzer.userId, rezept_id, patch);

    // Lern-Update (Fehler hier nicht fatal, aber sichtbar loggen)
    if (kommentar) {
      try {
        await merkeRezeptNotiz(nutzer.userId, rezept, aktion, String(kommentar).slice(0, 500));
      } catch (e) {
        console.error("[api/rezepte] Rezept-Notiz fehlgeschlagen:", e);
      }
    }

    return NextResponse.json({ ok: true, rezept: aktualisiert });
  } catch (e) {
    console.error("[api/rezepte POST]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}
