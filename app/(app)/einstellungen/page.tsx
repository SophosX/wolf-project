// /einstellungen — Dein Radar-Profil pflegen: Marke/Nische, Themen (an/aus),
// Suchqueries (hinzufügen/löschen), Trigger-Liste, Beobachtungsliste, Plan.
// Nutzt die Onboarding-API (GET/PUT) — gleiche Datenbasis, gleiche Rechte.
"use client";

import { useCallback, useEffect, useState } from "react";

interface Thema { slug: string; name: string; kerngewicht: number; aktiv: boolean }
interface Query {
  id: number; plattform: string; query: string; aktiv: boolean;
  letzte_treffer?: number; leer_folge?: number; zuletzt?: string | null;
}

/** "fand zuletzt 6 Videos" / "3× ohne Treffer" — damit der Nutzer sieht, welche
 *  Begriffe tragen und welche er schärfen oder ersetzen sollte. */
function Ertrag({ q }: { q: Query }) {
  if (!q.zuletzt) return <span className="query-ertrag">noch nicht gesucht</span>;
  if ((q.letzte_treffer || 0) > 0)
    return <span className="query-ertrag gut">{q.letzte_treffer} Treffer zuletzt</span>;
  const n = q.leer_folge || 0;
  // leer_folge 0 bei 0 Treffern = der letzte Lauf war gestoert (kein Urteil ueber den Begriff)
  if (n === 0) return <span className="query-ertrag">zuletzt keine Treffer</span>;
  return (
    <span className={"query-ertrag" + (n >= 3 ? " tot" : "")}>
      {n}× ohne Treffer{n >= 3 ? " — wird ersetzt" : " — sucht breiter"}
    </span>
  );
}
interface Person { id: number; name: string; plattform: string | null; handle: string | null; folgt: boolean }
interface Trigger { trigger: string; staerke?: number; quelle?: string }
interface InteressenChip { slug: string; label: string; emoji: string; gewaehlt: boolean }
interface Vorschlaege {
  themen: { slug: string; name: string; keywords: string[] }[];
  queries: { id: number; plattform: string; query: string }[];
}
interface Daten {
  status: string;
  plan?: string;
  rezepte_aktiv?: boolean;
  profil: { nische: string | null; marke: string | null; reaktions_ausloeser: Trigger[] } | null;
  themen: Thema[];
  queries: Query[];
  personen: Person[];
  interessen?: InteressenChip[];
  vorschlaege?: Vorschlaege;
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
  const [labelEntwurf, setLabelEntwurf] = useState<string[] | null>(null);
  const [rezepteEntwurf, setRezepteEntwurf] = useState<boolean | null>(null);

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

