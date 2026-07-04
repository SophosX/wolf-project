"use client";

// Live-Panel für /agenten: zeigt Christian, was der Radar GERADE tut
// (Phase + Schritt-Feed wie ein "denkender" Chatbot), was dabei herauskommt,
// und erlaubt "Jetzt suchen". Technische Fehler bleiben bewusst eingeklappt —
// sichtbar ist nur, was Mehrwert bringt.

import { useCallback, useEffect, useRef, useState } from "react";
import { formatDatum, relativeZeit } from "@/lib/format";
import type { AgentRun, AgentStatus } from "@/lib/typen";

const QUELLE_LABEL: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
  transkription: "Transkripte",
  nachanalyse: "Nach-Analyse",
  neubewertung: "Neubewertung",
};

interface ApiAntwort {
  status: AgentStatus | null;
  angefragt: boolean;
  runs: AgentRun[];
  naechsterLauf: string | null;
}

function quelleLabel(q: string): string {
  return QUELLE_LABEL[q] || q;
}

/** "in 2 h 5 min" für den nächsten automatischen Lauf */
function inZeit(iso: string): string {
  const diffMin = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 60000));
  if (diffMin < 1) return "in unter einer Minute";
  if (diffMin < 60) return `in ${diffMin} min`;
  const h = Math.floor(diffMin / 60);
  const m = diffMin % 60;
  return m > 0 ? `in ${h} h ${m} min` : `in ${h} h`;
}

/** Laufzeit seit Start, live ("2:41 min") */
function seitStart(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  const min = Math.floor(s / 60);
  const rest = s % 60;
  return `${min}:${rest.toString().padStart(2, "0")} min`;
}

