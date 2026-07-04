# -*- coding: utf-8 -*-
"""
Wolf Radar — Narrativ-Index-Builder (RAG über Chris' eigene Videos)

Baut aus Chris' Transkripten einen Embedding-Index, damit Verdict und
Skript-Generierung mit seinen ECHTEN Aussagen arbeiten (O-Ton statt Paraphrase):
  Quellen: 01_quellen/transkripte_text/*.txt   (kuratierte Volltranskripte,
           "REAKTION - *" = seine Richtigstellungs-Videos, besonders wertvoll)
           01_quellen/transkripte_auto/txt/*.txt (Auto-Untertitel seines Kanals,
           Titel-Zuordnung über 01_quellen/youtube/videos_alle.json)

Ausgabe: scraper/wissen/narrativ_index.json
  {modell, dim, erstellt, chunks: [{text, quelle, reaktion, vektor}]}

Einmalig / bei neuem Material ausführen:
  python3 narrativ_index_bauen.py
"""

import glob
import json
import os
import re
import sys
import time
import urllib.request

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

from analyse import lade_gemini_key  # noqa: E402

PROJEKT_DIR = os.path.abspath(os.path.join(SCRAPER_DIR, "..", "..", ".."))
KURATIERT_DIR = os.path.join(PROJEKT_DIR, "01_quellen", "transkripte_text")
AUTO_DIR = os.path.join(PROJEKT_DIR, "01_quellen", "transkripte_auto", "txt")
VIDEOS_ALLE = os.path.join(PROJEKT_DIR, "01_quellen", "youtube", "videos_alle.json")
AUSGABE = os.path.join(SCRAPER_DIR, "wissen", "narrativ_index.json")

EMBED_MODELL = "gemini-embedding-001"
EMBED_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
             + EMBED_MODELL + ":batchEmbedContents")
DIMENSION = 512
CHUNK_ZEICHEN = 800
MIN_CHUNK_ZEICHEN = 250
BATCH = 40


def _titel_karte():
    """video_id -> Titel aus dem Kanal-Scrape."""
    try:
        with open(VIDEOS_ALLE, encoding="utf-8") as f:
            daten = json.load(f)
        videos = daten if isinstance(daten, list) else daten.get("videos", [])
        karte = {}
        for v in videos:
            vid = v.get("video_id") or v.get("id")
            if isinstance(vid, dict):
                vid = vid.get("videoId")
            titel = v.get("titel") or v.get("title")
            if vid and titel:
                karte[vid] = titel
        return karte
    except (OSError, ValueError):
        return {}


def _chunke(text, quelle, reaktion):
    """Satzweise zu ~CHUNK_ZEICHEN grossen Blöcken zusammensetzen."""
    text = re.sub(r"\s+", " ", text).strip()
    saetze = re.split(r"(?<=[.!?]) +", text)
    chunks, aktuell = [], ""
    for satz in saetze:
        if len(aktuell) + len(satz) + 1 > CHUNK_ZEICHEN and aktuell:
            chunks.append(aktuell.strip())
            # leichter Überlapp: letzter Satz wandert mit in den nächsten Chunk
            aktuell = (aktuell.strip().split(". ")[-1] + ". ") if ". " in aktuell else ""
        aktuell += satz + " "
    if aktuell.strip():
        chunks.append(aktuell.strip())
    return [{"text": c, "quelle": quelle, "reaktion": reaktion}
            for c in chunks if len(c) >= MIN_CHUNK_ZEICHEN]


def sammle_chunks():
    titel_von = _titel_karte()
    chunks = []
    for pfad in sorted(glob.glob(os.path.join(KURATIERT_DIR, "*.txt"))):
        name = os.path.splitext(os.path.basename(pfad))[0]
        with open(pfad, encoding="utf-8") as f:
            chunks += _chunke(f.read(), name, name.upper().startswith("REAKTION"))
    for pfad in sorted(glob.glob(os.path.join(AUTO_DIR, "*.txt"))):
        vid = os.path.splitext(os.path.basename(pfad))[0]
        titel = titel_von.get(vid, "YouTube-Video " + vid)
        with open(pfad, encoding="utf-8") as f:
            chunks += _chunke(f.read(), titel, False)
    return chunks


def embedde(chunks):
    """Batch-Embeddings via REST; RETRIEVAL_DOCUMENT, reduzierte Dimension."""
    key = lade_gemini_key()
    for start in range(0, len(chunks), BATCH):
        gruppe = chunks[start:start + BATCH]
        koerper = json.dumps({
            "requests": [{
                "model": "models/" + EMBED_MODELL,
                "content": {"parts": [{"text": c["text"]}]},
                "taskType": "RETRIEVAL_DOCUMENT",
                "outputDimensionality": DIMENSION,
            } for c in gruppe]
        }).encode("utf-8")
        anfrage = urllib.request.Request(
            EMBED_URL, data=koerper, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key})
        for versuch in range(1, 4):
            try:
                with urllib.request.urlopen(anfrage, timeout=120) as antwort:
                    daten = json.loads(antwort.read().decode("utf-8"))
                break
            except Exception as fehler:
                if versuch == 3:
                    raise
                print("  Batch %d: %s — Retry %d" % (start // BATCH, fehler, versuch))
                time.sleep(3 * versuch)
        embeddings = daten.get("embeddings", [])
        if len(embeddings) != len(gruppe):
            raise RuntimeError("Batch %d: %d Embeddings für %d Chunks"
                               % (start // BATCH, len(embeddings), len(gruppe)))
        for c, e in zip(gruppe, embeddings):
            c["vektor"] = [round(x, 5) for x in e.get("values", [])]
        print("  %d/%d Chunks embedded" % (min(start + BATCH, len(chunks)), len(chunks)))
        time.sleep(0.3)
    return chunks


def main():
    chunks = sammle_chunks()
    quellen = sorted(set(c["quelle"] for c in chunks))
    print("[narrativ] %d Chunks aus %d Quellen (%d Reaktions-Chunks)"
          % (len(chunks), len(quellen),
             sum(1 for c in chunks if c["reaktion"])))
    chunks = embedde(chunks)
    ausgabe = {
        "modell": EMBED_MODELL,
        "dim": DIMENSION,
        "erstellt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chunks": chunks,
    }
    os.makedirs(os.path.dirname(AUSGABE), exist_ok=True)
    tmp = AUSGABE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False)
    os.replace(tmp, AUSGABE)
    groesse = os.path.getsize(AUSGABE) / 1048576.0
    print("[narrativ] Index geschrieben: %s (%.1f MB)" % (AUSGABE, groesse))


if __name__ == "__main__":
    main()
