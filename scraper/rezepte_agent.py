# -*- coding: utf-8 -*-
"""
Wolf Radar — Rezepte-Agent (REZEPTE-RADAR)

Findet Community-erprobte Abnehm-Rezepte auf YouTube und bewertet sie auf
Chris-Fit (kalorienbewusst / "Genuss ohne Reue", High Protein, simpel,
Sattmacher- oder Suesshunger-tauglich, deutschsprachig).

Ablauf:
  a) YouTube-Suche (Data API v3, Key YT_API_KEY): 8 deutsche Rezept-Queries,
     letzte 90 Tage, je order=viewCount, maxResults=10 -> videos.list Statistiken.
  b) Gemini-Fit-Bewertung (analyse.gemini_json, Batch a 5): fit_score 0-100,
     kategorie, begruendung, zutaten_kurz (nur aus Titel/Beschreibung,
     NICHTS erfinden), chris_haken.
  c) Gesamtscore = 0.5*Community-Resonanz (log-Views+Velocity, Muster
     analyse._reichweite_score) + 0.5*fit_score. Nur fit_score >= 55 speichern.
  d) Persistenz: daten/rezepte.json — Merge per id, status/feedback nie
     ueberschreiben (Muster speicher.py). Lauf-Protokoll: agent_runs, quelle "rezepte".

CLI:
    python3 rezepte_agent.py [--limit N]
"""

import argparse
import logging
import math
import os
import sys
import time

# scraper/ importierbar machen, egal von wo gestartet wird
SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import analyse
import speicher
import status
import youtube_agent

REZEPTE_DATEI = os.path.join(speicher.DATEN_DIR, "rezepte.json")

# "Ankommen in der Community" — Suchqueries fuer erprobte Abnehm-Rezepte
REZEPT_QUERIES = [
    "high protein rezept",
    "kalorienarm rezept einfach",
    "abnehmen rezept schnell",
    "protein dessert rezept",
    "kalorien sparen rezept",
    "meal prep abnehmen",
    "proteinpizza rezept",
    "low calorie snack deutsch",
]

SUCHE_TAGE = 90                # publishedAfter-Fenster
MAX_RESULTS_PRO_QUERY = 10
MINDEST_VIEWS = 2000           # Community-erprobt heisst: hat schon Resonanz
FIT_SCHWELLE = 55              # nur fit_score >= 55 wird gespeichert
BATCH_GROESSE_FIT = 5          # Gemini-Bewertung gebuendelt (Kosten)
MAX_BESCHREIBUNG_ZEICHEN = 1200

KATEGORIEN = ["sattmacher", "suesshunger", "snack", "meal_prep", "sonstiges"]

# Merge-Semantik wie speicher.py: bestehende Eintraege -> nur Metriken,
# status / feedback / Fit-Analyse werden NIE ueberschrieben.
METRIK_FELDER = ("views", "likes", "kommentare")
NACHTRAG_FELDER = ("thumbnail_url", "dauer_s")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("wolf_radar.rezepte")


# ---------------------------------------------------------------------------
# a) YouTube-Suche (Muster: youtube_agent.claim_suche, Helfer wiederverwendet)
# ---------------------------------------------------------------------------

def _roh_rezept(video_id, snippet, statistik, content):
    """Rohes Rezept-Dict (Fit-Felder leer, 'beschreibung' nur fuer den Prompt)."""
    return {
        "id": "youtube:" + video_id,
        "url": "https://www.youtube.com/watch?v=" + video_id,
        "titel": snippet.get("title"),
        "kanal": snippet.get("channelTitle"),
        "views": int(statistik.get("viewCount", 0) or 0),
        "likes": int(statistik["likeCount"]) if statistik.get("likeCount") else None,
        "kommentare": int(statistik["commentCount"]) if statistik.get("commentCount") else None,
        "veroeffentlicht": snippet.get("publishedAt"),
        "thumbnail_url": youtube_agent._bestes_thumbnail(snippet.get("thumbnails")),
        "dauer_s": youtube_agent._dauer_zu_sekunden(content.get("duration")) if content else None,
        "fit_score": 0,
        "kategorie": "sonstiges",
        "begruendung": "",
        "zutaten_kurz": [],
        "chris_haken": "",
        "score": 0,
        "status": "vorschlag",
        "feedback": [],
        "gefunden_am": youtube_agent._jetzt_iso(),
        # nur fuer die Gemini-Bewertung, wird vor dem Speichern entfernt:
        "beschreibung": snippet.get("description") or "",
    }


