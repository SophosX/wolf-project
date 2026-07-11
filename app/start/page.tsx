// /start — öffentliche Landing für nicht eingeloggte Besucher.
// Erklärt die Plattform, bietet Login + Signup. Keine Nutzerdaten, kein Auth.

export const dynamic = "force-static";

const SCHRITTE = [
  {
    nr: "1",
    titel: "Verbinden & Interessen wählen",
    text:
      "Du wählst deine Themen-Bereiche und verbindest deinen Kanal. Dein Radar " +
      "liest deine Videos und lernt daraus: deine Positionen, deinen Ton — und " +
      "was dich erfahrungsgemäß triggert.",
  },
  {
    nr: "2",
    titel: "Es sucht & prüft für dich",
    text:
      "Alle paar Stunden durchsucht es YouTube, TikTok und Instagram mit deinen " +
      "Suchanfragen. Jeder Kandidat wird per KI-Faktencheck gegen deine " +
      "Positionen geprüft — mit echter Websuche und Quellen.",
  },
  {
    nr: "3",
    titel: "Du entscheidest nur noch",
    text:
      "In deiner Inbox landen nur echte Treffer — mit Begründung, Belegen und " +
      "auf Wunsch Reaktions-Skripten in deinem Ton. Jedes Annehmen oder Ablehnen " +
      "macht dein Radar treffsicherer.",
  },
];

const FEATURES = [
  {
    emoji: "🎯",
    titel: "Lebende Trigger-Liste",
    text: "Aus deinen Videos aufgebaut, aus deinem Feedback täglich fortgeschrieben — dein Radar weiß, worauf du reagierst.",
  },
  {
    emoji: "🔎",
    titel: "Belegte Urteile",
    text: "Kein Bauchgefühl: jede Falschbehauptung kommt mit Websuche-Verifikation und Quellen — konservativ im Zweifel.",
  },
  {
    emoji: "✍️",
    titel: "Skripte, die nach dir klingen",
    text: "Ein Sprach-Gedächtnis aus deinen eigenen Videos sorgt dafür, dass Reaktions-Skripte deinen Ton treffen.",
  },
  {
    emoji: "📡",
    titel: "Läuft von allein",
    text: "Suche, Faktencheck, Sortierung — automatisch alle paar Stunden. Du triffst nur noch die Entscheidungen.",
  },
];

export default function StartSeite() {
  return (
    <div className="landing">
      {/* Mini-Header */}
      <header className="landing-kopf">
        <div className="landing-kopf-innen">
          <div className="logo">
            📡 Dein <span className="gelb">Radar</span>
          </div>
          <a href="#login" className="btn landing-btn-sekundaer">
            Anmelden
          </a>
        </div>
      </header>

      <main className="landing-main">
        {/* Hero */}
        <section className="landing-hero">
          <h1>
            Dein persönliches{" "}
            <span className="gelb">Falschinfo-Radar</span>.
          </h1>
          <p className="landing-sub">
            Es durchsucht YouTube, TikTok und Instagram nach den Falschbehauptungen{" "}
            <b>deiner Nische</b>, prüft sie mit echten Quellen — und legt dir
            reaktionsfertige Funde in die Inbox. Gebaut auf dich: deine Themen,
            deine Positionen, dein Ton.
          </p>
          <div className="landing-cta-zeile">
            <a href="/signup" className="btn primaer landing-cta">
              Radar starten →
            </a>
            <a href="#login" className="btn landing-btn-sekundaer">
              Ich habe schon ein Konto
            </a>
          </div>
          <p className="landing-invite-hinweis">
            Aktuell invite-only — du brauchst einen Einladungs-Code.
          </p>
        </section>

        {/* So funktioniert's */}
        <section className="landing-sektion">
          <h2>So funktioniert&rsquo;s</h2>
          <div className="landing-schritte">
            {SCHRITTE.map((s) => (
              <div key={s.nr} className="karte landing-schritt">
                <div className="landing-schritt-nr">{s.nr}</div>
                <h3>{s.titel}</h3>
                <p>{s.text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Das bekommst du: Mock-Fund-Karte */}
        <section className="landing-sektion landing-produkt">
          <div className="landing-produkt-text">
            <h2>Das landet in deiner Inbox</h2>
            <p>
              Kein Feed zum Durchwühlen — jede Karte ist eine fertige
              Entscheidungsvorlage: die konkrete Falschaussage, warum sie falsch
              ist, die Belege dazu und wie relevant sie für dich ist.
            </p>
            <p className="landing-dim">
              Annehmen, ablehnen oder für später speichern — mehr musst du nicht
              tun. Den Rest lernt dein Radar.
            </p>
          </div>
          <div className="karte landing-mock" aria-hidden="true">
            <div className="landing-mock-kopf">
              <span className="landing-mock-badge">⚠ klar falsch · 92 %</span>
              <span className="landing-mock-score">87</span>
            </div>
            <div className="landing-mock-titel">
              „Mit diesem Trick verbrennst du Fett im Schlaf — ganz ohne Defizit“
            </div>
            <div className="landing-mock-meta">TikTok · 480.000 Views · vor 2 Tagen</div>
            <div className="landing-mock-grund">
              Fettabbau ohne Kaloriendefizit widerspricht der gesamten Studienlage —
              der behauptete Mechanismus existiert nicht.
            </div>
            <div className="landing-mock-quellen">
              <span>📄 Metaanalyse 2024</span>
              <span>📄 Fachgesellschaft</span>
            </div>
            <div className="landing-mock-aktionen">
              <span className="btn primaer">✓ Annehmen</span>
              <span className="btn">✕ Ablehnen</span>
              <span className="btn">🕐 Später</span>
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="landing-sektion">
          <h2>Warum es funktioniert</h2>
          <div className="landing-features">
            {FEATURES.map((f) => (
              <div key={f.titel} className="karte landing-feature">
                <div className="landing-feature-emoji">{f.emoji}</div>
                <h3>{f.titel}</h3>
                <p>{f.text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Login */}
        <section className="landing-sektion" id="login">
          <div className="karte landing-login">
            <h2>Anmelden</h2>
            <form method="post" action="/api/login" className="landing-login-form">
              <input
                name="email"
                type="email"
                placeholder="E-Mail"
                required
                autoComplete="email"
              />
              <input
                name="passwort"
                type="password"
                placeholder="Passwort"
                required
                autoComplete="current-password"
              />
              <button type="submit" className="btn primaer" style={{ justifyContent: "center" }}>
                Rein ins Radar
              </button>
            </form>
            <p className="landing-dim" style={{ marginTop: 10 }}>
              Noch kein Konto? <a href="/signup">Radar starten →</a>
            </p>
          </div>
        </section>
      </main>

      <footer className="landing-fuss">
        <span>📡 Dein Radar</span>
        <span>
          Kontakt: <a href="mailto:business@sustinerin.de">business@sustinerin.de</a>
        </span>
      </footer>
    </div>
  );
}
