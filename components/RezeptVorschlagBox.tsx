"use client";

// Rezept-Vorschlags-Box: Chris sagt dem Rezepte-Radar in Freitext, wonach er
// suchen soll — die abgeleiteten Suchanfragen laufen 7 Tage in der täglichen
// Rezept-Suche mit und sind hier sichtbar & jederzeit entfernbar.

import { useEffect, useState } from "react";
import type { RezeptVorschlag } from "@/lib/vorschlaege";

export default function RezeptVorschlagBox() {
  const [text, setText] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [vorschlaege, setVorschlaege] = useState<RezeptVorschlag[]>([]);

  async function laden() {
    try {
      const res = await fetch("/api/rezepte/vorschlag");
      const daten = await res.json();
      setVorschlaege(daten.vorschlaege || []);
    } catch {
      /* Liste ist nicht kritisch */
    }
  }

  useEffect(() => {
    laden();
  }, []);

  /** Suchqueries laufen 7 Tage (QUERY_LAUFZEIT_TAGE serverseitig). */
  function restTage(v: RezeptVorschlag): number {
    const bis = new Date(v.zeit).getTime() + 7 * 86_400_000;
    return Math.max(0, Math.ceil((bis - Date.now()) / 86_400_000));
  }

  async function senden() {
    if (text.trim().length < 5 || laeuft) return;
    setLaeuft(true);
    setFehler(null);
    try {
      const res = await fetch("/api/rezepte/vorschlag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.trim() }),
      });
      const daten = await res.json();
      if (!res.ok) throw new Error(daten.fehler || "Fehler " + res.status);
      setText("");
      setVorschlaege((alt) => [daten.vorschlag, ...alt]);
    } catch (e) {
      setFehler(e instanceof Error ? e.message : "Vorschlag fehlgeschlagen");
    } finally {
      setLaeuft(false);
    }
  }

  async function entfernen(zeit: string) {
    setVorschlaege((alt) => alt.filter((v) => v.zeit !== zeit));
    try {
      const res = await fetch("/api/rezepte/vorschlag", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zeit }),
      });
      if (!res.ok) throw new Error();
    } catch {
      laden();
    }
  }

  return (
    <section className="vorschlag-box">
      <h2 className="abschnitt-titel">🍳 Dein Rezept-Wunsch an den Radar</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 14, marginTop: 4 }}>
        Sag dem Radar, welche Rezepte er suchen soll — z.&nbsp;B. „High-Protein
        Frühstücksrezepte“ oder „kalorienarme Pasta-Alternativen“. Die Suche läuft
        7&nbsp;Tage im täglichen Rezepte-Lauf mit; mit ✕ beendest du sie sofort.
      </p>
      <div className="zeile" style={{ marginTop: 10, gap: 8, display: "flex" }}>
        <textarea
          rows={2}
          style={{ flex: 1 }}
          placeholder="Wonach soll der Rezepte-Radar suchen?"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              senden();
            }
          }}
        />
        <button className="btn primaer" disabled={laeuft || text.trim().length < 5} onClick={senden}>
          {laeuft ? "⏳ Radar denkt …" : "An den Radar senden"}
        </button>
      </div>
      {fehler && <p style={{ color: "var(--rot, #e5484d)", fontSize: 13 }}>{fehler}</p>}

      {vorschlaege.length > 0 && (
        <ul className="vorschlag-liste">
          {vorschlaege.slice(0, 6).map((v) => {
            const tage = restTage(v);
            return (
              <li key={v.zeit}>
                <div className="vorschlag-kopf">
                  <div className="vorschlag-text">„{v.text}“</div>
                  <span className={"vorschlag-badge" + (tage > 0 ? " aktiv" : "")}>
                    {tage > 0 ? `Suche aktiv · noch ${tage} Tag${tage === 1 ? "" : "e"}` : "Suche beendet"}
                  </span>
                  <button
                    className="vorschlag-entfernen"
                    title="Vorschlag entfernen — die Suche danach stoppt sofort"
                    onClick={() => entfernen(v.zeit)}
                  >
                    ✕
                  </button>
                </div>
                <div className="vorschlag-ableitung">
                  ↳ Suchen: {v.queries.map((q) => "„" + q + "“").join(", ")}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