def rezept_suche(fehler):
    """Rezept-Queries (Chris' Vorschlaege zuerst, dann die 8 Basis-Queries),
    letzte 90 Tage, order=viewCount -> rohe Rezept-Dicts."""
    published_after = youtube_agent._iso_vor_tagen(SUCHE_TAGE)
    gefundene_ids = []
    schon_gesehen = set()

    # Chris' aktive Rezept-Vorschlaege laufen VOR den Basis-Queries mit
    try:
        extra = speicher.lade_rezept_extra_queries()
    except Exception as e:
        extra = []
        fehler.append("rezepte extra-queries: %s" % e)
    if extra:
        status.schritt("Deine Rezept-Vorschlaege fliessen ein: %s"
                       % ", ".join("„%s“" % q for q in extra), typ="erfolg")
    queries = list(dict.fromkeys(extra + REZEPT_QUERIES))

    for query in queries:
        antwort = youtube_agent._api_get("search", {
            "part": "snippet",
            "q": query,
            "type": "video",
            "relevanceLanguage": "de",
            "regionCode": "DE",
            "publishedAfter": published_after,
            "order": "viewCount",
            "maxResults": MAX_RESULTS_PRO_QUERY,
        }, fehler)
        if not antwort:
            continue
        for item in antwort.get("items", []):
            vid = (item.get("id") or {}).get("videoId")
            if vid and vid not in schon_gesehen:
                schon_gesehen.add(vid)
                gefundene_ids.append(vid)

    print("[rezepte] Suche: %d Queries, %d eindeutige Video-IDs"
          % (len(queries), len(gefundene_ids)))
    status.schritt("Rezepte: %d Suchanfragen ausgefuehrt — %d Videos gefunden"
                   % (len(queries), len(gefundene_ids)))

    details = youtube_agent._videos_details(gefundene_ids, fehler)
    rezepte = []
    for vid in gefundene_ids:
        item = details.get(vid)
        if not item:
            continue
        rezepte.append(_roh_rezept(
            vid, item.get("snippet", {}), item.get("statistics", {}),
            item.get("contentDetails", {})))
    return rezepte


# ---------------------------------------------------------------------------
# c) Community-Resonanz: views + likes + kommentare + Velocity
#    (log-skaliert, Muster: analyse._reichweite_score)
# ---------------------------------------------------------------------------

def community_resonanz(rezept):
    """0-100: Engagement-gewichtete Views (log) plus Velocity-Bonus (Views/Tag)."""
    views = float(rezept.get("views") or 0)
    likes = float(rezept.get("likes") or 0)
    kommentare = float(rezept.get("kommentare") or 0)
    # Likes/Kommentare zaehlen als gewichtete Zusatz-Resonanz
    basis = views + 25.0 * likes + 150.0 * kommentare
    punkte = 15.0 * math.log10(basis) + 10.0 if basis >= 1 else 0.0
    tage = analyse._tage_seit(rezept.get("veroeffentlicht"))
    velocity = views / max(tage or 14.0, 1.0)
    bonus = min(15.0, 3.0 * math.log10(velocity + 1.0)) if velocity > 0 else 0.0
    return int(round(max(0.0, min(100.0, punkte + bonus))))


def gesamtscore(rezept):
    """Kontrakt-Formel des Rezepte-Radars: 0.5*Community-Resonanz + 0.5*fit_score."""
    return int(round(0.5 * community_resonanz(rezept) + 0.5 * float(rezept.get("fit_score") or 0)))


# ---------------------------------------------------------------------------
# b) Gemini-Fit-Bewertung (analyse.gemini_json, Batch a 5, ID-Echo)
# ---------------------------------------------------------------------------

