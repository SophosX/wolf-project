// Admin-API: Nutzerverwaltung (nur rolle=admin mit echter Supabase-Session).
//   GET   → alle Nutzer mit Plan, Limits, Aktivität (Zuordnungen, letzte Kuration)
//   PATCH → {user_id, plan?, rolle?, limits?} — Plan/Rolle/Usage-Limits setzen

import { NextRequest, NextResponse } from "next/server";
import { adminNutzer } from "@/lib/adminGate";
import { supabaseAdmin } from "@/lib/daten";
import { PLAN_LIMITS } from "@/lib/plan";

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

    const [{ data: profile }, { data: zuordnungen }, { data: runs }, { data: queries }] =
      await Promise.all([
        sb
          .from("profiles")
          .select("id, email, anzeige_name, rolle, plan, limits, onboarding_status, erstellt_am")
          .is("geloescht_am", null)
          .order("erstellt_am", { ascending: true }),
        sb.from("video_zuordnung").select("user_id, status"),
        sb
          .from("agent_runs")
          .select("user_id, typ, zeit")
          .eq("typ", "kuration")
          .order("zeit", { ascending: false })
          .limit(500),
        sb.from("suchqueries").select("user_id").eq("aktiv", true),
      ]);

    const statistik = new Map<string, Record<string, number>>();
    for (const z of zuordnungen || []) {
      const s = statistik.get(z.user_id) || {};
      s[z.status] = (s[z.status] || 0) + 1;
      statistik.set(z.user_id, s);
    }
    const letzteKuration = new Map<string, string>();
    for (const r of runs || []) {
      if (r.user_id && !letzteKuration.has(r.user_id)) letzteKuration.set(r.user_id, r.zeit);
    }
    const queryZahl = new Map<string, number>();
    for (const q of queries || []) {
      queryZahl.set(q.user_id, (queryZahl.get(q.user_id) || 0) + 1);
    }

    return NextResponse.json({
      plan_defaults: PLAN_LIMITS,
      nutzer: (profile || []).map((p) => ({
        ...p,
        statistik: statistik.get(p.id) || {},
        letzte_kuration: letzteKuration.get(p.id) || null,
        queries_aktiv: queryZahl.get(p.id) || 0,
      })),
    });
  } catch (e) {
    console.error("[api/admin/nutzer GET]", e);
    return NextResponse.json({ fehler: "Nutzerliste nicht ladbar" }, { status: 500 });
  }
}

// Nur diese Limit-Schlüssel dürfen per Admin-Override gesetzt werden
const ERLAUBTE_LIMITS = new Set([
  "import_videos", "themen", "suchqueries", "watchlist", "kuration_pro_tag",
  "kuration_max_neu", "queries_pro_lauf", "skripte_pro_woche", "rezepte", "webcheck",
]);

export async function PATCH(req: NextRequest) {
  try {
    const admin = await adminNutzer();
    if (!admin) return KEIN_ZUGANG;
    const body = await req.json().catch(() => ({}));
    const userId = String(body.user_id || "");
    if (!userId) return NextResponse.json({ fehler: "user_id fehlt" }, { status: 400 });

    const patch: Record<string, unknown> = {};
    if (body.plan === "free" || body.plan === "pro") patch.plan = body.plan;
    if (body.rolle === "creator" || body.rolle === "admin") {
      if (userId === admin.userId && body.rolle !== "admin") {
        return NextResponse.json(
          { fehler: "Du kannst dir nicht selbst die Admin-Rolle entziehen." },
          { status: 400 }
        );
      }
      patch.rolle = body.rolle;
    }
    if (body.limits && typeof body.limits === "object") {
      const limits: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(body.limits as Record<string, unknown>)) {
        if (!ERLAUBTE_LIMITS.has(k)) continue;
        if (v === null || v === "" || v === undefined) continue; // leer = Plan-Default
        limits[k] = typeof v === "boolean" ? v : Number(v);
      }
      patch.limits = limits;
    }
    if (Object.keys(patch).length === 0) {
      return NextResponse.json({ fehler: "Nichts zu ändern." }, { status: 400 });
    }

    const sb = await supabaseAdmin();
    const { error } = await sb.from("profiles").update(patch).eq("id", userId);
    if (error) throw new Error(error.message);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/admin/nutzer PATCH]", e);
    return NextResponse.json({ fehler: "Änderung fehlgeschlagen" }, { status: 500 });
  }
}
