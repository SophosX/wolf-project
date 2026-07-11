// DELETE /api/konto — DSGVO-Konto-Löschung des ANGEMELDETEN Nutzers.
// auth.users-Löschung kaskadiert über profiles auf ALLE user_id-Tabellen
// (video_zuordnung, radar_profile, themen, suchqueries, watchlist_personen,
// narrativ_chunks inkl. eigener Transkripte, einstellungen, rezepte,
// agent_runs, auftraege). Pool-Videos bleiben — öffentliche Fremddaten.

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { datenModus } from "@/lib/daten";

export const dynamic = "force-dynamic";

export async function DELETE(req: NextRequest) {
  try {
    if (datenModus() !== "supabase") {
      return NextResponse.json(
        { fehler: "Konto-Löschung gibt es nur im Multi-Tenant-Betrieb." },
        { status: 501 }
      );
    }
    const nutzer = await aktuellerNutzer();
    if (nutzer.quelle !== "supabase") {
      return NextResponse.json(
        { fehler: "Nur für angemeldete Nutzer (nicht im Zugangscode-Betrieb)." },
        { status: 403 }
      );
    }
    // Bestätigung erzwingen: {bestaetigung: "LOESCHEN"}
    const body = await req.json().catch(() => ({}));
    if (body.bestaetigung !== "LOESCHEN") {
      return NextResponse.json(
        { fehler: 'Bitte mit {"bestaetigung":"LOESCHEN"} bestätigen.' },
        { status: 400 }
      );
    }

    // GoTrue-Admin-API (Service-Key) — löscht auth.users, Kaskade räumt den Rest
    const url = (process.env.SUPABASE_URL || "").replace(/\/$/, "");
    const key = process.env.SUPABASE_SERVICE_KEY || "";
    const res = await fetch(url + "/auth/v1/admin/users/" + nutzer.userId, {
      method: "DELETE",
      headers: { apikey: key, Authorization: "Bearer " + key },
      signal: AbortSignal.timeout(20_000),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error("Admin-Delete " + res.status + ": " + text.slice(0, 200));
    }
    const antwort = NextResponse.json({ ok: true });
    // Session-Cookies sind jetzt wertlos — aufräumen macht der nächste Request
    return antwort;
  } catch (e) {
    console.error("[api/konto DELETE]", e);
    return NextResponse.json({ fehler: "Löschung fehlgeschlagen." }, { status: 500 });
  }
}
