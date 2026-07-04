// POST /api/feedback {video_id, aktion, kommentar?}
// → aktualisiert status + feedback-Historie, triggert Lern-Update

import { NextRequest, NextResponse } from "next/server";
import { aktualisiereVideo, holeVideo } from "@/lib/daten";
import { lernUpdate } from "@/lib/lernen";
import { nachschubBeiBedarf } from "@/lib/nachschub";
import type { Status } from "@/lib/typen";

export const dynamic = "force-dynamic";

// aktion → neuer Status ("kommentar" ändert den Status nicht)
const STATUS_MAP: Record<string, Status | null> = {
  angenommen: "angenommen",
  abgelehnt: "abgelehnt",
  gespeichert: "gespeichert",
  archiv: "archiv",
  inbox: "inbox", // rückgängig machen
  kommentar: null,
};

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { video_id, aktion, kommentar } = body || {};

    if (!video_id || !aktion || !(aktion in STATUS_MAP)) {
      return NextResponse.json(
        { fehler: "video_id und gültige aktion (angenommen|abgelehnt|gespeichert|archiv|inbox|kommentar) erforderlich" },
        { status: 400 }
      );
    }

    const video = await holeVideo(video_id);
    if (!video) {
      return NextResponse.json({ fehler: "Video nicht gefunden: " + video_id }, { status: 404 });
    }

    const eintrag = {
      aktion,
      ...(kommentar ? { kommentar: String(kommentar).slice(0, 500) } : {}),
      zeit: new Date().toISOString(),
    };

    const neuerStatus = STATUS_MAP[aktion];
    const patch: Record<string, unknown> = {
      feedback: [...(video.feedback || []), eintrag],
    };
    if (neuerStatus) patch.status = neuerStatus;

    const aktualisiert = await aktualisiereVideo(video_id, patch);

    // Lern-Update (Fehler hier nicht fatal, aber sichtbar loggen)
    try {
      await lernUpdate(video, aktion, kommentar);
    } catch (e) {
      console.error("[api/feedback] Lern-Update fehlgeschlagen:", e);
    }

    // Dynamik: wird die Inbox durch Entscheidungen dünn, sucht der Radar
    // sofort Nachschub (lokal; in Prod übernimmt der 4-h-Cron)
    if (aktion === "angenommen" || aktion === "abgelehnt" || aktion === "archiv") {
      nachschubBeiBedarf().catch(() => {});
    }

    return NextResponse.json({ ok: true, video: aktualisiert });
  } catch (e) {
    console.error("[api/feedback]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Unbekannter Fehler" },
      { status: 500 }
    );
  }
}
