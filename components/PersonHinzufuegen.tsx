// Person zur Beobachtungsliste hinzufügen (Name + mind. ein Handle) —
// nutzt den bestehenden user-scoped POST /api/personen (setzeFolgen).
"use client";

import { useState } from "react";

export default function PersonHinzufuegen() {
  const [name, setName] = useState("");
  const [youtube, setYoutube] = useState("");
  const [tiktok, setTiktok] = useState("");
  const [instagram, setInstagram] = useState("");
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  async function absenden(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    setMeldung(null);
    if (!youtube.trim() && !tiktok.trim() && !instagram.trim()) {
      setFehler("Bitte mindestens einen Kanal-Handle angeben.");
      return;
    }
    setLaeuft(true);
    try {
      const res = await fetch("/api/personen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          folgen: true,
          handles: {
            youtube: youtube.trim() || null,
            tiktok: tiktok.trim() || null,
            instagram: instagram.trim() || null,
          },
        }),
      });
      const d = await res.json();
      if (!res.ok) setFehler(d.fehler || "Hinzufügen fehlgeschlagen.");
      else {
        setMeldung("„" + name + "“ wird ab dem nächsten Lauf beobachtet.");
        setName("");
        setYoutube("");
        setTiktok("");
        setInstagram("");
        // Server-Komponenten (Liste) aktualisieren
        window.location.reload();
      }
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <form onSubmit={absenden} className="karte" style={{ padding: 14, marginTop: 12 }}>
      <div className="abschnitt-titel">Person hinzufügen</div>
      <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
        Neue Uploads dieser Person werden bei jedem Lauf geprüft.
      </p>
      {fehler && <div className="hinweis-fehler">{fehler}</div>}
      {meldung && <div className="banner">{meldung}</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <input
          placeholder="Name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ minWidth: 160, flex: 1 }}
        />
        <input
          placeholder="YouTube-Handle/Kanal-ID"
          value={youtube}
          onChange={(e) => setYoutube(e.target.value)}
          style={{ minWidth: 160, flex: 1 }}
        />
        <input
          placeholder="TikTok-Handle"
          value={tiktok}
          onChange={(e) => setTiktok(e.target.value)}
          style={{ minWidth: 140, flex: 1 }}
        />
        <input
          placeholder="Instagram-Handle"
          value={instagram}
          onChange={(e) => setInstagram(e.target.value)}
          style={{ minWidth: 140, flex: 1 }}
        />
        <button className="btn primaer" type="submit" disabled={laeuft}>
          {laeuft ? "Speichert …" : "＋ Beobachten"}
        </button>
      </div>
    </form>
  );
}