_SCHEMA_FIT = {
    "type": "OBJECT",
    "properties": {
        "ergebnisse": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING", "description": "exakt die uebergebene Rezept-ID"},
                    "fit_score": {"type": "INTEGER", "description": "0-100: wie gut passt das Rezept zu Chris?"},
                    "kategorie": {"type": "STRING", "enum": KATEGORIEN},
                    "begruendung": {"type": "STRING", "description": "genau ein Satz"},
                    "zutaten_kurz": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "max 6 Hauptzutaten, NUR aus Titel/Beschreibung; leer bei Unklarheit",
                    },
                    "chris_haken": {"type": "STRING",
                                    "description": "was Chris kritisieren wuerde — ein Satz oder leerer String"},
                },
                "required": ["id", "fit_score", "kategorie", "begruendung",
                             "zutaten_kurz", "chris_haken"],
            },
        }
    },
    "required": ["ergebnisse"],
}

_SYSTEM_FIT = """Du bist der Rezept-Scout des 'Wolf Radar' fuer den deutschen Fitness-Creator
Christian Wolf ("Genuss ohne Reue"). Du bewertest YouTube-Rezept-Videos darauf, wie gut sie
zu seinem Content passen.

CHRIS' REZEPT-PROFIL (Massstab fuer den fit_score 0-100):
- kalorienbewusst: kalorienreduzierte Versionen von Genuss-Klassikern ("Genuss ohne Reue")
- High Protein: viel Eiweiss pro Portion ist ein starkes Plus
- simpel: wenige Zutaten, wenige Schritte, alltagstauglich (Meal Prep zaehlt als simpel)
- Sattmacher-tauglich (grosses Volumen, wenig Kalorien) ODER Suesshunger-tauglich
  (Dessert/Snack-Ersatz ohne Kalorienbombe)
- deutschsprachig: Titel/Beschreibung auf Deutsch

BEWERTUNGSREGELN:
1. fit_score: 0-100. 80+ nur, wenn mehrere Kern-Kriterien klar erfuellt sind.
   Unter 40, wenn das Video gar kein Rezept ist (Vlog, Werbung, Supplement-Review,
   reine Diaet-Tipps) oder nicht deutschsprachig ist.
2. kategorie: sattmacher (herzhafte, saettigende Hauptmahlzeit), suesshunger
   (Dessert/suesser Snack), snack (herzhafter Snack/Fingerfood), meal_prep
   (Vorkochen/Wochenplan), sonstiges (alles andere).
3. begruendung: GENAU EIN Satz auf Deutsch, warum das Rezept (nicht) zu Chris passt.
4. zutaten_kurz: maximal 6 Hauptzutaten — AUSSCHLIESSLICH solche, die woertlich in Titel
   oder Beschreibung stehen. NICHTS erfinden, nicht aus dem Gerichtsnamen raten.
   Wenn keine Zutaten erkennbar sind: leere Liste.
5. chris_haken: Was wuerde Chris an dem Rezept kritisieren? (z.B. "nutzt Honig als
   'gesunden' Zucker", "'zuckerfrei' obwohl Datteln drin sind", "Kalorienangabe wirkt
   unrealistisch niedrig"). GENAU EIN Satz — oder leerer String, wenn nichts auffaellt.
Gib fuer jede uebergebene ID GENAU EIN Ergebnis zurueck und uebernimm die ID unveraendert."""


def _rezept_kontext(rezept):
    """Kompakter, klar gelabelter Kontextblock fuer den Fit-Prompt."""
    dauer = rezept.get("dauer_s")
    teile = [
        "ID: " + str(rezept.get("id", "?")),
        "Titel: " + (analyse._kuerze(rezept.get("titel"), 300) or "?"),
        "Kanal: " + str(rezept.get("kanal", "?")),
        "Views: " + str(rezept.get("views", "?")),
        "Likes: " + str(rezept.get("likes") if rezept.get("likes") is not None else "?"),
        "Dauer: " + (str(int(dauer)) + "s" if dauer else "?"),
        "Beschreibung: " + (analyse._kuerze(rezept.get("beschreibung"),
                                            MAX_BESCHREIBUNG_ZEICHEN) or "(keine)"),
    ]
    return "\n".join(teile)


def _fit_batch(rezepte):
    """Fit-Bewertung fuer eine Gruppe in einem Gemini-Aufruf (Muster _stufe_ab_batch)."""
    bloecke = ["=== REZEPT-KANDIDAT ===\n" + _rezept_kontext(r) for r in rezepte]
    daten = analyse.gemini_json("\n\n".join(bloecke), system=_SYSTEM_FIT,
                                schema=_SCHEMA_FIT, temperatur=0.1)
    ergebnisse = {e.get("id"): e for e in daten.get("ergebnisse", [])}
    fehlend = [r.get("id") for r in rezepte if r.get("id") not in ergebnisse]
    if fehlend:
        raise RuntimeError("Fit-Bewertung: keine Antwort fuer IDs " + ", ".join(map(str, fehlend)))
    return ergebnisse


