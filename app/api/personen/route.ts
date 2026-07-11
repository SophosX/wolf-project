// GET  /api/personen → Reaktions-Historie + Folgen-Status + Statistik
// POST /api/personen {name, folgen: boolean, handles?} → Watchlist aktualisieren

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { holePersonen, setzeFolgen } from "@/lib/personen";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const nutzer = await aktuellerNutzer();
    return NextResponse.json(await holePersonen(nutzer.userId));
  } catch (e) {
    console.error("[api/personen]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const name = String(body.name || "").trim();
    if (!name) {
      return NextResponse.json({ fehler: "name fehlt" }, { status: 400 });
    }
    const nutzer = await aktuellerNutzer();
    await setzeFolgen(nutzer.userId, name, Boolean(body.folgen), body.handles);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/personen]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}
