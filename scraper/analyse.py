# -*- coding: utf-8 -*-
"""
analyse.py — Gemini-Analyse-Pipeline für Wolf Radar.

Vier Stufen pro Kandidat (siehe KONTRAKT.md):
  Stufe A  Relevanz     — deutschsprachig? Ernährung/Fitness/Gesundheit? prüfbare Sachaussage?
  Stufe B  Claim        — konkreteste prüfbare Aussage wörtlich extrahieren + Thema-Slug
  Stufe C  Verdict      — konservativer Abgleich gegen Chris' belegte Positionen (Themenlandkarte)
  Stufe D  Scoring      — deterministisch in Python (Kontrakt-Formel), KEIN LLM

Öffentliche Schnittstellen:
  analysiere_batch(kandidaten: list[dict], gelernt: dict) -> list[dict]
  lerne_aus_feedback(videos: list[dict]) -> dict

Gemini-Zugriff: REST via urllib (keine Zusatz-Dependencies), Key aus ENV GEMINI_API_KEY
oder aus einer .env-Datei in einem übergeordneten Ordner. Retry mit Backoff bei 429/5xx.
Fehler werden transparent geloggt statt still verschluckt.
"""

import json
import logging
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("wolf_radar.analyse")

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Zwei Qualitätsstufen (User-Vorgabe: Verdict/Faktenbewertung auf hochwertigem Modell):
# - SCHNELL: Vorfilter/Claim-Extraktion (Stufe A/B), Feedback-Notizen — hoher Durchsatz
# - QUALITAET: Verdict (Stufe C), Skripte, Quellen-Recherche — Korrektheit vor Kosten
GEMINI_MODELL_SCHNELL = os.environ.get("RADAR_MODELL_SCHNELL", "gemini-2.5-flash")
GEMINI_MODELL_QUALITAET = os.environ.get("RADAR_MODELL_QUALITAET", "gemini-2.5-pro")
GEMINI_MODELL = GEMINI_MODELL_SCHNELL  # Rückwärtskompatibilität (Default schnell)
GEMINI_URL_VORLAGE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{modell}:generateContent"
)
MAX_VERSUCHE = 5           # Gemini-Aufrufe: Wiederholungen bei 429/5xx
BASIS_WARTEZEIT_S = 2.0    # exponentielles Backoff: 2, 4, 8, 16 …
PAUSE_ZWISCHEN_CALLS_S = 0.4
BATCH_GROESSE_STUFE_AB = 5   # Stufe A+B werden gebündelt geprüft (Kosten), Stufe C einzeln (Korrektheit)
MAX_TRANSKRIPT_ZEICHEN = 6000
MAX_CAPTION_ZEICHEN = 1500

_WISSEN_ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wissen")


# ---------------------------------------------------------------------------
# API-Key laden (ENV oder .env in übergeordneten Ordnern)
# ---------------------------------------------------------------------------

def _lies_env_datei(pfad):
    """Liest eine simple KEY=VALUE .env-Datei; ignoriert Kommentare und Müllzeilen."""
    werte = {}
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#") or "=" not in zeile:
                    continue
                schluessel, _, wert = zeile.partition("=")
                werte[schluessel.strip()] = wert.strip().strip('"').strip("'")
    except OSError as fehler:
        logger.debug(".env nicht lesbar (%s): %s", pfad, fehler)
    return werte


