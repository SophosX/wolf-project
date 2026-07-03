// / — Inbox: gerankte Kandidaten (score desc), eine Karte = eine Entscheidung

import ListenSeite, { SuchParams } from "@/components/ListenSeite";

export const dynamic = "force-dynamic";

export default async function InboxSeite(props: {
  searchParams: Promise<SuchParams>;
}) {
  const sp = await props.searchParams;
  return (
    <ListenSeite
      status="inbox"
      seite="inbox"
      searchParams={sp}
      leerText="Inbox leer — der Radar hat gerade keine neuen Kandidaten. Schau im Agenten-Status nach dem letzten Lauf."
    />
  );
}
