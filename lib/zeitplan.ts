// lib/zeitplan.ts — EINE Quelle der Wahrheit für den Scraper-Zeitplan im UI.
// Muss zu deploy/crontab passen (Container-TZ = UTC):
//   0 */4 * * *   youtube+tiktok  (alle 4 h zur vollen Stunde: 0,4,8,…,20)
//   30 5 * * *    instagram + Transkripte
//   30 8 * * *    Rezepte-Radar
// Wird von /api/agenten UND der Inbox-Such-Statusleiste genutzt, damit die
// Anzeige "nächster Lauf" nie vom echten Cron abdriftet.

/** Nächster youtube+tiktok-Lauf (das, was neue Videos findet): 0/4/8/12/16/20 UTC. */
export function naechsteVideoSuche(jetzt: Date = new Date()): Date {
  const t = new Date(jetzt);
  t.setUTCMinutes(0, 0, 0);
  // auf die nächste durch 4 teilbare Stunde (echt in der Zukunft) springen
  do {
    t.setUTCHours(t.getUTCHours() + 1);
  } while (t.getUTCHours() % 4 !== 0 || t <= jetzt);
  return t;
}

/** Frühester nächster automatischer Lauf über ALLE Cron-Jobs (für /agenten). */
export function naechsterLauf(jetzt: Date = new Date()): Date {
  const kandidaten: Date[] = [naechsteVideoSuche(jetzt)];
  for (const [stunde, minute] of [
    [5, 30],
    [8, 30],
  ] as const) {
    const t = new Date(jetzt);
    t.setUTCHours(stunde, minute, 0, 0);
    if (t <= jetzt) t.setUTCDate(t.getUTCDate() + 1);
    kandidaten.push(t);
  }
  kandidaten.sort((a, b) => a.getTime() - b.getTime());
  return kandidaten[0];
}
