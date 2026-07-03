// /strittig — nicht eindeutig widerlegbare Aussagen (transparent statt gelöscht)

import ListenSeite, { SuchParams } from "@/components/ListenSeite";

export const dynamic = "force-dynamic";

export default async function StrittigSeite(props: {
  searchParams: Promise<SuchParams>;
}) {
  const sp = await props.searchParams;
  return (
    <>
      <div className="banner">
        <b>Strittig:</b> Diese Aussagen sind <b>nicht eindeutig genug</b> — der
        Radar flaggt konservativ. „Kann sein, muss aber nicht“ ist kein
        Reaktionsanlass, sondern höchstens eine Einordnung.
      </div>
      <ListenSeite
        status="strittig"
        seite="strittig"
        searchParams={sp}
        leerText="Keine strittigen Fälle — der Radar hat aktuell nur eindeutige Kandidaten."
      />
    </>
  );
}
