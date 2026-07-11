// Onboarding-API (Supabase-Modus, angemeldete Nutzer):
//   GET  → Status + generierter Profil-Vorschlag (für den Review-Schritt)
//   POST → Import starten: {kanaele:[{plattform,handle}], marke?} → radar_profile
//          + Auftrag typ=onboarding (Scraper-Worker übernimmt)
//   PUT  → Review abschließen: {nische?, marke?, trigger?, interview?} →
//          Profil-Feinschliff, onboarding_status=fertig, Kurations-Auftrag

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeProfil, holeRadarProfil, holeThemen, supabaseAdmin } from "@/lib/daten";

export const dynamic = "force-dynamic";

function nichtVerfuegbar() {
  return NextResponse.json(
    { fehler: "Onboarding gibt es nur im Multi-Tenant-Betrieb (Supabase-Modus)." },
    { status: 501 }
  );
}

export async function GET() {
  try {
    if (datenModus() !== "supabase") return nichtVerfuegbar();
    const nutzer = await aktuellerNutzer();
    if (nutzer.quelle !== "supabase") return nichtVerfuegbar();

    const [profil, radarProfil, themen] = await Promise.all([
      holeProfil(nutzer.userId),
      holeRadarProfil(nutzer.userId),
      holeThemen(nutzer.userId).catch(() => []),
    ]);
    const sb = await supabaseAdmin();
    const { data: queries } = await sb
      .from("suchqueries")
      .select("id, plattform, query, thema_slug, aktiv")
      .eq("user_id", nutzer.userId);
    const { data: personen } = await sb
      .from("watchlist_personen")
      .select("id, name, plattform, handle, folgt")
      .eq("user_id", nutzer.userId);

    return NextResponse.json({
      status: profil?.onboarding_status || "offen",
      profil: radarProfil
        ? {
            nische: radarProfil.nische,
            marke: radarProfil.marke,
            quelle_kanaele: radarProfil.quelle_kanaele,
            reaktions_ausloeser: radarProfil.reaktions_ausloeser,
            positionen: radarProfil.positionen,
          }
        : null,
      themen,
      queries: queries || [],
      personen: personen || [],
    });
  } catch (e) {
    console.error("[api/onboarding GET]", e);
    return NextResponse.json({ fehler: "Status nicht ladbar" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    if (datenModus() !== "supabase") return nichtVerfuegbar();
    const nutzer = await aktuellerNutzer();
    if (nutzer.quelle !== "supabase") return nichtVerfuegbar();

    const body = await req.json().catch(() => ({}));
    const kanaele = (Array.isArray(body.kanaele) ? body.kanaele : [])
      .map((k: { plattform?: string; handle?: string }) => ({
        plattform: String(k.plattform || "youtube").toLowerCase(),
        handle: String(k.handle || "").trim().replace(/^@/, ""),
      }))
      .filter((k: { handle: string }) => k.handle.length > 1)
      .slice(0, 3);
    if (kanaele.length === 0) {
      return NextResponse.json(
        { fehler: "Bitte mindestens einen Kanal (Handle) angeben." },
        { status: 400 }
      );
    }

    const sb = await supabaseAdmin();
    const { error: profilFehler } = await sb.from("radar_profile").upsert({
      user_id: nutzer.userId,
      quelle_kanaele: kanaele,
      marke: String(body.marke || "").slice(0, 60) || null,
      aktualisiert_am: new Date().toISOString(),
    });
    if (profilFehler) throw new Error(profilFehler.message);

    await sb
      .from("profiles")
      .update({ onboarding_status: "import_laeuft" })
      .eq("id", nutzer.userId);
    const { error: auftragFehler } = await sb
      .from("auftraege")
      .insert({ user_id: nutzer.userId, typ: "onboarding" });
    if (auftragFehler) throw new Error(auftragFehler.message);

    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/onboarding POST]", e);
    return NextResponse.json({ fehler: "Import konnte nicht gestartet werden" }, { status: 500 });
  }
}

export async function PUT(req: NextRequest) {
  try {
    if (datenModus() !== "supabase") return nichtVerfuegbar();
    const nutzer = await aktuellerNutzer();
    if (nutzer.quelle !== "supabase") return nichtVerfuegbar();

    const body = await req.json().catch(() => ({}));
    const sb = await supabaseAdmin();

    // Profil-Feinschliff aus dem Review/Interview
    const patch: Record<string, unknown> = { aktualisiert_am: new Date().toISOString() };
    if (body.nische) patch.nische = String(body.nische).slice(0, 120);
    if (body.marke !== undefined) patch.marke = String(body.marke || "").slice(0, 60) || null;
    if (Array.isArray(body.trigger)) {
      const jetzt = new Date().toISOString();
      patch.reaktions_ausloeser = body.trigger
        .map((t: unknown) => String(t).trim())
        .filter((t: string) => t.length > 3)
        .slice(0, 20)
        .map((t: string) => ({
          trigger: t,
          staerke: 0.8,
          quelle: "interview",
          belege: [],
          aktualisiert_am: jetzt,
        }));
    }
    const { error: profilFehler } = await sb
      .from("radar_profile")
      .update(patch)
      .eq("user_id", nutzer.userId);
    if (profilFehler) throw new Error(profilFehler.message);

    // Themen an-/abwählen (Review): {themen_aktiv: {slug: boolean}}
    if (body.themen_aktiv && typeof body.themen_aktiv === "object") {
      for (const [slug, aktiv] of Object.entries(body.themen_aktiv as Record<string, boolean>)) {
        await sb
          .from("themen")
          .update({ aktiv: Boolean(aktiv) })
          .eq("user_id", nutzer.userId)
          .eq("slug", slug);
      }
    }

    // Suchqueries pflegen (auch von /einstellungen genutzt):
    // {queries_neu: [{plattform, query}], queries_loeschen: [id], queries_aktiv: {id: bool}}
    if (Array.isArray(body.queries_neu)) {
      for (const q of body.queries_neu.slice(0, 10)) {
        const query = String(q?.query || "").trim();
        if (query.length < 3) continue;
        await sb.from("suchqueries").upsert(
          {
            user_id: nutzer.userId,
            plattform: ["youtube", "tiktok", "instagram"].includes(String(q?.plattform))
              ? String(q.plattform)
              : "youtube",
            query,
            aktiv: true,
            quelle: "manuell",
          },
          { onConflict: "user_id,plattform,query", ignoreDuplicates: true }
        );
      }
    }
    if (Array.isArray(body.queries_loeschen)) {
      for (const id of body.queries_loeschen.slice(0, 50)) {
        await sb
          .from("suchqueries")
          .delete()
          .eq("user_id", nutzer.userId)
          .eq("id", Number(id));
      }
    }

    if (body.fertig) {
      await sb
        .from("profiles")
        .update({ onboarding_status: "fertig" })
        .eq("id", nutzer.userId);
      // Erste Kuration sofort anstoßen — die Inbox soll nicht leer starten
      await sb.from("auftraege").insert({ user_id: nutzer.userId, typ: "kuration" });
    }
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[api/onboarding PUT]", e);
    return NextResponse.json({ fehler: "Speichern fehlgeschlagen" }, { status: 500 });
  }
}
