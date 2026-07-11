// POST /api/logout — Supabase-Session beenden (+ Zugangscode-Cookie räumen).

import { NextRequest, NextResponse } from "next/server";
import { supabaseRouteClient } from "@/lib/supabaseRoute";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const supabase = await supabaseRouteClient();
    if (supabase) await supabase.auth.signOut();
  } catch (e) {
    console.error("[api/logout]", e);
  }
  const login = req.nextUrl.clone();
  login.pathname = "/start";
  login.search = "";
  const res = NextResponse.redirect(login, 303);
  res.cookies.delete("radar_zugang");
  return res;
}
