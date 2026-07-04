# -*- coding: utf-8 -*-
"""
Wolf Radar — Orchestrator

Ablauf: Agenten sammeln -> Dedupe gegen Bestand -> Vorfilter (deutsch,
Mindest-Views, Themen-Keywords) -> Transkripte (YouTube) -> Analyse
(Gemini, optional) -> Skripte (optional) -> Speichern -> agent_run-Protokoll.

CLI:
    python3 lauf.py [--nur youtube,tiktok,instagram] [--ohne-analyse] [--limit N]

Existieren analyse.py/skripte.py (parallele Builder) noch nicht, laeuft der
Lauf automatisch im --ohne-analyse-Modus weiter und speichert Rohkandidaten.
"""

import argparse
import json
import os
import re
import sys
import time

# scraper/ importierbar machen, egal von wo gestartet wird
SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import speicher
import youtube_agent
import tiktok_agent
import instagram_agent
from mythen_katalog import finde_themen

WATCHLIST_DATEI = os.path.join(SCRAPER_DIR, "watchlist.json")
MINDEST_VIEWS = 1000

# Haeufige deutsche Woerter fuer die Sprach-Heuristik (kleingeschrieben)
_DEUTSCHE_WOERTER = {
    "der", "die", "das", "und", "ist", "nicht", "mit", "für", "fuer", "auf",
    "ein", "eine", "wie", "was", "warum", "wenn", "aber", "auch", "sind",
    "euch", "ihr", "dich", "dein", "deine", "mein", "kein", "mehr", "beim",
    "gesund", "ungesund", "abnehmen", "essen", "macht", "wirklich", "diese",
    "dieser", "wahrheit", "über", "ueber", "warum", "sollte", "muss", "kann",
}
_UMLAUT_RE = re.compile(r"[äöüßÄÖÜ]")
_WORT_RE = re.compile(r"[a-zA-ZäöüßÄÖÜ]+")


def ist_deutsch(text):
    """
    Billige Sprach-Heuristik: Umlaute oder >= 2 haeufige deutsche Woerter.
    Bei sehr wenig Text (nicht beurteilbar) lassen wir den Kandidaten durch —
    die Gemini-Analyse sortiert Nicht-Deutsches spaeter sicher aus.
    """
    if not text or len(text.strip()) < 12:
        return True
    if _UMLAUT_RE.search(text):
        return True
    woerter = _WORT_RE.findall(text.lower())
    treffer = sum(1 for w in woerter if w in _DEUTSCHE_WOERTER)
    return treffer >= 2


def lade_watchlist():
    """Watchlist laden. Im Supabase-Modus ist die DB die Quelle der Wahrheit
    (das Personen-Dashboard schreibt 'Folgen' dorthin); die Datei ist der Seed."""
    datei_eintraege = []
    try:
        with open(WATCHLIST_DATEI, "r", encoding="utf-8") as f:
            datei_eintraege = json.load(f).get("eintraege", [])
    except (OSError, json.JSONDecodeError) as e:
        print("[lauf] WARNUNG: watchlist.json nicht lesbar: %s" % e)

    if speicher.daten_modus() == "supabase":
        try:
            zeilen = speicher._supabase_get("einstellungen", {"select": "value", "key": "eq.watchlist"})
            if zeilen and zeilen[0].get("value", {}).get("eintraege"):
                db_eintraege = zeilen[0]["value"]["eintraege"]
                print("[lauf] Watchlist aus Supabase: %d Eintraege (Datei-Seed: %d)"
                      % (len(db_eintraege), len(datei_eintraege)))
                return db_eintraege
        except Exception as e:
            print("[lauf] WARNUNG: Watchlist aus Supabase nicht ladbar (%s) — nutze Datei." % e)
    return datei_eintraege