export default function AgentenPanel() {
  const [daten, setDaten] = useState<ApiAntwort | null>(null);
  const [startFehler, setStartFehler] = useState<string | null>(null);
  const [startLaeuft, setStartLaeuft] = useState(false);
  const feedEnde = useRef<HTMLDivElement | null>(null);

  const laden = useCallback(async () => {
    try {
      const res = await fetch("/api/agenten", { cache: "no-store" });
      if (res.ok) setDaten(await res.json());
    } catch {
      /* nächster Poll versucht es erneut */
    }
  }, []);

  const aktiv = Boolean(daten?.status?.aktiv);
  const angefragt = Boolean(daten?.angefragt);

  // Polling: 3 s solange gearbeitet wird, sonst 30 s
  useEffect(() => {
    laden();
    const intervall = setInterval(laden, aktiv || angefragt ? 3000 : 30000);
    return () => clearInterval(intervall);
  }, [laden, aktiv, angefragt]);

  // Schritt-Feed ans Ende scrollen, wenn neue Schritte kommen
  const schrittAnzahl = daten?.status?.schritte.length || 0;
  useEffect(() => {
    if (aktiv) feedEnde.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [schrittAnzahl, aktiv]);

  async function jetztSuchen() {
    setStartLaeuft(true);
    setStartFehler(null);
    try {
      const res = await fetch("/api/agenten", { method: "POST" });
      const antwort = await res.json();
      if (!res.ok) throw new Error(antwort.grund || "Start fehlgeschlagen");
      await laden();
    } catch (e) {
      setStartFehler(e instanceof Error ? e.message : "Start fehlgeschlagen");
    } finally {
      setStartLaeuft(false);
    }
  }

  if (!daten) {
    return <div className="status-karte"><span className="dim">Lade Agenten-Status …</span></div>;
  }

  const { status, runs, naechsterLauf } = daten;
  const letzteSchritte = status?.schritte.slice(-12) || [];

  // Letzter abgeschlossener Scraping-Lauf (für die Bilanz im Ruhezustand)
  const letzterLauf = runs.find((r) =>
    ["youtube", "tiktok", "instagram"].includes(r.quelle));

  // Quellen-Kacheln: letzter Lauf je Scraping-Quelle
  const jeQuelle = new Map<string, AgentRun>();
  for (const r of runs) {
    if (["youtube", "tiktok", "instagram"].includes(r.quelle) && !jeQuelle.has(r.quelle)) {
      jeQuelle.set(r.quelle, r);
    }
  }

  return (
    <>
      {/* ---- Status-Karte ---- */}
      <div className={"status-karte" + (aktiv ? " arbeitet" : "")}>
        {aktiv && status ? (
          <>
            <div className="status-kopf">
              <span className="status-punkt aktiv" />
              <b>Radar arbeitet</b>
              <span className="dim" style={{ marginLeft: "auto" }}>
                seit {seitStart(status.gestartet)}
              </span>
            </div>
            <div className="status-phase">{status.phase}</div>
            <div className="zaehler-chips">
              <span className="chip">{status.zaehler.gefunden} gesichtet</span>
              <span className="chip">{status.zaehler.analysiert} analysiert</span>
              <span className="chip">{status.zaehler.neu} neu</span>
              <span className="chip akzent">{status.zaehler.geflaggt} geflaggt</span>
            </div>
            <div className="schritt-feed">
              {letzteSchritte.map((s, i) => (
                <div key={s.zeit + i} className={"schritt " + s.typ}>
                  <span className="schritt-zeit">
                    {new Date(s.zeit).toLocaleTimeString("de-DE", {
                      hour: "2-digit", minute: "2-digit",
                    })}
                  </span>
                  {s.text}
                </div>
              ))}
              <div className="schritt laufend">
                <span className="tipp-punkte"><i /><i /><i /></span>
              </div>
              <div ref={feedEnde} />
            </div>
          </>
        ) : angefragt ? (
          <>
            <div className="status-kopf">
              <span className="status-punkt wartet" />
              <b>Radar startet gleich …</b>
            </div>
            <p className="dim" style={{ margin: "6px 0 0" }}>
              Deine Suche ist angefordert — der Lauf beginnt in unter einer Minute.
            </p>
          </>
        ) : (
          <>
            <div className="status-kopf">
              <span className="status-punkt bereit" />
              <b>Radar bereit</b>
              {naechsterLauf && (
                <span className="dim" style={{ marginLeft: "auto" }}>
                  nächster automatischer Lauf {inZeit(naechsterLauf)}
                </span>
              )}
            </div>
            {status?.ergebnis && (
              <div className="status-bilanz">
                ✓ {status.ergebnis}
                {status.beendet && (
                  <span className="dim"> · {relativeZeit(status.beendet)}</span>
                )}
              </div>
            )}
            {!status?.ergebnis && letzterLauf && (
              <div className="status-bilanz">
                Letzter Lauf {relativeZeit(letzterLauf.zeit)}: {letzterLauf.neu} neue
                Videos, {letzterLauf.geflaggt} geflaggt
              </div>
            )}
            <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
              <button className="btn primaer" disabled={startLaeuft} onClick={jetztSuchen}>
                {startLaeuft ? "⏳ wird angefordert …" : "🔍 Jetzt suchen"}
              </button>
              <span className="dim" style={{ fontSize: 13 }}>
                durchsucht YouTube + TikTok sofort — dein Vorschlag oben fließt direkt ein
              </span>
            </div>
            {startFehler && (
              <p style={{ color: "var(--rot)", fontSize: 13, marginTop: 6 }}>{startFehler}</p>
            )}
          </>
        )}
      </div>

      {/* ---- Funde je Quelle (wertorientiert, ohne Fehler-Dump) ---- */}
      <div className="agenten-gitter">
        {[...jeQuelle.entries()].map(([quelle, run]) => {
          const gestoert = run.gefunden === 0 && (run.fehler || []).length > 0;
          return (
            <div key={quelle} className="agent-kachel">
              <h3>{quelleLabel(quelle)}</h3>
              <div className="gross-zahl">{run.geflaggt}</div>
              <div className="dim">
                geflaggt · {run.gefunden} gesichtet · {run.neu} neu
              </div>
              <div className="dim" style={{ marginTop: 6 }}>
                {relativeZeit(run.zeit)}
                {gestoert && <span style={{ color: "var(--rot)" }}> · Suche gestört</span>}
              </div>
            </div>
          );
        })}
      </div>

      {/* ---- Letzte Läufe (kompakt, ohne Fehlerspalte) ---- */}
      {runs.length > 0 && (
        <>
          <h2 className="abschnitt-titel">Letzte Läufe</h2>
          <div className="tabellen-scroll">
            <table className="lauf-tabelle">
              <thead>
                <tr>
                  <th>Zeit</th>
                  <th>Quelle</th>
                  <th>Gesichtet</th>
                  <th>Neu</th>
                  <th>Geflaggt</th>
                  <th>Dauer</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 15).map((r, i) => (
                  <tr key={i}>
                    <td title={formatDatum(r.zeit)}>{relativeZeit(r.zeit)}</td>
                    <td>{quelleLabel(r.quelle)}</td>
                    <td>{r.gefunden}</td>
                    <td>{r.neu}</td>
                    <td>{r.geflaggt}</td>
                    <td>{r.dauer_s}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Technisches bewusst eingeklappt — interessiert nur im Störungsfall */}
          <details className="technik-details">
            <summary>Technische Details</summary>
            {runs.filter((r) => (r.fehler || []).length > 0).length === 0 ? (
              <p className="dim">Keine technischen Hinweise — alles läuft rund. ✓</p>
            ) : (
              runs
                .filter((r) => (r.fehler || []).length > 0)
                .slice(0, 10)
                .map((r, i) => (
                  <div key={i} className="technik-block">
                    <b>{quelleLabel(r.quelle)}</b> · {relativeZeit(r.zeit)}
                    {(r.fehler || []).map((f, j) => (
                      <div key={j} className="dim technik-zeile">{f}</div>
                    ))}
                  </div>
                ))
            )}
          </details>
        </>
      )}
    </>
  );
}
