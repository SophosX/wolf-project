// GET  /api/suchstatus — "Warum ist meine Inbox leer?" — Diagnose pro Nutzer:
//      Ertrag jeder eigenen Suchanfrage (scrape_status), Ergebnis der letzten
//      Kuration (agent_runs.detail), Empfehlung (warten / breiter / spezifizieren).
// POST /api/suchstatus {aktion:"breiter"} — alle eigenen Suchanfragen auf das
//      weiteste Fenster stellen und sofort einen Lauf anfordern.

import { NextRequest, NextResponse } from "next/server";
import { aktuellerNutzer } from "@/lib/auth";
import {
  datenModus,
  fordereLaufAn,
  holeAgentStatus,
  holeEinstellungsWert,
  laufAngefragt,
  supabaseAdmin,
  zaehleStatus,
} from "@/lib/daten";
import { interessenBereiche, starterPack } from "@/lib/interessen";
import { planLimits } from "@/lib/plan";
import { naechsteVideoSuche } from "@/lib/zeitplan";

export const dynamic = "force-dynamic";

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface QueryStatus {
  id: number;
  plattform: string;
  query: string;
  aktiv: boolean;
  quelle: string;
  letzte_treffer: number;
  leer_folge: number;
  zuletzt: string | null;
  fenster: string | null;
  nie_gesucht: boolean;
}

export interface KurationDiagnose {
  zeit: string;
  neu: number;
  geflaggt: number;
  detail: Record<string, number>;
}

export type Empfehlung = "laeuft" | "warten" | "breiter" | "spezifizieren" | "ok";

