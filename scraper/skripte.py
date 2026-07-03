# -*- coding: utf-8 -*-
"""
skripte.py — Skript-Generator für Wolf Radar.

generiere_skripte(video, gelernt) erzeugt DREI Reaktions-Skript-Varianten im Chris-Ton
(Kontrakt: hook_typ = o_ton_konter | frage_hook | empoerungs_hook), jeweils 250-400 Wörter
mit der Struktur HOOK → O-TON/CLAIM → WIDERLEGUNG → EINORDNUNG → CTA.

Wissen wird zur Laufzeit aus scraper/wissen/ eingebettet:
  chris_stilguide.md      — Anrede, Verbotsliste, Signature-Phrasen, Wissenschafts-Regeln, Dos&Don'ts
  reaktions_playbook.md   — Hook-Typen, Argumentationsstruktur, Eskalationsleiter, Quellen-Format

Quellen kommen aus einem separaten Gemini-Aufruf mit google_search-Grounding — es werden
NUR echte URLs aus der Grounding-Antwort übernommen (Redirects werden best effort aufgelöst).
Liefert Grounding nichts, bleiben die Quellen leer und jedes Skript erhält den Hinweis
'Quellen manuell prüfen'.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request

try:
    import analyse  # Ausführung als Skript im scraper-Ordner
except ImportError:
    from . import analyse  # Import als Paket

logger = logging.getLogger("wolf_radar.skripte")

_WISSEN_ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wissen")

HOOK_TYPEN = ["o_ton_konter", "frage_hook", "empoerungs_hook"]

HOOK_BESCHREIBUNGEN = {
    "o_ton_konter": (
        "O-Ton-Konter: Das Skript startet mitten in Chris' stärkster Reaktion auf das "
        "eingeblendete Original-Zitat (Cold Open, Playbook-Hook Typ 1) — erst reagieren, "
        "dann Setup."
    ),
    "frage_hook": (
        "Frage-Hook: Das Skript startet mit einer direkten, provokanten Frage an die Zuschauer "
        "('Kennst du die Leute, die sowas sagen wie …?'), die den Mythos aufspannt."
    ),
    "empoerungs_hook": (
        "Empörungs-Hook: Das Skript startet mit Chris' Fassungslosigkeit über die Aussage "
        "('ich komme einfach nicht drauf klar, dass …'), Temperatur hoch, aber Spott gilt "
        "der Aussage — nie der Community."
    ),
}

MIN_WOERTER = 250
MAX_WOERTER = 400
# Toleranz für die Validierung (LLM-Wortzählung ist nie exakt)
MIN_WOERTER_HART = 210
MAX_WOERTER_HART = 480

MAX_QUELLEN = 4
QUELLEN_HINWEIS = (
    "\n\n---\n*Hinweis: Die automatische Quellensuche lieferte keine belastbaren Treffer — "
    "Quellen bitte manuell prüfen.*"
)


# ---------------------------------------------------------------------------
# Wissens-Abschnitte einbetten (Kernabschnitte statt Volltext — fokussierter Prompt)
# ---------------------------------------------------------------------------

_FALLBACK_STIL = """Chris-Ton in Kürze: nahbarer Ex-Betroffener ('ich war der dicke Junge') mit
wissenschaftlichem Anspruch; Du/Ihr/Wir-Wechsel; Fachbegriff und Slang nebeneinander, Fachbegriff
sofort übersetzt; Zahlen und Jahres-Hochrechnungen als Beweis; Signature-Phrasen: 'die Dosis macht
das Gift', 'Kaloriendefizit plus High Protein', 'es gibt keine Grundlage dafür', 'das ist Quatsch',
'am Ende ist die Welt in Ordnung'. VERBOTEN: 'Sünde/sündigen', 'Superfood', 'Detox', 'Clean Eating',
'verbotene/schlechte Lebensmittel' (stattdessen 'hochkalorische Lebensmittel'), Willenskraft-Appelle,
Crash-Diät-Vokabular, natürlich=gesund-Framing, formale Studien-Zitationen im Fließtext."""

_FALLBACK_PLAYBOOK = """Reaktions-Aufbau: Hook (erste 20 s klären Thema + Zuschauer-Gewinn) →
Zitat-Block (O-Ton wörtlich, nie paraphrasieren) → Widerlegung (nachrechenbare Rechnung, Evidenz-
Verdichtung mit Zahlenbereichen, konservative Zeugen: 'selbst die DGE sagt …') → Fairness-Anker
(zugestehen, was stimmt) → Zuschauer-Ableitung ('was heißt das für dich') → Schluss-CTA.
Standard-Ton: sachliche Richtigstellung (Eskalationsstufe 0-1), KEINE Abrechnung."""


def _lade_abschnitte(dateiname, prefixe, fallback):
    """Lädt gezielte Markdown-Abschnitte aus einer Wissens-Datei; Fallback bei Fehlern."""
    pfad = os.path.join(_WISSEN_ORDNER, dateiname)
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as fehler:
        logger.warning("%s nicht lesbar (%s) — nutze Fallback-Wissen.", dateiname, fehler)
        return fallback
    teile = []
    for prefix in prefixe:
        abschnitt = analyse.extrahiere_markdown_abschnitt(text, prefix)
        if abschnitt:
            teile.append(abschnitt)
        else:
            logger.warning("Abschnitt '%s' in %s nicht gefunden.", prefix, dateiname)
    return "\n\n".join(teile) if teile else fallback


def _lade_stilguide_kern():
    # Anrede, Verbotsliste, Signature-Phrasen, Wissenschafts-Regeln + Dos&Don'ts-Beispielpaare
    return _lade_abschnitte(
        "chris_stilguide.md",
        ["## 1.", "### 3.5", "## 4.", "## 6.", "## 9."],
        _FALLBACK_STIL,
    )


def _lade_playbook_kern():
    # Hook-Typen, Argumentationsstruktur, Eskalationsleiter, Quellen-Baustein-Format
    return _lade_abschnitte(
        "reaktions_playbook.md",
        ["## 2.", "## 3.", "## 6.", "## 9."],
        _FALLBACK_PLAYBOOK,
    )


# ---------------------------------------------------------------------------
# Quellen via google_search-Grounding (echte URLs, Redirects aufgelöst)
# ---------------------------------------------------------------------------

class _RedirectStopper(urllib.request.HTTPRedirectHandler):
    """Verhindert automatisches Folgen — wir wollen nur den Location-Header lesen."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _loese_redirect_auf(url):
    """Löst eine Grounding-Redirect-URL zur echten Ziel-URL auf (best effort)."""
    if "vertexaisearch.cloud.google.com" not in url:
        return url
    opener = urllib.request.build_opener(_RedirectStopper)
    try:
        antwort = opener.open(url, timeout=10)
        return antwort.geturl()
    except urllib.error.HTTPError as fehler:
        ziel = fehler.headers.get("Location") if fehler.headers else None
        if ziel:
            return ziel
    except Exception as fehler:
        logger.warning("Redirect-Auflösung fehlgeschlagen (%s): %s", url[:60], fehler)
    return url


