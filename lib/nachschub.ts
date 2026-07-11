// lib/nachschub.ts — On-Demand-Scraperlauf ("direkt neuer Content").
//
// Lokal-Modus: startet scraper/lauf_lokal.sh entkoppelt (der Wrapper hat einen
// Doppellauf-Lock, lädt .env und schreibt agent_runs → im Agenten-Panel sichtbar).
// Supabase-/Prod-Modus: kein lokaler Spawn möglich — dort übernimmt der
// GitHub-Actions-Cron (alle 4 h); die API meldet das transparent.

import { spawn } from "child_process";
import fs from "fs";
import path from "path";
import { datenModus, holeVideos } from "./daten";

const WRAPPER = path.join(process.cwd(), "scraper", "lauf_lokal.sh");
// Muss zum LOCK im Wrapper passen (lauf_lokal.sh) — fester Pfad, kein $TMPDIR
const LOCK = "/tmp/wolfradar-lauf.lock";
const INBOX_SCHWELLE = 6;

export function nachschubMoeglich(): boolean {
  return datenModus() === "lokal" && fs.existsSync(WRAPPER);
}

export function nachschubLaeuft(): boolean {
  return fs.existsSync(LOCK);
}

/** Startet einen Radar-Lauf (fire-and-forget). false, wenn nicht möglich/schon aktiv. */
export function starteNachschub(quellen = "youtube,tiktok"): boolean {
  if (!nachschubMoeglich() || nachschubLaeuft()) return false;
  try {
    const kind = spawn("/bin/sh", [WRAPPER, quellen], {
      detached: true,
      stdio: "ignore",
    });
    kind.unref();
    console.log("[nachschub] Radar-Lauf gestartet (" + quellen + ")");
    return true;
  } catch (e) {
    console.error("[nachschub] Start fehlgeschlagen:", e);
    return false;
  }
}

/** Nach Feedback-Aktionen: Inbox dünn? → Nachschub anstoßen (best effort). */
export async function nachschubBeiBedarf(userId: string): Promise<void> {
  if (!nachschubMoeglich() || nachschubLaeuft()) return;
  try {
    const inbox = await holeVideos(userId, { status: "inbox" });
    if (inbox.length < INBOX_SCHWELLE) starteNachschub();
  } catch {
    /* best effort — nie den Feedback-Flow blockieren */
  }
}
