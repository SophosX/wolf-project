"use client";

// Rezept-Liste mit optimistic UI (Muster: VideoListe):
// Aktion → Karte sofort umsortiert/raus, POST /api/rezepte im Hintergrund,
// bei Fehler Rollback + roter Hinweis. Plus Kategorie-Filter (URL-Query)
// und eingeklappter „Gemerkt“-Abschnitt unterhalb.

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { rezeptKategorieLabel } from "@/lib/typen";
import type { Rezept } from "@/lib/typen";
import RezeptKarte from "./RezeptKarte";

interface Props {
  vorschlaege: Rezept[];
  gemerkte: Rezept[];
  kategorien: string[];
  kategorie: string;
}

function sortiert(rezepte: Rezept[]): Rezept[] {
  return [...rezepte].sort((a, b) => (b.score || 0) - (a.score || 0));
}

export default function RezeptListe({
  vorschlaege: initialVorschlaege,
  gemerkte: initialGemerkte,
  kategorien,
  kategorie,
}: Props) {
  const [vorschlaege, setVorschlaege] = useState(initialVorschlaege);
  const [gemerkte, setGemerkte] = useState(initialGemerkte);
  const [fehler, setFehler] = useState<string | null>(null);
  const router = useRouter();
  const pfad = usePathname();

  // Server-Refresh (router.refresh) liefert neue Props → State synchronisieren
  useEffect(() => setVorschlaege(initialVorschlaege), [initialVorschlaege]);
  useEffect(() => setGemerkte(initialGemerkte), [initialGemerkte]);

  function setzeKategorie(wert: string) {
    router.push(pfad + (wert ? "?kategorie=" + encodeURIComponent(wert) : ""));
  }

  async function aktion(
    rezept: Rezept,
    a: string,
    kommentar?: string
  ): Promise<boolean> {
    // Optimistic: Listen sofort anpassen
    const vorher = { vorschlaege, gemerkte };
    if (a === "gemerkt") {
      setVorschlaege((rs) => rs.filter((r) => r.id !== rezept.id));
      setGemerkte((rs) => sortiert([...rs.filter((r) => r.id !== rezept.id), { ...rezept, status: "gemerkt" }]));
    } else if (a === "vorschlag") {
      setGemerkte((rs) => rs.filter((r) => r.id !== rezept.id));
      setVorschlaege((rs) => sortiert([...rs.filter((r) => r.id !== rezept.id), { ...rezept, status: "vorschlag" }]));
    } else if (a === "verworfen") {
      setVorschlaege((rs) => rs.filter((r) => r.id !== rezept.id));
      setGemerkte((rs) => rs.filter((r) => r.id !== rezept.id));
    }
    try {
      const res = await fetch("/api/rezepte", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rezept_id: rezept.id, aktion: a, kommentar }),
      });
      if (!res.ok) {
        const daten = await res.json().catch(() => ({}));
        throw new Error(daten.fehler || "HTTP " + res.status);
      }
      setFehler(null);
      router.refresh(); // Zähler in der Kopfleiste aktualisieren
      return true;
    } catch (e) {
      // Rollback
      setVorschlaege(vorher.vorschlaege);
      setGemerkte(vorher.gemerkte);
      setFehler(
        "Aktion fehlgeschlagen: " +
          (e instanceof Error ? e.message : "Unbekannter Fehler")
      );
      return false;
    }
  }

  return (
    <>
      <div className="filterleiste">
        <select
          aria-label="Kategorie filtern"
          value={kategorie}
          onChange={(e) => setzeKategorie(e.target.value)}
        >
          <option value="">Alle Kategorien</option>
          {kategorien.map((k) => (
            <option key={k} value={k}>
              {rezeptKategorieLabel(k)}
            </option>
          ))}
        </select>
      </div>

      {fehler && <div className="hinweis-fehler">⚠ {fehler}</div>}

      {vorschlaege.length === 0 ? (
        <div className="leer">
          <div className="gross">🍽</div>
          Keine offenen Rezept-Vorschläge — der nächste Agenten-Lauf bringt Nachschub.
        </div>
      ) : (
        <div className="karten">
          {vorschlaege.map((r) => (
            <RezeptKarte
              key={r.id}
              rezept={r}
              bereich="vorschlag"
              onAktion={(a, k) => aktion(r, a, k)}
            />
          ))}
        </div>
      )}

      <details className="lernkarte">
        <summary>🔖 Gemerkt ({gemerkte.length})</summary>
        <div className="lernkarte-inhalt">
          {gemerkte.length === 0 ? (
            <p style={{ color: "var(--text-dim)" }}>
              Noch nichts gemerkt — 🔖 auf einer Karte legt das Rezept hier ab.
            </p>
          ) : (
            <div className="karten">
              {gemerkte.map((r) => (
                <RezeptKarte
                  key={r.id}
                  rezept={r}
                  bereich="gemerkt"
                  onAktion={(a, k) => aktion(r, a, k)}
                />
              ))}
            </div>
          )}
        </div>
      </details>
    </>
  );
}
