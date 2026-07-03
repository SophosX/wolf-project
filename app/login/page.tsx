// /login — Zugangscode-Formular (Middleware lässt diese Seite frei durch)

export const dynamic = "force-dynamic";

export default async function LoginSeite(props: {
  searchParams: Promise<{ fehler?: string }>;
}) {
  const sp = await props.searchParams;
  return (
    <div className="login-seite">
      <form className="login-box" method="post" action="/api/login">
        <div style={{ fontSize: 44 }}>🐺</div>
        <h1>
          Wolf <span style={{ color: "var(--akzent)" }}>Radar</span>
        </h1>
        <p>
          Ernährungs-Falschinfos im Blick. Gib den Zugangscode ein, um
          fortzufahren.
        </p>
        {sp.fehler && (
          <div className="hinweis-fehler">
            Falscher Zugangscode — bitte nochmal versuchen.
          </div>
        )}
        <input
          name="code"
          type="password"
          placeholder="Zugangscode"
          autoFocus
          required
          autoComplete="current-password"
        />
        <button type="submit" className="btn primaer" style={{ justifyContent: "center" }}>
          Rein ins Radar
        </button>
      </form>
    </div>
  );
}
