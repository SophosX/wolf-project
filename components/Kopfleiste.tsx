// Kopfleiste (Server-Komponente): Logo + Tabs mit Live-Zählern

import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeRadarProfil, zaehleRezeptVorschlaege, zaehleStatus } from "@/lib/daten";
import NavTabs from "./NavTabs";

export default async function Kopfleiste() {
  let zaehler = {
    inbox: 0,
    angenommen: 0,
    gespeichert: 0,
    strittig: 0,
    abgelehnt: 0,
    archiv: 0,
  };
  let rezepte = 0;
  const nutzer = await aktuellerNutzer();
  // Branding: "«marke» Radar" aus dem Nutzer-Profil; Fallback "Wolf Radar"
  // (Lokal-/Christian-Betrieb) bzw. "Dein Radar" (Supabase ohne Marke).
  let marke: string | null = null;
  let logo = "🐺";
  if (datenModus() === "supabase") {
    try {
      const profil = await holeRadarProfil(nutzer.userId);
      marke = ((profil?.marke as string) || "").trim() || null;
      if (marke && marke.toLowerCase() !== "wolf") logo = "📡";
      if (!marke) {
        marke = "Dein";
        logo = "📡";
      }
    } catch (e) {
      console.error("[Kopfleiste] Profil nicht ladbar:", e);
    }
  }
  try {
    zaehler = await zaehleStatus(nutzer.userId);
  } catch (e) {
    console.error("[Kopfleiste] Zähler konnten nicht geladen werden:", e);
  }
  try {
    rezepte = await zaehleRezeptVorschlaege(nutzer.userId);
  } catch (e) {
    console.error("[Kopfleiste] Rezept-Zähler konnte nicht geladen werden:", e);
  }

  const tabs = [
    { pfad: "/", label: "Inbox", zahl: zaehler.inbox },
    { pfad: "/angenommen", label: "Angenommen", zahl: zaehler.angenommen },
    { pfad: "/gespeichert", label: "Gespeichert", zahl: zaehler.gespeichert },
    { pfad: "/strittig", label: "Strittig", zahl: zaehler.strittig },
    { pfad: "/rezepte", label: "Rezepte", zahl: rezepte },
    { pfad: "/personen", label: "Personen", zahl: null },
    { pfad: "/archiv", label: "Archiv", zahl: zaehler.abgelehnt + zaehler.archiv },
    { pfad: "/agenten", label: "Agenten", zahl: null },
  ];

  return (
    <header className="kopf">
      <div className="kopf-innen">
        <div className="kopf-zeile">
          <div className="logo">
            {logo} {marke || "Wolf"} <span className="gelb">Radar</span>
          </div>
        </div>
        <NavTabs tabs={tabs} />
      </div>
    </header>
  );
}
