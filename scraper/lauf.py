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
import status
import youtube_agent
import tiktok_agent
import instagram_agent
from mythen_katalog import finde_themen

# Christian-taugliche Quellen-Namen fuer den Live-Status
QUELLE_NAME = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}

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


def neubewertung(limit=None):
    """Bestand mit der aktuellen Pipeline neu bewerten (Qualitäts-Nachrüstung).

    Ausgewählt werden analysierte Videos OHNE Websuche-Verifikation (= alte Pipeline),
    deren Status der Nutzer noch nicht entschieden hat (inbox/strittig/archiv).
    Vorher werden fehlende Transkripte beschafft (inkl. frischer Apify-CDN-URLs) —
    gerade TikTok/Instagram wurden früher nur anhand der Caption beurteilt.
    Debunk-Archivierungen bleiben unangetastet. Status darf sich in BEIDE
    Richtungen ändern (archiv→inbox und inbox→archiv)."""
    analysiere_batch, generiere_skripte = analyse_laden()
    if analysiere_batch is None:
        print("[neubewertung] analyse.py nicht verfuegbar — Abbruch")
        return 1

    videos = [v for v in speicher.lade_fuer_neubewertung()
              if (v.get("claim") or {}).get("verdict") != "debunk"]
    videos.sort(key=lambda v: -(v.get("views") or 0))
    if limit:
        videos = videos[:limit]
    print("[neubewertung] %d Videos (alte Pipeline, ohne Websuche-Verifikation)" % len(videos))
    if not videos:
        return 0
    start, fehler = time.time(), []
    status_vorher = {v["id"]: v.get("status") for v in videos}

    # --- Fehlende Transkripte beschaffen (Analyse soll Volltext sehen) -----
    ohne_transkript = [v for v in videos if not v.get("transkript")]
    if ohne_transkript:
        ig_posts = [v for v in ohne_transkript if v.get("plattform") == "instagram" and v.get("url")]
        if ig_posts:
            try:
                import apify_agent
                if apify_agent.verfuegbar():
                    urls = apify_agent.hole_video_urls([v["url"] for v in ig_posts], fehler)
                    for v in ig_posts:
                        if v.get("video_id") in urls:
                            v["apify_video_url"] = urls[v["video_id"]]
                    print("[neubewertung] Instagram: %d/%d frische CDN-URLs" % (len(urls), len(ig_posts)))
            except ImportError:
                pass
        yt_ohne = [v for v in ohne_transkript if v.get("plattform") == "youtube"]
        if yt_ohne:
            youtube_agent.hole_transkripte(yt_ohne, fehler, min_views=0,
                                           max_videos=min(len(yt_ohne), 25))
        try:
            import transkription
            transkription.transkribiere_kandidaten(ohne_transkript, fehler,
                                                   max_videos=25,
                                                   min_views_kurz=1000, min_views_yt=1000)
        except Exception as e:
            fehler.append("neubewertung transkription: %s" % e)
        # Transkripte sofort sichern (aktualisiere_analyse schreibt sie nicht)
        neue_transkripte = [v for v in ohne_transkript if v.get("transkript")]
        for v in ohne_transkript:
            v.pop("apify_video_url", None)
            v.pop("transkript_429", None)
        if neue_transkripte:
            speicher.speichere_videos(neue_transkripte)
            print("[neubewertung] %d Transkripte nachgeholt und gesichert" % len(neue_transkripte))

    # --- Neu analysieren (Chunk-weise, Checkpoint nach jedem Block) --------
    CHUNK = 5
    neu_bewertet = 0
    for i in range(0, len(videos), CHUNK):
        chunk = videos[i:i + CHUNK]
        for v in chunk:  # alte Analyse-Felder zuruecksetzen, damit nichts durchsickert
            v["claim"], v["status_alt"] = None, v.pop("status", None)
        try:
            ueberlebende = analysiere_batch(chunk) or []
        except Exception as e:
            fehler.append("chunk %d: %s" % (i // CHUNK + 1, e))
            print("[neubewertung] FEHLER in Chunk %d: %s" % (i // CHUNK + 1, e))
            continue
        # Skripte nur fuer NEUE Inbox-Ankuenfte ohne vorhandenes Skript-Paket
        frisch_inbox = [v for v in ueberlebende
                        if v.get("status") == "inbox" and not v.get("skripte")]
        if frisch_inbox and generiere_skripte is not None:
            try:
                generiere_skripte(frisch_inbox)
            except Exception as e:
                fehler.append("skripte chunk %d: %s" % (i // CHUNK + 1, e))
        ueberlebt_ids = set(v["id"] for v in ueberlebende)
        verworfene = [v for v in chunk if v["id"] not in ueberlebt_ids and v.get("claim")]
        for v in list(ueberlebende) + verworfene:
            v.pop("status_alt", None)
        speicher.aktualisiere_analyse(ueberlebende)
        speicher.aktualisiere_analyse(verworfene)
        neu_bewertet += len(ueberlebende) + len(verworfene)
        print("[neubewertung] Chunk %d/%d: %d neu bewertet"
              % (i // CHUNK + 1, (len(videos) + CHUNK - 1) // CHUNK,
                 len(ueberlebende) + len(verworfene)))

    # --- Transparenz: Status-Wechsel ausgeben ------------------------------
    nachher = {v["id"]: v.get("status") for v in speicher.lade_videos()}
    wechsel = []
    for vid, alt in status_vorher.items():
        neu = nachher.get(vid)
        if neu and neu != alt:
            wechsel.append("%s: %s -> %s" % (vid, alt, neu))
    print("[neubewertung] Status-Wechsel (%d):" % len(wechsel))
    for w in wechsel:
        print("   " + w)

    speicher.speichere_agent_run({
        "zeit": speicher.jetzt_iso(), "quelle": "neubewertung",
        "gefunden": len(videos), "neu": 0, "analysiert": neu_bewertet,
        "geflaggt": len([1 for w in wechsel if "-> inbox" in w]),
        "fehler": fehler, "dauer_s": int(time.time() - start),
    })
    for f in fehler:
        print("[neubewertung] FEHLER: %s" % f)
    return 0


def transkribiere_bestand(limit=None):
    """Backfill: bestehende Videos ohne Transkript nachtranskribieren (alle Plattformen).
    Instagram: frische CDN-URLs via Apify nachladen (die alten sind abgelaufen)."""
    try:
        import transkription
    except ImportError as e:
        print("[transkribiere] transkription.py nicht ladbar: %s" % e)
        return 1
    offene = speicher.lade_ohne_transkript()
    offene.sort(key=lambda v: -(v.get("views") or 0))
    print("[transkribiere] %d Videos ohne Transkript (inbox/strittig/angenommen/gespeichert)"
          % len(offene))
    if not offene:
        return 0
    status.start("transkription")
    status.phase("Fehlende Transkripte nachholen (%d Videos) …" % len(offene))
    start, fehler = time.time(), []

    # YouTube zuerst über Auto-Untertitel (billig) — im Backfill ohne View-Schwelle,
    # es geht ja gerade um Videos, mit denen Chris arbeitet
    erfolgreich = 0
    yt_offene = [v for v in offene if v.get("plattform") == "youtube"]
    if yt_offene:
        erfolgreich += youtube_agent.hole_transkripte(yt_offene, fehler, min_views=0,
                                                      max_videos=min(len(yt_offene), 25))

    ig_posts = [v for v in offene if v.get("plattform") == "instagram" and v.get("url")]
    if ig_posts:
        try:
            import apify_agent
            if apify_agent.verfuegbar():
                urls = apify_agent.hole_video_urls([v["url"] for v in ig_posts], fehler)
                for v in ig_posts:
                    if v.get("video_id") in urls:
                        v["apify_video_url"] = urls[v["video_id"]]
                print("[transkribiere] Instagram: %d/%d frische CDN-URLs via Apify"
                      % (len(urls), len(ig_posts)))
        except ImportError:
            pass

    # Audio-Transkription für den Rest — im Backfill mit niedriger View-Schwelle
    # (das sind Chris' Arbeits-Videos, die Materialbasis soll vollständig werden)
    erfolgreich += transkription.transkribiere_kandidaten(
        offene, fehler, max_videos=limit, min_views_kurz=1000, min_views_yt=1000)
    transkribierte = [v for v in offene if v.get("transkript")]
    for v in transkribierte:
        v.pop("apify_video_url", None)
    if transkribierte:
        _, aktualisiert = speicher.speichere_videos(transkribierte)
        print("[transkribiere] %d Transkripte gespeichert" % aktualisiert)

    speicher.speichere_agent_run({
        "zeit": speicher.jetzt_iso(), "quelle": "transkription",
        "gefunden": len(offene), "neu": 0, "analysiert": erfolgreich,
        "geflaggt": 0, "fehler": fehler, "dauer_s": int(time.time() - start),
    })
    for f in fehler:
        print("[transkribiere] FEHLER: %s" % f)
    status.ende("Transkript-Nachholung fertig: %d von %d Videos ergaenzt"
                % (erfolgreich, len(offene)))
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
    parser.add_argument("--transkribiere", action="store_true",
                        help="Backfill: bestehende Videos ohne Transkript nachtranskribieren, kein Scraping")
    parser.add_argument("--neubewertung", action="store_true",
                        help="Bestand ohne Websuche-Verifikation neu analysieren (inkl. Transkript-Nachholung), kein Scraping")
    args = parser.parse_args()

    if args.nachanalyse:
        return nachanalyse(limit=args.limit)
    if args.transkribiere:
        return transkribiere_bestand(limit=args.limit)
    if args.neubewertung:
        return neubewertung(limit=args.limit)

    quellen = [q.strip() for q in args.nur.split(",") if q.strip()]
    watchlist = lade_watchlist()
    speicher.stelle_einstellungen_sicher()

    bestand_ids = set()
    for v in speicher.lade_videos():
        bestand_ids.add(v.get("id"))
    print("[lauf] Modus=%s, Bestand: %d Videos, Quellen: %s"
          % (speicher.daten_modus(), len(bestand_ids), ", ".join(quellen)))
    status.start("lauf", quellen)

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

    # Zusatz-Queries aus Chris' Vorschlaegen (App schreibt sie, 7 Tage aktiv)
    try:
        extra_queries = speicher.lade_extra_queries()
    except Exception as e:
        print("[lauf] WARNUNG: extra_queries nicht ladbar: %s" % e)
        extra_queries = []
    if extra_queries:
        status.schritt("Deine Vorschlaege fliessen in die Suche ein: %s"
                       % ", ".join("„%s“" % q for q in extra_queries[:4]),
                       typ="erfolg")

    agenten = {
        "youtube": lambda: youtube_agent.sammle(watchlist, extra_queries=extra_queries),
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
        such_protokoll = []
        gefunden, analysiert, geflaggt, neu = 0, 0, 0, 0
        qname = QUELLE_NAME.get(quelle, quelle)
        try:
            status.phase("%s durchsuchen …" % qname)
            ergebnis = agenten[quelle]()
            kandidaten = ergebnis["kandidaten"]
            fehler = ergebnis["fehler"]
            such_protokoll = ergebnis.get("such_protokoll") or []
            # Transparenz: die ergiebigsten Suchbegriffe live ins Protokoll (Top 5)
            if such_protokoll:
                top = sorted(such_protokoll, key=lambda p: -p.get("gefunden", 0))[:5]
                for p in top:
                    if p.get("gefunden"):
                        status.schritt("   • „%s“ → %d Treffer" % (p["query"], p["gefunden"]))
            gefunden = len(kandidaten)
            status.zaehler(gefunden=gefunden)
            status.schritt("%s: %d Videos gesichtet" % (qname, gefunden))

            durch, stat = vorfilter(kandidaten, bestand_ids, limit=args.limit)
            print("[lauf] %s: %d gefunden | Vorfilter: %d bekannt, %d <%d Views, "
                  "%d nicht deutsch, %d ohne Thema -> %d neu"
                  % (quelle, gefunden, stat["schon_bekannt"], stat["zu_wenig_views"],
                     MINDEST_VIEWS, stat["nicht_deutsch"], stat["kein_thema"], stat["durch"]))
            status.schritt("%s: %d relevante neue Kandidaten (Rest: bekannt, "
                           "zu klein oder kein Ernaehrungsthema)" % (qname, stat["durch"]))

            # Transkripte erst NACH dem Vorfilter (spart yt-dlp-Aufrufe).
            # YouTube: erst Auto-Untertitel (billig), dann Audio-Fallback.
            # TikTok/Instagram: direkt Audio-Transkription (Gemini) — die
            # Falschaussage steckt dort im gesprochenen Wort, nicht in der Caption.
            if durch:
                status.phase("%s: Transkripte der Videos holen …" % qname)
            if quelle == "youtube" and durch:
                youtube_agent.hole_transkripte(durch, fehler)
            if durch:
                try:
                    import transkription
                    transkription.transkribiere_kandidaten(durch, fehler)
                except Exception as e:
                    fehler.append("%s transkription: %s" % (quelle, e))
            if durch:
                mit_transkript = sum(1 for k in durch if k.get("transkript"))
                status.schritt("%s: %d/%d Transkripte liegen vor"
                               % (qname, mit_transkript, len(durch)))

            # Analyse (Gemini) — nur wenn verfuegbar und nicht abgeschaltet
            if durch and analysiere_batch is not None:
                try:
                    status.phase("%s: KI prueft %d Videos auf Falschaussagen …"
                                 % (qname, len(durch)))
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
                    status.zaehler(analysiert=analysiert, geflaggt=geflaggt)
                    status.schritt("%s: %d Videos analysiert — %d mit Falschaussage geflaggt"
                                   % (qname, analysiert, geflaggt),
                                   typ="erfolg" if geflaggt else "info")
                    # Skript-Pakete nur fuer Inbox-Funde (strittige bekommen erst nach Annahme welche)
                    skript_kandidaten = [k for k in geflaggte if k.get("status") == "inbox"]
                    if skript_kandidaten and generiere_skripte is not None:
                        try:
                            status.phase("%s: Antwort-Skripte fuer %d Funde schreiben …"
                                         % (qname, len(skript_kandidaten)))
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
                k.pop("apify_video_url", None)  # transient: kurzlebige CDN-URL nie speichern
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
            status.zaehler(neu=n)
            if n:
                status.schritt("%s: %d neue Videos im Radar gespeichert" % (qname, n),
                               typ="erfolg")
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
            status.schritt("%s: Quelle uebersprungen (technisches Problem)" % qname)

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
            # Pro-Suchbegriff-Aufschlüsselung (nur YouTube-Apify-Suche) für die
            # "Was die Suche ergab"-Ansicht im UI.
            "such_protokoll": such_protokoll,
        }
        try:
            speicher.speichere_agent_run(protokoll)
        except Exception as e:
            print("[lauf] FEHLER beim Protokoll-Schreiben (%s): %s" % (quelle, e))
        zusammenfassung.append(protokoll)

    # Fast-Dubletten desselben Creators zusammenfassen (nur eins bleibt in der Inbox)
    try:
        dubletten = speicher.markiere_dubletten()
        if dubletten:
            print("[lauf] %d Fast-Dublette(n) nach 'archiv' verschoben" % dubletten)
            status.schritt("%d fast identische Videos desselben Creators "
                           "zusammengefasst" % dubletten)
    except Exception as e:
        print("[lauf] WARNUNG: Dubletten-Erkennung fehlgeschlagen: %s" % e)

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

    gesamt_geflaggt = sum(p["geflaggt"] for p in zusammenfassung)
    status.ende("Lauf abgeschlossen: %d neue Videos, %d mit Falschaussage geflaggt"
                % (gesamt_neu, gesamt_geflaggt))

    # Exit-Code: 0 auch bei Teilfehlern (Protokoll ist geschrieben) —
    # nur wenn GAR NICHTS lief, signalisieren wir Fehler.
    alles_leer = all(p["gefunden"] == 0 for p in zusammenfassung)
    alle_fehler = any(p["fehler"] for p in zusammenfassung)
    if alles_leer and alle_fehler:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Absturz-Schutz: Status nie auf "aktiv" haengen lassen (no-op, wenn
        # der Lauf regulaer beendet wurde — ende() raeumt _status auf).
        status.ende("Lauf unerwartet beendet")
