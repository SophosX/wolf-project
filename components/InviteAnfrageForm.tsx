// Invite-Anfrage-Formular auf der Landing (/start): "Wer bist du, was willst du?"
"use client";

import { useState } from "react";

export default function InviteAnfrageForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [kanal, setKanal] = useState("");
  const [nachricht, setNachricht] = useState("");
  const [website, setWebsite] = useState(""); // Honeypot
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [fertig, setFertig] = useState(false);

  async function absenden(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    setLaeuft(true);
    try {
      const res = await fetch("/api/invite-anfrage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, kanal, nachricht, website }),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Senden fehlgeschlagen — bitte nochmal versuchen.");
      else {
        setMeldung(d.hinweis || "Danke! Wir melden uns per E-Mail.");
        setFertig(true);
      }
    } catch {
      setFehler("Netzwerkfehler — bitte nochmal versuchen.");
    } finally {
      setLaeuft(false);
    }
  }

  if (fertig) {
    return (
      <div className="karte landing-login" id="invite">
        <h2>✅ Anfrage angekommen</h2>
        <p className="landing-dim">{meldung}</p>
      </div>
    );
  }

  return (
    <div className="karte landing-login" id="invite">
      <h2>Invite anfordern</h2>
      <p className="landing-dim" style={{ marginBottom: 12 }}>
        Erzähl uns kurz, wer du bist und was du mit deinem Radar vorhast — du
        bekommst deinen Einladungs-Code per E-Mail.
      </p>
      {fehler && <div className="hinweis-fehler">{fehler}</div>}
      <form onSubmit={absenden} className="landing-login-form">
        <input
          placeholder="Dein Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
        />
        <input
          type="email"
          placeholder="E-Mail"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
        />
        <input
          placeholder="Dein Kanal (YouTube/TikTok/Instagram, optional)"
          value={kanal}
          onChange={(e) => setKanal(e.target.value)}
        />
        <textarea
          rows={4}
          required
          minLength={20}
          placeholder="Wer bist du und was willst du mit deinem Radar? (Nische, worauf du reagieren willst …)"
          value={nachricht}
          onChange={(e) => setNachricht(e.target.value)}
        />
        {/* Honeypot — für Menschen unsichtbar */}
        <input
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          style={{ position: "absolute", left: "-9999px", height: 0, opacity: 0 }}
          aria-hidden="true"
          placeholder="Website"
        />
        <button type="submit" className="btn primaer" disabled={laeuft}
                style={{ justifyContent: "center" }}>
          {laeuft ? "Sendet …" : "Anfrage senden"}
        </button>
      </form>
    </div>
  );
}
