# -*- coding: utf-8 -*-
"""
test_analyse.py — LIVE-Test der Analyse- und Skript-Pipeline mit dem echten Gemini-Key.

Vier handkonstruierte, realistische Fälle (siehe Aufgabenstellung):
  (a) klarer Mythos       — 'Kohlenhydrate nach 18 Uhr machen dick' → klar_falsch + 3 Skripte
  (b) Debunk-Video        — ARD-Aufklärung zu Süßstoffen → korrekt → verworfen
  (c) strittiges Thema    — 'Intervallfasten ist besser als normale Diät' → strittig
  (d) themenfremd         — 'Die 5 besten Aktien 2026' → verworfen in Stufe A

Bonus (e): lerne_aus_feedback mit synthetischem Feedback (Boost-Formel + Gemini-Notizen).

Ausführen:  python3 test_analyse.py   (im scraper-Ordner; Key aus ENV oder ../../../.env)
Exit-Code 0 = alle Erwartungen erfüllt.
"""

import logging
import sys
from datetime import datetime, timedelta, timezone

import analyse
import skripte

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wolf_radar.test")


def _iso_vor_tagen(tage):
    return (datetime.now(timezone.utc) - timedelta(days=tage)).strftime("%Y-%m-%dT%H:%M:%SZ")


def baue_kandidaten():
    """Vier realistische Kandidaten-Dicts nach Kontrakt-Datenmodell."""
    return [
        # (a) klarer Mythos — fiktives TikTok mit 500k Views
        {
            "id": "tiktok:test_carbs18uhr",
            "plattform": "tiktok",
            "video_id": "test_carbs18uhr",
            "url": "https://www.tiktok.com/@fitcoach.maxi/video/test_carbs18uhr",
            "titel": "Deshalb nimmst du nicht ab! Kohlenhydrate nach 18 Uhr",
            "kanal": "FitCoach Maxi",
            "kanal_id": "@fitcoach.maxi",
            "kanal_follower": 220000,
            "veroeffentlicht": _iso_vor_tagen(4),
            "views": 500000, "likes": 41000, "kommentare": 890,
            "dauer_s": 52, "thumbnail_url": None,
            "caption": "Der größte Abnehm-Fehler überhaupt! #abnehmen #fitness #ernaehrung",
            "transkript": (
                "Leute, wenn ihr abnehmen wollt, hört mir jetzt genau zu. Kohlenhydrate nach "
                "18 Uhr machen dick, weil der Stoffwechsel abends schläft. Euer Körper kann die "
                "Carbs am Abend nicht mehr verbrennen und lagert alles direkt als Fett ein. "
                "Deswegen: nach 18 Uhr keine Nudeln, kein Brot, kein Reis mehr. Macht das zwei "
                "Wochen und ihr werdet den Unterschied auf der Waage sehen, versprochen."
            ),
            "gefunden_am": _iso_vor_tagen(0),
            "quelle": "claim_suche",
        },
        # (b) Debunk-Video — ARD-Aufklärungsvideo zu Süßstoffen
        {
            "id": "youtube:test_ard_suessstoffe",
            "plattform": "youtube",
            "video_id": "test_ard_suessstoffe",
            "url": "https://www.youtube.com/watch?v=test_ard_suessstoffe",
            "titel": "Süßstoffe: Ungesund und krebserregend oder sinnvolle Zucker-Alternative?",
            "kanal": "ARD Gesund",
            "kanal_id": "UCtest_ardgesund",
            "kanal_follower": 310000,
            "veroeffentlicht": _iso_vor_tagen(6),
            "views": 180000, "likes": 6200, "kommentare": 540,
            "dauer_s": 720, "thumbnail_url": None,
            "caption": "Aspartam, Sucralose und Co. — wie gefährlich sind Süßstoffe wirklich? "
                       "Wir schauen auf die Studienlage.",
            "transkript": (
                "Im Netz kursiert immer wieder die Behauptung, Süßstoffe wie Aspartam seien "
                "krebserregend. Aber stimmt das wirklich? Schauen wir auf die Daten: Die "
                "europäische Lebensmittelbehörde EFSA hat Aspartam umfassend geprüft und hält "
                "die zulässige Tagesdosis von 40 Milligramm pro Kilogramm Körpergewicht für "
                "sicher — das wären umgerechnet mehr als ein Dutzend Dosen Light-Limonade am "
                "Tag. Auch die viel zitierte IARC-Einstufung von 2023 bedeutet nicht, dass "
                "normale Mengen gefährlich sind. Die Sorge vor Krebs durch Süßstoffe ist nach "
                "aktueller Studienlage unbegründet. Wer Kalorien sparen will, kann Süßstoffe "
                "als Zucker-Alternative durchaus sinnvoll einsetzen."
            ),
            "gefunden_am": _iso_vor_tagen(0),
            "quelle": "claim_suche",
        },
        # (c) strittiges Thema — Intervallfasten-Überlegenheits-Claim
        {
            "id": "youtube:test_intervallfasten",
            "plattform": "youtube",
            "video_id": "test_intervallfasten",
            "url": "https://www.youtube.com/watch?v=test_intervallfasten",
            "titel": "Intervallfasten ist besser als jede normale Diät!",
            "kanal": "HealthHacks DE",
            "kanal_id": "UCtest_healthhacks",
            "kanal_follower": 95000,
            "veroeffentlicht": _iso_vor_tagen(9),
            "views": 74000, "likes": 3100, "kommentare": 260,
            "dauer_s": 61, "thumbnail_url": None,
            "caption": "16:8 schlägt Kalorienzählen — probier es aus! #intervallfasten",
            "transkript": (
                "Ich sage es euch ganz klar: Intervallfasten ist besser als jede normale Diät. "
                "Mit 16 zu 8 verlierst du mehr Fett als mit klassischem Kalorienzählen, weil "
                "dein Körper im Fastenfenster viel effektiver arbeitet. Vergiss Kalorien zählen, "
                "iss einfach nur zwischen 12 und 20 Uhr und du nimmst automatisch ab."
            ),
            "gefunden_am": _iso_vor_tagen(0),
            "quelle": "claim_suche",
        },
        # (d) themenfremd — Finanz-Video
        {
            "id": "youtube:test_aktien2026",
            "plattform": "youtube",
            "video_id": "test_aktien2026",
            "url": "https://www.youtube.com/watch?v=test_aktien2026",
            "titel": "Die 5 besten Aktien 2026",
            "kanal": "FinanzFuchs",
            "kanal_id": "UCtest_finanzfuchs",
            "kanal_follower": 400000,
            "veroeffentlicht": _iso_vor_tagen(3),
            "views": 250000, "likes": 9800, "kommentare": 1200,
            "dauer_s": 640, "thumbnail_url": None,
            "caption": "Diese 5 Aktien solltest du 2026 auf dem Schirm haben! Keine Anlageberatung.",
            "transkript": (
                "Willkommen zurück auf dem Kanal! Heute schauen wir uns die fünf spannendsten "
                "Aktien für 2026 an. Auf Platz fünf: ein Halbleiter-Wert, der vom KI-Boom "
                "profitiert. Auf Platz vier: ein Pharma-Riese mit starker Pipeline."
            ),
            "gefunden_am": _iso_vor_tagen(0),
            "quelle": "discovery",
        },
    ]


