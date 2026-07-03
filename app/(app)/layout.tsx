// Layout für alle App-Seiten (hinter Zugangscode): Kopfleiste + Lern-Karte

import Kopfleiste from "@/components/Kopfleiste";
import LernKarte from "@/components/LernKarte";

export const dynamic = "force-dynamic";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
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
