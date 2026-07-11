// lib/auth.ts — Zentrale Identitäts-Auflösung (Phase 0, Multi-Tenant-Fundament).
// AUTH_MODUS=code     → wie bisher: alle teilen sich einen Zugangscode (Default)
// AUTH_MODUS=supabase → Supabase-Session (E-Mail + Passwort) ist Pflicht
// AUTH_MODUS=beides   → Zugangscode ODER Supabase-Session gelten
// ACHTUNG: NICHT in middleware.ts importieren (zieht next/headers in die Edge-Bundle).

import { cookies } from "next/headers";

export type AuthModus = "code" | "supabase" | "beides";

/** Liest AUTH_MODUS aus der Umgebung (lowercase, getrimmt). Default: "code". */
export function authModus(): AuthModus {
  const m = (process.env.AUTH_MODUS || "").trim().toLowerCase();
  if (m === "supabase") return "supabase";
  if (m === "beides") return "beides";
  return "code";
}

export interface Nutzer {
  userId: string;
  email: string | null;
  quelle: "supabase" | "code";
}

/**
 * Versucht, die Supabase-Session aus den Request-Cookies zu lesen.
 * Liefert null, wenn ENV fehlt, keine Session existiert oder etwas schiefgeht.
 */
async function supabaseNutzer(): Promise<Nutzer | null> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;

  try {
    const { createServerClient } = await import("@supabase/ssr");
    const cookieStore = await cookies();
    const supabase = createServerClient(url, key, {
      cookies: {
        getAll: () => cookieStore.getAll(),
        // No-Op: Server Components dürfen keine Cookies setzen —
        // den Token-Refresh übernimmt die Middleware.
        setAll: () => {},
      },
    });
    const { data } = await supabase.auth.getUser();
    if (data.user) {
      return {
        userId: data.user.id,
        email: data.user.email ?? null,
        quelle: "supabase",
      };
    }
  } catch (e) {
    console.error("[auth] Supabase-Session konnte nicht gelesen werden:", e);
  }
  return null;
}

/**
 * Ermittelt den aktuellen Nutzer der Anfrage.
 * Modus "supabase"/"beides": erst Supabase-Session versuchen.
 * Fallback (immer, auch im Modus "code"): der Standard-Nutzer des
 * Zugangscode-Betriebs — so bleibt bestehendes Verhalten identisch.
 */
export async function aktuellerNutzer(): Promise<Nutzer> {
  if (authModus() !== "code") {
    const nutzer = await supabaseNutzer();
    if (nutzer) return nutzer;
  }
  return {
    userId: process.env.RADAR_STANDARD_USER || "lokal",
    email: null,
    quelle: "code",
  };
}
