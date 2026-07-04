// Einheitliche, prominente Quellen-Darstellung: nummerierte, klickbare Pills.
// Genutzt an der VideoKarte (Belege aus der Websuche), im Skript-Paket und im
// Faktencheck-Modal — eine Optik für alle Belege.

import type { Quelle } from "@/lib/typen";

interface Props {
  quellen: Quelle[];
  label?: string;
  max?: number;
}

function kurzTitel(titel: string): string {
  const t = (titel || "").trim();
  return t.length > 38 ? t.slice(0, 36) + "…" : t;
}

export default function QuellenPills({ quellen, label, max = 6 }: Props) {
  if (!quellen || quellen.length === 0) return null;
  return (
    <div className="quellen-pills">
      {label && <span className="quellen-pills-label">{label}</span>}
      <span className="quellen-pills-liste">
        {quellen.slice(0, max).map((q, i) => (
          <a
            key={q.url + i}
            className="quelle-pill"
            href={q.url}
            target="_blank"
            rel="noopener noreferrer"
            title={q.titel}
          >
            <span className="quelle-pill-nr">{i + 1}</span>
            {kurzTitel(q.titel)}
          </a>
        ))}
      </span>
    </div>
  );
}
