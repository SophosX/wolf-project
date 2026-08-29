"use client";

// Inbox-Diagnose: Wenn (fast) nichts in der Inbox liegt, sieht der Nutzer
// WARUM — welche seiner Suchbegriffe etwas fanden, was die Prüfung ergab —
// und bekommt eine konkrete Handlung: breiter suchen (ein Klick), Begriffe
// schärfen, Interessen erweitern. Nie ein stummes "Inbox leer".

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { relativeZeit } from "@/lib/format";

interface QueryStatus {
  id: number;
  plattform: string;
  query: string;
  aktiv: boolean;
  letzte_treffer: number;
  leer_folge: number;
  zuletzt: string | null;
  fenster: string | null;
  nie_gesucht: boolean;
}
interface Antwort {
  queries: QueryStatus[];
  zusammenfassung: {
    gesamt: number; gesucht: number; nie_gesucht: number;
    mit_treffern: number; ohne_treffer: number; treffer_letzter: number; tote: number;
  };
  kuration: { zeit: string; neu: number; geflaggt: number; detail: Record<string, number> } | null;
  lauf: { angefragt: boolean; aktiv: boolean };
  naechsteSuche: string | null;
  hinweise: { alt: string; neu: string; plattform: string; zeit: string }[];
  bestand: { inbox: number; strittig: number; archiv: number };
  bereiche_ohne_thema: { slug: string; label: string; emoji: string }[];
  empfehlung: "laeuft" | "warten" | "breiter" | "spezifizieren" | "ok";
}

const PLATTFORM: Record<string, string> = { youtube: "YT", tiktok: "TT", instagram: "IG" };

function inZeit(iso: string | null): string {
  if (!iso) return "";
  const min = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 60000));
  if (min < 1) return "gleich";
  if (min < 60) return `in ${min} min`;
  const h = Math.floor(min / 60);
  return `in ${h} h${min % 60 ? ` ${min % 60} min` : ""}`;
}

