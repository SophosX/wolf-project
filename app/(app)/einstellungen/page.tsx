// /einstellungen — Dein Radar-Profil pflegen: Marke/Nische, Themen (an/aus),
// Suchqueries (hinzufügen/löschen), Trigger-Liste, Beobachtungsliste, Plan.
// Nutzt die Onboarding-API (GET/PUT) — gleiche Datenbasis, gleiche Rechte.
"use client";

import { useCallback, useEffect, useState } from "react";

interface Thema { slug: string; name: string; kerngewicht: number; aktiv: boolean }
interface Query { id: number; plattform: string; query: string; aktiv: boolean }
interface Person { id: number; name: string; plattform: string | null; handle: string | null; folgt: boolean }
interface Trigger { trigger: string; staerke?: number; quelle?: string }
interface Daten {
  status: string;
  profil: { nische: string | null; marke: string | null; reaktions_ausloeser: Trigger[] } | null;
  themen: Thema[];
  queries: Query[];
  personen: Person[];
}

export default function EinstellungenSeite() {
  const [daten, setDaten] = useState<Daten | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  const [marke, setMarke] = useState<string | null>(null);
  const [nische, setNische] = useState<string | null>(null);
  const [triggerText, setTriggerText] = useState<string | null>(null);
  const [themenAb, setThemenAb] = useState<Record<string, boolean>>({});
  const [neueQuery, setNeueQuery] = useState("");
  const [neuePlattform, setNeuePlattform] = useState("youtube");
  const [loeschListe, setLoeschListe] = useState<number[]>([]);

  const lade = useCallback(async () => {
    try {
      const res = await fetch("/api/onboarding");
      if (!res.ok) {
        setFehler(
          res.status === 501
            ? "Einstellungen gibt es nur im Multi-Tenant-Betrieb (angemeldeter Nutzer)."
            : "Einstellungen nicht ladbar."
        );
        return;
      }
      const d = (await res.json()) as Daten;
      setDaten(d);
      setLoeschListe([]);
    } catch {
      setFehler("Netzwerkfehler.");
    }
  }, []);

  useEffect(() => {
    lade();
  }, [lade]);

  async function kontoLoeschen() {
    const sicher = window.prompt(
      'Das löscht dein Konto und ALLE deine Daten unwiderruflich (DSGVO). Tippe LOESCHEN zum Bestätigen:'
    );
    if (sicher !== "LOESCHEN") return;
    setLaeuft(true);
    try {
      const res = await fetch("/api/konto", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bestaetigung: "LOESCHEN" }),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Löschung fehlgeschlagen.");
      else window.location.href = "/login";
    } finally {
      setLaeuft(false);
    }
  }

  async function speichern() {
    setLaeuft(true);
    setFehler(null);
    setMeldung(null);
    try {
      const body: Record<string, unknown> = { themen_aktiv: themenAb };
      if (marke !== null) body.marke = marke;
      if (nische !== null) body.nische = nische;
      if (triggerText !== null) {
        body.trigger = triggerText.split("\n").map((t) => t.trim()).filter(Boolean);
      }
      if (neueQuery.trim().length > 2) {
        body.queries_neu = [{ plattform: neuePlattform, query: neueQuery.trim() }];
      }
      if (loeschListe.length > 0) body.queries_loeschen = loeschListe;
      const res = await fetch("/api/onboarding", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Speichern fehlgeschlagen.");
      else {
        setMeldung("Gespeichert — Änderungen greifen ab dem nächsten Lauf.");
        setNeueQuery("");
        await lade();
      }
    } finally {
      setLaeuft(false);
    }
  }

  if (!daten) {
    return <p>{fehler || "Lade …"}</p>;
  }
  const profil = daten.profil;

  return (
    <>
      <div className="banner">
        <b>Dein Radar-Profil.</b> Alles hier steuert, was dein Radar sucht, wie es
        bewertet und in wessen Ton es schreibt.
      </div>
      {fehler && <div className="hinweis-fehler">{fehler}</div>}
      {meldung && <div className="banner">{meldung}</div>}

      <div className="karte" style={{ padding: 16 }}>
        <div className="abschnitt-titel">Identität</div>
        <label style={{ display: "block", marginTop: 6 }}>
          Name deines Radars (Marke)
          <input
            style={{ width: "100%" }}
            value={marke ?? profil?.marke ?? ""}
            onChange={(e) => setMarke(e.target.value)}
          />
        </label>
        <label style={{ display: "block", marginTop: 8 }}>
          Nische
          <input
            style={{ width: "100%" }}
            value={nische ?? profil?.nische ?? ""}
            onChange={(e) => setNische(e.target.value)}
          />
        </label>
      </div>

      <div className="karte" style={{ padding: 16, marginTop: 12 }}>
        <div className="abschnitt-titel">Themen ({daten.themen.length})</div>
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
        <div className="abschnitt-titel">Suchanfragen ({daten.queries.length})</div>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          Claim-formulierte Suchen, mit denen dein Radar YouTube/TikTok/Instagram
          durchkämmt. Zum Löschen markieren, dann speichern.
        </p>
        {daten.queries.map((q) => (
          <label key={q.id} style={{ display: "block", padding: "1px 0" }}>
            <input
              type="checkbox"
              checked={loeschListe.includes(q.id)}
              onChange={(e) =>
                setLoeschListe(
                  e.target.checked
                    ? [...loeschListe, q.id]
                    : loeschListe.filter((id) => id !== q.id)
                )
              }
            />{" "}
            <span style={{ color: "var(--text-dim)" }}>[{q.plattform}]</span> {q.query}
          </label>
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <select value={neuePlattform} onChange={(e) => setNeuePlattform(e.target.value)}>
            <option value="youtube">YouTube</option>
            <option value="tiktok">TikTok</option>
            <option value="instagram">Instagram (Hashtag)</option>
          </select>
          <input
            placeholder="Neue Suchanfrage (wie die Falschbehauptung klingt)"
            value={neueQuery}
            onChange={(e) => setNeueQuery(e.target.value)}
            style={{ flex: 1, minWidth: 220 }}
          />
        </div>
      </div>

      <div className="karte" style={{ padding: 16, marginTop: 12 }}>
        <div className="abschnitt-titel">Was dich erfahrungsgemäß triggert</div>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          Eine Zeile pro Trigger. Achtung: Manuelles Speichern überschreibt die
          gelernten Stärken — die Liste lernt danach aus deinem Feedback weiter.
        </p>
        <textarea
          rows={8}
          style={{ width: "100%" }}
          value={triggerText ?? (profil?.reaktions_ausloeser || []).map((t) => t.trigger).join("\n")}
          onChange={(e) => setTriggerText(e.target.value)}
        />
      </div>

      <div className="karte" style={{ padding: 16, marginTop: 12 }}>
        <div className="abschnitt-titel">Beobachtungsliste</div>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          Folgen/Entfolgen verwaltest du im <a href="/personen">Personen-Tab</a>.
        </p>
        <p>
          {daten.personen.filter((p) => p.folgt).map((p) => p.name).join(", ") ||
            "Du folgst noch niemandem."}
        </p>
      </div>

      <button
        className="btn primaer"
        onClick={speichern}
        disabled={laeuft}
        style={{ marginTop: 14 }}
      >
        {laeuft ? "Speichert …" : "Änderungen speichern"}
      </button>

      <div className="karte" style={{ padding: 16, marginTop: 20 }}>
        <div className="abschnitt-titel">Konto</div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 6 }}>
          <form method="post" action="/api/logout">
            <button className="btn" type="submit">Abmelden</button>
          </form>
          <button className="btn" onClick={kontoLoeschen} disabled={laeuft}
                  style={{ color: "var(--rot, #e5484d)" }}>
            Konto & alle Daten löschen
          </button>
        </div>
        <p style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 8 }}>
          Die Löschung entfernt Profil, Themen, Suchen, Zuordnungen, Transkript-
          Auszüge deiner Videos und alle Einstellungen unwiderruflich.
        </p>
      </div>
    </>
  );
}
