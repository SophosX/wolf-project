// Admin-API: Einladungs-Codes (nur rolle=admin).
//   GET    → alle Codes mit Nutzungsstand
//   POST   → {notiz?, max_nutzungen?} → neuen Code erzeugen
//   DELETE → {code} → Code entfernen

import { randomBytes } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { adminNutzer } from "@/lib/adminGate";
import { supabaseAdmin } from "@/lib/daten";

export const dynamic = "force-dynamic";

const KEIN_ZUGANG = NextResponse.json(
  { fehler: "Nur für Admins — bitte mit dem Admin-Konto anmelden." },
  { status: 403 }
);

export async function GET() {
  try {
    const admin = await adminNutzer();
    if (!admin) return KEIN_ZUGANG;
    const sb = await supabaseAdmin();
    const { data, error } = await sb
      .from("invites")
      .select("*")
      .order("erstellt_am", { ascending: false });
    if (error) throw new Error(error.message);
    return NextResponse.json({ invites: data || [] });
  } catch (e) {
    console.error("[api/admin/invites GET]", e);
    return NextResponse.json({ fehler: "Invites nicht ladbar" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const admin = await adminNutzer();
    if (!admin) return KEIN_ZUGANG;
    const body = await req.json().catch(() => ({}));
    const code = "radar-" + randomBytes(6).toString("base64url");
    const sb = await supabaseAdmin();
    const { error } = await sb.from("invites").insert({
      code,
      erstellt_von: admin.userId,
      notiz: String(body.notiz || "").slice(0, 200) || null,
      max_nutzungen: Math.max(1, Math.min(100, Number(body.max_nutzungen) || 1)),
    });
    if (error) throw new Error(error.message);
    return NextResponse.json({ ok: true, code });
  } catch (e) {
    console.error("[api/admin/invites POST]", e);
    return NextResponse.json({ fehler: "Code konnte nicht erzeugt werden" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const admin = await adminNutzer();
    if (!admin) return KEIN_ZUGANG;
    const { code } = (await req.json().catch(() => ({}))) as { code?: string };
    if (!code) return NextResponse.json({ fehler: "code fehlt" }, { status: 400 });
    const sb = await supabaseAdmin();
    const { error } = await sb.from("invites").delete().eq("code", code);
    if (error) throw new Error(error.message);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/admin/invites DELETE]", e);
    return NextResponse.json({ fehler: "Löschen fehlgeschlagen" }, { status: 500 });
  }
}
