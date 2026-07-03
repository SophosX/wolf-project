// Zugangsschutz: httpOnly-Cookie muss den Zugangscode enthalten.
// Einstieg per ?code=XYZ an beliebiger URL oder Formular auf /login.
// Code kommt aus ENV RADAR_ZUGANGSCODE (Dev-Default: "radar").

import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "radar_zugang";

function zugangscode(): string {
  return process.env.RADAR_ZUGANGSCODE || "radar";
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Login-Seite und Login-API sind frei erreichbar
  if (pathname === "/login" || pathname === "/api/login") {
    return NextResponse.next();
  }

  const code = zugangscode();

  // ?code=XYZ: Cookie setzen und URL bereinigen
  const urlCode = req.nextUrl.searchParams.get("code");
  if (urlCode && urlCode === code) {
    const ziel = req.nextUrl.clone();
    ziel.searchParams.delete("code");
    const res = NextResponse.redirect(ziel);
    res.cookies.set(COOKIE_NAME, code, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30, // 30 Tage
    });
    return res;
  }

  // Gültiges Cookie → durchlassen
  if (req.cookies.get(COOKIE_NAME)?.value === code) {
    return NextResponse.next();
  }

  // API ohne Zugang → 401 JSON (kein Redirect)
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { fehler: "Zugangscode fehlt oder ist falsch" },
      { status: 401 }
    );
  }

  // Seiten ohne Zugang → Login
  const login = req.nextUrl.clone();
  login.pathname = "/login";
  login.search = "";
  return NextResponse.redirect(login);
}

export const config = {
  // Statische Assets und Next-Interna auslassen
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
