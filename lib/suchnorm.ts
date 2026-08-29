// lib/suchnorm.ts — EINE Normalisierung für Suchbegriffe (Spiegel von
// scraper/themenwelt.query_norm): trim, alle führenden '#' weg, lowercase.
// Wird für den Join suchqueries ↔ scrape_status (plattform, query_norm) genutzt.
export function suchNorm(q: unknown): string {
  return String(q ?? "").trim().replace(/^#+/, "").toLowerCase();
}
