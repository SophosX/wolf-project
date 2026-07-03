"use client";

// Personen-Dashboard (Gamification): Wem reagiert Chris wie oft, welche Themen,
// wie viele Views haben seine Reaktionen geholt — und "Folgen" setzt die Person
// direkt auf die Scraper-Watchlist.

import { useState } from "react";
import { formatViews, relativeZeit } from "@/lib/format";
import { themaLabel } from "@/lib/typen";
import type { Person, PersonenDaten } from "@/lib/personen";

const TON_LABEL: Record<string, string> = {
  sachlich: "🧊 sachlich",
  scharf: "🌶️ scharf",
  abrechnung: "🔥 Abrechnung",
};

const TYP_LABEL: Record<string, string> = {
  influencer: "Influencer",
  medium: "Medium",
  arzt: "Arzt/Ärztin",
  marke: "Marke",
  sonstige: "Sonstige",
};

function PersonKarte({ person }: { person: Person }) {
  const [folgt, setFolgt] = useState(person.folgt);
  const [offen, setOffen] = useState(false);
  const [laedt, setLaedt] = useState(false);

  async function toggleFolgen() {
    setLaedt(true);
    const neu = !folgt;
    setFolgt(neu); // optimistisch
    const res = await fetch("/api/personen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: person.name, folgen: neu, handles: person.handles }),
    });
    if (!res.ok) setFolgt(!neu); // zurückrollen
    setLaedt(false);
  }

  const letzte = person.reaktionen[0];
  const viewsGesamt = person.reaktionen.reduce((s, r) => s + (r.views || 0), 0);

  return (
    <div className="karte" style={{ padding: "16px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <b style={{ fontSize: "1.05rem" }}>{person.name}</b>
        <span className="chip">{TYP_LABEL[person.typ] || person.typ}</span>
        <span className="chip">{TON_LABEL[person.ton] || person.ton}</span>
        <span style={{ marginLeft: "auto" }}>
          {"★".repeat(person.prioritaet)}
          <span style={{ opacity: 0.3 }}>{"★".repeat(Math.max(0, 5 - person.prioritaet))}</span>
        </span>
      </div>

      <div style={{ display: "flex", gap: 18, margin: "10px 0", flexWrap: "wrap" }}>
        <span>
          <b style={{ color: "var(--gelb, #FFB800)", fontSize: "1.3rem" }}>
            {person.reaktionen.length}
          </b>{" "}
          Reaktionen
        </span>
        <span>
          <b style={{ fontSize: "1.3rem" }}>{formatViews(viewsGesamt)}</b> Views geholt
        </span>
        {letzte && <span style={{ opacity: 0.7 }}>zuletzt {relativeZeit(letzte.datum)}</span>}
      </div>

      {person.themen.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          {person.themen.map((t) => (
            <span key={t} className="chip">
              # {themaLabel(t)}
            </span>
          ))}
        </div>
      )}

      <div className="aktionen" style={{ marginTop: 8 }}>
        <button className="btn" onClick={toggleFolgen} disabled={laedt}
          style={folgt ? { background: "var(--gelb, #FFB800)", color: "#141618", fontWeight: 700 } : {}}>
          {folgt ? "✓ Du folgst" : "＋ Folgen"}
        </button>
        {person.reaktionen.length > 0 && (
          <button className="btn" onClick={() => setOffen(!offen)}>
            {offen ? "▲ Historie" : `▼ Historie (${person.reaktionen.length})`}
          </button>
        )}
      </div>

      {offen && (
        <ul style={{ marginTop: 10, paddingLeft: 18, lineHeight: 1.7 }}>
          {person.reaktionen.map((r) => (
            <li key={r.video_id}>
              <a href={`https://www.youtube.com/watch?v=${r.video_id}`} target="_blank"
                 rel="noreferrer" style={{ color: "inherit" }}>
                {r.titel}
              </a>{" "}
              <span style={{ opacity: 0.6 }}>
                · {formatViews(r.views)} Views · {r.datum}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function PersonenDashboard({ daten }: { daten: PersonenDaten }) {
  const s = daten.statistik;
  return (
    <>
      {/* Gamification-Kopf: Chris' Bilanz auf einen Blick */}
      <div className="karte" style={{ padding: 16, marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 26, flexWrap: "wrap", alignItems: "baseline" }}>
          <span>
            <b style={{ fontSize: "1.7rem", color: "var(--gelb, #FFB800)" }}>
              {s.reaktionen_gesamt}
            </b>{" "}
            Richtigstellungen
          </span>
          <span>
            <b style={{ fontSize: "1.7rem" }}>{formatViews(s.views_durch_reaktionen)}</b>{" "}
            Views aufgeklärt
          </span>
          <span>
            <b style={{ fontSize: "1.7rem" }}>{s.gefolgt}</b>/{s.personen_gesamt} gefolgt
          </span>
        </div>
        {s.top_themen.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
            {s.top_themen.map((t) => (
              <span key={t.thema} className="chip">
                # {themaLabel(t.thema)} × {t.anzahl}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="karten">
        {daten.personen.map((p) => (
          <PersonKarte key={p.name} person={p} />
        ))}
        {daten.personen.length === 0 && (
          <div className="leer">
            Wissensbasis wird noch aufgebaut — Personen erscheinen nach dem nächsten Analyse-Lauf.
          </div>
        )}
      </div>
    </>
  );
}
