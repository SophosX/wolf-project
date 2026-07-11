// /personen — Gamification-Dashboard: Wem reagiert Chris, wie oft, welche Themen.
// "Folgen" setzt die Person auf die Scraper-Watchlist (wird ab dem nächsten Lauf überwacht).

import PersonenDashboard from "@/components/PersonenDashboard";
import PersonHinzufuegen from "@/components/PersonHinzufuegen";
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
      <PersonHinzufuegen />
      {daten.reaktions_ausloeser.length > 0 && (
        <div className="karte" style={{ padding: 16, marginTop: 14 }}>
          <div className="abschnitt-titel">Was dich erfahrungsgemäß triggert</div>
          {daten.trigger_details && daten.trigger_details.length > 0 ? (
            <ul style={{ paddingLeft: 18, lineHeight: 1.9 }}>
              {daten.trigger_details.map((t, i) => (
                <li key={i}>
                  {t.trigger}{" "}
                  {t.quelle === "feedback" && (
                    <span className="badge-frisch" title={"Stärke " + Math.round((t.staerke || 0) * 100) + " %"}>
                      🧠 gelernt aus deinem Feedback
                    </span>
                  )}
                  {t.quelle === "interview" && (
                    <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      · von dir bestätigt
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <ul style={{ paddingLeft: 18, lineHeight: 1.8 }}>
              {daten.reaktions_ausloeser.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          )}
          <p style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 8 }}>
            Diese Liste lebt: Sie wurde aus deinen Videos aufgebaut und schreibt
            sich anhand deiner Annehmen/Ablehnen-Entscheidungen täglich fort.
          </p>
        </div>
      )}
    </>
  );
}
