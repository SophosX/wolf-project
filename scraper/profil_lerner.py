# -*- coding: utf-8 -*-
"""
profil_lerner.py — Das lebende Trigger-Profil (Multi-Tenant Phase 5).

"Was dich erfahrungsgemäß triggert" ist keine gebackene Liste mehr, sondern
lernt aus dem Verhalten des Nutzers weiter:

  Schnelle Schleife (App, sofort): POST /api/feedback -> themen_boost/notizen.
  Langsame Schleife (HIER, täglich 03:00): liest angenommen/abgelehnt +
  Kommentare + Themen-/Personen-Engagement aus video_zuordnung und lässt
  Gemini die Trigger-Liste in radar_profile.reaktions_ausloeser UMSCHREIBEN
  (verstärken/abschwächen/neu/streichen — jeweils mit Video-Belegen).

Regeln:
  - Zerfall: staerke × 0.95 pro Woche ohne Verstärkung; < 0.2 wird gestrichen.
  - quelle='interview'-Einträge werden NIE automatisch gestrichen (der Nutzer
    hat sie explizit bestätigt) — nur ihre Stärke bewegt sich.
  - Läuft nur für Nutzer mit NEUEM Feedback seit dem letzten Lerner-Lauf.

CLI: python3 profil_lerner.py --alle | --user <uuid>
"""

import argparse
import datetime
import json
import os
import sys
import time

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import analyse
import speicher

MAX_TRIGGER = 15
ZERFALL_PRO_WOCHE = 0.95
STREICH_SCHWELLE = 0.2

_SCHEMA_LERNER = {
    "type": "OBJECT",
    "properties": {
        "trigger": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "trigger": {"type": "STRING"},
            "staerke": {"type": "NUMBER", "description": "0-1"},
            "belege": {"type": "ARRAY", "items": {"type": "STRING"},
                       "description": "video_ids aus dem Feedback, die den Trigger stuetzen"},
        }, "required": ["trigger", "staerke"]}},
        "themen_vorschlaege": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "slug": {"type": "STRING"}, "name": {"type": "STRING"},
            "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
            "begruendung": {"type": "STRING"}},
            "required": ["slug", "name", "keywords"]},
            "description": "max. 2 NEUE Themen, die das Feedback nahelegt (nur bei klarem Muster)"},
        "query_vorschlaege": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "plattform": {"type": "STRING", "enum": ["youtube", "tiktok", "instagram"]},
            "query": {"type": "STRING"}},
            "required": ["plattform", "query"]},
            "description": "max. 3 claim-formulierte Suchanfragen zu Luecken, die das Feedback zeigt"},
    },
    "required": ["trigger"],
}

_SYSTEM_LERNER = """Du pflegst die Trigger-Liste eines Creators in seinem Debunk-Radar:
'Was dich erfahrungsgemäß triggert'. Du bekommst (a) die AKTUELLE Liste und (b) sein
FRISCHES Feedback (angenommene/abgelehnte Videos mit Thema, Kanal, Aussage, Kommentaren).

Schreibe die Liste um:
- VERSTÄRKE Trigger, die durch angenommene Videos bestätigt werden (staerke moderat rauf,
  video_ids in belege aufnehmen).
- SCHWÄCHE Trigger, deren Videos wiederholt abgelehnt wurden.
- ERGÄNZE neue Trigger NUR bei klarem Muster (mind. 2 Belege) — kurze deutsche Sätze,
  konkret ('Angstmache vor X ohne Studienlage'), keine Dopplung bestehender Trigger.
- FORMULIERE bestehende Trigger präziser, wenn das Feedback das hergibt.
- Behalte staerke-Werte plausibel (0-1); maximal """ + str(MAX_TRIGGER) + """ Einträge,
  die stärksten zuerst. Gib die KOMPLETTE neue Liste zurück.

ZUSÄTZLICH (Vorschlags-Modus, konservativ): Wenn das Feedback KLARE Lücken zeigt
(der Nutzer nimmt wiederholt Videos zu einem Thema an, das seine Themen-Liste
nicht abdeckt), schlage maximal 2 neue Themen (slug snake_case, 4-8 deutsche
Keywords) und maximal 3 claim-formulierte Suchanfragen vor. Diese werden dem
Nutzer NUR VORGESCHLAGEN (er bestätigt sie in den Einstellungen) — im Zweifel
leere Listen."""


def _iso_jetzt():
    return speicher.jetzt_iso()


