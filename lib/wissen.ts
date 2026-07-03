// Lädt Stilguide + Reaktions-Playbook + Themenlandkarte aus scraper/wissen/
// (fs, nur serverseitig, beim ersten Zugriff gecacht — NICHT duplizieren!)

import fs from "fs";
import path from "path";

export interface Wissen {
  stilguide: string;
  playbook: string;
  themenlandkarte: string;
}

let cache: Wissen | null = null;

function liesMd(datei: string): string {
  const pfad = path.join(process.cwd(), "scraper", "wissen", datei);
  try {
    return fs.readFileSync(pfad, "utf-8");
  } catch (e) {
    console.error("[wissen] Konnte " + pfad + " nicht lesen:", e);
    return "";
  }
}

export function ladeWissen(): Wissen {
  if (!cache) {
    cache = {
      stilguide: liesMd("chris_stilguide.md"),
      playbook: liesMd("reaktions_playbook.md"),
      themenlandkarte: liesMd("themenlandkarte.md"),
    };
  }
  return cache;
}
