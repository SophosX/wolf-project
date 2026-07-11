"use client";

// Tab-Navigation mit aktivem Zustand + Scroll-Affordance (Client wegen usePathname/Refs)

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export interface TabDef {
  pfad: string;
  label: string;
  zahl: number | null;
}

export default function NavTabs({ tabs }: { tabs: TabDef[] }) {
  const pfad = usePathname();
  const navRef = useRef<HTMLElement>(null);
  const [rand, setRand] = useState({ links: false, rechts: false });

  // Fade-Ränder je nach Scrollposition/Breite aktualisieren
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const pruefe = () => {
      const links = nav.scrollLeft > 1;
      const rechts = nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 1;
      setRand((r) => (r.links === links && r.rechts === rechts ? r : { links, rechts }));
    };
    pruefe();
    nav.addEventListener("scroll", pruefe, { passive: true });
    const ro = new ResizeObserver(pruefe);
    ro.observe(nav);
    return () => {
      nav.removeEventListener("scroll", pruefe);
      ro.disconnect();
    };
  }, [tabs]);

  // Aktiven Tab bei Pfadwechsel/Mount sichtbar machen (instant, ohne Animation)
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const aktiv = nav.querySelector<HTMLElement>(".tab.aktiv");
    if (!aktiv) return;
    const nr = nav.getBoundingClientRect();
    const ar = aktiv.getBoundingClientRect();
    const ziel = nav.scrollLeft + (ar.left - nr.left) - (nav.clientWidth - ar.width) / 2;
    nav.scrollLeft = Math.max(0, ziel);
  }, [pfad]);

  return (
    <nav
      ref={navRef}
      className="tabs"
      aria-label="Hauptnavigation"
      data-mehr-links={rand.links ? "true" : undefined}
      data-mehr-rechts={rand.rechts ? "true" : undefined}
    >
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