def bewerte_fit(rezepte, fehler):
    """
    Fit-Bewertung mit Batching (a 5); faellt bei Inkonsistenzen auf Einzel-Aufrufe
    zurueck. Mutiert die Rezepte in-place (fit_score, kategorie, begruendung,
    zutaten_kurz, chris_haken). Rueckgabe: Anzahl bewerteter Rezepte.
    """
    ergebnisse = {}
    for i in range(0, len(rezepte), BATCH_GROESSE_FIT):
        gruppe = rezepte[i:i + BATCH_GROESSE_FIT]
        try:
            ergebnisse.update(_fit_batch(gruppe))
        except Exception as e:
            logger.warning("Fit-Batch fehlgeschlagen (%s) — versuche Einzelaufrufe.", e)
            for rezept in gruppe:
                try:
                    ergebnisse.update(_fit_batch([rezept]))
                except Exception as einzel_fehler:
                    fehler.append("rezepte fit %s: %s" % (rezept.get("id"), einzel_fehler))
        time.sleep(analyse.PAUSE_ZWISCHEN_CALLS_S)

    bewertet = 0
    for rezept in rezepte:
        e = ergebnisse.get(rezept.get("id"))
        if e is None:
            continue
        try:
            rezept["fit_score"] = int(max(0, min(100, int(e.get("fit_score", 0)))))
        except (TypeError, ValueError):
            rezept["fit_score"] = 0
        rezept["kategorie"] = e.get("kategorie") if e.get("kategorie") in KATEGORIEN else "sonstiges"
        rezept["begruendung"] = (e.get("begruendung") or "").strip()
        rezept["zutaten_kurz"] = [str(z).strip() for z in (e.get("zutaten_kurz") or [])
                                  if z and str(z).strip()][:6]
        rezept["chris_haken"] = (e.get("chris_haken") or "").strip()
        bewertet += 1
    return bewertet


# ---------------------------------------------------------------------------
# d) Persistenz: daten/rezepte.json (Merge-Muster aus speicher.py,
#    atomares Schreiben via speicher._schreibe_json_atomar)
# ---------------------------------------------------------------------------

def lade_rezepte():
    return speicher._lade_json(REZEPTE_DATEI, [])