def _wochen_seit(iso_zeit):
    try:
        dt = datetime.datetime.fromisoformat(str(iso_zeit).replace("Z", "+00:00"))
        delta = datetime.datetime.now(datetime.timezone.utc) - dt
        return max(0.0, delta.total_seconds() / (7 * 86400))
    except (ValueError, TypeError):
        return 0.0


def _letzter_lerner_lauf(user_id):
    zeilen = speicher._supabase_get("agent_runs", {
        "select": "zeit", "user_id": "eq." + str(user_id), "typ": "eq.lerner",
        "order": "zeit.desc", "limit": "1",
    }) or []
    return zeilen[0]["zeit"] if zeilen else None


def frisches_feedback(user_id, seit_iso):
    """Entschiedene Zuordnungen mit Feedback seit dem letzten Lauf (inkl. Video-Titel)."""
    params = {
        "select": "video_id,status,thema_slug,verdict,feedback,aktualisiert_am,video:videos(titel,kanal,claim)",
        "user_id": "eq." + str(user_id),
        "status": "in.(angenommen,abgelehnt,gespeichert)",
    }
    if seit_iso:
        params["aktualisiert_am"] = "gte." + seit_iso
    return speicher._supabase_get("video_zuordnung", params) or []


def zerfall_anwenden(trigger_liste):
    """Wochen-Zerfall + Streich-Schwelle (Interview-Eintraege nie streichen)."""
    ergebnis = []
    for t in trigger_liste:
        staerke = float(t.get("staerke") or 0.5)
        wochen = _wochen_seit(t.get("aktualisiert_am") or _iso_jetzt())
        staerke *= ZERFALL_PRO_WOCHE ** wochen
        t = dict(t)
        t["staerke"] = round(max(0.0, min(1.0, staerke)), 3)
        if t["staerke"] < STREICH_SCHWELLE and t.get("quelle") != "interview":
            continue
        ergebnis.append(t)
    return ergebnis