  async function vorschlagAktion(
    typ: "thema" | "query",
    ident: string | number,
    aktion: "uebernehmen" | "verwerfen"
  ) {
    await fetch("/api/onboarding", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vorschlag: { typ, aktion, ...(typ === "thema" ? { slug: ident } : { id: ident }) },
      }),
    });
    await lade();
  }

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
      if (rezepteEntwurf !== null) body.rezepte_aktiv = rezepteEntwurf;
      if (labelEntwurf !== null) body.labels_setzen = labelEntwurf;
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
        const s = d.starter as {
          themen_verworfen: number; queries_verworfen: number;
          limits: { themen: number; suchqueries: number };
        } | null;
        const cap = s && (s.themen_verworfen > 0 || s.queries_verworfen > 0)
          ? ` Plan-Limit erreicht (${s.limits.themen} Themen / ${s.limits.suchqueries} Suchanfragen): ` +
            `${s.themen_verworfen} Themen und ${s.queries_verworfen} Suchanfragen des neuen Bereichs ` +
            `wurden nicht übernommen — Themen/Suchanfragen tauschen oder Plan erweitern.`
          : "";
        setMeldung("Gespeichert — Änderungen greifen ab dem nächsten Lauf." + cap);
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

      {daten.interessen && daten.interessen.length > 0 && (
        <div className="karte" id="interessen" style={{ padding: 16, marginTop: 12 }}>
          <div className="abschnitt-titel">Deine Interessen-Bereiche</div>
          <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
            Neu angewählte Bereiche bringen sofort Start-Themen und Suchanfragen
            mit; abgewählte deaktivieren ihre Themen (nichts geht verloren).
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
            {daten.interessen.map((b) => {
              const gewaehlt = labelEntwurf
                ? labelEntwurf.includes(b.slug)
                : b.gewaehlt;
              return (
                <button
                  key={b.slug}
                  type="button"
                  className="btn"
                  onClick={() => {
                    const basis =
                      labelEntwurf ??
                      (daten.interessen || []).filter((x) => x.gewaehlt).map((x) => x.slug);
                    setLabelEntwurf(
                      gewaehlt ? basis.filter((l) => l !== b.slug) : [...basis, b.slug]
                    );
                  }}
                  style={{
                    borderRadius: 20,
                    padding: "6px 12px",
                    background: gewaehlt ? "var(--akzent)" : undefined,
                    color: gewaehlt ? "#000" : undefined,
                  }}
                >
                  {b.emoji} {b.label} {gewaehlt ? "✓" : ""}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {daten.vorschlaege &&
        (daten.vorschlaege.themen.length > 0 || daten.vorschlaege.queries.length > 0) && (
        <div className="karte" style={{ padding: 16, marginTop: 12 }}>
          <div className="abschnitt-titel">💡 Vorschläge deines Radars</div>
          <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
            Aus deinem Feedback gelernt — erst nach deiner Bestätigung fließen sie
            in die Suche ein (kostet sonst nichts).
          </p>
          {daten.vorschlaege.themen.map((t) => (
            <div key={t.slug} style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 0" }}>
              <span>
                Neues Thema: <b>{t.name}</b>{" "}
                <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
                  ({t.keywords.slice(0, 4).join(", ")})
                </span>
              </span>
              <button className="btn" style={{ marginLeft: "auto" }}
                      onClick={() => vorschlagAktion("thema", t.slug, "uebernehmen")}>✓ Übernehmen</button>
              <button className="btn" onClick={() => vorschlagAktion("thema", t.slug, "verwerfen")}>✕</button>
            </div>
          ))}
          {daten.vorschlaege.queries.map((q) => (
            <div key={q.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 0" }}>
              <span>
                Neue Suche: <span style={{ color: "var(--text-dim)" }}>[{q.plattform}]</span> „{q.query}“
              </span>
              <button className="btn" style={{ marginLeft: "auto" }}
                      onClick={() => vorschlagAktion("query", q.id, "uebernehmen")}>✓ Übernehmen</button>
              <button className="btn" onClick={() => vorschlagAktion("query", q.id, "verwerfen")}>✕</button>
            </div>
          ))}
        </div>
      )}

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

      <div className="karte" id="suchanfragen" style={{ padding: 16, marginTop: 12 }}>
        <div className="abschnitt-titel">Suchanfragen ({daten.queries.length})</div>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          Claim-formulierte Suchen, mit denen dein Radar YouTube/TikTok/Instagram
          durchkämmt. Zum Löschen markieren, dann speichern. Begriffe ohne Treffer
          sucht der Radar automatisch breiter (größerer Zeitraum, mehr Ergebnisse)
          und ersetzt sie nach drei leeren Läufen durch eine breitere Variante.
        </p>
        {daten.queries.map((q) => (
          <div key={q.id} style={{ display: "flex", alignItems: "center", gap: 4, padding: "1px 0" }}>
            <label>
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
            <Ertrag q={q} />
          </div>
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

      {daten.plan === "pro" && (
        <div className="karte" style={{ padding: 16, marginTop: 12 }}>
          <div className="abschnitt-titel">Zusatz-Features</div>
          <label style={{ display: "block" }}>
            <input
              type="checkbox"
              checked={rezepteEntwurf ?? Boolean(daten.rezepte_aktiv)}
              onChange={(e) => setRezepteEntwurf(e.target.checked)}
            />{" "}
            Rezepte-Radar (findet community-erprobte Rezepte — vor allem für
            Ernährungs-Creator sinnvoll)
          </label>
        </div>
      )}

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