def speichere_rezepte(kandidaten):
    """
    Kandidaten in den Bestand mergen. Neue ids -> komplett einfuegen.
    Bestehende ids -> NUR Metriken (views/likes/kommentare) aktualisieren,
    thumbnail/dauer nachtragen falls leer. status / feedback / Fit-Analyse /
    score werden NIE ueberschrieben.
    Rueckgabe: (anzahl_neu, anzahl_aktualisiert)
    """
    bestand = lade_rezepte()
    index = {r.get("id"): r for r in bestand}

    neu, aktualisiert = 0, 0
    for kand in kandidaten:
        rid = kand.get("id")
        if not rid:
            continue
        kand.pop("beschreibung", None)  # Prompt-Hilfsfeld nicht persistieren
        if rid in index:
            vorhanden = index[rid]
            geaendert = False
            for feld in METRIK_FELDER:
                wert = kand.get(feld)
                if wert is not None and wert != vorhanden.get(feld):
                    vorhanden[feld] = wert
                    geaendert = True
            for feld in NACHTRAG_FELDER:
                if not vorhanden.get(feld) and kand.get(feld):
                    vorhanden[feld] = kand[feld]
                    geaendert = True
            if geaendert:
                aktualisiert += 1
        else:
            bestand.append(kand)
            index[rid] = kand
            neu += 1

    speicher._schreibe_json_atomar(REZEPTE_DATEI, bestand)
    return neu, aktualisiert


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wolf Radar — Rezepte-Agent")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max. neue Kandidaten fuer die Gemini-Fit-Bewertung")
    args = parser.parse_args()

    start = time.time()
    fehler = []
    gefunden, analysiert, geflaggt = 0, 0, 0
    neu, aktualisiert = 0, 0

    status.start("rezepte")
    try:
        status.phase("Neue Rezepte auf YouTube suchen …")
        kandidaten = rezept_suche(fehler)
        gefunden = len(kandidaten)
        status.zaehler(gefunden=gefunden)

        bestand_ids = set(r.get("id") for r in lade_rezepte())

        # Bekannte Rezepte: nur Metrik-Update (kein erneuter Gemini-Call)
        bekannte = [k for k in kandidaten if k.get("id") in bestand_ids]
        neue = [k for k in kandidaten
                if k.get("id") not in bestand_ids and (k.get("views") or 0) >= MINDEST_VIEWS]
        zu_wenig = gefunden - len(bekannte) - len(neue)

        # Groesste Community-Resonanz zuerst — wichtig, falls --limit greift
        neue.sort(key=community_resonanz, reverse=True)
        if args.limit is not None:
            neue = neue[:args.limit]

        print("[rezepte] %d gefunden | %d schon bekannt, %d < %d Views -> %d zur Fit-Bewertung"
              % (gefunden, len(bekannte), zu_wenig, MINDEST_VIEWS, len(neue)))

        # Gemini-Fit-Bewertung
        if neue:
            status.phase("KI bewertet %d Rezepte auf Chris-Fit …" % len(neue))
        analysiert = bewerte_fit(neue, fehler) if neue else 0
        status.zaehler(analysiert=analysiert)

        # Nur Chris-Fit >= Schwelle speichern; Score = 0.5*Resonanz + 0.5*Fit
        passende = []
        for rezept in neue:
            if rezept.get("fit_score", 0) >= FIT_SCHWELLE:
                rezept["score"] = gesamtscore(rezept)
                passende.append(rezept)
            else:
                logger.info("Verworfen %s: fit_score=%s — %s", rezept.get("id"),
                            rezept.get("fit_score"), rezept.get("begruendung", ""))
        geflaggt = len(passende)
        passende.sort(key=lambda r: -(r.get("score") or 0))

        neu, aktualisiert = speichere_rezepte(passende + bekannte)
        status.zaehler(neu=neu, geflaggt=geflaggt)
    except Exception as e:
        fehler.append("rezepte: Lauf abgebrochen: %s" % e)
        print("[rezepte] FEHLER: %s" % e)

    dauer = int(time.time() - start)
    protokoll = {
        "zeit": speicher.jetzt_iso(),
        "quelle": "rezepte",
        "gefunden": gefunden,
        "neu": neu,
        "analysiert": analysiert,
        "geflaggt": geflaggt,
        "fehler": fehler,
        "dauer_s": dauer,
    }
    try:
        speicher.speichere_agent_run(protokoll)
    except Exception as e:
        print("[rezepte] FEHLER beim Protokoll-Schreiben: %s" % e)

    status.ende("Rezepte-Lauf abgeschlossen: %d neue Rezepte (Chris-Fit), %d gesichtet"
                % (neu, gefunden))

    print("")
    print("=" * 62)
    print("REZEPTE-RADAR — Lauf-Zusammenfassung (%s)" % speicher.jetzt_iso())
    print("=" * 62)
    print("gefunden=%d  fit-bewertet=%d  gespeichert(fit>=%d)=%d  neu=%d  "
          "metrik-updates=%d  dauer=%ds"
          % (gefunden, analysiert, FIT_SCHWELLE, geflaggt, neu, aktualisiert, dauer))
    for f in fehler:
        print("  FEHLER: %s" % f)

    top = sorted([r for r in lade_rezepte() if r.get("status") == "vorschlag"],
                 key=lambda r: -(r.get("score") or 0))[:3]
    if top:
        print("-" * 62)
        print("Top-Vorschlaege im Bestand:")
        for r in top:
            print("  score=%-3s fit=%-3s [%s] %s (%s Views)"
                  % (r.get("score"), r.get("fit_score"), r.get("kategorie"),
                     (r.get("titel") or "")[:60], r.get("views")))

    if gefunden == 0 and fehler:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Absturz-Schutz: Status nie auf "aktiv" haengen lassen (no-op nach
        # regulaerem Ende — status.ende() raeumt bereits auf).
        status.ende("Rezepte-Lauf unerwartet beendet")
