// POST /api/login (Formular) → prüft Zugangscode, setzt httpOnly-Cookie

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null);
  const code = String(form?.get("code") || "");
  const richtig = process.env.RADAR_ZUGANGSCODE || "radar";

  if (code !== richtig) {
    const zurueck = req.nextUrl.clone();
    zurueck.pathname = "/login";
    zurueck.search = "?fehler=1";
    return NextResponse.redirect(zurueck, 303);
  }

  const ziel = req.nextUrl.clone();
  ziel.pathname = "/";
  ziel.search = "";
  const res = NextResponse.redirect(ziel, 303);
  res.cookies.set("radar_zugang", code, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
