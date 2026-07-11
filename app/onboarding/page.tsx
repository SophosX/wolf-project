// /onboarding — 3-Schritte-Wizard: Kanal verbinden → Import läuft → Review & Interview.
// Der Import-Agent (scraper/onboarding_agent.py) liest die eigenen Videos des
// Nutzers und baut daraus Profil, Themen, Suchqueries und die Trigger-Liste.
"use client";

import { useCallback, useEffect, useState } from "react";

interface Thema {
  slug: string;
  name: string;
  kerngewicht: number;
  aktiv: boolean;
}
interface TriggerEintrag {
  trigger: string;
}
interface OnboardingDaten {
  status: string;
  profil: {
    nische: string | null;
    marke: string | null;
    reaktions_ausloeser: TriggerEintrag[];
  } | null;
  themen: Thema[];
  queries: { plattform: string; query: string }[];
  personen: { name: string; folgt: boolean }[];
}

export default function OnboardingSeite() {
  const [daten, setDaten] = useState<OnboardingDaten | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  // Schritt 1
  const [handle, setHandle] = useState("");
  const [plattform, setPlattform] = useState("youtube");
  const [marke, setMarke] = useState("");

  // Schritt 3
  const [triggerText, setTriggerText] = useState<string | null>(null);
  const [nische, setNische] = useState("");
  const [themenAb, setThemenAb] = useState<Record<string, boolean>>({});

  const lade = useCallback(async () => {
    try {
      const res = await fetch("/api/onboarding");
      if (!res.ok) throw new Error(String(res.status));
      const d = (await res.json()) as OnboardingDaten;
      setDaten(d);
      if (d.profil?.nische && !nische) setNische(d.profil.nische);
      if (triggerText === null && d.profil?.reaktions_ausloeser?.length) {
        setTriggerText(d.profil.reaktions_ausloeser.map((t) => t.trigger).join("\n"));
      }
    } catch {
      setFehler("Onboarding-Status nicht ladbar.");
    }
  }, [nische, triggerText]);

  useEffect(() => {
    lade();
  }, [lade]);

  // Import-Fortschritt pollen
  useEffect(() => {
    if (daten?.status !== "import_laeuft") return;
    const timer = setInterval(lade, 5000);
    return () => clearInterval(timer);
  }, [daten?.status, lade]);

  async function starteImport(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    setLaeuft(true);
    try {
      const res = await fetch("/api/onboarding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kanaele: [{ plattform, handle }], marke }),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Start fehlgeschlagen.");
      else await lade();
    } finally {
      setLaeuft(false);
    }
  }

  async function abschliessen() {
    setFehler(null);
    setLaeuft(true);
    try {
      const res = await fetch("/api/onboarding", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fertig: true,
          nische,
          marke,
          trigger: (triggerText || "").split("\n").map((t) => t.trim()).filter(Boolean),
          themen_aktiv: themenAb,
        }),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Abschluss fehlgeschlagen.");
      else window.location.href = "/";
    } finally {
      setLaeuft(false);
    }
  }

  if (!daten) {
    return <main className="container"><p>{fehler || "Lade …"}</p></main>;
  }

  return (
    <main className="container" style={{ maxWidth: 720, paddingTop: 32 }}>
      <h1>📡 Dein Radar einrichten</h1>
      {fehler && <div className="hinweis-fehler">{fehler}</div>}

      {daten.status === "offen" && (
        <form className="karte" onSubmit={starteImport}>
          <div className="abschnitt-titel">Schritt 1 · Kanal verbinden</div>
          <p>
            Dein Radar liest deine eigenen Videos und lernt daraus: deine Themen,
            deine Positionen, deinen Ton — und was dich erfahrungsgemäß triggert.
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select value={plattform} onChange={(e) => setPlattform(e.target.value)}>
              <option value="youtube">YouTube</option>
              <option value="tiktok">TikTok</option>
            </select>
            <input
              placeholder="@dein-handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              required
              style={{ flex: 1, minWidth: 200 }}
            />
          </div>
          <input
            placeholder="Wie soll dein Radar heißen? (z. B. dein Name/deine Marke)"
            value={marke}
            onChange={(e) => setMarke(e.target.value)}
            style={{ marginTop: 8, width: "100%" }}
          />
          <button className="btn primaer" type="submit" disabled={laeuft} style={{ marginTop: 12 }}>
            {laeuft ? "Startet …" : "Meine Videos analysieren"}
          </button>
        </form>
      )}

      {daten.status === "import_laeuft" && (
        <div className="karte">
          <div className="abschnitt-titel">Schritt 2 · Dein Radar liest deine Videos …</div>
          <p>
            Wir sammeln deine Videos, holen Transkripte und destillieren daraus dein
            Profil. Das dauert je nach Kanalgröße einige Minuten — du kannst die
            Seite offen lassen, sie aktualisiert sich selbst.
          </p>
        </div>
      )}

      {daten.status === "review" && (
        <>
          <div className="karte">
            <div className="abschnitt-titel">Schritt 3 · Stimmt das so?</div>
            <p>Wir haben deine Videos gelesen. Prüfe kurz, ob dein Radar dich richtig verstanden hat.</p>
            <label style={{ display: "block", marginTop: 8 }}>
              Deine Nische
              <input value={nische} onChange={(e) => setNische(e.target.value)}
                     style={{ width: "100%" }} />
            </label>
            <label style={{ display: "block", marginTop: 8 }}>
              Name deines Radars
              <input value={marke || daten.profil?.marke || ""}
                     onChange={(e) => setMarke(e.target.value)} style={{ width: "100%" }} />
            </label>
          </div>

          <div className="karte">
            <div className="abschnitt-titel">Deine Themen ({daten.themen.length})</div>
            <p>Abgewählte Themen fließen nicht in die Suche ein.</p>
            {daten.themen.map((t) => (
              <label key={t.slug} style={{ display: "block", padding: "2px 0" }}>
                <input
                  type="checkbox"
                  checked={themenAb[t.slug] ?? t.aktiv}
                  onChange={(e) => setThemenAb({ ...themenAb, [t.slug]: e.target.checked })}
                />{" "}
                {t.name} <span style={{ color: "var(--text-dim)" }}>
                  (Gewicht {Math.round(t.kerngewicht * 100)} %)
                </span>
              </label>
            ))}
          </div>

          <div className="karte">
            <div className="abschnitt-titel">Was dich erfahrungsgemäß triggert</div>
            <p>
              Aus deinen Videos abgeleitet — ergänze oder streiche frei (eine Zeile
              pro Trigger). Dein Radar lernt später aus deinem Feedback weiter.
            </p>
            <textarea
              rows={8}
              style={{ width: "100%" }}
              value={triggerText || ""}
              onChange={(e) => setTriggerText(e.target.value)}
            />
          </div>

          <div className="karte">
            <div className="abschnitt-titel">Suche ({daten.queries.length} Suchanfragen)</div>
            <p style={{ color: "var(--text-dim)" }}>
              {daten.queries.slice(0, 8).map((q) => "„" + q.query + "“").join(" · ")}
              {daten.queries.length > 8 ? " …" : ""}
            </p>
            {daten.personen.length > 0 && (
              <p style={{ color: "var(--text-dim)" }}>
                Erkannte Gegenspieler: {daten.personen.map((p) => p.name).join(", ")} —
                folgen kannst du ihnen später im Personen-Tab.
              </p>
            )}
          </div>

          <button className="btn primaer" onClick={abschliessen} disabled={laeuft}>
            {laeuft ? "Startet …" : "Radar starten 🚀"}
          </button>
        </>
      )}

      {daten.status === "fertig" && (
        <div className="karte">
          <p>Dein Radar läuft bereits — <a href="/">zur Inbox</a>.</p>
        </div>
      )}
    </main>
  );
}
