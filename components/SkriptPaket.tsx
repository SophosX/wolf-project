"use client";

// Aufklappbares Skript-Paket: 3 Tabs (Varianten mit hook_typ-Label),
// Markdown gerendert, Quellen-Liste, Kopieren / Neu generieren / Faktencheck / Export.

import { useState } from "react";
import { hookLabel } from "@/lib/typen";
import type { Quelle, Skript, Video } from "@/lib/typen";
import Markdown from "./Markdown";

export default function SkriptPaket({ video }: { video: Video }) {
  const [offen, setOffen] = useState(false);
  const [skripte, setSkripte] = useState<Skript[]>(video.skripte || []);
  const [tab, setTab] = useState(0);
  const [laedt, setLaedt] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [kopiert, setKopiert] = useState(false);

  // Faktencheck-Modal
  const [fcOffen, setFcOffen] = useState(false);
  const [fcLaedt, setFcLaedt] = useState(false);
  const [fcErgebnis, setFcErgebnis] = useState<{
    inhalt_md: string;
    quellen: Quelle[];
  } | null>(null);

  const aktiv = skripte[tab] || skripte[0];

  async function neuGenerieren() {
    setLaedt(true);
    setFehler(null);
    try {
      const res = await fetch("/api/skript", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: video.id }),
      });
      const daten = await res.json();
      if (!res.ok) throw new Error(daten.fehler || "HTTP " + res.status);
      setSkripte(daten.skripte || []);
      setTab(0);
    } catch (e) {
      setFehler(e instanceof Error ? e.message : "Skript-Generierung fehlgeschlagen");
    } finally {
      setLaedt(false);
    }
  }

  async function faktencheckStarten() {
    setFcOffen(true);
    if (fcErgebnis) return; // bereits geladen
    setFcLaedt(true);
    setFehler(null);
    try {
      const res = await fetch("/api/faktencheck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: video.id }),
      });
      const daten = await res.json();
      if (!res.ok) throw new Error(daten.fehler || "HTTP " + res.status);
      setFcErgebnis(daten);
    } catch (e) {
      setFcOffen(false);
      setFehler(e instanceof Error ? e.message : "Faktencheck fehlgeschlagen");
    } finally {
      setFcLaedt(false);
    }
  }

  async function kopieren() {
    if (!aktiv) return;
    const text =
      aktiv.inhalt_md +
      (aktiv.quellen?.length
        ? "\n\nQuellen:\n" + aktiv.quellen.map((q) => "- " + q.titel + ": " + q.url).join("\n")
        : "");
    try {
      await navigator.clipboard.writeText(text);
      setKopiert(true);
      setTimeout(() => setKopiert(false), 2000);
    } catch {
      setFehler("Kopieren nicht möglich (Clipboard blockiert?)");
    }
  }

  return (
    <div className="skript-paket">
      <button className="skript-kopf" onClick={() => setOffen(!offen)}>
        <span>
          📜 Skript-Paket{" "}
          {skripte.length > 0 ? "(" + skripte.length + " Varianten)" : "(noch keins)"}
        </span>
        <span>{offen ? "▾" : "▸"}</span>
      </button>

      {offen && (
        <>
          {fehler && (
            <div className="hinweis-fehler" style={{ margin: "0 16px 12px" }}>
              ⚠ {fehler}
            </div>
          )}

          {skripte.length === 0 ? (
            <div style={{ padding: "0 16px 16px" }}>
              <p style={{ color: "var(--text-dim)", marginBottom: 10 }}>
                Für dieses Video liegt noch kein Skript-Paket vor.
              </p>
              <button className="btn primaer" onClick={neuGenerieren} disabled={laedt}>
                {laedt ? "⏳ Gemini schreibt …" : "✨ Skripte generieren"}
              </button>
            </div>
          ) : (
            <>
              <div className="skript-tabs" role="tablist">
                {skripte.map((s, i) => (
                  <button
                    key={i}
                    role="tab"
                    aria-selected={i === tab}
                    className={"skript-tab" + (i === tab ? " aktiv" : "")}
                    onClick={() => setTab(i)}
                  >
                    Variante {s.variante} · {hookLabel(s.hook_typ)}
                  </button>
                ))}
              </div>

              {aktiv && (
                <div className="skript-inhalt">
                  <Markdown md={aktiv.inhalt_md} />
                </div>
              )}

              <div className="skript-buttons">
                <button className="btn" onClick={kopieren}>
                  {kopiert ? "✓ Kopiert!" : "📋 Kopieren"}
                </button>
                <button className="btn" onClick={neuGenerieren} disabled={laedt}>
                  {laedt ? "⏳ Gemini schreibt …" : "🔄 Neu generieren"}
                </button>
                <button className="btn" onClick={faktencheckStarten} disabled={fcLaedt}>
                  {fcLaedt ? "⏳ Prüfe Quellen …" : "🔎 Faktencheck"}
                </button>
                <a className="btn" href="/api/export?status=angenommen&format=md">
                  ⬇ Export MD
                </a>
                <a className="btn" href="/api/export?status=angenommen&format=csv">
                  ⬇ Export CSV
                </a>
              </div>

              {aktiv && aktiv.quellen?.length > 0 && (
                <div className="quellen">
                  <h4>Quellen</h4>
                  <ul>
                    {aktiv.quellen.map((q, i) => (
                      <li key={i}>
                        <a href={q.url} target="_blank" rel="noopener noreferrer">
                          {q.titel}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </>
      )}

      {fcOffen && (
        <div className="modal-hintergrund" onClick={() => setFcOffen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-kopf">
              <span>🔎 Faktencheck: {(video.claim?.aussage || video.titel).slice(0, 60)}…</span>
              <button className="btn klein" onClick={() => setFcOffen(false)}>
                ✕
              </button>
            </div>
            <div className="modal-inhalt">
              {fcLaedt && <p>⏳ Gemini prüft die Quellenlage (Search-Grounding) …</p>}
              {fcErgebnis && (
                <>
                  <Markdown md={fcErgebnis.inhalt_md} />
                  {fcErgebnis.quellen.length > 0 && (
                    <div className="quellen" style={{ margin: "12px 0 0" }}>
                      <h4>Quellen (aus Google-Suche belegt)</h4>
                      <ul>
                        {fcErgebnis.quellen.map((q, i) => (
                          <li key={i}>
                            <a href={q.url} target="_blank" rel="noopener noreferrer">
                              {q.titel}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
