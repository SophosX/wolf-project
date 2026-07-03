// /archiv — abgelehnte Videos (mit Ablehn-Grund) + Archiviertes

import ListenSeite, { SuchParams } from "@/components/ListenSeite";

export const dynamic = "force-dynamic";

export default async function ArchivSeite(props: {
  searchParams: Promise<SuchParams>;
}) {
  const sp = await props.searchParams;
  return (
    <ListenSeite
      status={["abgelehnt", "archiv"]}
      seite="archiv"
      searchParams={sp}
      leerText="Archiv leer — abgelehnte Kandidaten landen hier (mit Grund)."
    />
  );
}