def _suche_quellen(claim_aussage, thema):
    """
    Gemini + google_search: recherchiert Gegen-Evidenz zur Falschaussage.
    Rückgabe: (recherche_text, quellen) — quellen = [{"titel": ..., "url": ...}]
    Nur URLs aus groundingChunks werden übernommen, nie aus dem Antworttext.
    """
    prompt = (
        "Recherchiere den wissenschaftlichen Stand zu dieser Ernährungs-Behauptung "
        "(Thema: " + str(thema) + "):\n\n\"" + str(claim_aussage) + "\"\n\n"
        "Ich brauche für ein Richtigstellungs-Video:\n"
        "1. Was sagt die Studienlage/Metaanalysen konkret (mit Zahlen, Dosen, Endpunkten)?\n"
        "2. Positionen seriöser Institutionen (EFSA, DGE, WHO, BfR, Fachgesellschaften).\n"
        "3. Eine nachrechenbare Beispielrechnung, falls möglich.\n"
        "Bevorzuge Metaanalysen, Behörden und Fachgesellschaften als Quellen. Antworte auf Deutsch."
    )
    try:
        antwort = analyse.gemini_anfrage(prompt, tools=[{"google_search": {}}], temperatur=0.2)
    except Exception as fehler:
        logger.error("Quellen-Grounding fehlgeschlagen: %s — Quellen bleiben leer.", fehler)
        return "", []

    try:
        recherche_text = analyse.extrahiere_antwort_text(antwort)
    except RuntimeError:
        recherche_text = ""

    kandidat = (antwort.get("candidates") or [{}])[0]
    chunks = (kandidat.get("groundingMetadata") or {}).get("groundingChunks") or []

    quellen = []
    gesehen = set()
    for chunk in chunks:
        web = chunk.get("web") or {}
        roh_url = (web.get("uri") or "").strip()
        if not roh_url:
            continue
        echte_url = _loese_redirect_auf(roh_url)
        if echte_url in gesehen:
            continue
        gesehen.add(echte_url)
        quellen.append({"titel": web.get("title") or echte_url, "url": echte_url})
        if len(quellen) >= MAX_QUELLEN:
            break

    logger.info("Grounding: %d Quellen gefunden (%d Chunks).", len(quellen), len(chunks))
    return recherche_text, quellen


# ---------------------------------------------------------------------------
# Skript-Generierung (strukturierte JSON-Ausgabe, 3 Varianten)
# ---------------------------------------------------------------------------

