// /rezepte — REZEPTE-RADAR: Community-erprobte Abnehm-Rezepte, sortiert nach
// Score (0.5*Community-Resonanz + 0.5*Chris-Fit). Aktionen: Merken / Verwerfen /
// Kommentar (der Algorithmus lernt daraus). Gemerkte eingeklappt darunter.

import { holeRezepte } from "@/lib/daten";
import RezeptListe from "@/components/RezeptListe";
import type { Rezept } from "@/lib/typen";

export const dynamic = "force-dynamic";

interface SuchParams {
  kategorie?: string;
}

export default async function RezepteSeite(props: {
  searchParams: Promise<SuchParams>;
}) {
  const sp = await props.searchParams;
  const kategorie = sp.kategorie || "";

  let vorschlaege: Rezept[] = [];
  let gemerkte: Rezept[] = [];
  let kategorien: string[] = [];
  let ladefehler: string | null = null;

  try {
    // Kategorie-Auswahl aus allen Vorschlägen (unabhängig vom Filter)
    const basis = await holeRezepte({ status: "vorschlag" });
    kategorien = [...new Set(basis.map((r) => r.kategorie).filter(Boolean))];

    vorschlaege = kategorie
      ? basis.filter((r) => r.kategorie === kategorie)
      : basis;
    gemerkte = await holeRezepte({ status: "gemerkt" });
  } catch (e) {
    console.error("[RezepteSeite]", e);
    ladefehler = e instanceof Error ? e.message : "Rezepte konnten nicht geladen werden";
  }

  return (
    <>
      <div className="banner">
        <b>Rezepte-Radar:</b> Rezepte, die in der Community <b>nachweislich
        ankommen</b> (Views, Likes, Velocity) und zu „Genuss ohne Reue“ passen —
        High Protein, kalorienbewusst, simpel. Kommentare fließen ins Lernen ein.
      </div>
      {ladefehler && <div className="hinweis-fehler">⚠ {ladefehler}</div>}
      <RezeptListe
        vorschlaege={vorschlaege}
        gemerkte={gemerkte}
        kategorien={kategorien}
        kategorie={kategorie}
      />
    </>
  );
}
