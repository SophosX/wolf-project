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

export const dynamic = "force-dynamic";

/** Nächster automatischer Lauf laut deploy/crontab (UTC): alle 4 h zur vollen
 *  Stunde (0,4,8,…,20), täglich 05:30 (Instagram + Transkripte) und
 *  täglich 08:30 (Rezepte-Radar, nach dem YouTube-Quota-Reset). */
function naechsterCronLauf(): string {
  const jetzt = new Date();
  const kandidaten: Date[] = [];
  for (let h = 0; h <= 24; h += 4) {
    const t = new Date(jetzt);
    t.setUTCHours(h % 24, 0, 0, 0);
    if (h >= 24) t.setUTCDate(t.getUTCDate() + 1);
    if (t > jetzt) kandidaten.push(t);
  }
  for (const [stunde, minute] of [[5, 30], [8, 30]] as const) {
    const t = new Date(jetzt);
    t.setUTCHours(stunde, minute, 0, 0);
    if (t <= jetzt) t.setUTCDate(t.getUTCDate() + 1);
    kandidaten.push(t);
  }
  kandidaten.sort((a, b) => a.getTime() - b.getTime());
  return kandidaten[0].toISOString();
}

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
      naechsterLauf: naechsterCronLauf(),
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
