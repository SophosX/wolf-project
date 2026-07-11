// Feedback-Lernen: Annehmen/Ablehnen passt themen_boost an (∈ [-1,1])
// und hält menschenlesbare Notizen fest ("Was der Radar gelernt hat").

import { holeEinstellungen, speichereEinstellungen } from "./daten";
import { themaLabel } from "./typen";
import type { Video } from "./typen";

const SCHRITT = 0.15;
const MAX_NOTIZEN = 15;

export async function lernUpdate(
  userId: string,
  video: Video,
  aktion: string,
  kommentar?: string
): Promise<void> {
  const einstellungen = await holeEinstellungen(userId);
  const boost = einstellungen.gelernt.themen_boost;
  const slug = video.claim?.thema;
  const label = slug ? themaLabel(slug) : "unbekannt";

  let notiz: string | null = null;

  if (slug && aktion === "angenommen") {
    boost[slug] = Math.min(1, Math.round(((boost[slug] || 0) + SCHRITT) * 100) / 100);
    notiz = "Thema „" + label + "“ angenommen → wird höher gewichtet (Boost " + boost[slug] + ")";
  } else if (slug && aktion === "abgelehnt") {
    boost[slug] = Math.max(-1, Math.round(((boost[slug] || 0) - SCHRITT) * 100) / 100);
    notiz =
      "Thema „" + label + "“ abgelehnt" +
      (kommentar ? " („" + kommentar + "“)" : "") +
      " → wird niedriger gewichtet (Boost " + boost[slug] + ")";
  } else if (kommentar) {
    notiz = "Kommentar zu „" + video.titel.slice(0, 60) + "“: „" + kommentar + "“";
  }

  if (notiz) {
    einstellungen.gelernt.notizen = [notiz, ...einstellungen.gelernt.notizen].slice(0, MAX_NOTIZEN);
  }
  einstellungen.zuletzt_gelernt = new Date().toISOString();
  await speichereEinstellungen(userId, einstellungen);
}
