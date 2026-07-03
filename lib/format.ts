// Formatierungs-Helfer (deutsch), client- und serverseitig nutzbar

/** 1234567 → "1,2 Mio." · 87500 → "87.500" · 950 → "950" */
export function formatViews(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "–";
  if (n >= 1_000_000) {
    const mio = n / 1_000_000;
    const s = mio >= 10 ? Math.round(mio).toString() : mio.toFixed(1).replace(".", ",").replace(",0", "");
    return s + " Mio.";
  }
  return n.toLocaleString("de-DE");
}

/** Kompakt für Velocity: 80000 → "80k" · 1200000 → "1,2 Mio." */
export function formatKompakt(n: number): string {
  if (n >= 1_000_000) return formatViews(n);
  if (n >= 1_000) return Math.round(n / 1000) + "k";
  return Math.round(n).toString();
}

/** Views pro Tag seit Upload → "+80k/Tag" */
export function velocity(views: number, veroeffentlicht: string): string {
  const tage = Math.max(
    1,
    (Date.now() - new Date(veroeffentlicht).getTime()) / 86_400_000
  );
  const proTag = views / tage;
  if (proTag < 50) return ""; // zu klein, nicht anzeigen
  return "+" + formatKompakt(proTag) + "/Tag";
}

/** ISO → "vor 3 Tagen" / "heute" */
export function relativeZeit(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const stunden = diffMs / 3_600_000;
  if (stunden < 1) return "gerade eben";
  if (stunden < 24) return "vor " + Math.round(stunden) + " Std.";
  const tage = Math.round(stunden / 24);
  if (tage === 1) return "gestern";
  if (tage < 31) return "vor " + tage + " Tagen";
  const monate = Math.round(tage / 30);
  return "vor " + monate + (monate === 1 ? " Monat" : " Monaten");
}

/** ISO → "02.07.2026, 14:30" */
export function formatDatum(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Sekunden → "0:58" bzw. "12:03" */
export function formatDauer(s: number | null | undefined): string {
  if (s == null) return "";
  const min = Math.floor(s / 60);
  const sek = Math.round(s % 60);
  return min + ":" + String(sek).padStart(2, "0");
}
