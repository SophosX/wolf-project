// Score-Ring: 0-100 als Kreisanzeige

export default function ScoreRing({ score }: { score: number }) {
  const r = 24;
  const umfang = 2 * Math.PI * r;
  const anteil = Math.max(0, Math.min(100, score)) / 100;
  const farbe =
    score >= 75 ? "var(--akzent)" : score >= 50 ? "#ffd35c" : "#7d838a";
  return (
    <div className="score-ring" title={"Score " + score + "/100"}>
      <svg width="54" height="54" viewBox="0 0 54 54">
        <circle cx="27" cy="27" r={r} fill="none" stroke="var(--linie)" strokeWidth="5" />
        <circle
          cx="27"
          cy="27"
          r={r}
          fill="none"
          stroke={farbe}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={umfang * anteil + " " + umfang}
        />
      </svg>
      <div className="zahl" style={{ color: farbe }}>
        {score}
      </div>
    </div>
  );
}
