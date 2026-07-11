// POST /api/login — zwei Wege:
//   Formular {code}             → Zugangscode-Cookie (Alt-Verhalten, Lokal/Christian)
//   Formular {email, passwort}  → Supabase-Session (Multi-Tenant)

import { NextRequest, NextResponse } from "next/server";
import { supabaseAuthAktiv, supabaseRouteClient } from "@/lib/supabaseRoute";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null);
  const email = String(form?.get("email") || "").trim().toLowerCase();
  const passwort = String(form?.get("passwort") || "");
  const code = String(form?.get("code") || "");

  const zurueck = req.nextUrl.clone();
  zurueck.pathname = "/login";
  const ziel = req.nextUrl.clone();
  ziel.pathname = "/";
  ziel.search = "";

  // --- Supabase-Login (E-Mail + Passwort) -----------------------------------
  if (email && passwort) {
    if (!supabaseAuthAktiv()) {
      zurueck.search = "?fehler=1";
      return NextResponse.redirect(zurueck, 303);
    }
    const supabase = await supabaseRouteClient();
    const { error } = supabase
      ? await supabase.auth.signInWithPassword({ email, password: passwort })
      : { error: new Error("Supabase nicht konfiguriert") };
    if (error) {
      zurueck.search = "?fehler=1";
      return NextResponse.redirect(zurueck, 303);
    }
    return NextResponse.redirect(ziel, 303);
  }

  // --- Zugangscode (Alt-Verhalten) -------------------------------------------
  const richtig = process.env.RADAR_ZUGANGSCODE || "radar";
  if (code !== richtig) {
    zurueck.search = "?fehler=1";
    return NextResponse.redirect(zurueck, 303);
  }
  const res = NextResponse.redirect(ziel, 303);
  res.cookies.set("radar_zugang", code, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
