// /admin — Betreiber-Dashboard: alle Nutzer im Blick, Plan/Usage-Limits
// setzen, Einladungs-Codes verwalten. Nur rolle=admin mit echter Anmeldung
// (der offene Zugangscode-Betrieb hat hier bewusst KEINEN Zugriff).
"use client";

import { useCallback, useEffect, useState } from "react";

interface NutzerZeile {
  id: string;
  email: string;
  anzeige_name: string | null;
  rolle: string;
  plan: string;
  limits: Record<string, unknown> | null;
  onboarding_status: string;
  erstellt_am: string;
  statistik: Record<string, number>;
  letzte_kuration: string | null;
  queries_aktiv: number;
}
interface Invite {
  code: string;
  notiz: string | null;
  max_nutzungen: number;
  nutzungen: number;
  erstellt_am: string;
}
interface InviteAnfrage {
  id: number;
  name: string | null;
  email: string;
  kanal: string | null;
  nachricht: string;
  status: string;
  invite_code: string | null;
  erstellt_am: string;
}

const LIMIT_FELDER: { key: string; label: string }[] = [
  { key: "kuration_max_neu", label: "Kuration max/Lauf" },
  { key: "queries_pro_lauf", label: "Queries/Lauf" },
  { key: "skripte_pro_woche", label: "Skripte/Woche" },
  { key: "import_videos", label: "Import-Videos" },
];

