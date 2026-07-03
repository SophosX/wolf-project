// POST /api/skript {video_id} → generiert Skript-Paket neu (Gemini mit Feedback-Kontext)

import { NextRequest, NextResponse } from "next/server";
import { aktualisiereVideo, holeVideo } from "@/lib/daten";
import { generiereSkripte } from "@/lib/gemini";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  try {
    const { video_id } = (await req.json()) || {};
    if (!video_id) {
      return NextResponse.json({ fehler: "video_id erforderlich" }, { status: 400 });
    }
    const video = await holeVideo(video_id);
    if (!video) {
      return NextResponse.json({ fehler: "Video nicht gefunden: " + video_id }, { status: 404 });
    }
    if (!video.claim) {
      return NextResponse.json(
        { fehler: "Video hat noch keinen analysierten Claim — bitte Analyse-Lauf abwarten" },
        { status: 400 }
      );
    }

    const skripte = await generiereSkripte(video);
    await aktualisiereVideo(video_id, { skripte });
    return NextResponse.json({ ok: true, skripte });
  } catch (e) {
    console.error("[api/skript]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Skript-Generierung fehlgeschlagen" },
      { status: 500 }
    );
  }
}
