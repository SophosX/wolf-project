// /personen — Gamification-Dashboard: Wem reagiert Chris, wie oft, welche Themen.
// "Folgen" setzt die Person auf die Scraper-Watchlist (wird ab dem nächsten Lauf überwacht).

import PersonenDashboard from "@/components/PersonenDashboard";
import { aktuellerNutzer } from "@/lib/auth";
import { holePersonen } from "@/lib/personen";

export const dynamic = "force-dynamic";

export default async function PersonenSeite() {
  const nutzer = await aktuellerNutzer();
  const daten = await holePersonen(nutzer.userId);
  return (
    <>
      <div className="banner">
        <b>Deine Reaktions-Bilanz.</b> Aus deinen bisherigen Richtigstellungen
        extrahiert{daten.stand ? ` (Stand ${daten.stand})` : ""}. Personen, denen du
        folgst, werden von den Suchagenten auf YouTube, TikTok und Instagram überwacht —
        neue Falschaussagen landen automatisch in der Inbox.
      </div>
      <PersonenDashboard daten={daten} />
      {daten.reaktions_ausloeser.length > 0 && (
        <div className="karte" style={{ padding: 16, marginTop: 14 }}>
          <div className="abschnitt-titel">Was dich erfahrungsgemäß triggert</div>
          <ul style={{ paddingLeft: 18, lineHeight: 1.8 }}>
            {daten.reaktions_ausloeser.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
