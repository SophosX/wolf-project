// GET /api/videos?status=inbox&plattform=&thema=&zeitraum= → {videos:[...]} (score desc)

import { NextRequest, NextResponse } from "next/server";
import { holeVideos } from "@/lib/daten";
import type { Plattform, Status } from "@/lib/typen";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const p = req.nextUrl.searchParams;
    const status = (p.get("status") || undefined) as Status | undefined;
    const plattform = (p.get("plattform") || undefined) as Plattform | undefined;
    const thema = p.get("thema") || undefined;
    const zeitraum = parseInt(p.get("zeitraum") || "", 10);

    const videos = await holeVideos({
      status,
      plattform,
      thema,
      zeitraumTage: isNaN(zeitraum) ? undefined : zeitraum,
    });
    return NextResponse.json({ videos });
  } catch (e) {
    console.error("[api/videos]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}
