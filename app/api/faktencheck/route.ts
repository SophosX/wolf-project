// POST /api/faktencheck {video_id} → ausführlicher Quellen-Check
// (Gemini + google_search-Grounding) → {inhalt_md, quellen}

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeProfil, holeVideo } from "@/lib/daten";
import { planLimits } from "@/lib/plan";
import { faktencheck } from "@/lib/gemini";

export const dynamic = "force-dynamic";
// Mehrstufiger Check (Behauptungen parallel, je mit Websuche) braucht Luft
export const maxDuration = 300;

export async function POST(req: NextRequest) {
  try {
    const { video_id } = (await req.json()) || {};
    if (!video_id) {
      return NextResponse.json({ fehler: "video_id erforderlich" }, { status: 400 });
    }
    const nutzer = await aktuellerNutzer();
    if (datenModus() === "supabase") {
      const profil = await holeProfil(nutzer.userId).catch(() => null);
      if (!planLimits(profil?.plan).webcheck) {
        return NextResponse.json(
          { fehler: "Der manuelle Websuche-Faktencheck ist ein Pro-Feature." },
          { status: 403 }
        );
      }
    }
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

    const ergebnis = await faktencheck(video);
    return NextResponse.json(ergebnis);
  } catch (e) {
    console.error("[api/faktencheck]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Faktencheck fehlgeschlagen" },
      { status: 500 }
    );
  }
}
