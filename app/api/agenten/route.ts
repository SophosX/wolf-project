// GET /api/agenten → agent_runs + Gesundheits-Zusammenfassung

import { NextResponse } from "next/server";
import { holeAgentRuns } from "@/lib/daten";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const runs = await holeAgentRuns();

    // Gesundheit: letzter Lauf je Quelle + Fehlerzähler
    const quellen: Record<
      string,
      { letzter_lauf: string; gefunden: number; geflaggt: number; fehler: number }
    > = {};
    for (const run of runs) {
      if (!quellen[run.quelle]) {
        quellen[run.quelle] = {
          letzter_lauf: run.zeit,
          gefunden: run.gefunden,
          geflaggt: run.geflaggt,
          fehler: (run.fehler || []).length,
        };
      }
    }

    const gesundheit = {
      letzter_lauf: runs[0]?.zeit || null,
      laeufe_gesamt: runs.length,
      fehler_gesamt: runs.reduce((s, r) => s + (r.fehler || []).length, 0),
      quellen,
    };

    return NextResponse.json({ runs, gesundheit });
  } catch (e) {
    console.error("[api/agenten]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}
