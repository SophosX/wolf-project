"use client";

// Filter: Plattform, Thema, Zeitraum — schreibt Query-Parameter in die URL

import { usePathname, useRouter } from "next/navigation";
import { themaLabel } from "@/lib/typen";

interface Props {
  plattform: string;
  thema: string;
  zeitraum: string;
  themen: string[];
}

export default function FilterLeiste({ plattform, thema, zeitraum, themen }: Props) {
  const router = useRouter();
  const pfad = usePathname();

  function setzeFilter(patch: Partial<Props>) {
    const werte = { plattform, thema, zeitraum, ...patch };
    const params = new URLSearchParams();
    if (werte.plattform) params.set("plattform", werte.plattform);
    if (werte.thema) params.set("thema", werte.thema);
    if (werte.zeitraum) params.set("zeitraum", werte.zeitraum);
    const query = params.toString();
    router.push(pfad + (query ? "?" + query : ""));
  }

  return (
    <div className="filterleiste">
      <select
        aria-label="Plattform filtern"
        value={plattform}
        onChange={(e) => setzeFilter({ plattform: e.target.value })}
      >
        <option value="">Alle Plattformen</option>
        <option value="youtube">YouTube</option>
        <option value="tiktok">TikTok</option>
        <option value="instagram">Instagram</option>
      </select>
      <select
        aria-label="Thema filtern"
        value={thema}
        onChange={(e) => setzeFilter({ thema: e.target.value })}
      >
        <option value="">Alle Themen</option>
        {themen.map((t) => (
          <option key={t} value={t}>
            {themaLabel(t)}
          </option>
        ))}
      </select>
      <select
        aria-label="Zeitraum filtern"
        value={zeitraum}
        onChange={(e) => setzeFilter({ zeitraum: e.target.value })}
      >
        <option value="">Alle Zeiträume</option>
        <option value="1">Letzte 24 Std.</option>
        <option value="7">Letzte 7 Tage</option>
        <option value="14">Letzte 14 Tage</option>
        <option value="30">Letzte 30 Tage</option>
      </select>
    </div>
  );
}
