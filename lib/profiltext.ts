// lib/profiltext.ts — kleine Helfer, die Nutzer-Profildaten in Prompt-Text
// übersetzen. Lokal-Modus: Christian-Fallbacks (Verhalten unverändert).

import { datenModus, holeRadarProfil } from "./daten";

const CHRISTIAN_FALLBACK =
  "Christian Wolf (Fitness-Creator, stellt Ernährungs-Falschinfos richtig)";

/** Kurzbeschreibung des Creators für Prompts (z.B. Vorschlags-Ableitung). */
export async function creatorBeschreibung(userId: string): Promise<string> {
  if (datenModus() !== "supabase") return CHRISTIAN_FALLBACK;
  try {
    const profil = await holeRadarProfil(userId);
    const marke = (profil?.marke as string) || null;
    const nische = (profil?.nische as string) || null;
    if (marke || nische) {
      return (
        "Der Creator" +
        (marke ? " „" + marke + "“" : "") +
        (nische ? " (Nische: " + nische + ", stellt Falschinfos richtig)" : "")
      );
    }
  } catch (e) {
    console.error("[profiltext] radar_profile nicht ladbar:", e);
  }
  return CHRISTIAN_FALLBACK;
}

/** Themen-Slugs des Nutzers (Supabase) oder der übergebene Fallback (lokal). */
export async function holeThemenSlugs(
  userId: string,
  fallback: string[]
): Promise<string[]> {
  if (datenModus() !== "supabase") return fallback;
  try {
    const { holeThemen } = await import("./daten");
    const themen = await holeThemen(userId);
    const slugs = themen.map((t) => t.slug).filter(Boolean);
    if (slugs.length > 0) return slugs;
  } catch (e) {
    console.error("[profiltext] themen nicht ladbar:", e);
  }
  return fallback;
}
