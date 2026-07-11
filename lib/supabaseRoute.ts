// lib/supabaseRoute.ts — Supabase-Client für ROUTE HANDLER (Cookies schreibbar).
// Nur hier (und in der Middleware) dürfen Auth-Cookies GESETZT werden;
// lib/auth.ts liest sie ausschließlich. NICHT in Server Components verwenden.

import { cookies } from "next/headers";

export function supabaseAuthAktiv(): boolean {
  const modus = (process.env.AUTH_MODUS || "").trim().toLowerCase();
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  return modus !== "code" && Boolean(url && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
}

export async function supabaseRouteClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  const { createServerClient } = await import("@supabase/ssr");
  const store = await cookies();
  return createServerClient(url, key, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (zuSetzen) =>
        zuSetzen.forEach(({ name, value, options }) => store.set(name, value, options)),
    },
  });
}
