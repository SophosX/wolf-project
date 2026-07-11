"use client";

// Eine Karte = ein Rezept = eine Entscheidung (Muster: VideoKarte).
// Thumbnail · Views+Velocity · Kanal · Titel · Kategorie-Chip · Fit-Score-Ring ·
// Zutaten-Chips · Begründung · Chris-Haken (gelber Hinweis) · Aktionen

import { useState } from "react";
import { formatViews, formatDauer, relativeZeit, velocity } from "@/lib/format";
import { rezeptKategorieLabel } from "@/lib/typen";
import type { Rezept } from "@/lib/typen";

export type RezeptBereich = "vorschlag" | "gemerkt";

interface Props {
  rezept: Rezept;
  bereich: RezeptBereich;
  onAktion: (aktion: string, kommentar?: string) => Promise<boolean>;
}

/** Fit-Score als Kreisanzeige (Muster: ScoreRing, eigener Titel). */
function FitRing({ wert }: { wert: number }) {
  const r = 24;
  const umfang = 2 * Math.PI * r;
  const anteil = Math.max(0, Math.min(100, wert)) / 100;
  const farbe = wert >= 75 ? "var(--gruen)" : wert >= 60 ? "var(--akzent)" : "#7d838a";
  return (
    <div className="score-ring" title={"Dein Fit " + wert + "/100"}>
      <svg width="54" height="54" viewBox="0 0 54 54">
        <circle cx="27" cy="27" r={r} fill="none" stroke="var(--linie)" strokeWidth="5" />
        <circle
          cx="27"
          cy="27"
          r={r}
          fill="none"
          stroke={farbe}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={umfang * anteil + " " + umfang}
        />
      </svg>
      <div className="zahl" style={{ color: farbe, flexDirection: "column", lineHeight: 1 }}>
        <span>{wert}</span>
        <span style={{ fontSize: 8, fontWeight: 600, color: "var(--text-dim)" }}>FIT</span>
      </div>
    </div>
  );
}

export default function RezeptKarte({ rezept, bereich, onAktion }: Props) {
  const [menue, setMenue] = useState<"" | "kommentar">("");
  const [kommentarText, setKommentarText] = useState("");
  const [beschaeftigt, setBeschaeftigt] = useState(false);
  const [gespeichertOk, setGespeichertOk] = useState(false);
  const [bildFehler, setBildFehler] = useState(false);

  async function aktion(a: string, kommentar?: string) {
    setBeschaeftigt(true);
    const ok = await onAktion(a, kommentar);
    setBeschaeftigt(false);
    if (ok && a === "kommentar") {
      setKommentarText("");
      setMenue("");
      setGespeichertOk(true);
      setTimeout(() => setGespeichertOk(false), 2000);
    }
  }

  const velo = velocity(rezept.views, rezept.veroeffentlicht);

  return (
    <article className="karte">
      <div className="karte-layout">
        <a
          className="karte-thumb"
          href={rezept.url}
          target="_blank"
          rel="noopener noreferrer"
          title="Rezept-Video in neuem Tab öffnen"
        >
          {rezept.thumbnail_url && !bildFehler ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={rezept.thumbnail_url}
              alt={"Thumbnail: " + rezept.titel}
              loading="lazy"
              onError={() => setBildFehler(true)}
            />
          ) : (
            <div className="thumb-platzhalter">🍽</div>
          )}
          {rezept.dauer_s != null && (
            <span className="thumb-dauer">{formatDauer(rezept.dauer_s)}</span>
          )}
        </a>

        <div className="karte-inhalt">
          <div className="karte-meta">
            <span className="views">{formatViews(rezept.views)} Views</span>
            {velo && <span className="velocity">{velo}</span>}
            <span>·</span>
            <span>{rezept.kanal}</span>
            <span>·</span>
            <span>{relativeZeit(rezept.veroeffentlicht)}</span>
          </div>

          <div className="karte-hauptzeile">
            <div className="textteil">
              <div
                style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.35, letterSpacing: "-0.01em" }}
              >
                {rezept.titel}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                <span
                  className="chip"
                  style={{ color: "var(--akzent)", borderColor: "rgba(255,184,0,0.35)" }}
                >
                  {rezeptKategorieLabel(rezept.kategorie)}
                </span>
                {(rezept.zutaten_kurz || []).map((z) => (
                  <span key={z} className="chip">
                    {z}
                  </span>
                ))}
              </div>
              {rezept.begruendung && (
                <p className="warum">
                  <b>Warum es passt:</b> {rezept.begruendung}
                </p>
              )}
              {(rezept.haken || rezept.chris_haken) && (
                <p
                  className="warum"
                  style={{
                    background: "rgba(255, 184, 0, 0.1)",
                    border: "1px solid rgba(255, 184, 0, 0.35)",
                    borderRadius: 10,
                    padding: "8px 10px",
                  }}
                >
                  ⚠ <b style={{ color: "var(--akzent)" }}>Dein Haken:</b>{" "}
                  {rezept.haken || rezept.chris_haken}
                </p>
              )}
            </div>
            <FitRing wert={rezept.fit_score} />
          </div>

          <div className="aktionen">
            {bereich === "vorschlag" && (
              <button
                className="btn primaer"
                disabled={beschaeftigt}
                onClick={() => aktion("gemerkt")}
                title="Rezept merken"
              >
                🔖 Merken
              </button>
            )}
            {bereich === "gemerkt" && (
              <button
                className="btn"
                disabled={beschaeftigt}
                onClick={() => aktion("vorschlag")}
                title="Zurück zu den Vorschlägen"
              >
                ↩ Zurück zu Vorschlägen
              </button>
            )}
            <button
              className="btn gefahr"
              disabled={beschaeftigt}
              onClick={() => aktion("verworfen")}
            >
              ✕ Verwerfen
            </button>
            <button
              className="btn"
              disabled={beschaeftigt}
              onClick={() => setMenue(menue === "kommentar" ? "" : "kommentar")}
            >
              💬 Kommentar
            </button>
            {gespeichertOk && (
              <span style={{ color: "var(--gruen)", fontSize: 13 }}>✓ gespeichert</span>
            )}
            <a
              className="original-link"
              href={rezept.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Original ↗
            </a>
          </div>

          {menue === "kommentar" && (
            <div className="mini-menue">
              <textarea
                rows={2}
                placeholder="Kommentar für den Radar (z.B. „mehr davon“, „zu aufwendig“ — der Algorithmus lernt daraus) …"
                value={kommentarText}
                onChange={(e) => setKommentarText(e.target.value)}
              />
              <div className="zeile">
                <button
                  className="btn klein primaer"
                  disabled={beschaeftigt || !kommentarText.trim()}
                  onClick={() => aktion("kommentar", kommentarText.trim())}
                >
                  Kommentar speichern
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
