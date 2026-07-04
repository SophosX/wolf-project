# -*- coding: utf-8 -*-
"""
Wolf Radar — Narrativ-Retrieval (RAG über Chris' eigene Videos)

Liest den von narrativ_index_bauen.py erzeugten Embedding-Index und liefert
zu einer Aussage die passendsten O-Ton-Passagen aus Chris' Videos. Damit
urteilt Stufe C nicht nur gegen die destillierte Positions-Tabelle, sondern
gegen seine ECHTEN Formulierungen — und Skripte klingen nach ihm, weil sein
eigenes Wording zum Thema im Prompt liegt.

Fail-safe by design: Ist der Index nicht da oder schlägt das Query-Embedding
fehl, liefert alles [] — die Pipeline läuft dann unverändert weiter.
"""

import json
import logging
import math
import os
import urllib.request

from analyse import lade_gemini_key

logger = logging.getLogger("wolf_radar.narrativ")

INDEX_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "wissen", "narrativ_index.json")
EMBED_MODELL = "gemini-embedding-001"
EMBED_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
             + EMBED_MODELL + ":embedContent")
MIN_AEHNLICHKEIT = 0.55   # darunter ist die Passage nur noch thematisch verwandt
MAX_PASSAGE_ZEICHEN = 550

_INDEX_CACHE = None


def lade_index():
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        try:
            with open(INDEX_PFAD, encoding="utf-8") as f:
                _INDEX_CACHE = json.load(f)
            logger.info("Narrativ-Index geladen: %d Chunks (dim=%d).",
                        len(_INDEX_CACHE.get("chunks", [])), _INDEX_CACHE.get("dim", 0))
        except (OSError, ValueError) as fehler:
            logger.warning("Narrativ-Index nicht ladbar (%s) — Retrieval aus.", fehler)
            _INDEX_CACHE = {}
    return _INDEX_CACHE


def verfuegbar():
    return bool(lade_index().get("chunks"))


def _embed_query(text):
    koerper = json.dumps({
        "model": "models/" + EMBED_MODELL,
        "content": {"parts": [{"text": text[:1500]}]},
        "taskType": "RETRIEVAL_QUERY",
        "outputDimensionality": lade_index().get("dim", 512),
    }).encode("utf-8")
    anfrage = urllib.request.Request(
        EMBED_URL, data=koerper, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": lade_gemini_key()})
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:
        daten = json.loads(antwort.read().decode("utf-8"))
    return (daten.get("embedding") or {}).get("values") or []


def _cosinus(a, b):
    skalar = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return skalar / norm if norm else 0.0


def passende_zitate(text, k=2, nur_reaktionen_zuerst=True):
    """
    Top-k O-Ton-Passagen aus Chris' Videos zu einem Text.
    Rückgabe: [{"text", "quelle", "reaktion", "score"}] — [] bei Fehlern.
    Reaktions-Videos (seine Richtigstellungen) bekommen einen leichten Bonus:
    dort steht, WIE er widerlegt.
    """
    index = lade_index()
    chunks = index.get("chunks") or []
    if not chunks or not text:
        return []
    try:
        anfrage_vektor = _embed_query(text)
    except Exception as fehler:
        logger.warning("Narrativ-Query-Embedding fehlgeschlagen: %s — ohne O-Töne weiter.", fehler)
        return []
    if not anfrage_vektor:
        return []

    bewertet = []
    for c in chunks:
        score = _cosinus(anfrage_vektor, c.get("vektor") or [])
        if nur_reaktionen_zuerst and c.get("reaktion"):
            score += 0.03
        bewertet.append((score, c))
    bewertet.sort(key=lambda paar: -paar[0])

    ergebnis = []
    for score, c in bewertet[:k * 3]:
        if score < MIN_AEHNLICHKEIT or len(ergebnis) >= k:
            break
        ergebnis.append({
            "text": c["text"][:MAX_PASSAGE_ZEICHEN],
            "quelle": c.get("quelle", "?"),
            "reaktion": bool(c.get("reaktion")),
            "score": round(score, 3),
        })
    return ergebnis


def zitat_block(text, k=2):
    """Formatierter Prompt-Block oder '' — für Stufe C und Skripte."""
    zitate = passende_zitate(text, k=k)
    if not zitate:
        return ""
    zeilen = ["CHRIS' EIGENE AUSSAGEN ZUM THEMA (O-Ton aus seinen Videos):"]
    for z in zitate:
        marker = " [aus einem seiner Richtigstellungs-Videos]" if z["reaktion"] else ""
        zeilen.append("- »" + z["text"] + "« (Video: " + z["quelle"] + marker + ")")
    return "\n".join(zeilen)


if __name__ == "__main__":
    import sys
    frage = " ".join(sys.argv[1:]) or "Süßstoffe sind krebserregend"
    for z in passende_zitate(frage, k=3):
        print("%.3f %s%s\n   %s\n" % (z["score"], z["quelle"],
                                      " [REAKTION]" if z["reaktion"] else "", z["text"][:200]))
