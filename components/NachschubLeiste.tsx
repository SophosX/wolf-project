"use client";

// Inbox-Dynamik: "Jetzt neue Videos suchen" + Live-Status. Läuft der Radar,
// refresht die Seite periodisch — neue Funde erscheinen, sobald sie analysiert sind.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

export default function NachschubLeiste() {
  const [moeglich, setMoeglich] = useState(false);
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<string | null>(null);
  const router = useRouter();
  const liefVorher = useRef(false);

  const statusLaden = useCallback(async () => {
    try {
      const res = await fetch("/api/nachschub");
      const daten = await res.json();
      setMoeglich(Boolean(daten.moeglich));
      setLaeuft(Boolean(daten.laeuft));
      if (liefVorher.current && !daten.laeuft) {
        // Lauf gerade beendet → frische Funde in die Liste holen
        router.refresh();
        setMeldung("Radar-Lauf abgeschlossen — Liste aktualisiert.");
        setTimeout(() => setMeldung(null), 5000);
      }
      liefVorher.current = Boolean(daten.laeuft);
    } catch {
      /* Status ist nice-to-have */
    }
  }, [router]);

  useEffect(() => {
    statusLaden();
  }, [statusLaden]);

  // Solange der Radar läuft: alle 20 s Status prüfen + Liste refreshen
  useEffect(() => {
    if (!laeuft) return;
    const timer = setInterval(() => {
      statusLaden();
      router.refresh();
    }, 20_000);
    return () => clearInterval(timer);
  }, [laeuft, statusLaden, router]);

  async function starten() {
    setMeldung(null);
    try {
      const res = await fetch("/api/nachschub", { method: "POST" });
      const daten = await res.json();
      if (!res.ok) throw new Error(daten.fehler || "Fehler " + res.status);
      setLaeuft(true);
      liefVorher.current = true;
      setMeldung("Radar läuft — neue Funde erscheinen hier automatisch.");
    } catch (e) {
      setMeldung(e instanceof Error ? e.message : "Start fehlgeschlagen");
    }
  }

  if (!moeglich && !laeuft) return null;

  return (
    <div className="nachschub-leiste">
      {laeuft ? (
        <span className="nachschub-status">
          <span className="puls" /> Radar sucht gerade neue Videos — Funde erscheinen automatisch …
        </span>
      ) : (
        <button className="btn" onClick={starten}>
          🔄 Jetzt neue Videos suchen
        </button>
      )}
      {meldung && <span className="nachschub-meldung">{meldung}</span>}
    </div>
  );
}
