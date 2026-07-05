"use client";

// Inbox-Statusleiste: macht auf der Hauptseite sichtbar, DASS und WAS der Radar
// sucht — "Letzte Suche vor X · N Begriffe · M gesichtet · K neu · nächste in Y".
// Plus funktionierender "Jetzt suchen"-Knopf (Flag-Mechanismus über /api/agenten,
// funktioniert auch im Split-Container-Betrieb). Läuft der Radar, wird die Liste
// automatisch aktualisiert, sobald neue Funde analysiert sind.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { relativeZeit } from "@/lib/format";
import type { AgentRun, AgentStatus } from "@/lib/typen";

interface ApiAntwort {
  status: AgentStatus | null;
  angefragt: boolean;
  runs: AgentRun[];
  naechsterLauf: string | null;
  naechsteVideoSuche: string | null;
}

function inZeit(iso: string | null): string | null {
  if (!iso) return null;
  const diffMin = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 60000));
  if (diffMin < 1) return "in unter 1 min";
  if (diffMin < 60) return `in ${diffMin} min`;
  const h = Math.floor(diffMin / 60);
  const m = diffMin % 60;
  return m > 0 ? `in ${h} h ${m} min` : `in ${h} h`;
}

export default function SuchStatusLeiste() {
  const [daten, setDaten] = useState<ApiAntwort | null>(null);
  const [startFehler, setStartFehler] = useState<string | null>(null);
  const [startLaeuft, setStartLaeuft] = useState(false);
  const router = useRouter();
  const liefVorher = useRef(false);

  const laden = useCallback(async () => {
    try {
      const res = await fetch("/api/agenten", { cache: "no-store" });
      if (!res.ok) return;
      const d: ApiAntwort = await res.json();
      setDaten(d);
      const laeuft = Boolean(d.status?.aktiv) || Boolean(d.angefragt);
      if (liefVorher.current && !laeuft) {
        router.refresh(); // Lauf fertig → frische Funde in die Liste
      }
      liefVorher.current = laeuft;
    } catch {
      /* nächster Poll versucht es erneut */
    }
  }, [router]);

  const aktiv = Boolean(daten?.status?.aktiv);
  const angefragt = Boolean(daten?.angefragt);

  useEffect(() => {
    laden();
    const intervall = setInterval(laden, aktiv || angefragt ? 4000 : 20000);
    return () => clearInterval(intervall);
  }, [laden, aktiv, angefragt]);

  async function jetztSuchen() {
    setStartLaeuft(true);
    setStartFehler(null);
    try {
      const res = await fetch("/api/agenten", { method: "POST" });
      const antwort = await res.json();
      if (!res.ok) throw new Error(antwort.grund || "Start fehlgeschlagen");
      liefVorher.current = true;
      await laden();
    } catch (e) {
      setStartFehler(e instanceof Error ? e.message : "Start fehlgeschlagen");
    } finally {
      setStartLaeuft(false);
    }
  }

  if (!daten) return null;

  const { status, runs, naechsteVideoSuche } = daten;

  // Letzter YouTube-Lauf (das, was die Inbox füllt) + letzter *erfolgreicher*.
  const ytRuns = runs.filter((r) => r.quelle === "youtube");
  const letzter = ytRuns[0];
  const letzterErfolg = ytRuns.find((r) => r.gefunden > 0);
  const gestoert = letzter && letzter.gefunden === 0 && (letzter.fehler || []).length > 0;
  const begriffe = letzterErfolg?.such_protokoll?.length || 0;

  return (
    <div className="such-status">
      {aktiv || angefragt ? (
        <span className="such-status-live">
          <span className="puls" />
          {aktiv
            ? `Radar sucht gerade — ${status?.zaehler.gefunden ?? 0} gesichtet, ${status?.zaehler.neu ?? 0} neu …`
            : "Radar startet gleich — deine Suche ist angefordert …"}
        </span>
      ) : (
        <span className="such-status-info">
          {letzterErfolg ? (
            <>
              <b>Letzte Suche</b> {relativeZeit(letzterErfolg.zeit)}
              {begriffe > 0 && <> · {begriffe} Suchbegriffe</>} ·{" "}
              {letzterErfolg.gefunden} Videos gesichtet · {letzterErfolg.neu} neu
            </>
          ) : (
            <>Noch keine erfolgreiche Suche protokolliert.</>
          )}
          {naechsteVideoSuche && (
            <span className="dim"> · nächste Suche {inZeit(naechsteVideoSuche)}</span>
          )}
        </span>
      )}

      {gestoert && !aktiv && !angefragt && (
        <span className="such-status-warnung">
          ⚠ Der letzte automatische Lauf {relativeZeit(letzter!.zeit)} war gestört —
          Details unter <a href="/agenten">Agenten</a>.
        </span>
      )}

      {!aktiv && !angefragt && (
        <button className="btn" disabled={startLaeuft} onClick={jetztSuchen}>
          {startLaeuft ? "⏳ wird angefordert …" : "🔄 Jetzt neue Videos suchen"}
        </button>
      )}
      {startFehler && <span className="such-status-warnung">{startFehler}</span>}
    </div>
  );
}
