// /angenommen — angenommene Videos mit aufklappbarem Skript-Paket

import ListenSeite, { SuchParams } from "@/components/ListenSeite";

export const dynamic = "force-dynamic";

export default async function AngenommenSeite(props: {
  searchParams: Promise<SuchParams>;
}) {
  const sp = await props.searchParams;
  return (
    <ListenSeite
      status="angenommen"
      seite="angenommen"
      searchParams={sp}
      leerText="Noch nichts angenommen — nimm in der Inbox Kandidaten an, dann liegen hier die Skript-Pakete bereit."
    />
  );
}