function norm(q: string): string {
  return String(q || "").trim().replace(/^#/, "").toLowerCase();
}

export async function GET() {
  try {
    if (datenModus() !== "supabase") {
      return NextResponse.json({ fehler: "nur im Multi-Tenant-Betrieb" }, { status: 501 });
    }
    const nutzer = await aktuellerNutzer();
    const sb = await supabaseAdmin();
    const uid = nutzer.userId;

    const [
      { data: queriesRoh },
      { data: statusRoh },
      { data: kurationRoh },
      { data: themenRoh },
      { data: profilRoh },
      { data: kontoRoh },
      angefragt,
      agentStatus,
      zaehler,
      hinweise,
    ] = await Promise.all([
      sb.from("suchqueries").select("id, plattform, query, aktiv, quelle").eq("user_id", uid)
        .order("id", { ascending: true }),
      sb.from("scrape_status").select("plattform, query_norm, zuletzt, letzte_treffer, leer_folge, fenster"),
      sb.from("agent_runs").select("zeit, neu, geflaggt, detail").eq("user_id", uid)
        .eq("typ", "kuration").order("zeit", { ascending: false }).limit(1),
      sb.from("themen").select("slug, aktiv").eq("user_id", uid),
      sb.from("radar_profile").select("interessen_profil").eq("user_id", uid).maybeSingle(),
      sb.from("profiles").select("plan, limits").eq("id", uid).maybeSingle(),
      laufAngefragt(uid),
      holeAgentStatus(),
      zaehleStatus(uid).catch(() => ({} as Record<string, number>)),
      holeEinstellungsWert<any[]>(uid, "such_hinweise", []).catch(() => []),
    ]);

    const statusMap = new Map<string, any>();
    for (const s of statusRoh || []) statusMap.set(s.plattform + "|" + s.query_norm, s);

    const queries: QueryStatus[] = (queriesRoh || []).map((q: any) => {
      const s = statusMap.get(q.plattform + "|" + norm(q.query));
      return {
        id: q.id,
        plattform: q.plattform,
        query: q.query,
        aktiv: Boolean(q.aktiv),
        quelle: q.quelle,
        letzte_treffer: Number(s?.letzte_treffer || 0),
        leer_folge: Number(s?.leer_folge || 0),
        zuletzt: s?.zuletzt || null,
        fenster: s?.fenster || null,
        nie_gesucht: !s?.zuletzt,
      };
    });
    const aktive = queries.filter((q) => q.aktiv);
    const gesucht = aktive.filter((q) => !q.nie_gesucht);
    const mitTreffern = gesucht.filter((q) => q.letzte_treffer > 0);
    const ohneTreffer = gesucht.filter((q) => q.letzte_treffer === 0);
    const zusammenfassung = {
      gesamt: aktive.length,
      gesucht: gesucht.length,
      nie_gesucht: aktive.length - gesucht.length,
      mit_treffern: mitTreffern.length,
      ohne_treffer: ohneTreffer.length,
      treffer_letzter: gesucht.reduce((s, q) => s + q.letzte_treffer, 0),
      tote: aktive.filter((q) => q.leer_folge >= 3).length,
    };

    const k = (kurationRoh || [])[0];
    const kuration: KurationDiagnose | null = k
      ? { zeit: k.zeit, neu: k.neu || 0, geflaggt: k.geflaggt || 0, detail: (k.detail as any) || {} }
      : null;

    // Interessen-Bereiche ohne einziges aktives Starter-Thema — nur relevant,
    // wenn das Plan-Cap tatsaechlich erreicht ist (Kanal-Import-Nutzer haben
    // eigene Themen-Slugs, dort waere die Meldung falsch).
    const labels: string[] =
      ((profilRoh?.interessen_profil as any)?.interessen_labels as string[]) || [];
    const aktiveSlugs = new Set((themenRoh || []).filter((t: any) => t.aktiv).map((t: any) => t.slug));
    const limits = planLimits(kontoRoh?.plan, kontoRoh?.limits as any);
    const capErreicht = aktiveSlugs.size >= limits.themen;
    const bereicheOhneThema = !capErreicht ? [] : interessenBereiche()
      .filter((b) => labels.includes(b.slug))
      .filter((b) => !starterPack([b.slug]).themen.some((t) => aktiveSlugs.has(t.slug)))
      .map((b) => ({ slug: b.slug, label: b.label, emoji: b.emoji }));

    const laeuft = Boolean(agentStatus?.aktiv) || angefragt;
    let empfehlung: Empfehlung = "ok";
    if (laeuft) empfehlung = "laeuft";
    else if (aktive.length === 0) empfehlung = "spezifizieren";
    else if (gesucht.length === 0 || !kuration) empfehlung = "warten";
    else if (zusammenfassung.treffer_letzter === 0 || ohneTreffer.length * 2 >= gesucht.length) {
      empfehlung = "breiter";
    } else if ((kuration.detail.geflaggt || 0) === 0 && (zaehler.inbox || 0) === 0
               && (zaehler.strittig || 0) === 0) {
      empfehlung = "spezifizieren";
    }

    return NextResponse.json({
      queries,
      zusammenfassung,
      kuration,
      lauf: { angefragt, aktiv: Boolean(agentStatus?.aktiv) },
      naechsteSuche: naechsteVideoSuche().toISOString(),
      hinweise: Array.isArray(hinweise) ? hinweise.slice(-8).reverse() : [],
      bestand: {
        inbox: zaehler.inbox || 0,
        strittig: zaehler.strittig || 0,
        archiv: zaehler.archiv || 0,
      },
      bereiche_ohne_thema: bereicheOhneThema,
      empfehlung,
    });
  } catch (e) {
    console.error("[api/suchstatus GET]", e);
    return NextResponse.json({ fehler: "Suchstatus nicht ladbar" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    if (datenModus() !== "supabase") {
      return NextResponse.json({ fehler: "nur im Multi-Tenant-Betrieb" }, { status: 501 });
    }
    const nutzer = await aktuellerNutzer();
    const body = await req.json().catch(() => ({}));
    if (body.aktion !== "breiter") {
      return NextResponse.json({ fehler: "Unbekannte Aktion" }, { status: 400 });
    }
    const sb = await supabaseAdmin();
    const uid = nutzer.userId;
    const { data: queries } = await sb
      .from("suchqueries").select("plattform, query").eq("user_id", uid).eq("aktiv", true);
    if (!queries || queries.length === 0) {
      return NextResponse.json(
        { fehler: "Du hast noch keine aktiven Suchanfragen — lege unter Profil welche an." },
        { status: 400 }
      );
    }
    // Weitestes Fenster erzwingen: leer_folge >= 2 => YouTube 'year', TikTok/IG 'breit'.
    // zuletzt bleibt stehen (Mindestabstand 1 h bleibt als Kostenschutz).
    const { data: vorhanden } = await sb
      .from("scrape_status").select("plattform, query_norm, zuletzt, treffer_gesamt, leer_folge");
    const alt = new Map<string, any>();
    for (const v of vorhanden || []) alt.set(v.plattform + "|" + v.query_norm, v);
    const zeilen = queries.map((q: any) => {
      const key = q.plattform + "|" + norm(q.query);
      const a = alt.get(key);
      return {
        plattform: q.plattform,
        query_norm: norm(q.query),
        zuletzt: a?.zuletzt || null,
        treffer_gesamt: a?.treffer_gesamt || 0,
        leer_folge: Math.max(2, Number(a?.leer_folge || 0)),
        fenster: "breit",
      };
    });
    const { error } = await sb
      .from("scrape_status").upsert(zeilen, { onConflict: "plattform,query_norm" });
    if (error) throw new Error(error.message);

    let gestartet = false;
    const [angefragt, status] = await Promise.all([laufAngefragt(uid), holeAgentStatus()]);
    if (!angefragt && !status?.aktiv) {
      await fordereLaufAn(uid);
      gestartet = true;
    }
    return NextResponse.json({ ok: true, queries: zeilen.length, gestartet, angefragt });
  } catch (e) {
    console.error("[api/suchstatus POST]", e);
    return NextResponse.json({ fehler: "Breiter suchen fehlgeschlagen" }, { status: 500 });
  }
}
