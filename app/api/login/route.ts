// POST /api/login — zwei Wege:
//   Formular {code}             → Zugangscode-Cookie (Alt-Verhalten, Lokal/Christian)
//   Formular {email, passwort}  → Supabase-Session (Multi-Tenant)
//
// WICHTIG: Redirects hier sind RELATIV (Location: "/"), nicht absolut —
// hinter dem nginx-Proxy kennt der Route-Handler nur die interne
// Container-Adresse (0.0.0.0:3000); absolute URLs liefen ins Leere.

import { NextRequest, NextResponse } from "next/server";
import { supabaseAuthAktiv, supabaseRouteClient } from "@/lib/supabaseRoute";

export const dynamic = "force-dynamic";

function redirectRelativ(pfad: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { Location: pfad } });
}

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null);
  const email = String(form?.get("email") || "").trim().toLowerCase();
  const passwort = String(form?.get("passwort") || "");
  const code = String(form?.get("code") || "");

  // --- Supabase-Login (E-Mail + Passwort) -----------------------------------
  if (email && passwort) {
    if (!supabaseAuthAktiv()) {
      return redirectRelativ("/login?fehler=1");
    }
    const supabase = await supabaseRouteClient();
    const { error } = supabase
      ? await supabase.auth.signInWithPassword({ email, password: passwort })
      : { error: new Error("Supabase nicht konfiguriert") };
    if (error) {
      return redirectRelativ("/login?fehler=1");
    }
    return redirectRelativ("/");
  }

  // --- Zugangscode (Alt-Verhalten) -------------------------------------------
  const richtig = process.env.RADAR_ZUGANGSCODE || "radar";
  if (code !== richtig) {
    return redirectRelativ("/login?fehler=1");
  }
  const res = redirectRelativ("/");
  res.cookies.set("radar_zugang", code, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
