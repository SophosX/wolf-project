// Kopfleiste (Server-Komponente): Logo + Tabs mit Live-Zählern

import { aktuellerNutzer } from "@/lib/auth";
import { datenModus, holeEinstellungsWert, holeProfil, holeRadarProfil, zaehleRezeptVorschlaege, zaehleStatus } from "@/lib/daten";
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
  let istAdmin = false;
  // Rezepte ist ein optionales Feature (Ernaehrungs-Nische) — Tab nur, wenn
  // der Nutzer es aktiviert hat. Lokal-Modus: immer an (Christian-Dev).
  let rezepteAktiv = datenModus() !== "supabase";
  if (datenModus() === "supabase") {
    try {
      const [profil, konto] = await Promise.all([
        holeRadarProfil(nutzer.userId),
        holeProfil(nutzer.userId),
      ]);
      marke = ((profil?.marke as string) || "").trim() || null;
      if (marke && marke.toLowerCase() !== "wolf") logo = "📡";
      if (!marke) {
        marke = "Dein";
        logo = "📡";
      }
      // Admin-Tab nur bei echter Anmeldung (nicht im offenen Code-Betrieb)
      istAdmin = nutzer.quelle === "supabase" && konto?.rolle === "admin";
      rezepteAktiv = Boolean(
        await holeEinstellungsWert(nutzer.userId, "rezepte_aktiv", false)
      );
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
    ...(rezepteAktiv ? [{ pfad: "/rezepte", label: "Rezepte", zahl: rezepte }] : []),
    { pfad: "/personen", label: "Personen", zahl: null },
    { pfad: "/archiv", label: "Archiv", zahl: zaehler.abgelehnt + zaehler.archiv },
    { pfad: "/agenten", label: "Agenten", zahl: null },
    // Profil-Pflege gibt es nur im Multi-Tenant-Betrieb
    ...(datenModus() === "supabase"
      ? [{ pfad: "/einstellungen", label: "Profil", zahl: null }]
      : []),
    ...(istAdmin ? [{ pfad: "/admin", label: "Admin", zahl: null }] : []),
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
