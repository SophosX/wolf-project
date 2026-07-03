"use client";

// Tab-Navigation mit aktivem Zustand (Client wegen usePathname)

import Link from "next/link";
import { usePathname } from "next/navigation";

export interface TabDef {
  pfad: string;
  label: string;
  zahl: number | null;
}

export default function NavTabs({ tabs }: { tabs: TabDef[] }) {
  const pfad = usePathname();
  return (
    <nav className="tabs" aria-label="Hauptnavigation">
      {tabs.map((t) => (
        <Link
          key={t.pfad}
          href={t.pfad}
          className={"tab" + (pfad === t.pfad ? " aktiv" : "")}
        >
          {t.label}
          {t.zahl !== null && <span className="tab-zahl">{t.zahl}</span>}
        </Link>
      ))}
    </nav>
  );
}
