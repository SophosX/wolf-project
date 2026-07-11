// lib/adminGate.ts — Zugangsprüfung für den Admin-Bereich.
// WICHTIG: Der offene Zugangscode-Betrieb (quelle "code") zählt NICHT als
// Admin, auch wenn er auf den Admin-Tenant auflöst — für /admin ist eine
// echte Supabase-Anmeldung mit rolle=admin Pflicht.

import { aktuellerNutzer, type Nutzer } from "./auth";
import { datenModus, holeProfil } from "./daten";

export async function adminNutzer(): Promise<Nutzer | null> {
  if (datenModus() !== "supabase") return null;
  const nutzer = await aktuellerNutzer();
  if (nutzer.quelle !== "supabase") return null;
  try {
    const profil = await holeProfil(nutzer.userId);
    return profil?.rolle === "admin" ? nutzer : null;
  } catch (e) {
    console.error("[adminGate] Profil nicht ladbar:", e);
    return null;
  }
}