def lade_gemini_key():
    """GEMINI_API_KEY aus ENV oder aus einer .env-Datei bis 6 Ordner über diesem Modul."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    ordner = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        env_pfad = os.path.join(ordner, ".env")
        if os.path.isfile(env_pfad):
            key = _lies_env_datei(env_pfad).get("GEMINI_API_KEY", "").strip()
            if key:
                return key
        neuer_ordner = os.path.dirname(ordner)
        if neuer_ordner == ordner:
            break
        ordner = neuer_ordner
    raise RuntimeError(
        "GEMINI_API_KEY fehlt: weder in der Umgebung noch in einer .env-Datei gefunden."
    )


# ---------------------------------------------------------------------------
# Gemini-REST-Aufruf mit Retry/Backoff
# ---------------------------------------------------------------------------

def gemini_anfrage(prompt, system=None, schema=None, tools=None,
                   temperatur=0.2, max_versuche=MAX_VERSUCHE, modell=None):
    """
    Ein generateContent-Aufruf. Gibt das komplette Antwort-JSON (dict) zurück.
    modell: expliziter Modellname; Default GEMINI_MODELL_SCHNELL.

    prompt      : User-Text (str)
    system      : System-Instruktion (str, optional)
    schema      : responseSchema für strukturierte JSON-Ausgabe (dict, optional)
    tools       : z.B. [{"google_search": {}}] für Grounding (optional).
                  Achtung: tools und schema schließen sich bei Gemini aus.
    """
    if schema is not None and tools:
        raise ValueError("Gemini erlaubt tools (Grounding) und responseSchema nicht gleichzeitig.")

    url = GEMINI_URL_VORLAGE.format(modell=modell or GEMINI_MODELL_SCHNELL)
    koerper = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperatur},
    }
    if system:
        koerper["systemInstruction"] = {"parts": [{"text": system}]}
    if schema is not None:
        koerper["generationConfig"]["responseMimeType"] = "application/json"
        koerper["generationConfig"]["responseSchema"] = schema
    if tools:
        koerper["tools"] = tools

    daten = json.dumps(koerper).encode("utf-8")
    letzter_fehler = None

    for versuch in range(1, max_versuche + 1):
        anfrage = urllib.request.Request(
            url,
            data=daten,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": lade_gemini_key(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(anfrage, timeout=120) as antwort:
                return json.loads(antwort.read().decode("utf-8"))
        except urllib.error.HTTPError as fehler:
            rumpf = ""
            try:
                rumpf = fehler.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            letzter_fehler = "HTTP {0}: {1}".format(fehler.code, rumpf)
            if fehler.code in (429, 500, 502, 503, 504) and versuch < max_versuche:
                wartezeit = BASIS_WARTEZEIT_S * (2 ** (versuch - 1)) + random.uniform(0, 1)
                # Retry-After-Header respektieren, falls vorhanden
                retry_after = fehler.headers.get("Retry-After") if fehler.headers else None
                if retry_after:
                    try:
                        wartezeit = max(wartezeit, float(retry_after))
                    except ValueError:
                        pass
                logger.warning("Gemini %s — Versuch %d/%d, warte %.1fs",
                               letzter_fehler.split(":")[0], versuch, max_versuche, wartezeit)
                time.sleep(wartezeit)
                continue
            raise RuntimeError("Gemini-Aufruf fehlgeschlagen: " + letzter_fehler)
        except (urllib.error.URLError, TimeoutError, OSError) as fehler:
            letzter_fehler = "Netzwerkfehler: {0}".format(fehler)
            if versuch < max_versuche:
                wartezeit = BASIS_WARTEZEIT_S * (2 ** (versuch - 1))
                logger.warning("%s — Versuch %d/%d, warte %.1fs",
                               letzter_fehler, versuch, max_versuche, wartezeit)
                time.sleep(wartezeit)
                continue
            raise RuntimeError("Gemini-Aufruf fehlgeschlagen: " + letzter_fehler)

    raise RuntimeError("Gemini-Aufruf fehlgeschlagen: " + str(letzter_fehler))


def extrahiere_antwort_text(antwort):
    """Holt den Text des ersten Kandidaten aus einer generateContent-Antwort."""
    try:
        kandidaten = antwort.get("candidates") or []
        teile = kandidaten[0].get("content", {}).get("parts") or []
        texte = [t.get("text", "") for t in teile if t.get("text")]
        if not texte:
            grund = kandidaten[0].get("finishReason", "unbekannt")
            raise RuntimeError("Gemini-Antwort ohne Text (finishReason=" + str(grund) + ")")
        return "".join(texte)
    except (IndexError, KeyError, AttributeError):
        raise RuntimeError("Gemini-Antwort hat unerwartete Struktur: " + json.dumps(antwort)[:300])


def gemini_json(prompt, system=None, schema=None, temperatur=0.2, modell=None):
    """Bequemer Aufruf: strukturierte JSON-Antwort direkt als Python-Objekt."""
    antwort = gemini_anfrage(prompt, system=system, schema=schema, temperatur=temperatur,
                             modell=modell)
    text = extrahiere_antwort_text(antwort)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("Gemini lieferte kein gültiges JSON: " + text[:300])


# ---------------------------------------------------------------------------
# Themen-Katalog (aus mythen_katalog.py; robuster Fallback, weil parallel gebaut)
# ---------------------------------------------------------------------------

_FALLBACK_THEMEN = {
    "abnehmen_kalorien":        {"name": "Abnehmen & Kaloriendefizit", "kerngewicht": 1.0},
    "protein":                  {"name": "Protein & Nieren-Mythen", "kerngewicht": 1.0},
    "suessstoffe":              {"name": "Süßstoffe & Aspartam", "kerngewicht": 1.0},
    "zucker":                   {"name": "Zucker & 'Zucker ist Gift'", "kerngewicht": 0.9},
    "mahlzeiten_mythen":        {"name": "Mahlzeiten-Mythen (Frühstück, Carbs abends …)", "kerngewicht": 0.95},
    "detox_stoffwechsel":       {"name": "Detox, Entgiften, Stoffwechsel-Magie", "kerngewicht": 1.0},
    "verarbeitete_lebensmittel": {"name": "Chemophobie & verarbeitete Lebensmittel", "kerngewicht": 0.9},
    "supplements":              {"name": "Supplements & Wunder-Fatburner", "kerngewicht": 0.8},
    "training_fettabbau":       {"name": "Training-Mythen mit Ernährungsbezug", "kerngewicht": 0.8},
    "fasten":                   {"name": "Fasten & Intervallfasten", "kerngewicht": 0.85},
    "abnehmspritze":            {"name": "Abnehmspritze & Medikamente", "kerngewicht": 0.7},
    "sonstiges_ernaehrung":     {"name": "Sonstige Ernährungs-Claims", "kerngewicht": 0.6},
}
STANDARD_KERNGEWICHT = 0.7


def _normalisiere_themen(roh):
    """Bringt THEMEN aus mythen_katalog in die Form {slug: {name, kerngewicht}}."""
    themen = {}
    if isinstance(roh, dict):
        for slug, wert in roh.items():
            if isinstance(wert, dict):
                gewicht = wert.get("kerngewicht", wert.get("gewicht", STANDARD_KERNGEWICHT))
                name = wert.get("name", wert.get("titel", slug))
            elif isinstance(wert, (int, float)):
                gewicht, name = float(wert), slug
            else:
                gewicht, name = STANDARD_KERNGEWICHT, str(wert)
            themen[str(slug)] = {"name": name, "kerngewicht": float(gewicht)}
    elif isinstance(roh, (list, tuple)):
        for eintrag in roh:
            if isinstance(eintrag, dict) and eintrag.get("slug"):
                themen[str(eintrag["slug"])] = {
                    "name": eintrag.get("name", eintrag["slug"]),
                    "kerngewicht": float(eintrag.get("kerngewicht",
                                                     eintrag.get("gewicht", STANDARD_KERNGEWICHT))),
                }
    return themen


def lade_themen():
    """THEMEN aus mythen_katalog.py laden; Fallback-Katalog, wenn (noch) nicht vorhanden."""
    try:
        try:
            import mythen_katalog  # Ausführung als Skript im scraper-Ordner
        except ImportError:
            from . import mythen_katalog  # Import als Paket
        themen = _normalisiere_themen(getattr(mythen_katalog, "THEMEN", None))
        if themen:
            return themen
        logger.warning("mythen_katalog.THEMEN leer/unbekanntes Format — nutze Fallback-Themen.")
    except ImportError:
        logger.warning("mythen_katalog.py nicht gefunden — nutze Fallback-Themen.")
    except Exception as fehler:
        logger.warning("mythen_katalog nicht ladbar (%s) — nutze Fallback-Themen.", fehler)
    return dict(_FALLBACK_THEMEN)


# ---------------------------------------------------------------------------
# Wissens-Dateien: Positions-Tabelle aus der Themenlandkarte einbetten
# ---------------------------------------------------------------------------

def extrahiere_markdown_abschnitt(text, ueberschrift_prefix):
    """
    Schneidet aus Markdown den Abschnitt heraus, der mit einer Überschrift beginnt,
    die mit ueberschrift_prefix anfängt (z.B. '## 2.'), bis zur nächsten Überschrift
    gleicher oder höherer Ebene.
    """
    zeilen = text.splitlines()
    ebene = ueberschrift_prefix.split(" ")[0]  # z.B. '##'
    start = None
    for i, zeile in enumerate(zeilen):
        if zeile.strip().startswith(ueberschrift_prefix):
            start = i
            break
    if start is None:
        return ""
    ende = len(zeilen)
    for j in range(start + 1, len(zeilen)):
        gestutzt = zeilen[j].strip()
        # nächste Überschrift gleicher/höherer Ebene beendet den Abschnitt
        if gestutzt.startswith("#") and gestutzt.split(" ")[0] and len(gestutzt.split(" ")[0]) <= len(ebene):
            ende = j
            break
    return "\n".join(zeilen[start:ende]).strip()


_FALLBACK_POSITIONEN = """Kern-Positionen von Christian Wolf (Kurzform):
- Abnehmen: Kaloriendefizit plus High Protein ist die einzige Grundformel. FALSCH sind: Detox,
  'Stoffwechsel ankurbeln' durch Wunder-Lebensmittel, 'Stoffwechsel schläft ein', Fasten-Magie,
  pauschale Kalorien-Limits pro Mahlzeit, '5 kg in 5 Tagen'.
- Protein: 1,5-2 g/kg; Protein schadet gesunden Nieren nicht (eGFR/Kreatinin/Albuminurie unverändert).
- Süßstoffe: sicher und beim Abnehmen hilfreich (ADI-Logik); jede Aspartam-/Krebs-Panik ist falsch.
- Zucker: kein Gift, sondern hochkalorisch; 'die Dosis macht das Gift'; suchtÄHNLICH, nicht Sucht.
- Mahlzeiten: 'Frühstück ist die wichtigste Mahlzeit' ist ein Marketing-Mythos; Tageszeit von
  Kohlenhydraten ist egal — es zählt die Gesamtkalorienbilanz.
- Verarbeitung: an sich neutral; Zutatenlisten-Panik ist Chemophobie.
- Training: Nachbrenneffekt vernachlässigbar (~10 % ≈ 30 kcal); kein 'Fettverbrennungspuls';
  Fett wird nicht in Muskeln umgewandelt.