export default function AdminSeite() {
  const [nutzer, setNutzer] = useState<NutzerZeile[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [anfragen, setAnfragen] = useState<InviteAnfrage[]>([]);
  const [fehler, setFehler] = useState<string | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [entwurf, setEntwurf] = useState<Record<string, Record<string, string>>>({});
  const [planEntwurf, setPlanEntwurf] = useState<Record<string, string>>({});
  const [inviteNotiz, setInviteNotiz] = useState("");

  const lade = useCallback(async () => {
    try {
      const [nRes, iRes] = await Promise.all([
        fetch("/api/admin/nutzer"),
        fetch("/api/admin/invites"),
      ]);
      if (nRes.status === 403) {
        setFehler(
          "Nur für Admins: Bitte melde dich unter /login mit dem Admin-Konto an " +
            "(der offene Betrieb hat hier keinen Zugriff)."
        );
        return;
      }
      if (!nRes.ok) throw new Error(String(nRes.status));
      const nDaten = await nRes.json();
      setNutzer(nDaten.nutzer || []);
      if (iRes.ok) {
        const iDaten = await iRes.json();
        setInvites(iDaten.invites || []);
        setAnfragen(iDaten.anfragen || []);
      }
    } catch {
      setFehler("Admin-Daten nicht ladbar.");
    }
  }, []);

  useEffect(() => {
    lade();
  }, [lade]);

  async function speichereNutzer(n: NutzerZeile) {
    setMeldung(null);
    setFehler(null);
    const limitEntwurf = entwurf[n.id] || {};
    const limits: Record<string, unknown> = { ...(n.limits || {}) };
    for (const f of LIMIT_FELDER) {
      if (f.key in limitEntwurf) {
        const wert = limitEntwurf[f.key].trim();
        if (wert === "") delete limits[f.key];
        else limits[f.key] = Number(wert);
      }
    }
    const res = await fetch("/api/admin/nutzer", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: n.id,
        plan: planEntwurf[n.id] || n.plan,
        limits,
      }),
    });
    const d = await res.json();
    if (!res.ok) setFehler(d.fehler || "Speichern fehlgeschlagen.");
    else {
      setMeldung("Gespeichert — greift ab dem nächsten Lauf.");
      await lade();
    }
  }

  async function neuerInvite() {
    const res = await fetch("/api/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notiz: inviteNotiz }),
    });
    const d = await res.json();
    if (!res.ok) setFehler(d.fehler || "Code-Erzeugung fehlgeschlagen.");
    else {
      setMeldung("Neuer Einladungs-Code: " + d.code);
      setInviteNotiz("");
      await lade();
    }
  }

  async function anfrageAktion(anfrageId: number, ablehnen: boolean) {
    setMeldung(null);
    const res = await fetch("/api/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ anfrage_id: anfrageId, ablehnen }),
    });
    const d = await res.json();
    if (!res.ok) setFehler(d.fehler || "Aktion fehlgeschlagen.");
    else if (d.code) {
      setMeldung(
        "Code für " + d.email + ": " + d.code +
          " — Mail-Entwurf öffnet sich (Code wird NICHT automatisch verschickt)."
      );
      const betreff = encodeURIComponent("Dein Einladungs-Code für Dein Radar 📡");
      const text = encodeURIComponent(
        "Hi!\n\nHier ist dein Einladungs-Code für Dein Radar: " + d.code +
          "\n\nRegistrieren: https://radar.suessstoffmafia.de/signup\n\nViel Spaß!"
      );
      window.open("mailto:" + d.email + "?subject=" + betreff + "&body=" + text);
    }
    await lade();
  }

  async function loescheInvite(code: string) {
    await fetch("/api/admin/invites", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    await lade();
  }

  if (fehler && !nutzer) {
    return (
      <main className="container" style={{ paddingTop: 32 }}>
        <div className="hinweis-fehler">{fehler}</div>
        <p><a href="/login">Zum Login</a></p>
      </main>
    );
  }
  if (!nutzer) return <main className="container" style={{ paddingTop: 32 }}><p>Lade …</p></main>;

  return (
    <main className="container" style={{ paddingTop: 24, maxWidth: 1000 }}>
      <h1>🛠 Admin — Nutzer &amp; Einladungen</h1>
      {fehler && <div className="hinweis-fehler">{fehler}</div>}
      {meldung && <div className="banner">{meldung}</div>}

      {nutzer.map((n) => (
        <div key={n.id} className="karte" style={{ padding: 16, marginTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <div>
              <b>{n.anzeige_name || n.email}</b>{" "}
              <span style={{ color: "var(--text-dim)" }}>
                {n.email} · {n.rolle} · Onboarding: {n.onboarding_status} · seit{" "}
                {n.erstellt_am?.slice(0, 10)}
              </span>
            </div>
            <div style={{ color: "var(--text-dim)", fontSize: 13 }}>
              Inbox {n.statistik.inbox || 0} · Strittig {n.statistik.strittig || 0} ·
              Angenommen {n.statistik.angenommen || 0} · Archiv {n.statistik.archiv || 0} ·{" "}
              {n.queries_aktiv} Queries · letzte Kuration:{" "}
              {n.letzte_kuration ? n.letzte_kuration.slice(0, 16).replace("T", " ") : "nie"}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10, alignItems: "end" }}>
            <label>
              Plan{" "}
              <select
                value={planEntwurf[n.id] || n.plan}
                onChange={(e) => setPlanEntwurf({ ...planEntwurf, [n.id]: e.target.value })}
              >
                <option value="free">free</option>
                <option value="pro">pro</option>
              </select>
            </label>
            {LIMIT_FELDER.map((f) => (
              <label key={f.key} style={{ fontSize: 13 }}>
                {f.label}
                <br />
                <input
                  style={{ width: 110 }}
                  placeholder="Plan-Default"
                  value={
                    entwurf[n.id]?.[f.key] ??
                    (n.limits?.[f.key] !== undefined ? String(n.limits[f.key]) : "")
                  }
                  onChange={(e) =>
                    setEntwurf({
                      ...entwurf,
                      [n.id]: { ...(entwurf[n.id] || {}), [f.key]: e.target.value },
                    })
                  }
                />
              </label>
            ))}
            <button className="btn primaer" onClick={() => speichereNutzer(n)}>
              Speichern
            </button>
          </div>
        </div>
      ))}

      {anfragen.filter((a) => a.status === "offen").length > 0 && (
        <div className="karte" style={{ padding: 16, marginTop: 20 }}>
          <div className="abschnitt-titel">
            📨 Invite-Anfragen ({anfragen.filter((a) => a.status === "offen").length} offen)
          </div>
          {anfragen
            .filter((a) => a.status === "offen")
            .map((a) => (
              <div key={a.id} style={{ borderTop: "1px solid var(--linie)", padding: "10px 0" }}>
                <div>
                  <b>{a.name || a.email}</b>{" "}
                  <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
                    {a.email}
                    {a.kanal ? " · " + a.kanal : ""} · {a.erstellt_am?.slice(0, 16).replace("T", " ")}
                  </span>
                </div>
                <p style={{ margin: "6px 0", fontSize: 14 }}>{a.nachricht}</p>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn primaer" onClick={() => anfrageAktion(a.id, false)}>
                    ✓ Einladen (Code erzeugen)
                  </button>
                  <button className="btn" onClick={() => anfrageAktion(a.id, true)}>
                    ✕ Ablehnen
                  </button>
                </div>
              </div>
            ))}
        </div>
      )}

      <div className="karte" style={{ padding: 16, marginTop: 20 }}>
        <div className="abschnitt-titel">Einladungs-Codes</div>
        {invites.length === 0 && <p style={{ color: "var(--text-dim)" }}>Noch keine Codes.</p>}
        {invites.map((i) => (
          <div key={i.code} style={{ display: "flex", gap: 10, alignItems: "center", padding: "3px 0" }}>
            <code>{i.code}</code>
            <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
              {i.nutzungen}/{i.max_nutzungen} benutzt{i.notiz ? " · " + i.notiz : ""}
            </span>
            <button className="btn" onClick={() => loescheInvite(i.code)} style={{ marginLeft: "auto" }}>
              ✕
            </button>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <input
            placeholder="Notiz (für wen?)"
            value={inviteNotiz}
            onChange={(e) => setInviteNotiz(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="btn primaer" onClick={neuerInvite}>
            Neuen Code erzeugen
          </button>
        </div>
        <p style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 8 }}>
          Signup-Link: https://radar.suessstoffmafia.de/signup — Code gilt für die
          angegebene Anzahl Registrierungen.
        </p>
      </div>
    </main>
  );
}