def vorfilter(kandidaten, bestand_ids, limit=None):
    """
    Dedupe gegen Bestand + billige Filter ohne KI.
    Rueckgabe: (durchgelassen, statistik-Dict)
    """
    stat = {"schon_bekannt": 0, "zu_wenig_views": 0, "nicht_deutsch": 0,
            "kein_thema": 0, "durch": 0}
    durch = []
    gesehen = set()
    for k in kandidaten:
        kid = k.get("id")
        if not kid or kid in gesehen:
            continue
        gesehen.add(kid)
        if kid in bestand_ids:
            stat["schon_bekannt"] += 1
            continue
        # Reichweiten-Filter: Instagram-Foto-/Carousel-Posts haben keine Views —
        # dort sind Likes der Reichweiten-Proxy (Like-Rate grob 5-8% => Faktor 12).
        reichweite_proxy = k.get("views") or 0
        if not reichweite_proxy and k.get("plattform") == "instagram":
            reichweite_proxy = (k.get("likes") or 0) * 12
        if reichweite_proxy < MINDEST_VIEWS:
            stat["zu_wenig_views"] += 1
            continue
        text = " ".join(filter(None, [k.get("titel"), k.get("caption")]))
        if not ist_deutsch(text):
            stat["nicht_deutsch"] += 1
            continue
        themen = finde_themen(" ".join(filter(None, [
            k.get("titel"), k.get("caption"), k.get("transkript")])))
        if not themen:
            stat["kein_thema"] += 1
            continue
        durch.append(k)

    # Groesste Reichweite zuerst — wichtig, falls --limit greift
    durch.sort(key=lambda k: -(k.get("views") or 0))
    if limit is not None:
        durch = durch[:limit]
    stat["durch"] = len(durch)
    return durch, stat


def analyse_laden():
    """analyse.py / skripte.py importieren und auf die Lauf-Schnittstelle adaptieren.
    analyse.analysiere_batch(kandidaten, gelernt) -> Ueberlebende
    skripte.generiere_skripte(video, gelernt) -> Skript-Liste (pro Video)"""
    try:
        from analyse import analysiere_batch as _batch
    except ImportError:
        return None, None

    gelernt = (speicher.lade_einstellungen() or {}).get("gelernt", {})

    def batch_adapter(kandidaten):
        return _batch(kandidaten, gelernt)

    try:
        from skripte import generiere_skripte as _skripte
    except ImportError:
        return batch_adapter, None

    def skripte_adapter(videos):
        for v in videos:
            try:
                v["skripte"] = _skripte(v, gelernt) or []
            except Exception as e:
                print("[lauf] Skript-Generierung fuer %s fehlgeschlagen: %s" % (v.get("id"), e))

    return batch_adapter, skripte_adapter


