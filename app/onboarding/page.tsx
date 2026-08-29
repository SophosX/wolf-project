// /onboarding — geführter 3-Schritte-Wizard:
//   1) Content connecten + Fokus beschreiben
//   2) Import läuft (Live-Fortschritt des Agenten, erklärt WAS gerade passiert)
//   3) Review & Feinschliff ("Stimmt das so?") → Radar starten
// Durchgehendes Erwartungsmanagement: Der Nutzer versteht, WARUM die Inbox
// klein startet und was als Nächstes automatisch passiert.
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
interface InteressenChip {
  slug: string;
  label: string;
  emoji: string;
  gewaehlt: boolean;
}
interface OnboardingDaten {
  status: string;
  fortschritt: string | null;
  import_status: string | null;
  interessen?: InteressenChip[];
  profil: {
    nische: string | null;
    marke: string | null;
    reaktions_ausloeser: TriggerEintrag[];
  } | null;
  themen: Thema[];
  queries: { plattform: string; query: string }[];
  personen: { name: string; folgt: boolean }[];
}

function SchrittKopf({ aktiv }: { aktiv: 1 | 2 | 3 }) {
  const schritte = ["Content verbinden", "Radar lernt dich kennen", "Prüfen & starten"];
  return (
    <div style={{ display: "flex", gap: 6, margin: "14px 0 20px", flexWrap: "wrap" }}>
      {schritte.map((s, i) => (
        <div
          key={s}
          style={{
            padding: "6px 12px",
            borderRadius: 20,
            fontSize: 13,
            background: i + 1 === aktiv ? "var(--akzent)" : "var(--karte, #222)",
            color: i + 1 === aktiv ? "#000" : "var(--text-dim)",
            opacity: i + 1 <= aktiv ? 1 : 0.55,
          }}
        >
          {i + 1 < aktiv ? "✓ " : i + 1 + " · "}
          {s}
        </div>
      ))}
    </div>
  );
}

