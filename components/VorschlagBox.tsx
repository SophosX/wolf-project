"use client";

// Vorschlags-Box: Chris schreibt dem Radar in Freitext, was er sehen will —
// der Suchalgorithmus adaptiert sich sofort (Queries, Watchlist, Themen-Boosts).

import { useEffect, useState } from "react";
import type { Vorschlag } from "@/lib/vorschlaege";

export default function VorschlagBox() {
  const [text, setText] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [vorschlaege, setVorschlaege] = useState<Vorschlag[]>([]);

  async function laden() {
    try {
      const res = await fetch("/api/vorschlag");
      const daten = await res.json();
      setVorschlaege(daten.vorschlaege || []);
    } catch {
      /* Liste ist nicht kritisch */
    }
  }

  useEffect(() => {
    laden();
  }, []);

  async function senden() {
    if (text.trim().length < 5 || laeuft) return;
    setLaeuft(true);
    setFehler(null);
    try {
      const res = await fetch("/api/vorschlag", {
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

  return (
    <section className="vorschlag-box">
      <h2 className="abschnitt-titel">💡 Dein Vorschlag an den Radar</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 14, marginTop: 4 }}>
        Sag dem Radar in einem Satz, was er suchen oder beobachten soll — z.&nbsp;B.
        „Schau dir die Kreatin-Mythen an“ oder „Beobachte den Kanal XY auf TikTok“.
        Suchanfragen, Beobachtungsliste und Themen-Gewichtung passen sich sofort an.
      </p>
      <div className="zeile" style={{ marginTop: 10, gap: 8, display: "flex" }}>
        <textarea
          rows={2}
          style={{ flex: 1 }}
          placeholder="Was soll der Radar für dich finden?"
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
          {vorschlaege.slice(0, 6).map((v) => (
            <li key={v.zeit}>
              <div className="vorschlag-text">„{v.text}“</div>
              <div className="vorschlag-ableitung">
                ↳ {v.ableitung.notiz}
                {v.ableitung.queries.length > 0 && (
                  <span> · Suchen: {v.ableitung.queries.map((q) => "„" + q + "“").join(", ")}</span>
                )}
                {v.ableitung.kanaele.length > 0 && (
                  <span> · Beobachtet: {v.ableitung.kanaele.map((k) => k.name).join(", ")}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
