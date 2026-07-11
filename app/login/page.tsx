// /login — Zugangscode-Formular (Alt-Betrieb) bzw. E-Mail-Login (Multi-Tenant).
// Die Middleware lässt diese Seite frei durch.

export const dynamic = "force-dynamic";

function supabaseLoginAktiv(): boolean {
  const modus = (process.env.AUTH_MODUS || "").trim().toLowerCase();
  return (
    modus !== "code" &&
    Boolean(
      (process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL) &&
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
    )
  );
}

export default async function LoginSeite(props: {
  searchParams: Promise<{ fehler?: string }>;
}) {
  const sp = await props.searchParams;
  const mitSupabase = supabaseLoginAktiv();
  return (
    <div className="login-seite">
      <form className="login-box" method="post" action="/api/login">
        <div style={{ fontSize: 44 }}>📡</div>
        <h1>
          Dein <span style={{ color: "var(--akzent)" }}>Radar</span>
        </h1>
        <p>
          Falschinfos aus deiner Nische im Blick.{" "}
          {mitSupabase ? "Melde dich an, um fortzufahren." : "Gib den Zugangscode ein."}
        </p>
        {sp.fehler && (
          <div className="hinweis-fehler">
            Anmeldung fehlgeschlagen — bitte nochmal versuchen.
          </div>
        )}
        {mitSupabase ? (
          <>
            <input
              name="email"
              type="email"
              placeholder="E-Mail"
              autoFocus
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
          </>
        ) : (
          <input
            name="code"
            type="password"
            placeholder="Zugangscode"
            autoFocus
            required
            autoComplete="current-password"
          />
        )}
        <button type="submit" className="btn primaer" style={{ justifyContent: "center" }}>
          Rein ins Radar
        </button>
        {mitSupabase && (
          <p style={{ marginTop: 10 }}>
            Noch kein Konto? <a href="/signup">Jetzt registrieren</a>
            <br />
            <a href="/start" style={{ fontSize: 13 }}>Was ist Dein Radar? →</a>
          </p>
        )}
      </form>
    </div>
  );
}
