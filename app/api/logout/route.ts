// POST /api/logout — Supabase-Session beenden (+ Zugangscode-Cookie räumen).
// Redirect RELATIV (siehe /api/login: interne Adresse hinter dem Proxy).

import { NextResponse } from "next/server";
import { supabaseRouteClient } from "@/lib/supabaseRoute";

export const dynamic = "force-dynamic";

export async function POST() {
  try {
    const supabase = await supabaseRouteClient();
    if (supabase) await supabase.auth.signOut();
  } catch (e) {
    console.error("[api/logout]", e);
  }
  const res = new NextResponse(null, { status: 303, headers: { Location: "/start" } });
  res.cookies.delete("radar_zugang");
  return res;
}
