// Zugangsschutz + Supabase-Token-Refresh (Edge).
//
// AUTH_MODUS steuert das Verhalten (siehe lib/auth.ts — hier NICHT importieren,
// lib/auth zieht next/headers in das Edge-Bundle!):
//   code     : wie bisher — nur der optionale Zugangscode (RADAR_ZUGANGSCODE).
//              Ohne gesetzten Code ist die App offen.
//   beides   : Supabase-Session ODER Zugangscode gelten. Ohne gesetzten Code
//              bleibt die App offen (Cutover: Christian merkt nichts).
//   supabase : Supabase-Session ist Pflicht (Self-Service-Betrieb).
//
// Der Supabase-Client hier übernimmt außerdem den TOKEN-REFRESH: abgelaufene
// Access-Tokens werden erneuert und als Cookies auf Request UND Response
// geschrieben (Server Components dürfen keine Cookies setzen — lib/auth.ts
// liest nur; das Setzen passiert ausschließlich hier).

import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "radar_zugang";

function zugangscode(): string {
  return (process.env.RADAR_ZUGANGSCODE || "").trim();
}

type AuthModus = "code" | "supabase" | "beides";

function authModus(): AuthModus {
  const m = (process.env.AUTH_MODUS || "").trim().toLowerCase();
  if (m === "supabase") return "supabase";
  if (m === "beides") return "beides";
  return "code";
}

// Ohne Session/Code frei erreichbare Pfade (Login, Signup + deren APIs)
const FREIE_PFADE = new Set(["/start", "/login", "/api/login", "/signup", "/api/signup", "/api/invite-anfrage"]);

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const modus = authModus();
  const code = zugangscode();

  // --- Supabase-Session lesen + Token-Refresh (nur wenn Modus es braucht) ---
  let res = NextResponse.next({ request: req });
  let angemeldet = false;
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (modus !== "code" && supabaseUrl && anonKey) {
    try {
      const supabase = createServerClient(supabaseUrl, anonKey, {
        cookies: {
          getAll: () => req.cookies.getAll(),
          setAll: (cookies) => {
            // erneuerte Tokens für nachgelagerte Server Components (Request)
            // UND den Browser (Response) sichtbar machen
            cookies.forEach(({ name, value }) => req.cookies.set(name, value));
            res = NextResponse.next({ request: req });
            cookies.forEach(({ name, value, options }) =>
              res.cookies.set(name, value, options)
            );
          },
        },
      });
      const { data } = await supabase.auth.getUser();
      angemeldet = Boolean(data?.user);
    } catch (e) {
      console.error("[middleware] Supabase-Session nicht lesbar:", e);
    }
  }

  // --- Freie Pfade -----------------------------------------------------------
  if (FREIE_PFADE.has(pathname)) {
    // Bereits angemeldet (oder App offen) → Login/Signup direkt überspringen
    const offen = modus !== "supabase" && !code;
    if ((angemeldet || offen) && (pathname === "/login" || pathname === "/signup")) {
      const ziel = req.nextUrl.clone();
      ziel.pathname = "/";
      ziel.search = "";
      return NextResponse.redirect(ziel);
    }
    return res;
  }

  // --- Zugang entscheiden ------------------------------------------------------
  // 1) Supabase-Session gilt in den Modi supabase/beides
  if (angemeldet) return res;

  // 2) Zugangscode-Betrieb (code/beides)
  if (modus !== "supabase") {
    // Kein Code konfiguriert → App offen (heutiges Verhalten)
    if (!code) return res;

    // ?code=XYZ: Cookie setzen und URL bereinigen
    const urlCode = req.nextUrl.searchParams.get("code");
    if (urlCode && urlCode === code) {
      const ziel = req.nextUrl.clone();
      ziel.searchParams.delete("code");
      const redirect = NextResponse.redirect(ziel);
      redirect.cookies.set(COOKIE_NAME, code, {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: 60 * 60 * 24 * 30, // 30 Tage
      });
      return redirect;
    }
    if (req.cookies.get(COOKIE_NAME)?.value === code) return res;
  }

  // --- Kein Zugang -------------------------------------------------------------
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { fehler: "Nicht angemeldet" },
      { status: 401 }
    );
  }
  // Nicht angemeldete Besucher landen auf der Landing (erklaert die Plattform)
  const start = req.nextUrl.clone();
  start.pathname = "/start";
  start.search = "";
  return NextResponse.redirect(start);
}

export const config = {
  // Statische Assets und Next-Interna auslassen
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
