// POST /api/nachschub — Radar-Lauf auf Knopfdruck starten ("Jetzt neue Videos suchen").
// GET  /api/nachschub — Status: läuft gerade ein Lauf? Ist On-Demand hier möglich?

import { NextResponse } from "next/server";
import { nachschubLaeuft, nachschubMoeglich, starteNachschub } from "@/lib/nachschub";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    moeglich: nachschubMoeglich(),
    laeuft: nachschubLaeuft(),
  });
}

export async function POST() {
  if (!nachschubMoeglich()) {
    return NextResponse.json(
      { fehler: "On-Demand-Lauf nur im Lokal-Modus — in Produktion läuft der Cron alle 4 h." },
      { status: 501 }
    );
  }
  if (nachschubLaeuft()) {
    return NextResponse.json({ ok: true, laeuft: true, hinweis: "Ein Lauf ist bereits aktiv." });
  }
  const gestartet = starteNachschub();
  return NextResponse.json({ ok: gestartet, laeuft: gestartet });
}