export default function OnboardingSeite() {
  const [daten, setDaten] = useState<OnboardingDaten | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  // Schritt 1
  const [handle, setHandle] = useState("");
  const [plattform, setPlattform] = useState("youtube");
  const [marke, setMarke] = useState("");
  const [fokus, setFokus] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [starterHinweis, setStarterHinweis] = useState<string | null>(null);
  const [ohneKanal, setOhneKanal] = useState(false);

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
      setFehler("Onboarding-Status nicht ladbar — bitte Seite neu laden.");
    }
  }, [nische, triggerText]);

  useEffect(() => {
    lade();
  }, [lade]);

  // Import-Fortschritt live pollen
  useEffect(() => {
    if (daten?.status !== "import_laeuft") return;
    const timer = setInterval(lade, 4000);
    return () => clearInterval(timer);
  }, [daten?.status, lade]);

  async function starteImport(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    if (ohneKanal && labels.length === 0) {
      setFehler("Ohne Kanal brauchen wir mindestens ein Interesse als Startpunkt.");
      return;
    }
    setLaeuft(true);
    try {
      const res = await fetch("/api/onboarding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kanaele: ohneKanal ? [] : [{ plattform, handle }],
          marke,
          fokus,
          labels,
        }),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Start fehlgeschlagen.");
      else {
        setStarterHinweis(starterText(d.starter));
        await lade();
      }
    } finally {
      setLaeuft(false);
    }
  }

  /** Plan-Cap transparent machen: was NICHT übernommen wurde (statt still zu verschwinden). */
  function starterText(s: {
    themen_neu: number; themen_verworfen: number; queries_neu: number; queries_verworfen: number;
    bereiche_ohne_thema: string[]; limits: { themen: number; suchqueries: number };
  } | null | undefined): string | null {
    if (!s) return null;
    if (s.themen_verworfen === 0 && s.queries_verworfen === 0) return null;
    const teile = [];
    if (s.themen_verworfen > 0) teile.push(`${s.themen_verworfen} Themen`);
    if (s.queries_verworfen > 0) teile.push(`${s.queries_verworfen} Suchanfragen`);
    return `Dein Plan erlaubt ${s.limits.themen} Themen und ${s.limits.suchqueries} Suchanfragen — ` +
      `wir haben aus jedem gewählten Bereich die wichtigsten genommen (${teile.join(" und ")} ` +
      `nicht übernommen). Unter „Profil“ kannst du jederzeit tauschen.`;
  }

  function toggleLabel(slug: string) {
    setLabels((alt) =>
      alt.includes(slug) ? alt.filter((l) => l !== slug) : [...alt, slug]
    );
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
          marke: marke || daten?.profil?.marke || "",
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
    return <main className="container" style={{ paddingTop: 32 }}><p>{fehler || "Lade …"}</p></main>;
  }

  return (
    <main className="container" style={{ maxWidth: 720, paddingTop: 28 }}>
      <h1>📡 Dein Radar einrichten</h1>
      <SchrittKopf aktiv={daten.status === "offen" ? 1 : daten.status === "import_laeuft" ? 2 : 3} />
      {fehler && <div className="hinweis-fehler">{fehler}</div>}

      {daten.status === "offen" && (
        <form onSubmit={starteImport}>
          <div className="karte" style={{ padding: 16 }}>
            <div className="abschnitt-titel">Warum dieser Schritt?</div>
            <p>
              Dein Radar ist kein fertiges Produkt von der Stange — es wird{" "}
              <b>auf dich gebaut</b>. Dafür liest es zuerst deine eigenen Videos und
              lernt daraus deine Themen, deine Positionen, deinen Ton — und was dich
              erfahrungsgemäß triggert. Deshalb startet es auch nicht mit hunderten
              Treffern: Es sucht ab Tag 1 <b>gezielt für dich</b> statt dir
              Beliebiges vorzusetzen.
            </p>
          </div>

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">1 · Was interessiert dich?</div>
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
              Wähle deine Bereiche — damit weiß dein Radar <b>sofort</b>, wo es
              suchen soll. Dein Kanal-Import verfeinert das gleich noch.
            </p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
              {(daten.interessen || []).map((b) => {
                const aktiv = labels.includes(b.slug);
                return (
                  <button
                    key={b.slug}
                    type="button"
                    onClick={() => toggleLabel(b.slug)}
                    className="btn"
                    style={{
                      borderRadius: 20,
                      padding: "7px 14px",
                      background: aktiv ? "var(--akzent)" : undefined,
                      color: aktiv ? "#000" : undefined,
                      fontWeight: aktiv ? 600 : 400,
                    }}
                  >
                    {b.emoji} {b.label} {aktiv ? "✓" : ""}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">2 · Deinen Content verbinden</div>
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
              Nur öffentliche Daten — kein Login bei YouTube/TikTok nötig. Aus
              deinen Videos lernt das Radar deine Positionen und deinen Ton.
            </p>
            {!ohneKanal && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <select value={plattform} onChange={(e) => setPlattform(e.target.value)}>
                  <option value="youtube">YouTube</option>
                  <option value="tiktok">TikTok</option>
                </select>
                <input
                  placeholder="@dein-handle"
                  value={handle}
                  onChange={(e) => setHandle(e.target.value)}
                  required={!ohneKanal}
                  style={{ flex: 1, minWidth: 200 }}
                />
              </div>
            )}
            <label style={{ display: "block", marginTop: 8, color: "var(--text-dim)", fontSize: 14 }}>
              <input
                type="checkbox"
                checked={ohneKanal}
                onChange={(e) => setOhneKanal(e.target.checked)}
              />{" "}
              Später verbinden — erstmal nur mit meinen Interessen starten
            </label>
          </div>

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">3 · Deinen Fokus beschreiben</div>
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
              Worauf willst du reagieren? Je konkreter, desto besser trifft dein
              Radar von Anfang an. (Optional, aber sehr empfohlen.)
            </p>
            <textarea
              rows={3}
              style={{ width: "100%" }}
              placeholder='z. B. "Falsche Steuer-Spartipps und Krypto-Scam-Versprechen — keine Politik, keine Immobilien."'
              value={fokus}
              onChange={(e) => setFokus(e.target.value)}
            />
            <input
              placeholder="Wie soll dein Radar heißen? (dein Name / deine Marke)"
              value={marke}
              onChange={(e) => setMarke(e.target.value)}
              style={{ marginTop: 8, width: "100%" }}
            />
          </div>

          <button className="btn primaer" type="submit" disabled={laeuft} style={{ marginTop: 14 }}>
            {laeuft
              ? "Startet …"
              : ohneKanal
                ? "Radar mit meinen Interessen starten →"
                : "Meine Videos analysieren →"}
          </button>
          <p style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 6 }}>
            {ohneKanal
              ? "Du bekommst sofort ein Start-Profil aus deinen Interessen — den Kanal kannst du jederzeit nachziehen."
              : "Dauert je nach Kanalgröße 5–15 Minuten. Du siehst live, was passiert."}
          </p>
        </form>
      )}

      {daten.status === "import_laeuft" && starterHinweis && (
        <div className="karte" style={{ padding: 12, marginBottom: 12, borderColor: "var(--akzent)" }}>
          ℹ️ {starterHinweis}
        </div>
      )}
      {daten.status === "import_laeuft" && (
        <>
          <div className="karte" style={{ padding: 16 }}>
            <div className="abschnitt-titel">Dein Radar lernt dich gerade kennen …</div>
            <p style={{ fontSize: 15 }}>
              <span className="badge-frisch">⏳ läuft</span>{" "}
              {daten.fortschritt || "Import startet — der Agent meldet sich gleich mit dem ersten Schritt …"}
            </p>
            <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
              Die Seite aktualisiert sich alle paar Sekunden von selbst — du kannst
              sie auch schließen und später wiederkommen.
            </p>
          </div>
          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">Was hier gerade passiert</div>
            <ol style={{ paddingLeft: 18, lineHeight: 1.9 }}>
              <li>Deine Videos werden eingesammelt (Bestseller + Neueste).</li>
              <li>Transkripte werden geholt — die KI liest, nicht nur Titel.</li>
              <li>Daraus destilliert sie: deine Positionen, deinen Ton, deine Themen
                  und deine Trigger-Liste.</li>
              <li>Zum Schluss baut sie dein Sprach-Gedächtnis auf, damit spätere
                  Skripte nach <i>dir</i> klingen.</li>
            </ol>
          </div>
        </>
      )}

      {daten.status === "review" && (
        <>
          {starterHinweis && (
            <div className="karte" style={{ padding: 12, marginBottom: 12, borderColor: "var(--akzent)" }}>
              ℹ️ {starterHinweis}
            </div>
          )}
          <div className="karte" style={{ padding: 16 }}>
            <div className="abschnitt-titel">Wir haben deine Videos gelesen — stimmt das so?</div>
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
              Alles hier ist dein Startprofil. Du kannst es jetzt korrigieren —
              und später jederzeit unter „Profil" ändern. Dein Radar lernt
              außerdem aus jeder Annehmen/Ablehnen-Entscheidung weiter.
            </p>
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

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">Deine Themen ({daten.themen.length})</div>
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
              Abgewählte Themen fließen nicht in die Suche ein.
            </p>
            {daten.themen.map((t) => (
              <label key={t.slug} style={{ display: "block", padding: "2px 0" }}>
                <input
                  type="checkbox"
                  checked={themenAb[t.slug] ?? t.aktiv}
                  onChange={(e) => setThemenAb({ ...themenAb, [t.slug]: e.target.checked })}
                />{" "}
                {t.name}{" "}
                <span style={{ color: "var(--text-dim)" }}>
                  (Gewicht {Math.round(t.kerngewicht * 100)} %)
                </span>
              </label>
            ))}
          </div>

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">Was dich erfahrungsgemäß triggert</div>
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
              Aus deinen Videos abgeleitet — ergänze oder streiche frei (eine Zeile
              pro Trigger). Diese Liste lebt: Sie schreibt sich anhand deines
              Feedbacks täglich fort.
            </p>
            <textarea
              rows={8}
              style={{ width: "100%" }}
              value={triggerText || ""}
              onChange={(e) => setTriggerText(e.target.value)}
            />
          </div>

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">Dein Suchplan ({daten.queries.length} Suchanfragen)</div>
            <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
              {daten.queries.slice(0, 8).map((q) => "„" + q.query + "“").join(" · ")}
              {daten.queries.length > 8 ? " …" : ""}
            </p>
            {daten.personen.length > 0 && (
              <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
                Erkannte Gegenspieler: {daten.personen.map((p) => p.name).join(", ")} —
                folgen kannst du ihnen später im Personen-Tab.
              </p>
            )}
          </div>

          <div className="karte" style={{ padding: 16, marginTop: 12 }}>
            <div className="abschnitt-titel">Was nach dem Start passiert</div>
            <p style={{ fontSize: 14 }}>
              Direkt nach dem Start läuft eine <b>erste Suche mit deinen
              Suchanfragen</b> — die ersten eigenen Funde sind in etwa
              30&nbsp;Minuten da. Ab dann sucht dein Radar automatisch alle paar
              Stunden. Eine gut gefüllte, wirklich relevante Inbox wächst über
              die ersten 24–48 Stunden — Qualität vor Masse.
            </p>
          </div>

          <button className="btn primaer" onClick={abschliessen} disabled={laeuft} style={{ marginTop: 8 }}>
            {laeuft ? "Startet …" : "Radar starten 🚀"}
          </button>
        </>
      )}

      {daten.status === "fertig" && (
        <div className="karte" style={{ padding: 16 }}>
          <p>Dein Radar läuft bereits — <a href="/">zur Inbox</a>.</p>
        </div>
      )}
    </main>
  );
}
