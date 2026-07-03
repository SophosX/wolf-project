"use client";

// Karten-Liste mit optimistic UI: Aktion → Karte sofort raus,
// POST /api/feedback im Hintergrund, bei Fehler Karte zurück + roter Hinweis.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import VideoKarte, { Seite, VideoAnzeige } from "./VideoKarte";

interface Props {
  videos: VideoAnzeige[];
  seite: Seite;
  leerText: string;
}

export default function VideoListe({ videos: initial, seite, leerText }: Props) {
  const [videos, setVideos] = useState(initial);
  const [fehler, setFehler] = useState<string | null>(null);
  const router = useRouter();

  // Server-Refresh (router.refresh) liefert neue Props → State synchronisieren
  useEffect(() => setVideos(initial), [initial]);

  async function aktion(
    video: VideoAnzeige,
    a: string,
    kommentar?: string
  ): Promise<boolean> {
    const entfernt = a !== "kommentar";
    if (entfernt) {
      // Optimistic: sofort aus der Liste nehmen
      setVideos((vs) => vs.filter((v) => v.id !== video.id));
    }
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: video.id, aktion: a, kommentar }),
      });
      if (!res.ok) {
        const daten = await res.json().catch(() => ({}));
        throw new Error(daten.fehler || "HTTP " + res.status);
      }
      setFehler(null);
      router.refresh(); // Zähler in der Kopfleiste aktualisieren
      return true;
    } catch (e) {
      if (entfernt) {
        // Rollback: Karte wieder einsortieren (score desc)
        setVideos((vs) =>
          [...vs, video].sort((a2, b2) => (b2.score || 0) - (a2.score || 0))
        );
      }
      setFehler(
        "Aktion fehlgeschlagen: " +
          (e instanceof Error ? e.message : "Unbekannter Fehler")
      );
      return false;
    }
  }

  return (
    <>
      {fehler && <div className="hinweis-fehler">⚠ {fehler}</div>}
      {videos.length === 0 ? (
        <div className="leer">
          <div className="gross">🐺</div>
          {leerText}
        </div>
      ) : (
        <div className="karten">
          {videos.map((v) => (
            <VideoKarte
              key={v.id}
              video={v}
              seite={seite}
              onAktion={(a, k) => aktion(v, a, k)}
            />
          ))}
        </div>
      )}
    </>
  );
}
