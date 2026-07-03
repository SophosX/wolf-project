// /gespeichert — für später gemerkte Kandidaten

import ListenSeite, { SuchParams } from "@/components/ListenSeite";

export const dynamic = "force-dynamic";

export default async function GespeichertSeite(props: {
  searchParams: Promise<SuchParams>;
}) {
  const sp = await props.searchParams;
  return (
    <ListenSeite
      status="gespeichert"
      seite="gespeichert"
      searchParams={sp}
      leerText="Nichts gespeichert — markiere Kandidaten in der Inbox mit 🔖 Später."
    />
  );
}
