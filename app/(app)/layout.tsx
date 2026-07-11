// Layout für alle App-Seiten (hinter Login/Zugangscode): Kopfleiste + Lern-Karte.
// Onboarding-Weiche lebt HIER (nicht in der Middleware — kein DB-Roundtrip im
// Edge): Supabase-Nutzer ohne abgeschlossenes Onboarding landen im Wizard.

import { redirect } from "next/navigation";
import { aktuellerNutzer } from "@/lib/auth";
import { holeProfil } from "@/lib/daten";
import Kopfleiste from "@/components/Kopfleiste";
import LernKarte from "@/components/LernKarte";

export const dynamic = "force-dynamic";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const nutzer = await aktuellerNutzer();
  if (nutzer.quelle === "supabase") {
    let onboardingOffen = false;
    try {
      const profil = await holeProfil(nutzer.userId);
      onboardingOffen = Boolean(profil && profil.onboarding_status !== "fertig");
    } catch (e) {
      console.error("[AppLayout] Profil nicht ladbar:", e);
    }
    if (onboardingOffen) redirect("/onboarding");
  }
  return (
    <>
      <Kopfleiste />
      <main className="container">
        <LernKarte />
        {children}
      </main>
    </>
  );
}
