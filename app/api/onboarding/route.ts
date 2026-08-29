// Onboarding-API (Supabase-Modus, angemeldete Nutzer):
//   GET  → Status + generierter Profil-Vorschlag (für den Review-Schritt)
//   POST → Import starten: {kanaele:[{plattform,handle}], marke?} → radar_profile
//          + Auftrag typ=onboarding (Scraper-Worker übernimmt)
//   PUT  → Review abschließen: {nische?, marke?, trigger?, interview?} →
//          Profil-Feinschliff, onboarding_status=fertig, Kurations-Auftrag

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeProfil, holeRadarProfil, holeThemen, supabaseAdmin } from "@/lib/daten";
import { interessenBereiche, starterPack, validiereLabels } from "@/lib/interessen";
import { planLimits } from "@/lib/plan";

/* eslint-disable @typescript-eslint/no-explicit-any */
/** Reihum über die Bereiche (1. Element jedes Bereichs, dann 2. …), damit
 *  bei Plan-Caps JEDER gewählte Bereich vertreten ist — statt first-come, bei
 *  dem der 4. Bereich (z. B. Klima) komplett leer ausging. */
function reihum<T>(listen: T[][]): T[] {
  const out: T[] = [];
  const max = Math.max(0, ...listen.map((l) => l.length));
  for (let i = 0; i < max; i++) {
    for (const l of listen) if (i < l.length) out.push(l[i]);
  }
  return out;
}

export interface StarterErgebnis {
  themen_neu: number;
  themen_verworfen: number;
  queries_neu: number;
  queries_verworfen: number;
  bereiche_ohne_thema: string[];
  limits: { themen: number; suchqueries: number };
}

/** Starter-Pack der gewählten Interessen-Bereiche materialisieren:
 *  Themen (merge), Suchqueries (ignore-duplicates), Trigger-Seeds — unter
 *  Beachtung der Plan-Caps (bestehende Zeilen zählen mit). Liefert zurück,
 *  was NICHT mehr Platz hatte, damit das UI es dem Nutzer sagen kann. */
