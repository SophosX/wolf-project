// POST /api/signup {email, passwort, invite?} → Supabase-Registrierung.
// Invite-only-Phase: Ist RADAR_INVITE_CODES gesetzt (kommagetrennt), muss der
// Invite-Code passen. Öffnung für alle = ENV einfach entfernen (Phase 6).

import { NextRequest, NextResponse } from "next/server";
import { supabaseAuthAktiv, supabaseRouteClient } from "@/lib/supabaseRoute";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    if (!supabaseAuthAktiv()) {
      return NextResponse.json(
        { fehler: "Registrierung ist auf dieser Instanz nicht aktiviert." },
        { status: 501 }
      );
    }
    const body = await req.json().catch(() => ({}));
    const email = String(body.email || "").trim().toLowerCase();
    const passwort = String(body.passwort || "");
    const invite = String(body.invite || "").trim();

    if (!email.includes("@") || passwort.length < 8) {
      return NextResponse.json(
        { fehler: "Bitte gültige E-Mail und ein Passwort mit mindestens 8 Zeichen angeben." },
        { status: 400 }
      );
    }
    const inviteCodes = (process.env.RADAR_INVITE_CODES || "")
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean);
    if (inviteCodes.length > 0 && !inviteCodes.includes(invite)) {
      return NextResponse.json(
        { fehler: "Ungültiger Einladungs-Code — die Registrierung ist aktuell invite-only." },
        { status: 403 }
      );
    }

    const supabase = await supabaseRouteClient();
    if (!supabase) {
      return NextResponse.json({ fehler: "Supabase nicht konfiguriert." }, { status: 501 });
    }
    const { data, error } = await supabase.auth.signUp({
      email,
      password: passwort,
      options: { data: { anzeige_name: String(body.anzeige_name || "").slice(0, 80) || null } },
    });
    if (error) {
      return NextResponse.json({ fehler: error.message }, { status: 400 });
    }
    // Ohne E-Mail-Bestätigung existiert sofort eine Session (Cookies gesetzt);
    // mit Bestätigung muss der Nutzer erst den Link klicken.
    return NextResponse.json({
      ok: true,
      angemeldet: Boolean(data.session),
      hinweis: data.session ? null : "Bitte E-Mail bestätigen, dann anmelden.",
    });
  } catch (e) {
    console.error("[api/signup]", e);
    return NextResponse.json({ fehler: "Registrierung fehlgeschlagen." }, { status: 500 });
  }
}