export default function InboxDiagnose({ inboxAnzahl }: { inboxAnzahl: number }) {
  const [d, setD] = useState<Antwort | null>(null);
  const [offen, setOffen] = useState(inboxAnzahl === 0);
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<string | null>(null);

  const laden = useCallback(async () => {
    try {
      const res = await fetch("/api/suchstatus", { cache: "no-store" });
      if (res.ok) setD(await res.json());
    } catch {
      /* naechster Versuch beim naechsten Render */
    }
  }, []);

  useEffect(() => {
    laden();
  }, [laden]);

  // Laeuft eine Suche: alle 15 s nachladen. (Den Listen-Refresh am Ende
  // uebernimmt SuchStatusLeiste — sie sitzt auf derselben Seite.)
  const sucheAngefragt = Boolean(d?.lauf.angefragt || d?.lauf.aktiv);
  useEffect(() => {
    if (!sucheAngefragt) return;
    const t = setInterval(() => { laden(); }, 15000);
    return () => clearInterval(t);
  }, [sucheAngefragt, laden]);

  async function breiterSuchen() {
    setMeldung(null);
    setLaeuft(true);
    try {
      const res = await fetch("/api/suchstatus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aktion: "breiter" }),
      });
      const a = await res.json();
      if (!res.ok) throw new Error(a.fehler || "Fehler " + res.status);
      setMeldung(
        a.gestartet
          ? `${a.queries} von ${a.gesamt} Suchanfragen (die ohne Treffer) suchen jetzt im weitesten Zeitraum — der Lauf startet in unter einer Minute (Ergebnis in ~10–30 min).`
          : "Suchanfragen erweitert — ein Lauf ist bereits unterwegs, die Erweiterung greift dort."
      );
      await laden();
    } catch (e) {
      setMeldung(e instanceof Error ? e.message : "Breiter suchen fehlgeschlagen");
    } finally {
      setLaeuft(false);
    }
  }

  if (!d) return null;
  const z = d.zusammenfassung;
  const k = d.kuration;
  const det = k?.detail || {};
  const sucheLaeuft = d.lauf.aktiv || d.lauf.angefragt;

  // Kompakte Zeile, wenn die Inbox nicht leer ist (nur bei wenigen Karten)
  if (inboxAnzahl > 0 && !offen) {
    return (
      <div className="diagnose kompakt">
        <span className="dim">
          {z.mit_treffern}/{z.gesucht} Suchbegriffe mit Treffern
          {k && <> · letzte Prüfung {relativeZeit(k.zeit)}: {det.geflaggt || 0} geflaggt, {det.korrekt || 0} korrekt</>}
        </span>
        <button className="btn klein" onClick={() => setOffen(true)}>Details</button>
      </div>
    );
  }

  return (
    <div className="diagnose karte">
      <div className="diagnose-kopf">
        <div className="abschnitt-titel" style={{ margin: 0 }}>
          {inboxAnzahl === 0 ? "Warum ist hier (noch) nichts?" : "Was dein Radar gerade findet"}
        </div>
        {inboxAnzahl > 0 && (
          <button className="btn klein" onClick={() => setOffen(false)}>Einklappen</button>
        )}
      </div>

      {/* ---- Lagebild ---- */}
      {sucheLaeuft ? (
        <p className="diagnose-status">
          <span className="puls" /> Deine Suche läuft gerade — neue Funde erscheinen hier automatisch.
        </p>
      ) : z.gesamt === 0 ? (
        <p className="diagnose-status">
          Du hast noch keine aktiven Suchanfragen. Ohne Suchbegriffe kann der Radar nichts finden.
        </p>
      ) : z.gesucht === 0 ? (
        <p className="diagnose-status">
          Deine {z.gesamt} Suchanfragen wurden noch nicht durchsucht — die erste Suche startet{" "}
          <b>{inZeit(d.naechsteSuche)}</b>, oder du stößt sie jetzt an.
        </p>
      ) : (
        <p className="diagnose-status">
          <b>{z.mit_treffern} von {z.gesucht}</b> Suchbegriffen fanden zuletzt Videos
          ({z.treffer_letzter} gesichtet)
          {z.nie_gesucht > 0 && <>, {z.nie_gesucht} sind neu und noch nicht gesucht</>}.
          {k && (
            <>
              {" "}Letzte Prüfung {relativeZeit(k.zeit)}:{" "}
              {det.kandidaten || 0} Kandidaten im Pool, {det.gematcht || 0} passten zu deinen Themen,{" "}
              {det.bewertet || 0} geprüft → <b>{det.geflaggt || 0} mit Falschaussage</b>
              {(det.korrekt || 0) > 0 && <>, {det.korrekt} sachlich korrekt (kein Debunk nötig)</>}
              {(det.warteschlange || 0) > 0 && <>, {det.warteschlange} warten auf den nächsten Lauf</>}.
            </>
          )}
        </p>
      )}

      {d.bestand.strittig > 0 && inboxAnzahl === 0 && (
        <p className="diagnose-status">
          Übrigens: <a href="/strittig"><b>{d.bestand.strittig} strittige Funde</b></a> warten auf
          deinen Blick — Videos, bei denen die KI eine Falschaussage vermutet, aber nicht sicher ist.
        </p>
      )}

      {/* ---- Suchbegriffe mit Ertrag ---- */}
      {d.queries.filter((q) => q.aktiv).length > 0 && (
        <div className="such-protokoll" style={{ marginTop: 8 }}>
          {d.queries.filter((q) => q.aktiv).map((q) => (
            <span
              key={q.id}
              className={"such-chip" + (q.letzte_treffer > 0 ? "" : " leer") + (q.leer_folge >= 3 ? " tot" : "")}
              title={
                q.nie_gesucht
                  ? "noch nicht gesucht"
                  : `${q.letzte_treffer} Treffer · ${relativeZeit(q.zuletzt || "")}` +
                    (q.leer_folge > 0 ? ` · ${q.leer_folge}× leer` : "") +
                    (q.fenster ? ` · Fenster ${q.fenster}` : "")
              }
            >
              <span className="such-chip-q">
                <span className="dim">{PLATTFORM[q.plattform] || q.plattform}</span> {q.query}
              </span>
              <span className="such-chip-n">{q.nie_gesucht ? "·" : q.letzte_treffer}</span>
            </span>
          ))}
        </div>
      )}

      {/* ---- Automatische Ersetzungen ---- */}
      {d.hinweise.length > 0 && (
        <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>
          Automatisch ersetzt, weil mehrfach ohne Treffer:{" "}
          {d.hinweise.slice(0, 3).map((h, i) => (
            <span key={i}>
              {i > 0 && " · "}„{h.alt}“ → „{h.neu}“
            </span>
          ))}
        </p>
      )}

      {/* ---- Empfehlung + Handlung ---- */}
      {!sucheLaeuft && (
        <div className="diagnose-aktion">
          {d.empfehlung === "breiter" && (
            <p>
              <b>Empfehlung: breiter suchen.</b> Deine Begriffe sind eng oder die Nische ist auf den
              Plattformen gerade ruhig. Ein Klick weitet alle Suchen auf den größten Zeitraum und
              mehr Treffer je Begriff aus.
            </p>
          )}
          {d.empfehlung === "spezifizieren" && z.gesamt > 0 && (
            <p>
              <b>Empfehlung: schärfen.</b> Es werden Videos gefunden, aber keine enthält eine
              Falschaussage zu deinen Themen — formuliere Suchanfragen so, wie die Falschbehauptung
              klingt („Mit X heilst du Y“), oder wähle weitere Interessen.
            </p>
          )}
          {d.empfehlung === "warten" && z.gesucht === 0 && (
            <p>
              <b>Alles bereit.</b> Die erste Suche läuft {inZeit(d.naechsteSuche)} automatisch —
              oder du startest sie jetzt breit.
            </p>
          )}
          {d.empfehlung === "warten" && z.gesucht > 0 && (
            <p>
              <b>Gefunden, noch nicht geprüft.</b> Deine Begriffe haben Videos gesichtet; die
              Prüfung gegen deine Themen folgt beim nächsten Kurationslauf (Free: täglich, Pro: alle 4 h)
              — oder du startest jetzt eine Suche samt Prüfung.
            </p>
          )}
          {d.bereiche_ohne_thema.length > 0 && (
            <p className="dim" style={{ fontSize: 13 }}>
              Hinweis: {d.bereiche_ohne_thema.map((b) => `${b.emoji} ${b.label}`).join(", ")} hat
              wegen des Plan-Limits kein aktives Thema — unter Profil Themen tauschen oder Plan
              erweitern.
            </p>
          )}
          <div className="diagnose-knoepfe">
            {z.gesamt > 0 && (
              <button className="btn primaer" disabled={laeuft || sucheAngefragt} onClick={breiterSuchen}>
                {laeuft ? "⏳ wird angefordert …" : "🔎 Jetzt breiter suchen"}
              </button>
            )}
            <Link className="btn" href="/einstellungen#suchanfragen">
              <span aria-hidden="true">✏️ </span>Suchbegriffe anpassen
            </Link>
            <Link className="btn" href="/einstellungen#interessen">
              <span aria-hidden="true">➕ </span>Interessen erweitern
            </Link>
          </div>
          {meldung && <p className="diagnose-meldung">{meldung}</p>}
        </div>
      )}
    </div>
  );
}
