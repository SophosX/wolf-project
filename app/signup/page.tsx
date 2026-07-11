// /signup — Registrierung (Supabase, invite-only solange RADAR_INVITE_CODES gesetzt).
"use client";

import { useState } from "react";

export default function SignupSeite() {
  const [email, setEmail] = useState("");
  const [passwort, setPasswort] = useState("");
  const [name, setName] = useState("");
  const [invite, setInvite] = useState("");
  const [fehler, setFehler] = useState<string | null>(null);
  const [hinweis, setHinweis] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  async function absenden(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    setLaeuft(true);
    try {
      const res = await fetch("/api/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, passwort, invite, anzeige_name: name }),
      });
      const daten = await res.json();
      if (!res.ok) {
        setFehler(daten.fehler || "Registrierung fehlgeschlagen.");
      } else if (daten.angemeldet) {
        window.location.href = "/onboarding";
      } else {
        setHinweis(daten.hinweis || "Bitte E-Mail bestätigen, dann anmelden.");
      }
    } catch {
      setFehler("Netzwerkfehler — bitte nochmal versuchen.");
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div className="login-seite">
      <form className="login-box" onSubmit={absenden}>
        <div style={{ fontSize: 44 }}>📡</div>
        <h1>
          Dein <span style={{ color: "var(--akzent)" }}>Radar</span>
        </h1>
        <p>
          Dein persönliches Falschinfo-Radar: Es lernt aus deinen Videos, was dich
          triggert — und findet die Inhalte, auf die du reagieren willst.
        </p>
        {fehler && <div className="hinweis-fehler">{fehler}</div>}
        {hinweis && <div className="banner">{hinweis}</div>}
        <input
          type="text"
          placeholder="Anzeigename (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
        />
        <input
          type="email"
          placeholder="E-Mail"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
        <input
          type="password"
          placeholder="Passwort (mind. 8 Zeichen)"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
          required
          minLength={8}
          autoComplete="new-password"
        />
        <input
          type="text"
          placeholder="Einladungs-Code"
          value={invite}
          onChange={(e) => setInvite(e.target.value)}
          autoComplete="off"
        />
        <button type="submit" className="btn primaer" disabled={laeuft}
                style={{ justifyContent: "center" }}>
          {laeuft ? "Wird angelegt …" : "Konto anlegen"}
        </button>
        <p style={{ marginTop: 10 }}>
          Schon ein Konto? <a href="/login">Anmelden</a>
        </p>
      </form>
    </div>
  );
}
