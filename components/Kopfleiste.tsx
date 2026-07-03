// Kopfleiste (Server-Komponente): Logo + Tabs mit Live-Zählern

import { zaehleRezeptVorschlaege, zaehleStatus } from "@/lib/daten";
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
  try {
    zaehler = await zaehleStatus();
  } catch (e) {
    console.error("[Kopfleiste] Zähler konnten nicht geladen werden:", e);
  }
  try {
    rezepte = await zaehleRezeptVorschlaege();
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
            🐺 Wolf <span className="gelb">Radar</span>
          </div>
        </div>
        <NavTabs tabs={tabs} />
      </div>
    </header>
  );
}