"""


def lade_positions_tabelle():
    """Positions-Tabelle (Abschnitt 2 der Themenlandkarte) für den Verdict-Systemprompt."""
    pfad = os.path.join(_WISSEN_ORDNER, "themenlandkarte.md")
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            text = f.read()
        abschnitt = extrahiere_markdown_abschnitt(text, "## 2.")
        if abschnitt:
            return abschnitt
        logger.warning("Positions-Tabelle (## 2.) in themenlandkarte.md nicht gefunden — Fallback.")
    except OSError as fehler:
        logger.warning("themenlandkarte.md nicht lesbar (%s) — Fallback-Positionen.", fehler)
    return _FALLBACK_POSITIONEN


# ---------------------------------------------------------------------------
# Hilfen: Video-Kontext als Prompt-Text
# ---------------------------------------------------------------------------

def _kuerze(text, max_zeichen):
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_zeichen:
        return text
    return text[:max_zeichen] + " …[gekürzt]"


def _video_kontext(video):
    """Kompakter, klar gelabelter Kontextblock für die Prompts."""
    teile = [
        "ID: " + str(video.get("id", "?")),
        "Plattform: " + str(video.get("plattform", "?")),
        "Titel: " + _kuerze(video.get("titel"), 300),
        "Kanal: " + str(video.get("kanal", "?")),
        "Views: " + str(video.get("views", "?")),
        "Caption: " + (_kuerze(video.get("caption"), MAX_CAPTION_ZEICHEN) or "(keine)"),
        "Transkript: " + (_kuerze(video.get("transkript"), MAX_TRANSKRIPT_ZEICHEN) or "(keins)"),
    ]
    return "\n".join(teile)


def _tage_seit(iso_zeit):
    """Tage seit einem ISO-Zeitstempel; None wenn nicht parsebar."""
    if not iso_zeit:
        return None
    try:
        roh = str(iso_zeit).replace("Z", "+00:00")
        zeitpunkt = datetime.fromisoformat(roh)
        if zeitpunkt.tzinfo is None:
            zeitpunkt = zeitpunkt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - zeitpunkt
        return max(delta.total_seconds() / 86400.0, 0.0)
    except (ValueError, TypeError):
        logger.debug("Zeitstempel nicht parsebar: %r", iso_zeit)
        return None


# ---------------------------------------------------------------------------
# Stufe A + B: Relevanz-Filter + Claim-Extraktion (gebündelt, mit ID-Echo)
# ---------------------------------------------------------------------------

def _schema_stufe_ab(themen_slugs):
    return {
        "type": "OBJECT",
        "properties": {
            "ergebnisse": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "STRING", "description": "exakt die übergebene Video-ID"},
                        "deutsch": {"type": "BOOLEAN"},
                        "themenbezug": {"type": "BOOLEAN",
                                        "description": "Ernährung/Fitness/Gesundheit?"},
                        "sachaussage": {"type": "BOOLEAN",
                                        "description": "prüfbare Sachaussage vorhanden (nicht bloß Meinung/Werbung/Rezept)?"},
                        "aussage": {"type": "STRING",
                                    "description": "konkreteste prüfbare Aussage, möglichst wörtlich"},
                        "thema": {"type": "STRING", "enum": themen_slugs},
                        "begruendung": {"type": "STRING"},
                    },
                    "required": ["id", "deutsch", "themenbezug", "sachaussage", "begruendung"],
                },
            }
        },
        "required": ["ergebnisse"],
    }


# Standard-Nische (Lokal-/Christian-Betrieb). Multi-Tenant: pro Nutzer aus radar_profile.nische.
STANDARD_NISCHE = "Ernährung, Abnehmen, Fitness oder Gesundheit"


def _system_stufe_ab(nische=None):
    nische = (nische or STANDARD_NISCHE).strip()
    return """Du bist der Vorfilter eines Debunk-Radars — einer App, die für Creator
Videos mit Falschinformationen aus ihrer Nische findet.

NISCHE DIESES RADARS: """ + nische + """

Prüfe JEDEN übergebenen Video-Kandidaten auf genau drei Kriterien:
1. deutsch: Ist der Inhalt (Titel/Caption/Transkript) deutschsprachig?
2. themenbezug: Geht es thematisch um die oben genannte Nische?
3. sachaussage: Enthält das Video mindestens eine KONKRETE, PRÜFBARE Sachaussage mit
   Behauptungscharakter aus dieser Nische (z. B. über die WIRKUNG von
   Ernährung/Lebensmitteln/Stoffen/Training auf Körper oder Gesundheit)?
   (NICHT ausreichend: bloße Meinung, Geschmacksurteil, reine Werbung, reines Rezept ohne
   Gesundheits-Behauptung, persönlicher Erfahrungsbericht ohne verallgemeinernde Behauptung.
   AUCH NICHT ausreichend: reine META-AUSSAGEN über Industrie, Medien, Studienlage oder
   Personen — z. B. 'die Industrie vertuscht', 'Süßstoffmafia', 'gekaufte Studien',
   'Big Pharma lügt' — ohne eine konkrete gesundheitsbezogene Behauptung dahinter.)

