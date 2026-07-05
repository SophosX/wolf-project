// GET  /api/agenten — Live-Status des Scrapers + letzte Läufe + nächster Cron-Lauf.
//      Wird vom /agenten-Panel gepollt (3 s bei aktivem Lauf, sonst 30 s).
// POST /api/agenten — "Jetzt suchen": legt die Lauf-Anfrage-Flag an; der
//      Scraper-Cron prüft sie minütlich und startet youtube+tiktok.

import { NextResponse } from "next/server";
import {
  fordereLaufAn,
  holeAgentRuns,
  holeAgentStatus,
  laufAngefragt,
} from "@/lib/daten";
import { naechsteVideoSuche, naechsterLauf } from "@/lib/zeitplan";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [status, runs, angefragt] = await Promise.all([
      holeAgentStatus(),
      holeAgentRuns(),
      laufAngefragt(),
    ]);
    return NextResponse.json({
      status,
      angefragt,
      runs: runs.slice(0, 30),
      naechsterLauf: naechsterLauf().toISOString(),
      naechsteVideoSuche: naechsteVideoSuche().toISOString(),
    });
  } catch (e) {
    console.error("[api/agenten GET]", e);
    return NextResponse.json(
      { status: null, angefragt: false, runs: [], naechsterLauf: null },
      { status: 500 }
    );
  }
}

export async function POST() {
  try {
    const [status, angefragt] = await Promise.all([
      holeAgentStatus(),
      laufAngefragt(),
    ]);
    if (status?.aktiv) {
      return NextResponse.json(
        { ok: false, grund: "Der Radar arbeitet bereits." },
        { status: 409 }
      );
    }
    if (angefragt) {
      return NextResponse.json(
        { ok: false, grund: "Ein Lauf ist bereits angefordert." },
        { status: 409 }
      );
    }
    await fordereLaufAn();
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/agenten POST]", e);
    return NextResponse.json(
      { ok: false, grund: "Lauf-Anfrage fehlgeschlagen." },
      { status: 500 }
    );
  }
}
