// POST /api/skript {video_id} → generiert Skript-Paket neu (Gemini mit Feedback-Kontext)

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import {
  aktualisiereVideo,
  datenModus,
  holeEinstellungsWert,
  holeProfil,
  holeVideo,
  speichereEinstellungsWert,
} from "@/lib/daten";
import { generiereSkripte } from "@/lib/gemini";
import { planLimits } from "@/lib/plan";

/** ISO-Woche als Schluessel, z.B. "2026-W28" */
function wochenSchluessel(): string {
  const d = new Date();
  const start = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const woche = Math.ceil(((d.getTime() - start.getTime()) / 86_400_000 + start.getUTCDay() + 1) / 7);
  return d.getUTCFullYear() + "-W" + woche;
}

/** Plan-Gate: Free-Nutzer haben ein Wochen-Limit fuer Skript-Generierungen. */
async function skriptBudgetPruefen(userId: string): Promise<string | null> {
  if (datenModus() !== "supabase") return null; // Lokal-Betrieb: kein Gate
  const profil = await holeProfil(userId).catch(() => null);
  const limit = planLimits(profil?.plan, profil?.limits).skripteProWoche;
  if (!isFinite(limit)) return null;
  const woche = wochenSchluessel();
  const zaehler = (await holeEinstellungsWert<{ woche: string; anzahl: number }>(
    userId, "skript_zaehler", { woche, anzahl: 0 }
  )) || { woche, anzahl: 0 };
  const anzahl = zaehler.woche === woche ? zaehler.anzahl : 0;
  if (anzahl >= limit) {
    return "Wochen-Limit erreicht (" + limit + " Skripte/Woche im Free-Plan). Mit Pro sind Skripte unbegrenzt.";
  }
  await speichereEinstellungsWert(userId, "skript_zaehler", { woche, anzahl: anzahl + 1 });
  return null;
}

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  try {
    const { video_id } = (await req.json()) || {};
    if (!video_id) {
      return NextResponse.json({ fehler: "video_id erforderlich" }, { status: 400 });
    }
    const nutzer = await aktuellerNutzer();
    const video = await holeVideo(nutzer.userId, video_id);
    if (!video) {
      return NextResponse.json({ fehler: "Video nicht gefunden: " + video_id }, { status: 404 });
    }
    if (!video.claim) {
      return NextResponse.json(
        { fehler: "Video hat noch keinen analysierten Claim — bitte Analyse-Lauf abwarten" },
        { status: 400 }
      );
    }

    const limitFehler = await skriptBudgetPruefen(nutzer.userId).catch(() => null);
    if (limitFehler) {
      return NextResponse.json({ fehler: limitFehler }, { status: 403 });
    }
    const skripte = await generiereSkripte(nutzer.userId, video);
    await aktualisiereVideo(nutzer.userId, video_id, { skripte });
    return NextResponse.json({ ok: true, skripte });
  } catch (e) {
    console.error("[api/skript]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Skript-Generierung fehlgeschlagen" },
      { status: 500 }
    );
  }
}