async function starterPackAnwenden(
  sb: any, userId: string, labels: string[]
): Promise<StarterErgebnis | null> {
  if (labels.length === 0) return null;
  const konto = await holeProfil(userId).catch(() => null);
  const limits = planLimits(konto?.plan, konto?.limits);
  const packs = labels.map((l) => ({ slug: l, ...starterPack([l]) }));
  const pack = {
    themen: reihum(packs.map((p) => p.themen)),
    queries: reihum(packs.map((p) => p.queries)),
    trigger: packs.flatMap((p) => p.trigger),
  };

  const { data: vorhandeneThemen } = await sb
    .from("themen").select("slug").eq("user_id", userId);
  const vorhandeneSlugs = new Set((vorhandeneThemen || []).map((t: any) => t.slug));
  let themenPlatz = Math.max(0, limits.themen - vorhandeneSlugs.size);
  const themenZeilen = [];
  let themenVerworfen = 0;
  for (const t of pack.themen) {
    if (vorhandeneSlugs.has(t.slug)) continue;
    if (themenPlatz <= 0) { themenVerworfen++; continue; }
    themenPlatz--;
    themenZeilen.push({
      user_id: userId, slug: t.slug, name: t.name,
      kerngewicht: t.kerngewicht, keywords: t.keywords,
      aktiv: true, quelle: "onboarding",
    });
  }
  if (themenZeilen.length > 0) {
    await sb.from("themen").upsert(themenZeilen, { onConflict: "user_id,slug" });
  }
  const alleSlugs = new Set([...vorhandeneSlugs, ...themenZeilen.map((t) => t.slug)]);
  const bereicheOhneThema = packs
    .filter((p) => !p.themen.some((t) => alleSlugs.has(t.slug)))
    .map((p) => p.slug);

  const { count: queryZahl } = await sb
    .from("suchqueries").select("id", { count: "exact", head: true })
    .eq("user_id", userId);
  let queryPlatz = Math.max(0, limits.suchqueries - (queryZahl || 0));
  const queryZeilen = [];
  let queriesVerworfen = 0;
  for (const q of pack.queries) {
    if (queryPlatz <= 0) { queriesVerworfen++; continue; }
    queryPlatz--;
    queryZeilen.push({
      user_id: userId, plattform: q.plattform, query: q.query,
      aktiv: true, quelle: "onboarding",
    });
  }
  if (queryZeilen.length > 0) {
    await sb.from("suchqueries").upsert(queryZeilen, {
      onConflict: "user_id,plattform,query", ignoreDuplicates: true,
    });
  }
  const ergebnis: StarterErgebnis = {
    themen_neu: themenZeilen.length, themen_verworfen: themenVerworfen,
    queries_neu: queryZeilen.length, queries_verworfen: queriesVerworfen,
    bereiche_ohne_thema: bereicheOhneThema,
    limits: { themen: limits.themen, suchqueries: limits.suchqueries },
  };

  // Trigger-Seeds an bestehende anfügen (Dedupe über den Text)
  const profil = await holeRadarProfil(userId).catch(() => null);
  const bestehend = ((profil?.reaktions_ausloeser as any[]) || []);
  const texte = new Set(bestehend.map((t) => String(t.trigger || "").toLowerCase()));
  const jetzt = new Date().toISOString();
  const neue = pack.trigger
    .filter((t) => !texte.has(t.toLowerCase()))
    .map((t) => ({ trigger: t, staerke: 0.6, quelle: "onboarding", belege: [], aktualisiert_am: jetzt }));
  if (neue.length > 0) {
    await sb.from("radar_profile").upsert({
      user_id: userId,
      reaktions_ausloeser: [...bestehend, ...neue].slice(0, 25),
      aktualisiert_am: jetzt,
    });
  }
  return ergebnis;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

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
    const { data: queriesRoh } = await sb
      .from("suchqueries")
      .select("id, plattform, query, thema_slug, aktiv")
      .eq("user_id", nutzer.userId);
    // Ertrag je Suchanfrage (scrape_status) — "fand zuletzt 6 Videos" / "3× leer"
    const { data: statusRoh } = await sb
      .from("scrape_status").select("plattform, query_norm, zuletzt, letzte_treffer, leer_folge");
    const statusMap = new Map<string, any>();
    for (const s of statusRoh || []) statusMap.set(s.plattform + "|" + s.query_norm, s);
    const queries = (queriesRoh || []).map((q: any) => {
      const s = statusMap.get(
        q.plattform + "|" + String(q.query || "").trim().replace(/^#/, "").toLowerCase());
      return {
        ...q,
        letzte_treffer: Number(s?.letzte_treffer || 0),
        leer_folge: Number(s?.leer_folge || 0),
        zuletzt: s?.zuletzt || null,
      };
    });
    const { data: personen } = await sb
      .from("watchlist_personen")
      .select("id, name, plattform, handle, folgt")
      .eq("user_id", nutzer.userId);
    const { data: auftraege } = await sb
      .from("auftraege")
      .select("status, payload, erstellt_am")
      .eq("user_id", nutzer.userId)
      .eq("typ", "onboarding")
      .order("erstellt_am", { ascending: false })
      .limit(1);
    const importAuftrag = (auftraege || [])[0] || null;

    const gewaehlt = ((radarProfil?.interessen_profil as
      { interessen_labels?: string[] } | null)?.interessen_labels) || [];
    const { data: lernerThemen } = await sb
      .from("themen").select("slug, name, keywords")
      .eq("user_id", nutzer.userId).eq("quelle", "lerner").eq("aktiv", false);
    const { data: lernerQueries } = await sb
      .from("suchqueries").select("id, plattform, query")
      .eq("user_id", nutzer.userId).eq("quelle", "lerner").eq("aktiv", false);

    const { holeEinstellungsWert } = await import("@/lib/daten");
    const rezepteAktiv = Boolean(
      await holeEinstellungsWert(nutzer.userId, "rezepte_aktiv", false).catch(() => false)
    );

    return NextResponse.json({
      status: profil?.onboarding_status || "offen",
      plan: profil?.plan || "free",
      rezepte_aktiv: rezepteAktiv,
      fortschritt:
        (importAuftrag?.payload as { schritt?: string } | null)?.schritt || null,
      import_status: importAuftrag?.status || null,
      interessen: interessenBereiche().map((b) => ({
        slug: b.slug, label: b.label, emoji: b.emoji,
        gewaehlt: gewaehlt.includes(b.slug),
      })),
      vorschlaege: {
        themen: lernerThemen || [],
        queries: lernerQueries || [],
      },
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
    const labels = validiereLabels(body.labels);
    if (kanaele.length === 0 && labels.length === 0) {
      return NextResponse.json(
        { fehler: "Bitte einen Kanal verbinden ODER mindestens ein Interesse wählen." },
        { status: 400 }
      );
    }

    const sb = await supabaseAdmin();
    const fokus = String(body.fokus || "").trim().slice(0, 600);
    const { error: profilFehler } = await sb.from("radar_profile").upsert({
      user_id: nutzer.userId,
      quelle_kanaele: kanaele,
      marke: String(body.marke || "").slice(0, 60) || null,
      // Fokus + Labels: sofortige Richtung + Leitplanke fuer den Import-Agenten
      interessen_profil: {
        ...(fokus ? { fokus_text: fokus } : {}),
        interessen_labels: labels,
      },
      aktualisiert_am: new Date().toISOString(),
    });
    if (profilFehler) throw new Error(profilFehler.message);

    // Starter-Pack SOFORT anlegen — der Algorithmus hat ab jetzt eine Richtung,
    // der Kanal-Import verfeinert nur noch.
    const starter = await starterPackAnwenden(sb, nutzer.userId, labels);

    if (kanaele.length === 0) {
      // Ohne Kanal: direkt in den Review — das Starter-Profil ist das Profil.
      await sb
        .from("profiles")
        .update({ onboarding_status: "review" })
        .eq("id", nutzer.userId);
      return NextResponse.json({ ok: true, ohne_kanal: true, starter });
    }

    await sb
      .from("profiles")
      .update({ onboarding_status: "import_laeuft" })
      .eq("id", nutzer.userId);
    const { error: auftragFehler } = await sb
      .from("auftraege")
      .insert({ user_id: nutzer.userId, typ: "onboarding" });
    if (auftragFehler) throw new Error(auftragFehler.message);

    return NextResponse.json({ ok: true, starter });
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
    let starterErgebnis: StarterErgebnis | null = null;

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

    // Interessen-Bereiche nachträglich setzen (/einstellungen-Chips):
    // neue Bereiche -> Starter-Pack nachlegen; abgewählte -> deren Themen aus.
    if (Array.isArray(body.labels_setzen)) {
      const neu = validiereLabels(body.labels_setzen);
      const profilRow = await holeRadarProfil(nutzer.userId).catch(() => null);
      const interessen = (profilRow?.interessen_profil as Record<string, unknown>) || {};
      const alt = ((interessen.interessen_labels as string[]) || []);
      await sb.from("radar_profile").upsert({
        user_id: nutzer.userId,
        interessen_profil: { ...interessen, interessen_labels: neu },
        aktualisiert_am: new Date().toISOString(),
      });
      const dazu = neu.filter((l) => !alt.includes(l));
      const weg = alt.filter((l) => !neu.includes(l));
      if (dazu.length > 0) starterErgebnis = await starterPackAnwenden(sb, nutzer.userId, dazu);
      for (const bereich of weg) {
        const slugs = starterPack([bereich]).themen.map((t) => t.slug);
        if (slugs.length > 0) {
          await sb.from("themen").update({ aktiv: false })
            .eq("user_id", nutzer.userId).in("slug", slugs);
        }
      }
    }

    // Vorschläge des Radars (quelle=lerner, aktiv=false) übernehmen/verwerfen
    if (body.vorschlag && typeof body.vorschlag === "object") {
      const v = body.vorschlag as { typ?: string; slug?: string; id?: number; aktion?: string };
      const uebernehmen = v.aktion === "uebernehmen";
      if (v.typ === "thema" && v.slug) {
        if (uebernehmen) {
          await sb.from("themen").update({ aktiv: true })
            .eq("user_id", nutzer.userId).eq("slug", v.slug);
        } else {
          await sb.from("themen").delete()
            .eq("user_id", nutzer.userId).eq("slug", v.slug).eq("quelle", "lerner");
        }
      } else if (v.typ === "query" && v.id) {
        if (uebernehmen) {
          await sb.from("suchqueries").update({ aktiv: true })
            .eq("user_id", nutzer.userId).eq("id", Number(v.id));
        } else {
          await sb.from("suchqueries").delete()
            .eq("user_id", nutzer.userId).eq("id", Number(v.id)).eq("quelle", "lerner");
        }
      }
    }

    // Rezepte-Radar an/aus (nur wenn der Plan es erlaubt)
    if (typeof body.rezepte_aktiv === "boolean") {
      const konto = await holeProfil(nutzer.userId).catch(() => null);
      const { planLimits } = await import("@/lib/plan");
      if (planLimits(konto?.plan, konto?.limits).rezepte) {
        const { speichereEinstellungsWert } = await import("@/lib/daten");
        await speichereEinstellungsWert(nutzer.userId, "rezepte_aktiv", body.rezepte_aktiv);
      }
    }

    if (body.fertig) {
      await sb
        .from("profiles")
        .update({ onboarding_status: "fertig" })
        .eq("id", nutzer.userId);
      // Sofort einen VOLLEN Lauf anstoßen (typ 'lauf' = Akquise mit den
      // frischen Queries des Nutzers + direkt seine Kuration) — erste eigene
      // Funde in ~15-30 min statt erst beim nächsten Cron-Slot.
      await sb.from("auftraege").insert({ user_id: nutzer.userId, typ: "lauf" });
    }
    return NextResponse.json({ ok: true, starter: starterErgebnis });
  } catch (e) {
    console.error("[api/onboarding PUT]", e);
    return NextResponse.json({ fehler: "Speichern fehlgeschlagen" }, { status: 500 });
  }
}