def pruefe(bedingung, meldung, fehler_liste):
    status = "BESTANDEN" if bedingung else "FEHLGESCHLAGEN"
    log.info("[%s] %s", status, meldung)
    if not bedingung:
        fehler_liste.append(meldung)


def main():
    fehler = []
    kandidaten = baue_kandidaten()

    # ---------------- analysiere_batch (Fälle a-d) ----------------
    log.info("=== LIVE-TEST analysiere_batch mit %d Kandidaten ===", len(kandidaten))
    ergebnisse = analyse.analysiere_batch(kandidaten, gelernt={})
    nach_id = {v["id"]: v for v in ergebnisse}

    # (a) klarer Mythos
    a = nach_id.get("tiktok:test_carbs18uhr")
    pruefe(a is not None, "(a) Carbs-nach-18-Uhr-Mythos überlebt die Pipeline", fehler)
    if a:
        pruefe(a["claim"]["verdict"] in ("klar_falsch", "irrefuehrend"),
               "(a) Verdict ist klar_falsch/irrefuehrend (ist: " + a["claim"]["verdict"] + ")", fehler)
        pruefe(a["claim"]["konfidenz"] >= 0.75,
               "(a) Konfidenz >= 0.75 (ist: " + str(a["claim"]["konfidenz"]) + ")", fehler)
        pruefe(a["status"] == "inbox",
               "(a) Status ist inbox (ist: " + a["status"] + ")", fehler)
        pruefe(bool(a["claim"]["aussage"]), "(a) Claim-Aussage extrahiert", fehler)
        pruefe(0 < a["score"] <= 100,
               "(a) Score im Bereich 1-100 (ist: " + str(a["score"]) + ")", fehler)
        s = a["scores"]
        log.info("(a) Scores: reichweite=%d relevanz=%d tauglichkeit=%d gesamt=%d | Claim: %s",
                 s["reichweite"], s["relevanz"], s["tauglichkeit"], a["score"],
                 a["claim"]["aussage"][:120])
        # 500k Views, 4 Tage alt, 52s, Transkript: Reichweite muss hoch sein, Tauglichkeit 70
        pruefe(s["reichweite"] >= 85, "(a) Reichweite >= 85 bei 500k Views", fehler)
        pruefe(s["tauglichkeit"] == 70,
               "(a) Tauglichkeit == 70 (kurz+frisch+transkript, keine Watchlist; ist: " +
               str(s["tauglichkeit"]) + ")", fehler)

    # (b) Debunk-Video muss verworfen sein
    pruefe("youtube:test_ard_suessstoffe" not in nach_id,
           "(b) ARD-Süßstoff-Debunk wurde verworfen (korrekt/Debunk)", fehler)

    # (c) strittig
    c = nach_id.get("youtube:test_intervallfasten")
    pruefe(c is not None, "(c) Intervallfasten-Video ist im Ergebnis", fehler)
    if c:
        pruefe(c["status"] == "strittig",
               "(c) Status ist strittig (ist: " + c["status"] + ")", fehler)
        pruefe(c["claim"]["verdict"] == "strittig",
               "(c) Verdict ist strittig (ist: " + c["claim"]["verdict"] + ")", fehler)

    # (d) themenfremd verworfen
    pruefe("youtube:test_aktien2026" not in nach_id,
           "(d) Aktien-Video wurde in Stufe A verworfen", fehler)

    # ---------------- generiere_skripte (für Fall a) ----------------
    if a:
        log.info("=== LIVE-TEST generiere_skripte für Fall (a) ===")
        try:
            skript_liste = skripte.generiere_skripte(a, gelernt={})
        except Exception as fehler_skript:
            skript_liste = []
            pruefe(False, "(a) Skript-Generierung ohne Exception (" + str(fehler_skript) + ")",
                   fehler)
        if skript_liste:
            pruefe(len(skript_liste) == 3, "(a) genau 3 Skript-Varianten", fehler)
            typen = [s["hook_typ"] for s in skript_liste]
            pruefe(typen == ["o_ton_konter", "frage_hook", "empoerungs_hook"],
                   "(a) Hook-Typen in Kontrakt-Reihenfolge (ist: " + ", ".join(typen) + ")",
                   fehler)
            for s in skript_liste:
                woerter = len(s["inhalt_md"].split())
                pruefe(210 <= woerter <= 480,
                       "(a) Variante " + str(s["variante"]) + " Wortzahl ok (" +
                       str(woerter) + ")", fehler)
                pruefe(all(marke in s["inhalt_md"] for marke in
                           ["HOOK", "O-TON", "WIDERLEGUNG", "EINORDNUNG", "CTA"]),
                       "(a) Variante " + str(s["variante"]) + " hat alle 5 Struktur-Blöcke",
                       fehler)
            q = skript_liste[0]["quellen"]
            pruefe(2 <= len(q) <= 4 or
                   (len(q) < 2 and "Quellen manuell prüfen" in skript_liste[0]["inhalt_md"]),
                   "(a) 2-4 Grounding-Quellen ODER leere Quellen + Hinweis (ist: " +
                   str(len(q)) + ")", fehler)
            for eintrag in q:
                pruefe(eintrag["url"].startswith("http"),
                       "(a) Quellen-URL echt aus Grounding: " + eintrag["url"][:80], fehler)
            log.info("--- GENERIERTES SKRIPT (Variante 1, o_ton_konter) ---")
            for zeile in skript_liste[0]["inhalt_md"].splitlines():
                log.info("  %s", zeile)
            log.info("--- QUELLEN: %s", "; ".join(e["url"] for e in q) or "(leer)")

    # ---------------- lerne_aus_feedback (Bonus e) ----------------
    log.info("=== LIVE-TEST lerne_aus_feedback ===")
    feedback_videos = [
        {"claim": {"thema": "suessstoffe"},
         "feedback": [
             {"aktion": "angenommen", "kommentar": "Genau sowas — großer Account, klarer Quatsch.",
              "zeit": _iso_vor_tagen(1)},
             {"aktion": "angenommen", "kommentar": None, "zeit": _iso_vor_tagen(1)},
         ]},
        {"claim": {"thema": "abnehmspritze"},
         "feedback": [
             {"aktion": "abgelehnt", "kommentar": "Thema langweilt mich, zu wenig Reichweite.",
              "zeit": _iso_vor_tagen(2)},
         ]},
    ]
    gelernt = analyse.lerne_aus_feedback(feedback_videos)
    pruefe(gelernt["themen_boost"].get("suessstoffe") == 0.5,
           "(e) Boost suessstoffe == +0.5 (ist: " +
           str(gelernt["themen_boost"].get("suessstoffe")) + ")", fehler)
    pruefe(gelernt["themen_boost"].get("abnehmspritze") == -0.25,
           "(e) Boost abnehmspritze == -0.25 (ist: " +
           str(gelernt["themen_boost"].get("abnehmspritze")) + ")", fehler)
    pruefe(1 <= len(gelernt["notizen"]) <= 3,
           "(e) 1-3 Gemini-Notizen erzeugt (ist: " + str(len(gelernt["notizen"])) + ")", fehler)
    for notiz in gelernt["notizen"]:
        log.info("(e) Notiz: %s", notiz)

    # ---------------- Fazit ----------------
    log.info("=" * 60)
    if fehler:
        log.error("TEST FEHLGESCHLAGEN — %d Erwartung(en) nicht erfüllt:", len(fehler))
        for f in fehler:
            log.error("  - %s", f)
        return 1
    log.info("ALLE ERWARTUNGEN ERFÜLLT — Pipeline live getestet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
