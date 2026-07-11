// GET  /api/agenten — Live-Status des Scrapers + letzte Läufe + nächster Cron-Lauf.
//      Wird vom /agenten-Panel gepollt (3 s bei aktivem Lauf, sonst 30 s).
// POST /api/agenten — "Jetzt suchen": legt die Lauf-Anfrage-Flag an; der
//      Scraper-Cron prüft sie minütlich und startet youtube+tiktok.

import { NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import {
  datenModus,
  fordereLaufAn,
  holeAgentRuns,
  holeAgentStatus,
  laufAngefragt,
  supabaseAdmin,
} from "@/lib/daten";
import { holeExtraQueries } from "@/lib/vorschlaege";
import { naechsteVideoSuche, naechsterLauf } from "@/lib/zeitplan";
import type { AgentRun } from "@/lib/typen";

/** Such-Protokolle GETEILTER Akquise-Läufe auf die Queries DES NUTZERS
 *  filtern — Query-Texte anderer Nutzer sind nie sichtbar (Privacy +
 *  Relevanz). Eigene Läufe (Kuration/Onboarding) bleiben unverändert. */
async function filtereProtokolle(userId: string, runs: AgentRun[]): Promise<AgentRun[]> {
  if (datenModus() !== "supabase") return runs;
  const eigene = new Set<string>();
  try {
    const sb = await supabaseAdmin();
    const { data } = await sb
      .from("suchqueries")
      .select("query")
      .eq("user_id", userId)
      .eq("aktiv", true);
    for (const q of data || []) eigene.add(String(q.query).trim().toLowerCase());
    for (const q of await holeExtraQueries(userId).catch(() => [])) {
      eigene.add(q.query.trim().toLowerCase());
    }
  } catch (e) {
    console.error("[api/agenten] Query-Set nicht ladbar:", e);
    // Im Zweifel NICHTS Fremdes zeigen
  }
  /* eslint-disable @typescript-eslint/no-explicit-any */
  return runs.map((r) => {
    const roh = r as AgentRun & { user_id?: string | null };
    const { user_id, ...rest } = roh;
    if (user_id && user_id === userId) return rest as AgentRun;
    return {
      ...rest,
      such_protokoll: (rest.such_protokoll || []).filter((e: any) =>
        eigene.has(String(e.query || "").trim().toLowerCase())
      ),
    } as AgentRun;
  });
  /* eslint-enable @typescript-eslint/no-explicit-any */
}

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const nutzer = await aktuellerNutzer();
    const [status, runsRoh, angefragt] = await Promise.all([
      holeAgentStatus(),
      holeAgentRuns(nutzer.userId),
      laufAngefragt(nutzer.userId),
    ]);
    const runs = await filtereProtokolle(nutzer.userId, runsRoh);
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
    const nutzer = await aktuellerNutzer();
    const [status, angefragt] = await Promise.all([
      holeAgentStatus(),
      laufAngefragt(nutzer.userId),
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
    await fordereLaufAn(nutzer.userId);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/agenten POST]", e);
    return NextResponse.json(
      { ok: false, grund: "Lauf-Anfrage fehlgeschlagen." },
      { status: 500 }
    );
  }
}