_SCHEMA_SKRIPTE = {
    "type": "OBJECT",
    "properties": {
        "skripte": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "hook_typ": {"type": "STRING", "enum": HOOK_TYPEN},
                    "inhalt_md": {"type": "STRING"},
                },
                "required": ["hook_typ", "inhalt_md"],
            },
        }
    },
    "required": ["skripte"],
}


def _system_skripte(gelernt):
    stil = _lade_stilguide_kern()
    playbook = _lade_playbook_kern()
    notizen = (gelernt or {}).get("notizen") or []

    teile = [
        "Du schreibst Reaktions-Skripte für den deutschen Fitness-Creator Christian Wolf "
        "(147k YouTube-Abos, Marke 'Kaloriendefizit plus High Protein'). Du schreibst "
        "AUSSCHLIESSLICH in seinem Ton — gesprochene Sprache, die vorgelesen wie Chris klingt.",
        "=== STILGUIDE (verbindlich) ===\n" + stil,
        "=== REAKTIONS-PLAYBOOK (verbindlich) ===\n" + playbook,
        "=== ESKALATIONS-REGEL FÜR DIESE SKRIPTE ===\n"
        "Standard ist die SACHLICHE RICHTIGSTELLUNG (Eskalationsstufe 0-1): Mythos/Aussage "
        "korrigieren, Person respektvoll behandeln, mindestens ein Fairness-Anker (zugestehen, "
        "was stimmt). KEINE Abrechnung, kein Vorführen der Person, keine Motiv-Unterstellungen.",
    ]
    if notizen:
        teile.append("=== GELERNTES FEEDBACK VON CHRIS (beachten!) ===\n- " + "\n- ".join(notizen))
    hook_erklaerung = "\n".join(
        "- " + typ + ": " + HOOK_BESCHREIBUNGEN[typ] for typ in HOOK_TYPEN
    )
    teile.append(
        "=== AUSGABE-REGELN ===\n"
        "Du lieferst GENAU DREI Skripte, je eines pro hook_typ:\n" + hook_erklaerung + "\n"
        "Jedes Skript ist Markdown (inhalt_md) mit GENAU diesen fünf Abschnitts-Überschriften:\n"
        "**HOOK** (1-2 Sätze, nach dem jeweiligen Hook-Typ) →\n"
        "**O-TON** (die Falschaussage als wörtliches Zitat einleiten, z.B. 'ich blende euch die "
        "Stelle mal ein') →\n"
        "**WIDERLEGUNG** (konkrete Zahlen aus der Recherche, eine nachrechenbare "
        "Dreisatz-/Jahres-Hochrechnung wo möglich, 'die Dosis macht das Gift'-artige Chris-Logik, "
        "Evidenz-Verdichtung statt formaler Zitate) →\n"
        "**EINORDNUNG** (was stattdessen gilt: Kaloriendefizit plus High Protein, konkrete "
        "Handlungsregel für die Zuschauer) →\n"
        "**CTA** (kurzer Schluss im Chris-Stil).\n"
        "Jede Abschnitts-Überschrift steht ALLEIN auf einer eigenen Zeile (z.B. '**HOOK**'), "
        "danach eine Leerzeile, dann der Text.\n"
        "Länge: 250 bis 400 Wörter pro Skript — nicht kürzer, nicht länger.\n"
        "Keine erfundenen Quellen-URLs im Text, keine formalen Zitationen, keine Emojis, "
        "keine erfundenen Jahreszahlen oder Datumsangaben."
    )
    return "\n\n".join(teile)


def _zaehle_woerter(text):
    return len([w for w in (text or "").split() if w.strip()])


def _skript_prompt(video, recherche_text):
    claim = video.get("claim") or {}
    zeilen = [
        "ZIEL-VIDEO, auf das Chris reagiert:",
        "- Plattform: " + str(video.get("plattform", "?")),
        "- Titel: " + str(video.get("titel", "?")),
        "- Kanal: " + str(video.get("kanal", "?")) +
        " (" + str(video.get("kanal_follower", "?")) + " Follower)",
        "- Views: " + str(video.get("views", "?")),
        "",
        "FALSCHAUSSAGE (wörtlich zu zitieren im O-TON-Block):",
        "\"" + str(claim.get("aussage", video.get("titel", ""))) + "\"",
        "",
        "WARUM FALSCH (Analyse-Verdict): " + str(claim.get("begruendung", "")),
        "THEMA: " + str(claim.get("thema", "")),
    ]
    if recherche_text:
        zeilen += ["", "RECHERCHE-ERGEBNIS (Zahlen hieraus verwenden, keine URLs in den Text):",
                   recherche_text[:5000]]
    else:
        zeilen += ["", "HINWEIS: Keine Recherche verfügbar — nutze nur etabliertes Konsens-Wissen "
                       "und bleib bei Zahlen konservativ."]
    zeilen += ["", "Schreibe jetzt die drei Skript-Varianten."]
    return "\n".join(zeilen)