Wenn alle drei Kriterien erfüllt sind, zusätzlich:
- aussage: Extrahiere die KERNBEHAUPTUNG, die das Video dem Zuschauer verkauft — also das
  zentrale Versprechen/These (oft im Titel angeteasert und im Transkript ausgeführt), NICHT
  einen beiläufigen Nebensatz oder ein referiertes Studien-Detail. Beruft sich das Video auf
  eine Studie, extrahiere die SCHLUSSFOLGERUNG, die daraus fürs Publikum gezogen wird
  (z. B. 'Mit diesem Trick verlierst du gezielt Bauchfett'), nicht den Studienbericht selbst.
  WICHTIG bei Verschwörungs-/Industrie-Rahmung ('Mafia', 'vertuscht', 'will nicht, dass du
  das weißt'): Die Kernbehauptung ist IMMER die konkrete GESUNDHEITS-Behauptung, die damit
  transportiert wird (z. B. 'Süßstoffe sind gesundheitsschädlich'), NIEMALS die Meta-Aussage
  über Industrie/Medien selbst — die ist nicht wissenschaftlich prüfbar und für ein
  Richtigstellungs-Video unbrauchbar.
  EBENSO WICHTIG: Wähle NIEMALS einen wahren TEILMECHANISMUS als Kernbehauptung, wenn die
  dem Zuschauer verkaufte SCHLUSSFOLGERUNG darüber hinausgeht. Beispiel: Video erklärt
  korrekt 'Insulin hemmt den Fettabbau' und verkauft daraus 'Nur wer seinen Insulinspiegel
  senkt, kann Fett verlieren' → Kernbehauptung ist die verkaufte Schlussfolgerung
  (inklusive des Programms/Versprechens, z. B. '50 % Fett in 60 Tagen'), nicht der Mechanismus.
  Möglichst wörtlich (Zitat vor Paraphrase), als VOLLSTÄNDIGER Satz von maximal ~220 Zeichen —
  niemals mitten im Wort oder Satz abschneiden.
- thema: Ordne die Aussage dem passendsten Themen-Slug aus der erlaubten Liste zu.

Wichtig: In diesem Schritt NICHT bewerten, ob die Aussage wahr oder falsch ist —
auch Aufklärungs-/Debunk-Videos haben eine prüfbare Sachaussage und passieren diesen Filter.
Gib für jede übergebene ID GENAU EIN Ergebnis zurück und übernimm die ID unverändert."""


def _stufe_ab_batch(kandidaten, themen_slugs, nische=None):
    """Führt Stufe A+B für eine Gruppe Kandidaten in einem Gemini-Aufruf aus."""
    bloecke = []
    for video in kandidaten:
        bloecke.append("=== KANDIDAT ===\n" + _video_kontext(video))
    prompt = "\n\n".join(bloecke)
    daten = gemini_json(prompt, system=_system_stufe_ab(nische),
                        schema=_schema_stufe_ab(themen_slugs), temperatur=0.1)
    ergebnisse = {e.get("id"): e for e in daten.get("ergebnisse", [])}
    fehlend = [v.get("id") for v in kandidaten if v.get("id") not in ergebnisse]
    if fehlend:
        raise RuntimeError("Stufe A/B: keine Antwort für IDs " + ", ".join(map(str, fehlend)))
    return ergebnisse


def _stufe_ab(kandidaten, themen_slugs, nische=None):
    """
    Stufe A+B mit Batching; fällt bei Inkonsistenzen auf Einzel-Aufrufe zurück.
    Rückgabe: {video_id: ergebnis_dict}
    """
    ergebnisse = {}
    for i in range(0, len(kandidaten), BATCH_GROESSE_STUFE_AB):
        gruppe = kandidaten[i:i + BATCH_GROESSE_STUFE_AB]
        try:
            ergebnisse.update(_stufe_ab_batch(gruppe, themen_slugs, nische))
        except Exception as fehler:
            logger.warning("Stufe A/B Batch fehlgeschlagen (%s) — versuche Einzelaufrufe.", fehler)
            for video in gruppe:
                try:
                    ergebnisse.update(_stufe_ab_batch([video], themen_slugs, nische))
                except Exception as einzel_fehler:
                    logger.error("Stufe A/B endgültig fehlgeschlagen für %s: %s",
                                 video.get("id"), einzel_fehler)
        time.sleep(PAUSE_ZWISCHEN_CALLS_S)
    return ergebnisse


# ---------------------------------------------------------------------------
# Stufe C: Verdict (konservativ, gegen Chris' Positionen; Debunk-Erkennung)
# ---------------------------------------------------------------------------

_SCHEMA_VERDICT = {
    "type": "OBJECT",
    "properties": {
        "verdict": {"type": "STRING", "enum": ["klar_falsch", "strittig", "korrekt"]},
        "konfidenz": {"type": "NUMBER", "description": "0 bis 1"},
        "begruendung": {"type": "STRING", "description": "genau ein Satz"},
        "schadenspotential": {"type": "INTEGER", "description": "1 (harmlos) bis 5 (gefährlich)"},
        "ist_debunk": {"type": "BOOLEAN",
                       "description": "true, wenn das VIDEO den Mythos widerlegt statt ihn zu verbreiten"},
        "aktualitaetsabhaengig": {"type": "BOOLEAN",
                                  "description": "true, wenn die Aussage von einem aktuellen Ereignis abhängt (neue Studie, Behörden-Veröffentlichung, News), das nur mit Websuche prüfbar wäre"},
    },
    "required": ["verdict", "konfidenz", "begruendung", "schadenspotential", "ist_debunk",
                 "aktualitaetsabhaengig"],
}


def _system_verdict(positions_tabelle):
    return """Du bist der konservative Faktenprüfer eines Debunk-Radars für einen Creator,
der Falschinformationen aus seiner Nische richtigstellt. Du bewertest, ob die extrahierte
Aussage eines Videos eine klare Falschinformation ist, gegen die der Creator ein
Reaktionsvideo machen würde.

DIE BELEGTEN POSITIONEN DES CREATORS (verbindlicher Maßstab — nur was hier gedeckt ist,
darf 'klar_falsch' werden):

""" + positions_tabelle + """

Zusätzlich können im Prompt EIGENE AUSSAGEN DES CREATORS ZUM THEMA stehen (O-Ton aus seinen
Videos, per Retrieval gefunden): Nutze sie als Beleg dafür, ob und wie die Aussage von
seinen Positionen gedeckt ist — sie ersetzen aber NICHT die wissenschaftliche Prüfung.

BEWERTUNGSREGELN (streng konservativ):
1. verdict = "klar_falsch" NUR, wenn die Aussage wissenschaftlich EINDEUTIG WIDERLEGT ist
   UND von Chris' Positionen oben gedeckt wird. Im Zweifel NIE klar_falsch.
   Achtung Unterschied: 'nicht belegt' ist NICHT dasselbe wie 'widerlegt' — eine bloß
   unbelegte oder übertriebene Behauptung ist strittig, nicht klar_falsch.
2. verdict = "strittig", wenn die Evidenz gemischt/unklar ist ('kann sein, muss aber nicht').
   Insbesondere: Überlegenheits-Vergleiche von Diät-Methoden ('X ist besser als Y', z.B.
   Intervallfasten vs. klassische Diät, Low Carb vs. Low Fat) sind IMMER strittig, denn bei
   gleichem Kaloriendefizit zeigen Metaanalysen Gleichwertigkeit — die behauptete Überlegenheit
   ist weder belegt noch in jedem Kontext eindeutig widerlegt. Das gilt auch dann, wenn im Video
   zusätzlich ein fragwürdiger Mechanismus als Begründung genannt wird: Der KERN der Botschaft
   (der Methoden-Vergleich) bestimmt das Verdict.
3. verdict = "korrekt", wenn die Aussage wissenschaftlich haltbar ist.
KALIBRIER-BEISPIELE:
- 'Kohlenhydrate nach 18 Uhr machen dick, weil der Stoffwechsel abends schläft'
  → klar_falsch (Mechanismus eindeutig widerlegt; nur die Gesamtkalorienbilanz zählt).
- 'Süßstoffe verursachen Krebs' → klar_falsch (EFSA/ADI-Datenlage eindeutig).
- 'Intervallfasten ist besser als jede normale Diät' → strittig (Methoden-Vergleich;
  Metaanalysen zeigen bei gleichem Defizit ähnliche Ergebnisse).
- 'Frühstück auslassen ist ungesund' → strittig (Evidenz gemischt).
3b. STUDIEN-REFERENZEN: Beruft sich das Video auf eine konkrete Studie, bewerte die dem
   Zuschauer VERKAUFTE SCHLUSSFOLGERUNG, nicht die Existenz der Studie. Ist die Schlussfolgerung
   durch etablierten Konsens klar widerlegt (z. B. gezielte lokale Fettverbrennung /
   'Spot Reduction', 'Fett wird zu Muskeln'), darf sie klar_falsch sein — setze die konfidenz
   dann aber auf höchstens 0.85, weil die referenzierte Studie selbst nicht vorliegt und
   geprüft werden kann. Ein korrektes Studien-Referat ohne eigene irreführende
   Schlussfolgerung ist "korrekt".
3c. AKTUALITÄTS-REGEL (kritisch): Dein Wissen ist NICHT tagesaktuell. Wenn die Aussage von
   einem aktuellen Ereignis abhängt — eine neue Studie, eine frische Behörden-Veröffentlichung
   (EFSA/BfR/WHO), eine News-Meldung ('hat sich heute geäußert', 'neue Bewertung erschienen') —
   kannst du sie aus dem Gedächtnis WEDER bestätigen noch widerlegen. Setze dann
   aktualitaetsabhaengig = true und NIEMALS verdict = "klar_falsch" (höchstens strittig).
   Solche Fälle klärt der Faktencheck mit Websuche, nicht du.
3d. META-AUSSAGEN: Ist die zu bewertende Aussage selbst eine Meta-/Verschwörungsaussage
   über Industrie, Medien oder Personen ('es gibt eine Süßstoffmafia', 'Studien sind gekauft')
   statt einer konkreten Gesundheitsbehauptung, dann ist sie wissenschaftlich nicht sauber
   prüfbar: verdict = "strittig" und begruendung nennt die konkrete Gesundheitsbehauptung,
   die stattdessen geprüft werden müsste. NIE klar_falsch für Meta-Aussagen.
4. DEBUNK-ERKENNUNG (sehr wichtig): Wenn das VIDEO den Mythos WIDERLEGT oder aufklärt
   (typisch: seriöse Medien/Wissenschafts-Formate, Fragezeichen-Titel mit aufklärendem Inhalt,
   Formulierungen wie 'stimmt das wirklich?', 'die Studienlage zeigt aber …'), dann verbreitet
   es KEINE Falschinformation: setze ist_debunk = true und verdict = "korrekt" — auch wenn der
   Titel den Mythos wörtlich zitiert. Beurteile die POSITION DES VIDEOS, nicht den Mythos selbst.
5. konfidenz: Wie sicher bist du im Verdict (0-1)? Sei ehrlich, nicht gefällig.
6. begruendung: GENAU EIN Satz, warum falsch/strittig/korrekt (deutsch, konkret, mit Fakt).
7. schadenspotential 1-5: 5 = akute Gesundheitsgefahr oder gefährliche Therapie-Abraten,
   4 = Gesundheitsangst ohne Grundlage oder Abnehm-Sabotage mit Kauffolgen,
   3 = typischer Abnehm-Mythos, 2 = eher harmloser Irrtum, 1 = kosmetisch."""


def _o_ton_block(aussage, narrativ_fn=None):
    """O-Ton-Passagen aus den EIGENEN Videos des Creators zum Claim (Narrativ-RAG).
    narrativ_fn: optionaler per-User-Retriever (Multi-Tenant); Default = Datei-Index
    des Lokal-Betriebs (narrativ.py). '' bei Fehlern."""
    try:
        if narrativ_fn is not None:
            return narrativ_fn(aussage) or ""
        import narrativ
        return narrativ.zitat_block(aussage, k=2)
    except Exception as fehler:
        logger.debug("Narrativ-Retrieval nicht verfügbar: %s", fehler)
        return ""


_chris_o_ton_block = _o_ton_block  # Rueckwaerts-Alias


def _stufe_c(video, aussage, positions_tabelle, o_ton=None, narrativ_fn=None):
    if o_ton is None:
        o_ton = _o_ton_block(aussage, narrativ_fn)
    prompt = (
        "VIDEO-KONTEXT:\n" + _video_kontext(video) +
        "\n\nEXTRAHIERTE AUSSAGE (zu bewerten):\n\"" + str(aussage) + "\"\n\n"
        + ((o_ton + "\n\n") if o_ton else "")
        + "Bewerte konservativ nach den Regeln im Systemprompt."
    )
    daten = gemini_json(prompt, system=_system_verdict(positions_tabelle),
                        schema=_SCHEMA_VERDICT, temperatur=0.1,
                        modell=GEMINI_MODELL_QUALITAET)
    # Werte härten
    daten["konfidenz"] = max(0.0, min(1.0, float(daten.get("konfidenz", 0.0))))
    daten["schadenspotential"] = int(max(1, min(5, int(daten.get("schadenspotential", 1)))))
    if daten.get("verdict") not in ("klar_falsch", "strittig", "korrekt"):
        raise RuntimeError("Ungültiges Verdict: " + str(daten.get("verdict")))
    # Sicherheitsnetz: Debunk kann nie klar_falsch sein
    if daten.get("ist_debunk") and daten["verdict"] == "klar_falsch":
        logger.info("Debunk-Sicherheitsnetz greift für %s — Verdict auf korrekt gesetzt.",
                    video.get("id"))
        daten["verdict"] = "korrekt"
    # Sicherheitsnetz: News-/ereignisabhängige Aussagen sind ohne Websuche nicht widerlegbar
    if daten.get("aktualitaetsabhaengig") and daten["verdict"] == "klar_falsch":
        logger.info("Aktualitäts-Sicherheitsnetz greift für %s — klar_falsch → strittig.",
                    video.get("id"))
        daten["verdict"] = "strittig"
        daten["begruendung"] = ("[Per Faktencheck mit Websuche prüfen — ereignisabhängige Aussage] "
                                + daten.get("begruendung", ""))
    return daten


# ---------------------------------------------------------------------------
# Stufe C+: Websuche-Verifikation (google_search-Grounding)
#
# Warum: Stufe C urteilt aus Modellwissen — ohne Websuche. Das hätte beinahe
# einen False-Flag produziert (EFSA-Neubewertung 02/2026, Status-Log 10).
# Deshalb wird JEDER prospektive Inbox-Fund (klar_falsch) vor der Inbox mit
# aktueller Websuche gegengeprüft; ereignisabhängige Fälle (Aktualitäts-Regel)
# werden hier aufgelöst statt pauschal vertagt. Konservative Richtung:
# Websuche kann Funde bestätigen, abschwächen oder kippen — ein Websuche-
# FEHLER ändert nichts (dann gilt das konservative Stufe-C-Urteil).
# ---------------------------------------------------------------------------

WEBCHECK_AKTIV = (os.environ.get("RADAR_WEBCHECK", "1").strip() or "1") != "0"
INBOX_KONFIDENZ = 0.75  # Schwelle klar_falsch -> inbox (Kontrakt)

_WEBCHECK_SYSTEM = """Du bist ein präziser, wissenschaftlich arbeitender Faktenchecker mit
Spezialisierung auf Ernährung, Fitness und Gesundheit. Prüfe die übergebene Aussage GRÜNDLICH
mit der Google-Suche, bevor du urteilst — verlasse dich nicht auf dein internes Wissen.
Suche gezielt nach seriösen Quellen: EFSA, DGE, BfR, WHO, Cochrane, Metaanalysen,
Fachgesellschaften. Bei ereignisbezogenen Aussagen (neue Studie, Behörden-Meldung, News):
prüfe zuerst, ob das Ereignis real ist und was die Originalquelle wirklich sagt.

BEWERTUNG (streng konservativ — im Zweifel die mildere Kategorie):
- bestaetigt_falsch : die Aussage ist wissenschaftlich eindeutig widerlegt
- stark_irrefuehrend: technisch nicht komplett falsch, aber die Botschaft führt klar in die Irre
- nuanciert         : Evidenz gemischt/kontextabhängig ('kann sein, muss aber nicht')
- korrekt           : wissenschaftlich haltbar
- unklar            : per Suche nicht sauber zu klären

ZIELGRUPPEN-REGEL für die Grenze stark_irrefuehrend vs. nuanciert: Beurteile die Botschaft
für die ZIELGRUPPE des Videos (gesunde Menschen, die abnehmen wollen). Führt sie DIE klar in
die Irre, ist es stark_irrefuehrend — auch wenn die Aussage für Randgruppen (z. B. chronisch
Kranke) einen wahren Kern hat oder ein Teilmechanismus real existiert.

Antworte EXAKT in diesem Format (drei Zeilen, deutsch, keine weiteren Zeilen):
URTEIL: bestaetigt_falsch | stark_irrefuehrend | nuanciert | korrekt | unklar
BEGRUENDUNG: <genau ein Satz mit dem entscheidenden Fakt (Zahl/Quelle), der das Urteil trägt>
EVIDENZ: <2-4 Sätze: was deine Suche konkret ergab — Studien/Behörden mit Kernergebnis>"""

_WEBCHECK_URTEILE = ("bestaetigt_falsch", "stark_irrefuehrend", "nuanciert", "korrekt", "unklar")
_WEBCHECK_URTEIL_RE = re.compile(r"URTEIL\s*:\s*\**\s*([a-zäöüß_]+)", re.IGNORECASE)


def _normalisiere_urteil(roh):
    """Modelle schreiben Urteile gern in deutscher Schreibweise ('stark_irreführend')."""
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        roh = roh.replace(a, b)
    return roh
_WEBCHECK_GRUND_RE = re.compile(r"BEGRUENDUNG\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _grounding_quellen(antwort, maximal=4):
    """Echte Quellen-Links aus den Grounding-Metadaten einer Gemini-Antwort ziehen."""
    quellen = []
    try:
        chunks = ((antwort.get("candidates") or [{}])[0]
                  .get("groundingMetadata", {}).get("groundingChunks") or [])
        for chunk in chunks:
            web = chunk.get("web") or {}
            url = web.get("uri")
            if not url or any(q["url"] == url for q in quellen):
                continue
            quellen.append({"titel": (web.get("title") or url)[:120], "url": url})
            if len(quellen) >= maximal:
                break
    except (AttributeError, TypeError, IndexError):
        pass
    return quellen


def _stufe_c_websuche_einmal(video, aussage):
    """Ein grounded Gegencheck-Aufruf. Rückgabe {urteil, begruendung, quellen} oder None."""
    prompt = (
        "VIDEO-KONTEXT:\n" + _video_kontext(video) +
        "\n\nZU PRÜFENDE AUSSAGE:\n\"" + str(aussage) + "\"\n\n"
        "Recherchiere mit der Google-Suche und antworte im vorgegebenen Drei-Zeilen-Format."
    )
    try:
        antwort = gemini_anfrage(prompt, system=_WEBCHECK_SYSTEM,
                                 tools=[{"google_search": {}}], temperatur=0.1,
                                 modell=GEMINI_MODELL_QUALITAET)
        text = extrahiere_antwort_text(antwort)
    except Exception as fehler:
        logger.warning("Stufe C+ (Websuche) fehlgeschlagen für %s: %s — Stufe-C-Urteil bleibt.",
                       video.get("id"), fehler)
        return None
    urteil_treffer = _WEBCHECK_URTEIL_RE.search(text)
    urteil = _normalisiere_urteil(urteil_treffer.group(1).lower()) if urteil_treffer else ""
    if urteil not in _WEBCHECK_URTEILE:
        logger.warning("Stufe C+ unparsebar für %s (%r) — Stufe-C-Urteil bleibt.",
                       video.get("id"), text[:120])
        return None
    grund_treffer = _WEBCHECK_GRUND_RE.search(text)
    begruendung = " ".join((grund_treffer.group(1) if grund_treffer else "").split())
    # BEGRUENDUNG endet an der EVIDENZ-Zeile (DOTALL-Regex frisst sonst alles)
    begruendung = begruendung.split("EVIDENZ:")[0].strip()[:400]
    return {"urteil": urteil, "begruendung": begruendung,
            "quellen": _grounding_quellen(antwort)}


def _stufe_c_websuche(video, aussage):
    """Grounded Gegencheck mit Quellen-Garantie-Versuch: Flag-würdige Urteile
    (bestaetigt_falsch/stark_irrefuehrend) sollen mit Belegen in die Inbox —
    liefert die API keine Grounding-Chunks (kommt vor), einmal wiederholen."""
    ergebnis = _stufe_c_websuche_einmal(video, aussage)
    if (ergebnis and not ergebnis.get("quellen")
            and ergebnis.get("urteil") in ("bestaetigt_falsch", "stark_irrefuehrend")):
        logger.info("Stufe C+ %s: Urteil ohne Quellen — ein Wiederholungsversuch.",
                    video.get("id"))
        time.sleep(PAUSE_ZWISCHEN_CALLS_S)
        zweiter = _stufe_c_websuche_einmal(video, aussage)
        if zweiter and (zweiter.get("quellen") or not ergebnis):
            return zweiter
    return ergebnis


def _stufe_c_plus_anwenden(video, aussage, verdict_daten, webcheck_cache=None):
    """Websuche-Verifikation auf ein Stufe-C-Ergebnis anwenden (mutiert verdict_daten).

    Läuft nur für (a) prospektive Inbox-Funde (klar_falsch, Konfidenz über Schwelle)
    und (b) ereignisabhängige Fälle, die das Aktualitäts-Netz auf strittig gesetzt hat.

    webcheck_cache: bereits vorhandenes Websuche-Ergebnis dieses Videos
    ({urteil, begruendung, quellen}) aus dem geteilten Pool — dann kein neuer
    API-Call. Das frische Ergebnis wird unter verdict_daten['_webcheck_roh']
    zurückgegeben, damit Aufrufer es am Pool-Video cachen können.
    """
    if not WEBCHECK_AKTIV:
        return verdict_daten
    verdict = verdict_daten.get("verdict")
    konfidenz = verdict_daten.get("konfidenz", 0.0)
    aktualitaet = bool(verdict_daten.get("aktualitaetsabhaengig"))
    braucht_check = ((verdict == "klar_falsch" and konfidenz >= INBOX_KONFIDENZ)
                     or (aktualitaet and verdict != "korrekt"))
    if not braucht_check:
        # Markieren, dass die neue Pipeline lief (Neubewertungs-Auswahl bleibt idempotent)
        verdict_daten["websuche"] = "uebersprungen"
        return verdict_daten

    if webcheck_cache and webcheck_cache.get("urteil") in _WEBCHECK_URTEILE:
        ergebnis = webcheck_cache
        logger.info("Stufe C+ %s: Webcheck aus Pool-Cache übernommen (%s).",
                    video.get("id"), ergebnis["urteil"])
    else:
        ergebnis = _stufe_c_websuche(video, aussage)
        time.sleep(PAUSE_ZWISCHEN_CALLS_S)
        if ergebnis is not None:
            verdict_daten["_webcheck_roh"] = ergebnis
    if ergebnis is None:
        verdict_daten["websuche"] = "fehlgeschlagen"
        return verdict_daten

    urteil, grund = ergebnis["urteil"], ergebnis["begruendung"]
    verdict_daten["websuche"] = urteil
    verdict_daten["websuche_quellen"] = ergebnis.get("quellen") or []
    logger.info("Stufe C+ %s: %s → %s — %s", video.get("id"), verdict, urteil, grund)

    if urteil == "bestaetigt_falsch":
        verdict_daten["verdict"] = "klar_falsch"
        verdict_daten["konfidenz"] = max(konfidenz, 0.85)
        if grund:
            verdict_daten["begruendung"] = grund + " (per Websuche bestätigt)"
    elif urteil == "stark_irrefuehrend":
        # Nach Chris' Faktenchecker-Briefing reaktionswürdig — aber mit moderater Konfidenz
        verdict_daten["verdict"] = "klar_falsch"
        verdict_daten["konfidenz"] = max(INBOX_KONFIDENZ + 0.03,
                                         min(konfidenz, 0.85)) if konfidenz else 0.78
        verdict_daten["begruendung"] = ("[Websuche: stark irreführend] "
                                        + (grund or verdict_daten.get("begruendung", "")))
    elif urteil == "nuanciert":
        verdict_daten["verdict"] = "strittig"
        verdict_daten["begruendung"] = ("[Websuche: Evidenz nuanciert] "
                                        + (grund or verdict_daten.get("begruendung", "")))
    elif urteil == "korrekt":
        verdict_daten["verdict"] = "korrekt"
        if grund:
            verdict_daten["begruendung"] = grund + " (per Websuche geprüft)"
    else:  # unklar — konservativ: nicht in die Inbox
        verdict_daten["verdict"] = "strittig"
        verdict_daten["begruendung"] = ("[Websuche ohne klares Ergebnis] "
                                        + (grund or verdict_daten.get("begruendung", "")))
    return verdict_daten


# ---------------------------------------------------------------------------
# Stufe D: Scoring — deterministisch nach Kontrakt-Formel
# ---------------------------------------------------------------------------

def _reichweite_score(video):
    """log-skaliert: 100k Views ≈ 85, 1M ≈ 100; plus Velocity-Bonus (Views/Tag).
    Instagram-Foto-Posts ohne Views: Likes×12 als Reichweiten-Proxy."""
    views = float(video.get("views") or 0)
    if not views and video.get("plattform") == "instagram":
        views = float(video.get("likes") or 0) * 12.0
    follower = float(video.get("kanal_follower") or 0)
    basis = max(views, follower / 10.0)
    punkte = 15.0 * math.log10(basis) + 10.0 if basis >= 1 else 0.0
    tage = _tage_seit(video.get("veroeffentlicht"))
    velocity = views / max(tage or 14.0, 1.0)
    bonus = min(15.0, 3.0 * math.log10(velocity + 1.0)) if velocity > 0 else 0.0
    return int(round(max(0.0, min(100.0, punkte + bonus))))


def _relevanz_score(thema_slug, konfidenz, schadenspotential, gelernt, themen):
    """kerngewicht*100 × konfidenz × (0.6+0.08*schaden) × (1+0.3*themen_boost)."""
    kerngewicht = themen.get(thema_slug, {}).get("kerngewicht", STANDARD_KERNGEWICHT)
    boost_roh = ((gelernt or {}).get("themen_boost") or {}).get(thema_slug, 0.0)
    try:
        boost = max(-1.0, min(1.0, float(boost_roh)))
    except (TypeError, ValueError):
        boost = 0.0
    wert = (kerngewicht * 100.0) * konfidenz * (0.6 + 0.08 * schadenspotential) * (1.0 + 0.3 * boost)
    return int(round(max(0.0, min(100.0, wert))))


def _tauglichkeit_score(video):
    """Kurzformat<90s +25, Watchlist +30, <14 Tage alt +25, Transkript vorhanden +20."""
    punkte = 0
    dauer = video.get("dauer_s")
    if dauer and 0 < float(dauer) < 90:
        punkte += 25
    if video.get("quelle") == "watchlist":
        punkte += 30
    tage = _tage_seit(video.get("veroeffentlicht"))
    if tage is not None and tage < 14:
        punkte += 25
    if video.get("transkript"):
        punkte += 20
    return min(punkte, 100)


_WISSENSBASIS_CACHE = None


def lade_wissensbasis():
    """Wissensbasis (aus Chris' Reaktions-Historie extrahiert) — optional, gecacht."""
    global _WISSENSBASIS_CACHE
    if _WISSENSBASIS_CACHE is None:
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wissen", "wissensbasis.json")
        try:
            with open(pfad, encoding="utf-8") as f:
                _WISSENSBASIS_CACHE = json.load(f)
            logger.info("Wissensbasis geladen: %d Personen, %d Interessen-Themen.",
                        len(_WISSENSBASIS_CACHE.get("personen", [])),
                        len(_WISSENSBASIS_CACHE.get("interessen_profil", {})))
        except (OSError, ValueError):
            _WISSENSBASIS_CACHE = {}
    return _WISSENSBASIS_CACHE


# Mythen-Katalog-Slugs -> Interessen-Profil-Slugs der Wissensbasis (Reaktions-Historie).
# Nicht gemappte Slugs bleiben neutral (Faktor 1.0).
_INTERESSEN_ALIAS = {
    "protein_allgemein": "protein",
    "protein_niere": "protein",
    "clean_eating_chemie": "verarbeitete_lebensmittel",
    "light_produkte": "verarbeitete_lebensmittel",
    "detox_kuren": "heilsversprechen_angstmache",
    "fasten_magie": "heilsversprechen_angstmache",
    "crash_diaeten": "heilsversprechen_angstmache",
    "stoffwechsel_mythen": "ernaehrungs_mythen",
    "fruehstuecksmythos": "ernaehrungs_mythen",
    "kohlenhydrate_abends": "ernaehrungs_mythen",
    "mahlzeiten_regeln": "ernaehrungs_mythen",
    "kaloriendefizit": "ernaehrungs_mythen",
    "vollkorn_dogma": "ernaehrungs_mythen",
    "honig_datteln_zucker": "zucker",
    "saefte_fluessige_kalorien": "zucker",
    "training_fettabbau_mythen": "training_mythen",
    "uebergewicht_disziplin": "body_positivity",
}


def _wissensbasis_boni(video, thema_slug, wissensbasis=None):
    """(interessen_faktor, personen_bonus): Passt das Video zur Reaktions-Historie des Creators?
    - interessen_faktor 0.9-1.25: Thema, auf das er nachweislich oft reagiert, rankt hoeher
    - personen_bonus 0-30: Absender ist eine Person, auf die er schon reagiert hat
    wissensbasis: per-User-Dict (Multi-Tenant); Default = Datei des Lokal-Betriebs."""
    wb = wissensbasis if wissensbasis is not None else lade_wissensbasis()
    profil = wb.get("interessen_profil") or {}
    interesse = profil.get(thema_slug)
    if interesse is None:
        interesse = profil.get(_INTERESSEN_ALIAS.get(thema_slug, ""))
    interessen_faktor = 1.0 if interesse is None else 0.9 + 0.35 * float(interesse)

    personen_bonus = 0
    kanal = ((video.get("kanal") or "") + " " + (video.get("kanal_id") or "")).lower()
    if kanal.strip():
        for person in wb.get("personen", []):
            # Namens-Kern ohne Klammer-Zusatz ("Coach Aaron (Rohgang)" -> "coach aaron")
            kandidaten_namen = []
            name_kern = (person.get("name") or "").split("(")[0].strip().lower()
            if name_kern:
                kandidaten_namen.append(name_kern)
            kandidaten_namen += [h.lower() for h in (person.get("handles") or {}).values() if h]
            if any(n and n in kanal for n in kandidaten_namen):
                personen_bonus = min(30, 6 * int(person.get("prioritaet", 1)))
                break
    return interessen_faktor, personen_bonus


def berechne_scores(video, verdict_daten, thema_slug, gelernt, themen, wissensbasis=None):
    """Stufe D komplett: Teil-Scores + Gesamt-Score nach Kontrakt (0.4/0.4/0.2).
    Wissensbasis-Einfluss: Interessen-Profil skaliert die Relevanz, Reaktions-Historie
    des Absenders erhoeht die Tauglichkeit (wie ein Watchlist-Treffer)."""
    interessen_faktor, personen_bonus = _wissensbasis_boni(video, thema_slug, wissensbasis)
    reichweite = _reichweite_score(video)
    relevanz = _relevanz_score(thema_slug, verdict_daten["konfidenz"],
                               verdict_daten["schadenspotential"], gelernt, themen)
    relevanz = int(max(0, min(100, round(relevanz * interessen_faktor))))
    tauglichkeit = int(max(0, min(100, _tauglichkeit_score(video) + personen_bonus)))
    gesamt = int(round(0.4 * reichweite + 0.4 * relevanz + 0.2 * tauglichkeit))
    return gesamt, {"reichweite": reichweite, "relevanz": relevanz, "tauglichkeit": tauglichkeit}


# ---------------------------------------------------------------------------
# Öffentlich: analysiere_batch
# ---------------------------------------------------------------------------

def _markiere_verworfen(video, verdict, begruendung, aussage=None, thema=None, ist_debunk=False,
                        websuche=None, quellen=None):
    """Verworfene Kandidaten IN PLACE annotieren (status=archiv + konkreter Grund),
    damit Aufrufer sie transparent speichern können statt sie still zu verlieren."""
    video["status"] = "archiv"
    video["claim"] = {
        "aussage": aussage,
        "verdict": ("debunk" if ist_debunk else verdict),
        "konfidenz": None,
        "begruendung": begruendung,
        "thema": thema,
        "websuche": websuche,
        "quellen": quellen or [],
    }


def positionen_als_text(positionen):
    """radar_profile.positionen ([{thema, position, kurzbeleg}]) als Prompt-Text —
    Multi-Tenant-Ersatz fuer die themenlandkarte.md-Tabelle."""
    if not positionen:
        return ""
    zeilen = ["Belegte Positionen des Creators:"]
    for p in positionen:
        if not isinstance(p, dict) or not p.get("position"):
            continue
        zeile = "- %s: %s" % (p.get("thema") or "Allgemein", p["position"])
        if p.get("kurzbeleg"):
            zeile += " (Beleg: %s)" % p["kurzbeleg"]
        zeilen.append(zeile)
    return "\n".join(zeilen) if len(zeilen) > 1 else ""


def extrahiere_claims(kandidaten, themen_slugs=None, nische=None):
    """NUR Stufe A+B (mandantenneutral) — fuer den geteilten Akquise-Lauf.
    Annotiert Kandidaten in place mit video['claim'] = {aussage, thema, ...} bzw.
    verwirft sie (claim.verdict='aussortiert'). Rueckgabe: Liste der Kandidaten
    MIT extrahierter Aussage (Verdict/Score kommen erst in der per-User-Kuration)."""
    if not kandidaten:
        return []
    if themen_slugs is None:
        themen_slugs = sorted(lade_themen().keys())
    ab_ergebnisse = _stufe_ab(kandidaten, themen_slugs, nische)
    mit_claim = []
    for video in kandidaten:
        vid = video.get("id")
        e = ab_ergebnisse.get(vid)
        if e is None:
            continue  # API-Fehler: naechster Lauf versucht erneut
        if not (e.get("deutsch") and e.get("themenbezug") and e.get("sachaussage")):
            _markiere_verworfen(video, "aussortiert",
                                e.get("begruendung") or "Kein Themenbezug oder keine prüfbare Sachaussage.")
            continue
        aussage = (e.get("aussage") or "").strip()
        if not aussage:
            _markiere_verworfen(video, "aussortiert", "Keine konkrete prüfbare Aussage extrahierbar.")
            continue
        video["claim"] = {
            "aussage": aussage,
            "thema": e.get("thema"),
            "verdict": None,       # kommt erst in der per-User-Kuration
            "konfidenz": None,
            "begruendung": e.get("begruendung") or "",
        }
        mit_claim.append(video)
    return mit_claim


def bewerte_kandidat(video, aussage, thema, gelernt, themen, positions_tabelle,
                     wissensbasis=None, narrativ_fn=None, webcheck_cache=None):
    """Stufe C -> C+ -> D fuer EINEN Kandidaten gegen ein konkretes Creator-Profil.
    Rueckgabe: angereichertes Video-Dict (status inbox|strittig) ODER None, wenn die
    Aussage 'korrekt' ist (der Kandidat wird dann in place als verworfen annotiert).
    Wirft bei API-Fehlern (Aufrufer entscheidet ueber Retry)."""
    vid = video.get("id")
    o_ton = _o_ton_block(aussage, narrativ_fn)
    verdict_daten = _stufe_c(video, aussage, positions_tabelle, o_ton=o_ton)
    time.sleep(PAUSE_ZWISCHEN_CALLS_S)
    verdict_daten = _stufe_c_plus_anwenden(video, aussage, verdict_daten,
                                           webcheck_cache=webcheck_cache)

    verdict = verdict_daten["verdict"]
    konfidenz = verdict_daten["konfidenz"]
    if verdict == "korrekt":
        logger.info("Verworfen (Stufe C) %s: korrekt%s — %s", vid,
                    " (Debunk)" if verdict_daten.get("ist_debunk") else "",
                    verdict_daten.get("begruendung", ""))
        _markiere_verworfen(video, "korrekt",
                            verdict_daten.get("begruendung", "Aussage ist wissenschaftlich haltbar."),
                            aussage=aussage, thema=thema,
                            ist_debunk=bool(verdict_daten.get("ist_debunk")),
                            websuche=verdict_daten.get("websuche") or "uebersprungen",
                            quellen=verdict_daten.get("websuche_quellen"))
        if verdict_daten.get("_webcheck_roh"):
            video["_webcheck_roh"] = verdict_daten["_webcheck_roh"]
        return None

    # Konservativ OHNE Transkript: Bei TikTok/Instagram ohne Transkript kennt die
    # KI nur Titel + (oft Clickbait-)Caption — das reicht NICHT fuer ein bestaetigtes
    # "klar_falsch" in der Inbox.
    kein_transkript = not (video.get("transkript") or "").strip()
    kurzvideo = video.get("plattform") in ("tiktok", "instagram")
    if verdict == "klar_falsch" and konfidenz >= 0.75 and kein_transkript and kurzvideo:
        logger.info("%s: klar_falsch, aber ohne Transkript (nur Titel/Caption) "
                    "→ strittig (konservativ).", vid)
        verdict = "strittig"
        konfidenz = min(konfidenz, 0.74)
        verdict_daten["begruendung"] = (
            "[ohne Transkript – nur nach Titel/Caption bewertet] "
            + verdict_daten.get("begruendung", ""))

    # Status nach Kontrakt: klar_falsch + Konfidenz >= 0.75 → inbox; sonst strittig
    if verdict == "klar_falsch" and konfidenz >= 0.75:
        status = "inbox"
    else:
        if verdict == "klar_falsch":
            logger.info("%s: klar_falsch, aber Konfidenz %.2f < 0.75 → strittig (konservativ).",
                        vid, konfidenz)
            verdict = "strittig"
        status = "strittig"

    score, scores = berechne_scores(video, verdict_daten, thema, gelernt, themen,
                                    wissensbasis=wissensbasis)

    angereichert = dict(video)
    angereichert["status"] = status
    angereichert["score"] = score
    angereichert["scores"] = scores
    angereichert["claim"] = {
        "aussage": aussage,
        "verdict": verdict,
        "konfidenz": round(konfidenz, 2),
        "begruendung": verdict_daten["begruendung"],
        "thema": thema,
        "websuche": verdict_daten.get("websuche"),
        "quellen": verdict_daten.get("websuche_quellen") or [],
    }
    if verdict_daten.get("_webcheck_roh"):
        angereichert["_webcheck_roh"] = verdict_daten["_webcheck_roh"]
    logger.info("Behalten %s: %s (%.2f) → status=%s score=%d thema=%s",
                vid, verdict, konfidenz, status, score, thema)
    return angereichert


def analysiere_batch(kandidaten, gelernt, profil=None):
    """
    Analysiert Kandidaten-Videos in vier Stufen. Gibt NUR die Überlebenden zurück —
    angereichert um claim, score, scores und status (inbox | strittig).

    kandidaten: Liste von video-dicts nach Kontrakt (mind. id, titel; caption/transkript optional)
    gelernt   : einstellungen.gelernt ({"themen_boost": {...}, "notizen": [...]}) oder {}
    profil    : optionales Creator-Profil (Multi-Tenant): {nische, positionen_text,
                themen, wissensbasis, narrativ_fn}. Ohne profil laeuft der bisherige
                Lokal-/Christian-Betrieb (mythen_katalog + wissen/-Dateien) unveraendert.
    """
    if not kandidaten:
        return []
    gelernt = gelernt or {}
    profil = profil or {}
    themen = profil.get("themen") or lade_themen()
    themen_slugs = sorted(themen.keys())
    positions_tabelle = profil.get("positionen_text") or lade_positions_tabelle()
    nische = profil.get("nische")
    wissensbasis = profil.get("wissensbasis")
    narrativ_fn = profil.get("narrativ_fn")

    logger.info("Analyse startet: %d Kandidaten, %d Themen-Slugs.",
                len(kandidaten), len(themen_slugs))

    # --- Stufe A+B ---------------------------------------------------------
    ab_ergebnisse = _stufe_ab(kandidaten, themen_slugs, nische)

    ueberlebende = []
    for video in kandidaten:
        vid = video.get("id")
        e = ab_ergebnisse.get(vid)
        if e is None:
            logger.error("Kandidat %s: keine Stufe-A/B-Antwort — wird übersprungen (nicht verworfen).", vid)
            continue
        if not (e.get("deutsch") and e.get("themenbezug") and e.get("sachaussage")):
            logger.info("Verworfen (Stufe A) %s: deutsch=%s themenbezug=%s sachaussage=%s — %s",
                        vid, e.get("deutsch"), e.get("themenbezug"), e.get("sachaussage"),
                        e.get("begruendung", ""))
            _markiere_verworfen(video, "aussortiert",
                                e.get("begruendung") or "Kein Themenbezug oder keine prüfbare Sachaussage.")
            continue
        aussage = (e.get("aussage") or "").strip()
        if not aussage:
            logger.info("Verworfen (Stufe B) %s: keine konkrete Aussage extrahierbar.", vid)
            _markiere_verworfen(video, "aussortiert", "Keine konkrete prüfbare Aussage extrahierbar.")
            continue
        thema = e.get("thema") if e.get("thema") in themen else "sonstiges_ernaehrung"
        ueberlebende.append((video, aussage, thema))

    logger.info("Stufe A/B überstanden: %d von %d.", len(ueberlebende), len(kandidaten))

    # --- Stufe C + D --------------------------------------------------------
    ergebnis_liste = []
    for video, aussage, thema in ueberlebende:
        vid = video.get("id")
        try:
            angereichert = bewerte_kandidat(video, aussage, thema, gelernt, themen,
                                            positions_tabelle, wissensbasis=wissensbasis,
                                            narrativ_fn=narrativ_fn)
        except Exception as fehler:
            logger.error("Stufe C fehlgeschlagen für %s: %s — Kandidat wird übersprungen.", vid, fehler)
            continue
        if angereichert is None:
            continue  # korrekt/Debunk — in place als verworfen annotiert
        angereichert.pop("_webcheck_roh", None)  # nur fuer den Pool-Cache relevant
        ergebnis_liste.append(angereichert)

    ergebnis_liste.sort(key=lambda v: v.get("score", 0), reverse=True)
    logger.info("Analyse fertig: %d von %d Kandidaten behalten.",
                len(ergebnis_liste), len(kandidaten))
    return ergebnis_liste


# ---------------------------------------------------------------------------
# Öffentlich: lerne_aus_feedback
# ---------------------------------------------------------------------------

_SCHEMA_NOTIZEN = {
    "type": "OBJECT",
    "properties": {
        "notizen": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "2-3 kurze Sätze, was Chris am Radar-Output mag/nicht mag",
        }
    },
    "required": ["notizen"],
}

_SYSTEM_NOTIZEN = """Du fasst Feedback-Kommentare von Christian Wolf zu seiner Falschinfo-Radar-App
zusammen. Jeder Kommentar ist markiert mit [aktion / thema-slug]. Destilliere daraus 2-3 kurze,
konkrete Merksätze auf Deutsch, die künftige Video-Auswahl und Skript-Generierung steuern
(z.B. 'Chris will größere Accounts, kleine Kanäle langweilen ihn.').
Keine Wiederholung der Rohkommentare, keine Floskeln."""

BOOST_SCHRITT = 0.25  # pro Annahme +0.25, pro Ablehnung -0.25, gedeckelt auf [-1, 1]


def lerne_aus_feedback(videos):
    """
    Aggregiert Feedback zu einstellungen.gelernt:
      themen_boost: {slug: -1..1} — plus je angenommen, minus je abgelehnt
      notizen:      2-3 Sätze via Gemini aus den Freitext-Kommentaren
    """
    zaehler = {}
    kommentare = []
    for video in videos or []:
        slug = ((video.get("claim") or {}).get("thema")) or "sonstiges_ernaehrung"
        for fb in video.get("feedback") or []:
            aktion = fb.get("aktion")
            if aktion in ("angenommen", "abgelehnt"):
                eintrag = zaehler.setdefault(slug, {"angenommen": 0, "abgelehnt": 0})
                eintrag[aktion] += 1
            kommentar = (fb.get("kommentar") or "").strip()
            if kommentar:
                kommentare.append("[" + str(aktion or "?") + " / " + slug + "] " + kommentar)

    themen_boost = {}
    for slug, z in zaehler.items():
        roh = BOOST_SCHRITT * (z["angenommen"] - z["abgelehnt"])
        themen_boost[slug] = round(max(-1.0, min(1.0, roh)), 2)

    notizen = []
    if kommentare:
        try:
            daten = gemini_json("FEEDBACK-KOMMENTARE:\n" + "\n".join(kommentare[:100]),
                                system=_SYSTEM_NOTIZEN, schema=_SCHEMA_NOTIZEN, temperatur=0.3)
            notizen = [n.strip() for n in daten.get("notizen", []) if n and n.strip()][:3]
        except Exception as fehler:
            logger.error("Notizen-Zusammenfassung fehlgeschlagen: %s — notizen bleiben leer.", fehler)

    logger.info("Feedback gelernt: %d Themen-Boosts, %d Notizen aus %d Kommentaren.",
                len(themen_boost), len(notizen), len(kommentare))
    return {"themen_boost": themen_boost, "notizen": notizen}