def lerne_nutzer(user_id):
    start = time.time()
    profil = speicher.lade_profil(user_id)
    if not profil:
        return None
    aktuelle = profil.get("reaktions_ausloeser") or []
    seit = _letzter_lerner_lauf(user_id)
    feedback = frisches_feedback(user_id, seit)
    if not feedback:
        # Kein neues Feedback: nur Zerfall anwenden (still, kein LLM-Call)
        nach_zerfall = zerfall_anwenden(aktuelle)
        if len(nach_zerfall) != len(aktuelle):
            speicher.speichere_profil(user_id, {"reaktions_ausloeser": nach_zerfall})
            print("[lerner] %s: kein Feedback, Zerfall entfernte %d Trigger"
                  % (user_id, len(aktuelle) - len(nach_zerfall)))
        return None

    # Feedback kompakt fuer den Prompt aufbereiten
    zeilen = []
    for z in feedback[:60]:
        video = z.get("video") or {}
        verdict = z.get("verdict") or {}
        kommentare = [f.get("kommentar") for f in (z.get("feedback") or []) if f.get("kommentar")]
        zeilen.append({
            "video_id": z.get("video_id"),
            "entscheidung": z.get("status"),
            "thema": z.get("thema_slug"),
            "kanal": video.get("kanal"),
            "titel": (video.get("titel") or "")[:120],
            "aussage": ((video.get("claim") or {}).get("aussage") or "")[:180],
            "begruendung": (verdict.get("begruendung") or "")[:150],
            "kommentare": kommentare[:2],
        })

    themen_bestand = speicher.lade_themen(user_id, nur_aktive=False)
    alte_liste = zerfall_anwenden(aktuelle)
    prompt = ("BESTEHENDE THEMEN DES NUTZERS: "
              + ", ".join(t.get("slug", "?") for t in themen_bestand)
              + "\n\nAKTUELLE TRIGGER-LISTE:\n"
              + json.dumps([{"trigger": t.get("trigger"), "staerke": t.get("staerke"),
                             "quelle": t.get("quelle")} for t in alte_liste],
                           ensure_ascii=False)
              + "\n\nFRISCHES FEEDBACK:\n" + json.dumps(zeilen, ensure_ascii=False))
    try:
        daten = analyse.gemini_json(prompt, system=_SYSTEM_LERNER,
                                    schema=_SCHEMA_LERNER, temperatur=0.2)
    except Exception as e:
        print("[lerner] %s: Gemini fehlgeschlagen: %s" % (user_id, e))
        return None

    jetzt = _iso_jetzt()
    alte_nach_text = {t.get("trigger", "").strip().lower(): t for t in alte_liste}
    neue_liste = []
    for t in (daten.get("trigger") or [])[:MAX_TRIGGER]:
        text = (t.get("trigger") or "").strip()
        if not text:
            continue
        alt = alte_nach_text.get(text.lower())
        belege_alt = (alt or {}).get("belege") or []
        belege_neu = [b for b in (t.get("belege") or []) if isinstance(b, str)]
        neue_liste.append({
            "trigger": text,
            "staerke": round(max(0.0, min(1.0, float(t.get("staerke") or 0.5))), 3),
            # quelle bleibt erhalten (interview schuetzt vor Auto-Streichung);
            # neue Eintraege stammen aus dem Feedback
            "quelle": (alt or {}).get("quelle") or "feedback",
            "belege": list(dict.fromkeys(belege_alt + belege_neu))[-6:],
            "aktualisiert_am": jetzt,
        })
    # Interview-Eintraege, die Gemini gestrichen hat, wieder anfuegen (Schutzregel)
    neue_texte = {t["trigger"].strip().lower() for t in neue_liste}
    for t in alte_liste:
        if t.get("quelle") == "interview" and (t.get("trigger", "").strip().lower()
                                               not in neue_texte):
            neue_liste.append(t)
    neue_liste.sort(key=lambda t: -float(t.get("staerke") or 0))

    speicher.speichere_profil(user_id, {"reaktions_ausloeser": neue_liste[:MAX_TRIGGER + 5]})

    # --- Themen-/Query-Vorschlaege (aktiv=false — Nutzer bestaetigt in /einstellungen)
    vorhandene_slugs = {t.get("slug") for t in themen_bestand}
    themen_vorschlaege = []
    for tv in (daten.get("themen_vorschlaege") or [])[:2]:
        slug = (tv.get("slug") or "").strip().lower().replace("-", "_")[:40]
        if not slug or slug in vorhandene_slugs:
            continue
        themen_vorschlaege.append({
            "user_id": str(user_id), "slug": slug,
            "name": tv.get("name") or slug,
            "keywords": [k.lower() for k in (tv.get("keywords") or []) if k][:10],
            "kerngewicht": 0.7, "aktiv": False, "quelle": "lerner",
        })
    if themen_vorschlaege:
        speicher._supabase_post("themen", themen_vorschlaege,
                                prefer="return=minimal,resolution=ignore-duplicates")
    query_vorschlaege = [{
        "user_id": str(user_id),
        "plattform": qv.get("plattform") or "youtube",
        "query": (qv.get("query") or "").strip(),
        "aktiv": False, "quelle": "lerner",
    } for qv in (daten.get("query_vorschlaege") or [])[:3]
        if (qv.get("query") or "").strip()]
    if query_vorschlaege:
        speicher._supabase_post("suchqueries", query_vorschlaege,
                                prefer="return=minimal,resolution=ignore-duplicates")
    if themen_vorschlaege or query_vorschlaege:
        print("[lerner] %s: %d Themen- + %d Query-Vorschlaege abgelegt (aktiv=false)"
              % (user_id, len(themen_vorschlaege), len(query_vorschlaege)))

    speicher.speichere_agent_run({
        "user_id": str(user_id), "typ": "lerner", "quelle": "profil_lerner",
        "gefunden": len(feedback), "analysiert": len(alte_liste),
        "neu": len(neue_liste), "fehler": [],
        "dauer_s": int(time.time() - start),
    })
    print("[lerner] %s: %d Feedback-Events -> Trigger %d -> %d"
          % (user_id, len(feedback), len(aktuelle), len(neue_liste)))
    return len(neue_liste)


def main():
    parser = argparse.ArgumentParser(description="Wolf Radar — Profil-Lerner (Trigger-Liste)")
    parser.add_argument("--user")
    parser.add_argument("--alle", action="store_true")
    args = parser.parse_args()

    if speicher.daten_modus() != "supabase":
        print("[lerner] Nur im Supabase-Modus.")
        return 0
    if args.user:
        nutzer_ids = [args.user]
    elif args.alle:
        profile = speicher._supabase_get("profiles", {
            "select": "id", "onboarding_status": "eq.fertig", "geloescht_am": "is.null",
        }) or []
        nutzer_ids = [p["id"] for p in profile]
    else:
        parser.error("--user <uuid> oder --alle angeben")
        return 1

    for uid in nutzer_ids:
        try:
            lerne_nutzer(uid)
        except Exception as e:
            print("[lerner] FEHLER bei %s: %s" % (uid, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