def _validiere_skripte(daten):
    """Prüft: genau 3 Skripte, alle Hook-Typen vorhanden, Wortzahlen im Toleranzband."""
    skripte = daten.get("skripte") or []
    nach_typ = {}
    for s in skripte:
        typ = s.get("hook_typ")
        if typ in HOOK_TYPEN and typ not in nach_typ and (s.get("inhalt_md") or "").strip():
            nach_typ[typ] = s
    fehler = []
    for typ in HOOK_TYPEN:
        if typ not in nach_typ:
            fehler.append("Variante '" + typ + "' fehlt")
            continue
        woerter = _zaehle_woerter(nach_typ[typ]["inhalt_md"])
        if woerter < MIN_WOERTER_HART or woerter > MAX_WOERTER_HART:
            fehler.append("'" + typ + "' hat " + str(woerter) + " Wörter (Soll: " +
                          str(MIN_WOERTER) + "-" + str(MAX_WOERTER) + ")")
    return nach_typ, fehler


def generiere_skripte(video, gelernt):
    """
    Erzeugt drei Skript-Varianten nach Kontrakt für ein analysiertes Video.

    Rückgabe: [{"variante": 1..3, "hook_typ": ..., "inhalt_md": ..., "quellen": [...]}, ...]
    quellen: 2-4 echte URLs aus Gemini-google_search-Grounding; leer + Hinweis im Skript,
    wenn die Suche nichts Belastbares liefert.
    """
    claim = video.get("claim") or {}
    aussage = claim.get("aussage") or video.get("titel") or ""
    if not aussage:
        raise ValueError("generiere_skripte: Video hat weder claim.aussage noch titel.")

    # 1) Quellen-Recherche mit Grounding (getrennter Aufruf: tools + responseSchema
    #    schließen sich bei Gemini aus)
    recherche_text, quellen = _suche_quellen(aussage, claim.get("thema", ""))
    time.sleep(analyse.PAUSE_ZWISCHEN_CALLS_S)

    # 2) Drei Varianten strukturiert generieren, mit einem Korrektur-Versuch
    system = _system_skripte(gelernt)
    prompt = _skript_prompt(video, recherche_text)

    nach_typ, fehler = {}, ["noch kein Versuch"]
    letzte_daten = {}
    for versuch in range(1, 3):
        zusatz = ""
        if versuch > 1:
            zusatz = ("\n\nKORREKTUR (vorheriger Versuch abgelehnt: " + "; ".join(fehler) +
                      "): Liefere exakt drei Skripte, eines pro hook_typ, jeweils " +
                      str(MIN_WOERTER) + "-" + str(MAX_WOERTER) + " Wörter.")
        try:
            letzte_daten = analyse.gemini_json(prompt + zusatz, system=system,
                                               schema=_SCHEMA_SKRIPTE, temperatur=0.7)
        except Exception as fehler_aufruf:
            logger.error("Skript-Generierung Versuch %d fehlgeschlagen: %s", versuch, fehler_aufruf)
            fehler = [str(fehler_aufruf)]
            continue
        nach_typ, fehler = _validiere_skripte(letzte_daten)
        if not fehler:
            break
        logger.warning("Skript-Validierung Versuch %d: %s", versuch, "; ".join(fehler))

    if len(nach_typ) < len(HOOK_TYPEN):
        vorhanden = ", ".join(sorted(nach_typ.keys())) or "keine"
        raise RuntimeError(
            "Skript-Generierung unvollständig für " + str(video.get("id")) +
            " (vorhanden: " + vorhanden + "; Fehler: " + "; ".join(fehler) + ")"
        )
    if fehler:
        # nur noch Wortzahl-Abweichungen — durchlassen, aber transparent loggen
        logger.warning("Skripte für %s mit Wortzahl-Abweichung übernommen: %s",
                       video.get("id"), "; ".join(fehler))

    # 3) Ergebnis nach Kontrakt zusammenbauen (feste Varianten-Reihenfolge)
    ergebnis = []
    for nummer, typ in enumerate(HOOK_TYPEN, start=1):
        inhalt = nach_typ[typ]["inhalt_md"].strip()
        if len(quellen) < 2:
            inhalt += QUELLEN_HINWEIS
        ergebnis.append({
            "variante": nummer,
            "hook_typ": typ,
            "inhalt_md": inhalt,
            "quellen": list(quellen),
        })

    logger.info("Skripte für %s generiert: 3 Varianten, %d Quellen, Wortzahlen: %s",
                video.get("id"), len(quellen),
                ", ".join(str(_zaehle_woerter(s["inhalt_md"])) for s in ergebnis))
    return ergebnis