def nachanalyse(limit=None):
    """Bestehende Videos ohne claim analysieren (z.B. nach Analyse-Ausfall im Sammellauf)."""
    analysiere_batch, generiere_skripte = analyse_laden()
    if analysiere_batch is None:
        print("[nachanalyse] analyse.py nicht verfuegbar — Abbruch")
        return 1
    offene = speicher.lade_unanalysierte()
    if limit:
        offene = offene[:limit]
    print("[nachanalyse] %d unanalysierte Videos" % len(offene))
    if not offene:
        return 0
    start, fehler = time.time(), []
    gesamt_geflaggt, gesamt_archiviert = 0, 0

    # Chunk-weise mit Checkpoint nach jedem Block: ein Abbruch verliert maximal einen Chunk
    CHUNK = 5
    for i in range(0, len(offene), CHUNK):
        chunk = offene[i:i + CHUNK]
        chunk_ids = set(v["id"] for v in chunk)
        try:
            ueberlebende = analysiere_batch(chunk) or []
        except Exception as e:
            fehler.append("chunk %d: %s" % (i // CHUNK + 1, e))
            print("[nachanalyse] FEHLER in Chunk %d: %s" % (i // CHUNK + 1, e))
            continue
        geflaggte = [v for v in ueberlebende if v.get("claim")]
        skript_kandidaten = [v for v in geflaggte if v.get("status") == "inbox"]
        if skript_kandidaten and generiere_skripte is not None:
            try:
                generiere_skripte(skript_kandidaten)
            except Exception as e:
                fehler.append("skripte chunk %d: %s" % (i // CHUNK + 1, e))
        # Verworfene transparent archivieren: analyse.py annotiert sie in place mit
        # konkretem Grund (claim.verdict = aussortiert/korrekt/debunk). Kandidaten OHNE
        # Annotation (API-Fehler) bleiben unangefasst und werden beim naechsten Lauf erneut versucht.
        ueberlebt_ids = set(v["id"] for v in ueberlebende)
        verworfene = [v for v in chunk
                      if v["id"] not in ueberlebt_ids and v.get("claim")]
        speicher.aktualisiere_analyse(ueberlebende)
        speicher.aktualisiere_analyse(verworfene)
        gesamt_geflaggt += len(geflaggte)
        gesamt_archiviert += len(verworfene)
        print("[nachanalyse] Chunk %d/%d gespeichert: %d geflaggt, %d archiviert"
              % (i // CHUNK + 1, (len(offene) + CHUNK - 1) // CHUNK, len(geflaggte), len(verworfene)))

    protokoll = {"zeit": speicher.jetzt_iso(), "quelle": "nachanalyse",
                 "gefunden": len(offene), "neu": 0, "analysiert": len(offene),
                 "geflaggt": gesamt_geflaggt, "fehler": fehler,
                 "dauer_s": int(time.time() - start)}
    speicher.speichere_agent_run(protokoll)
    print("[nachanalyse] fertig: %d analysiert, %d geflaggt (inbox/strittig), %d archiviert"
          % (len(offene), gesamt_geflaggt, gesamt_archiviert))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Wolf Radar — Scraper-Lauf")
    parser.add_argument("--nur", default="youtube,tiktok,instagram",
                        help="Kommagetrennte Quellen (youtube,tiktok,instagram)")
    parser.add_argument("--ohne-analyse", action="store_true",
                        help="Gemini-Analyse ueberspringen, Rohkandidaten speichern")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max. neue Kandidaten pro Quelle (nach Vorfilter)")
    parser.add_argument("--nachanalyse", action="store_true",
                        help="Nur bestehende unanalysierte Videos (claim=null) analysieren, kein Scraping")
    args = parser.parse_args()

    if args.nachanalyse:
        return nachanalyse(limit=args.limit)

    quellen = [q.strip() for q in args.nur.split(",") if q.strip()]
    watchlist = lade_watchlist()
    speicher.stelle_einstellungen_sicher()

    bestand_ids = set()
    for v in speicher.lade_videos():
        bestand_ids.add(v.get("id"))
    print("[lauf] Modus=%s, Bestand: %d Videos, Quellen: %s"
          % (speicher.daten_modus(), len(bestand_ids), ", ".join(quellen)))

    analysiere_batch, generiere_skripte = (None, None)
    if not args.ohne_analyse:
        analysiere_batch, generiere_skripte = analyse_laden()
        if analysiere_batch is None:
            print("[lauf] analyse.py noch nicht vorhanden — laufe ohne Analyse weiter (Rohkandidaten)")

    # Instagram: mit APIFY_TOKEN läuft der zuverlässige Apify-Scraper,
    # ohne Token der gallery-dl-Best-Effort (rate-limit-anfällig).
    def instagram_sammeln():
        try:
            import apify_agent
            if apify_agent.verfuegbar():
                print("[lauf] instagram: Apify-Modus (APIFY_TOKEN gesetzt)")
                return apify_agent.sammle_instagram(watchlist)
        except ImportError:
            pass
        return instagram_agent.sammle(watchlist)

    agenten = {
        "youtube": lambda: youtube_agent.sammle(watchlist),
        "tiktok": lambda: tiktok_agent.sammle(watchlist),
        "instagram": instagram_sammeln,
    }

    gesamt_neu, gesamt_aktualisiert = 0, 0
    zusammenfassung = []

    for quelle in quellen:
        if quelle not in agenten:
            print("[lauf] Unbekannte Quelle uebersprungen: %s" % quelle)
            continue
        start = time.time()
        fehler = []
        gefunden, analysiert, geflaggt, neu = 0, 0, 0, 0
        try:
            ergebnis = agenten[quelle]()
            kandidaten = ergebnis["kandidaten"]
            fehler = ergebnis["fehler"]
            gefunden = len(kandidaten)

            durch, stat = vorfilter(kandidaten, bestand_ids, limit=args.limit)
            print("[lauf] %s: %d gefunden | Vorfilter: %d bekannt, %d <%d Views, "
                  "%d nicht deutsch, %d ohne Thema -> %d neu"
                  % (quelle, gefunden, stat["schon_bekannt"], stat["zu_wenig_views"],
                     MINDEST_VIEWS, stat["nicht_deutsch"], stat["kein_thema"], stat["durch"]))

            # Transkripte erst NACH dem Vorfilter (spart yt-dlp-Aufrufe)
            if quelle == "youtube" and durch:
                youtube_agent.hole_transkripte(durch, fehler)

            # Analyse (Gemini) — nur wenn verfuegbar und nicht abgeschaltet
            if durch and analysiere_batch is not None:
                try:
                    analysiert = len(durch)
                    analysierte = analysiere_batch(durch)
                    if analysierte is not None:
                        # Ueberlebende + annotierte Verworfene speichern (transparentes Archiv);
                        # unannotierte (API-Fehler) NICHT speichern -> naechster Lauf versucht erneut
                        ueberlebt_ids = set(v["id"] for v in analysierte)
                        verworfen_annotiert = [k for k in durch
                                               if k["id"] not in ueberlebt_ids and k.get("claim")]
                        durch = analysierte + verworfen_annotiert
                    geflaggte = [k for k in durch if k.get("claim") and k.get("status") in ("inbox", "strittig")]
                    geflaggt = len(geflaggte)
                    # Skript-Pakete nur fuer Inbox-Funde (strittige bekommen erst nach Annahme welche)
                    skript_kandidaten = [k for k in geflaggte if k.get("status") == "inbox"]
                    if skript_kandidaten and generiere_skripte is not None:
                        try:
                            generiere_skripte(skript_kandidaten)
                        except Exception as e:
                            fehler.append("%s skripte: %s" % (quelle, e))
                except Exception as e:
                    fehler.append("%s analyse: %s — Rohkandidaten werden gespeichert" % (quelle, e))

            # Transkript-429-Schutz: Wurde ein Kandidat OHNE Transkript (Rate-Limit)
            # mangels pruefbarem Material "aussortiert", ist das kein Urteil ueber den
            # Inhalt, sondern ueber die Materiallage. Nicht speichern — der naechste
            # Lauf holt das Transkript nach und urteilt mit vollem Material.
            vertagt_ids = set()
            for k in durch:
                war_429 = k.pop("transkript_429", False)
                if war_429 and (k.get("claim") or {}).get("verdict") == "aussortiert":
                    vertagt_ids.add(k.get("id"))
            if vertagt_ids:
                durch = [k for k in durch if k.get("id") not in vertagt_ids]
                meldung = ("%s: %d Kandidat(en) vertagt — 'aussortiert' ohne Transkript "
                           "(429), Retry im naechsten Lauf" % (quelle, len(vertagt_ids)))
                print("[lauf] " + meldung)
                fehler.append(meldung)

            n, a = speicher.speichere_videos(durch)
            neu, gesamt_neu, gesamt_aktualisiert = n, gesamt_neu + n, gesamt_aktualisiert + a
            for k in durch:
                bestand_ids.add(k.get("id"))

            # Metrik-Updates fuer schon bekannte Videos (Views aktuell halten)
            bekannte = [k for k in kandidaten if k.get("id") in bestand_ids
                        and k not in durch]
            if bekannte:
                _, a2 = speicher.speichere_videos(bekannte)
                gesamt_aktualisiert += a2
        except Exception as e:
            fehler.append("%s: Lauf abgebrochen: %s" % (quelle, e))
            print("[lauf] FEHLER in Quelle %s: %s" % (quelle, e))

        dauer = int(time.time() - start)
        protokoll = {
            "zeit": speicher.jetzt_iso(),
            "quelle": quelle,
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
            print("[lauf] FEHLER beim Protokoll-Schreiben (%s): %s" % (quelle, e))
        zusammenfassung.append(protokoll)

    # ---------------- Konsolen-Summary ----------------
    print("")
    print("=" * 62)
    print("WOLF RADAR — Lauf-Zusammenfassung (%s)" % speicher.jetzt_iso())
    print("=" * 62)
    for p in zusammenfassung:
        print("%-10s gefunden=%-4d neu=%-4d analysiert=%-4d geflaggt=%-3d dauer=%ds"
              % (p["quelle"], p["gefunden"], p["neu"], p["analysiert"],
                 p["geflaggt"], p["dauer_s"]))
        for f in p["fehler"]:
            print("           FEHLER: %s" % f)
    print("-" * 62)
    print("Gesamt: %d neue Videos, %d Metrik-Updates, Modus=%s"
          % (gesamt_neu, gesamt_aktualisiert, speicher.daten_modus()))

    # Exit-Code: 0 auch bei Teilfehlern (Protokoll ist geschrieben) —
    # nur wenn GAR NICHTS lief, signalisieren wir Fehler.
    alles_leer = all(p["gefunden"] == 0 for p in zusammenfassung)
    alle_fehler = any(p["fehler"] for p in zusammenfassung)
    if alles_leer and alle_fehler:
        sys.exit(1)


if __name__ == "__main__":
    main()
