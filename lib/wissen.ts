// Lädt Stilguide + Reaktions-Playbook + Themenlandkarte.
// Supabase-Modus: aus radar_profile DES NUTZERS (Onboarding-Ergebnis);
// Lokal-Modus / fehlende Profilfelder: aus scraper/wissen/ (Christian-Dateien).
// (fs-Reads beim ersten Zugriff gecacht — NICHT duplizieren!)

import fs from "fs";
import path from "path";
import { datenModus, holeRadarProfil } from "./daten";

export interface Wissen {
  stilguide: string;
  playbook: string;
  themenlandkarte: string;
  /** Anzeige-/Prompt-Identität des Creators (null = Christian-Fallback) */
  creatorBeschreibung: string | null;
  kernBotschaft: string | null;
}

let dateiCache: { stilguide: string; playbook: string; themenlandkarte: string } | null = null;

function liesMd(datei: string): string {
  const pfad = path.join(process.cwd(), "scraper", "wissen", datei);
  try {
    return fs.readFileSync(pfad, "utf-8");
  } catch (e) {
    console.error("[wissen] Konnte " + pfad + " nicht lesen:", e);
    return "";
  }
}

function ladeDateien() {
  if (!dateiCache) {
    dateiCache = {
      stilguide: liesMd("chris_stilguide.md"),
      playbook: liesMd("reaktions_playbook.md"),
      themenlandkarte: liesMd("themenlandkarte.md"),
    };
  }
  return dateiCache;
}

export async function ladeWissen(userId?: string): Promise<Wissen> {
  const dateien = ladeDateien();
  if (userId && datenModus() === "supabase") {
    try {
      const profil = await holeRadarProfil(userId);
      if (profil) {
        const marke = (profil.marke as string) || (profil.nische as string) || null;
        const positionen = (profil.positionen as { thema?: string; position?: string }[]) || [];
        const positionenText = positionen
          .filter((p) => p?.position)
          .map((p) => "- " + (p.thema ? p.thema + ": " : "") + p.position)
          .join("\n");
        return {
          stilguide: (profil.stilguide as string) || dateien.stilguide,
          playbook: (profil.playbook as string) || dateien.playbook,
          themenlandkarte: positionenText || dateien.themenlandkarte,
          creatorBeschreibung: marke
            ? "den Creator „" + marke + "“ (Nische: " + ((profil.nische as string) || "?") + ")"
            : null,
          kernBotschaft: null,
        };
      }
    } catch (e) {
      console.error("[wissen] radar_profile nicht ladbar — Datei-Fallback:", e);
    }
  }
  return { ...dateien, creatorBeschreibung: null, kernBotschaft: null };
}
