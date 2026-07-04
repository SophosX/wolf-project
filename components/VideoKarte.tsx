"use client";

// Eine Karte = ein Video = eine Entscheidung.
// Thumbnail · Plattform-Badge · Views+Velocity · Kanal (+Watchlist) ·
// Falschaussage als Zitat · Warum-falsch · Themen-Chip · Score-Ring · Aktionen

import { useState } from "react";
import { formatViews, formatDauer, relativeZeit, velocity } from "@/lib/format";
import { themaLabel } from "@/lib/typen";
import type { Video } from "@/lib/typen";
import ScoreRing from "./ScoreRing";
import SkriptPaket from "./SkriptPaket";

export type VideoAnzeige = Video & { beobachtung: boolean };
export type Seite = "inbox" | "angenommen" | "gespeichert" | "strittig" | "archiv";

const PLATTFORM_LABEL: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
};

const ABLEHN_GRUENDE = ["zu klein", "Thema passt nicht", "nicht klar falsch"];

interface Props {
  video: VideoAnzeige;
  seite: Seite;
  onAktion: (aktion: string, kommentar?: string) => Promise<boolean>;
}

export default function VideoKarte({ video, seite, onAktion }: Props) {
  const [menue, setMenue] = useState<"" | "ablehnen" | "kommentar">("");
  const [eigenerGrund, setEigenerGrund] = useState("");
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

  const velo = velocity(video.views, video.veroeffentlicht);
  const letzterGrund = [...(video.feedback || [])]
    .reverse()
    .find((f) => f.aktion === "abgelehnt");

  return (
    <article className="karte">
      <div className="karte-layout">
        <a
          className="karte-thumb"
          href={video.url}
          target="_blank"
          rel="noopener noreferrer"
          title="Original in neuem Tab öffnen"
        >
          {video.thumbnail_url && !bildFehler ? (
            // Lazy-Loading; TikTok/IG-Thumbnails laufen ab → Platzhalter-Fallback
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={video.thumbnail_url}
              alt={"Thumbnail: " + video.titel}
              loading="lazy"
              onError={() => setBildFehler(true)}
            />
          ) : (
            <div className="thumb-platzhalter">
              {video.plattform === "youtube" ? "▶" : video.plattform === "tiktok" ? "♪" : "◎"}
            </div>
          )}
          <span className={"badge-plattform " + video.plattform}>
            {PLATTFORM_LABEL[video.plattform] || video.plattform}
          </span>
          {video.dauer_s != null && (
            <span className="thumb-dauer">{formatDauer(video.dauer_s)}</span>
          )}
        </a>

        <div className="karte-inhalt">
          <div className="karte-meta">
            <span className="views">{formatViews(video.views)} Views</span>
            {velo && <span className="velocity">{velo}</span>}
            <span>·</span>
            <span>{video.kanal}</span>
            {video.beobachtung && (
              <span className="badge-watchlist">⚠ Beobachtungsliste</span>
            )}
            <span>·</span>
            <span>{relativeZeit(video.veroeffentlicht)}</span>
          </div>

          <div className="karte-titel">{video.titel}</div>

          <div className="karte-hauptzeile">
            <div className="textteil">
              {video.claim ? (
                <>
                  <blockquote className="zitat">„{video.claim.aussage}“</blockquote>
                  <p className="warum">
                    <b>Warum falsch:</b> {video.claim.begruendung}
                  </p>
                  {(video.claim.quellen?.length ?? 0) > 0 && (
                    <p className="claim-quellen">
                      <b>Belege:</b>{" "}
                      {video.claim.quellen!.slice(0, 4).map((q, i) => (
                        <span key={q.url}>
                          {i > 0 && " · "}
                          <a href={q.url} target="_blank" rel="noopener noreferrer" title={q.titel}>
                            {q.titel.length > 40 ? q.titel.slice(0, 38) + "…" : q.titel}
                          </a>
                        </span>
                      ))}
                    </p>
                  )}
                  <span className="chip"># {themaLabel(video.claim.thema)}</span>
                </>
              ) : (
                <p className="warum">
                  ⏳ <b>Analyse ausstehend</b> — der Radar hat dieses Video
                  gefunden, aber noch keinen Claim extrahiert (nächster
                  Analyse-Lauf).
                </p>
              )}
              {seite === "archiv" && letzterGrund && (
                <div>
                  <span className="grund-badge">
                    Abgelehnt{letzterGrund.kommentar ? ": „" + letzterGrund.kommentar + "“" : ""}
                  </span>
                </div>
              )}
            </div>
            <ScoreRing score={video.score} />
          </div>

          <div className="aktionen">
            {(seite === "inbox" || seite === "gespeichert" || seite === "strittig") && (
              <button
                className="btn primaer"
                disabled={beschaeftigt}
                onClick={() => aktion("angenommen")}
              >
                ✓ Annehmen
              </button>
            )}
            {seite !== "archiv" && (
              <button
                className="btn gefahr"
                disabled={beschaeftigt}
                onClick={() => setMenue(menue === "ablehnen" ? "" : "ablehnen")}
              >
                ✕ Ablehnen
              </button>
            )}
            {seite === "inbox" && (
              <button
                className="btn"
                disabled={beschaeftigt}
                onClick={() => aktion("gespeichert")}
                title="Für später speichern"
              >
                🔖 Später
              </button>
            )}
            {seite === "archiv" && (
              <button
                className="btn"
                disabled={beschaeftigt}
                onClick={() => aktion("inbox")}
              >
                ↩ Zurück in die Inbox
              </button>
            )}
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
              href={video.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Original ↗
            </a>
          </div>

          {menue === "ablehnen" && (
            <div className="mini-menue">
              <div className="gruende">
                {ABLEHN_GRUENDE.map((g) => (
                  <button
                    key={g}
                    className="btn klein"
                    disabled={beschaeftigt}
                    onClick={() => aktion("abgelehnt", g)}
                  >
                    {g}
                  </button>
                ))}
              </div>
              <div className="zeile">
                <input
                  placeholder="Eigener Grund …"
                  value={eigenerGrund}
                  onChange={(e) => setEigenerGrund(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && eigenerGrund.trim())
                      aktion("abgelehnt", eigenerGrund.trim());
                  }}
                />
                <button
                  className="btn klein gefahr"
                  disabled={beschaeftigt || !eigenerGrund.trim()}
                  onClick={() => aktion("abgelehnt", eigenerGrund.trim())}
                >
                  Ablehnen
                </button>
              </div>
            </div>
          )}

          {menue === "kommentar" && (
            <div className="mini-menue">
              <textarea
                rows={2}
                placeholder="Kommentar für den Radar (fließt ins Lernen und in die Skripte ein) …"
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

      {seite === "angenommen" && <SkriptPaket video={video} />}
    </article>
  );
}
