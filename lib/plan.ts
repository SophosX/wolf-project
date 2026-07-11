// lib/plan.ts — Free/Pro-Limits als Code-Konstanten (Single Source in TS;
// scraper/plan_limits.py spiegelt dieselben Werte für den Python-Teil).
// Billing ist bewusst außerhalb: profiles.plan setzt zunächst der Admin.

export type Plan = "free" | "pro";

export interface PlanLimits {
  /** Videos beim Kanal-Import im Onboarding */
  importVideos: number;
  /** max. aktive Themen im Profil */
  themen: number;
  /** max. aktive Suchqueries (über alle Plattformen) */
  suchqueries: number;
  /** max. Personen auf der Beobachtungsliste */
  watchlist: number;
  /** Kurationsläufe pro Tag (Free 1x täglich, Pro alle 4 h) */
  kurationProTag: number;
  /** max. NEUE Inbox-Zuordnungen pro Kurationslauf */
  kurationMaxNeu: number;
  /** Skript-Generierungen pro Woche (Infinity = unbegrenzt) */
  skripteProWoche: number;
  /** Rezepte-Radar verfügbar? */
  rezepte: boolean;
  /** Manueller Websuche-Faktencheck verfügbar? */
  webcheck: boolean;
}

export const PLAN_LIMITS: Record<Plan, PlanLimits> = {
  free: {
    importVideos: 25,
    themen: 6,
    suchqueries: 12,
    watchlist: 5,
    kurationProTag: 1,
    kurationMaxNeu: 10,
    skripteProWoche: 3,
    rezepte: false,
    webcheck: false,
  },
  pro: {
    importVideos: 200,
    themen: 25,
    suchqueries: 50,
    watchlist: 25,
    kurationProTag: 6,
    kurationMaxNeu: 25,
    skripteProWoche: Infinity,
    rezepte: true,
    webcheck: true,
  },
};

export function planLimits(plan: string | null | undefined): PlanLimits {
  return PLAN_LIMITS[(plan as Plan) || "free"] || PLAN_LIMITS.free;
}
