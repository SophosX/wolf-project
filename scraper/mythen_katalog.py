# -*- coding: utf-8 -*-
"""
Wolf Radar — Mythen-Katalog
Themenwelt von Christian Wolf (abgeleitet aus wissen/themenlandkarte.md):
- THEMEN: slug -> {name, kerngewicht (0-1, wie zentral fuer Chris), keywords}
- SUCHQUERIES: deutsche YouTube-Suchqueries, die Falschinfo-Kandidaten finden
  (claim-formuliert: so wie die Falschbehauptung selbst klingt)

Wird benutzt von:
- youtube_agent.py  (SUCHQUERIES fuer die Claim-Suche)
- lauf.py           (Themen-Keyword-Vorfilter)
- analyse.py        (Kerngewicht fliesst in den Relevanz-Score)
"""

# ---------------------------------------------------------------------------
# Themen-Katalog
# kerngewicht: 1.0 = absolutes Kernthema (Chris reagiert fast sicher),
#              0.5 = Randthema (nur bei grosser Reichweite interessant)
# keywords: kleingeschrieben, werden als Substring gegen
#           titel+caption+transkript gematcht (Vorfilter + Themen-Zuordnung)
# ---------------------------------------------------------------------------

THEMEN = {
    "suessstoffe": {
        "name": "Süßstoffe & Aspartam-Panik",
        "kerngewicht": 1.0,
        "keywords": [
            "süßstoff", "suessstoff", "aspartam", "sucralose", "stevia",
            "zuckerersatz", "cola zero", "cola light", "light getränk",
            "erythrit", "xylit", "zerup", "künstliche süße", "süßungsmittel",
            "darmflora",
        ],
    },
    "kaloriendefizit": {
        "name": "Kaloriendefizit & Energiebilanz",
        "kerngewicht": 1.0,
        "keywords": [
            "kaloriendefizit", "kalorienbilanz", "energiebilanz", "kalorien zählen",
            "kalorien tracken", "abnehmen ohne kalorien", "kalorien sind egal",
            "kalorien lüge", "negative energiebilanz", "grundumsatz",
        ],
    },
    "stoffwechsel_mythen": {
        "name": "Stoffwechsel-Mythen (eingeschlafen/ankurbeln)",
        "kerngewicht": 0.9,
        "keywords": [
            "stoffwechsel ankurbeln", "stoffwechsel anregen", "stoffwechsel kaputt",
            "stoffwechsel eingeschlafen", "stoffwechsel boost", "fettverbrennung ankurbeln",
            "hungerstoffwechsel", "stoffwechsel trick", "metabolismus",
            "cortisol", "stoffwechseltyp", "hormone blockieren", "hormonbalance",
        ],
    },
    "fruehstuecksmythos": {
        "name": "Frühstücks-Mythos (wichtigste Mahlzeit)",
        "kerngewicht": 0.8,
        "keywords": [
            "frühstück wichtigste mahlzeit", "frühstück auslassen", "ohne frühstück",
            "frühstück weglassen", "nüchtern in den tag", "frühstücken abnehmen",
            "wichtigste mahlzeit des tages",
        ],
    },
    "kohlenhydrate_abends": {
        "name": "Kohlenhydrate abends / Carb-Timing",
        "kerngewicht": 0.8,
        "keywords": [
            "kohlenhydrate abends", "abends keine kohlenhydrate", "carbs am abend",
            "kohlenhydrate nach 18", "low carb abnehmen", "kohlenhydrate machen dick",
            "insulin abnehmen", "insulinspiegel abnehmen", "carb timing",
        ],
    },
    "honig_datteln_zucker": {
        "name": "Honig/Datteln/Kokosblütenzucker 'gesünder als Zucker'",
        "kerngewicht": 0.9,
        "keywords": [
            "honig gesünder", "honig statt zucker", "datteln statt zucker",
            "dattelsüße", "kokosblütenzucker", "agavendicksaft", "natürlicher zucker",
            "zucker ist gift", "zucker droge", "zuckerfrei challenge", "raffinierter zucker",
            "fruktose", "fructose", "obst macht dick",
        ],
    },
    "detox_kuren": {
        "name": "Detox, Entgiften & Leber-Kuren",
        "kerngewicht": 0.9,
        "keywords": [
            "detox", "entgiften", "entgiftung", "entschlacken", "saftkur",
            "leber entgiften", "leber entfetten", "darmreinigung", "körper reinigen",
            "giftstoffe ausleiten", "heilfasten",
        ],
    },
    "protein_niere": {
        "name": "Protein & Nieren-Angstmache",
        "kerngewicht": 0.9,
        "keywords": [
            "protein niere", "eiweiß niere", "protein schädlich", "eiweiß schädlich",
            "zu viel protein", "zu viel eiweiß", "proteinshake ungesund",
            "eiweißshake ungesund", "protein gefährlich", "kreatinin",
            "kreatin schädlich", "kreatin niere",
        ],
    },
    "protein_allgemein": {
        "name": "Protein-Mythen allgemein (Bedarf, Pulver = Chemie)",
        "kerngewicht": 0.8,
        "keywords": [
            "proteinpulver", "eiweißpulver", "proteinbedarf", "eiweißbedarf",
            "proteinshake", "whey", "proteine sind", "high protein", "eiweiß mythos",
        ],
    },
    "abnehm_wundermittel": {
        "name": "Abnehm-Wundermittel & Fatburner",
        "kerngewicht": 0.9,
        "keywords": [
            "fatburner", "abnehm trick", "abnehmtrick", "wundermittel", "fett verbrennen über nacht",
            "apfelessig abnehmen", "zitronenwasser abnehmen", "ingwer shot abnehmen",
            "abnehmtropfen", "abnehmtee", "glucomannan", "kohlenhydratblocker",
            "fettkiller", "schnell abnehmen ohne",
            "superfood", "abnehmen im schlaf", "blähbauch", "zitronenwasser",
        ],
    },
    "crash_diaeten": {
        "name": "Crash-Diäten & Radikal-Versprechen",
        "kerngewicht": 0.8,
        "keywords": [
            "crash diät", "crashdiät", "radikal abnehmen", "5 kilo in", "10 kilo in",
            "kilo in einer woche", "kilo in 2 wochen", "militär diät", "eier diät",
            "reis diät", "blitzdiät", "in 3 tagen abnehmen",
        ],
    },
    "fasten_magie": {
        "name": "Fasten-Magie (Autophagie, Intervallfasten als Wunder)",
        "kerngewicht": 0.7,
        "keywords": [
            "intervallfasten", "autophagie", "16 8", "fasten zellreinigung",
            "fasten heilt", "intermittierendes fasten", "fastenkur",
        ],
    },
    "clean_eating_chemie": {
        "name": "Clean Eating & Chemie-/Zutatenlisten-Panik",
        "kerngewicht": 0.8,
        "keywords": [
            "clean eating", "chemie im essen", "e-nummern", "zusatzstoffe gefährlich",
            "zutatenliste", "hochverarbeitet", "ultra processed", "industriezucker",
            "nichts essen was", "künstliche zusatzstoffe", "aussprechen kannst",
            "samenöl", "seed oil", "rapsöl", "sonnenblumenöl", "mikrowelle",
            "milch ungesund", "milch entzünd", "entzündungsfördernd",
        ],
    },
    "light_produkte": {
        "name": "Light-Produkte-Bashing",
        "kerngewicht": 0.7,
        "keywords": [
            "light produkte", "light produkt", "diät produkte machen dick",
            "zero getränke ungesund", "light joghurt", "light lüge",
        ],
    },
    "saefte_fluessige_kalorien": {
        "name": "Säfte & flüssige Kalorien ('Saft ist gesund')",
        "kerngewicht": 0.6,
        "keywords": [
            "saft gesund", "smoothie abnehmen", "frisch gepresst", "saftfasten",
            "vitaminsaft", "smoothie gesund", "juice cleanse",
        ],
    },
    "vollkorn_dogma": {
        "name": "Vollkorn-Dogma & 'gute/böse' Lebensmittel",
        "kerngewicht": 0.5,
        "keywords": [
            "vollkorn gesünder", "weißmehl ungesund", "weizen gift", "gluten ungesund",
            "brot macht dick", "gute kohlenhydrate", "böse lebensmittel",
            "cholesterin", "eier ungesund",
        ],
    },
    "training_fettabbau_mythen": {
        "name": "Trainings-Mythen mit Fettabbau-Bezug",
        "kerngewicht": 0.7,
        "keywords": [
            "fettverbrennungspuls", "nachbrenneffekt", "nüchtern cardio",
            "fett in muskeln", "bauchfett gezielt", "problemzonen training",
            "abnehmen nur mit sport", "cardio abnehmen", "fettverbrennung training",
            "sixpack übungen bauchfett", "lokale fettverbrennung",
        ],
    },
    "abnehmspritze": {
        "name": "Abnehmspritze & Medikamente",
        "kerngewicht": 0.6,
        "keywords": [
            "abnehmspritze", "ozempic", "wegovy", "semaglutid", "glp-1", "glp1",
            "berberin", "natürliches ozempic",
        ],
    },
    "mahlzeiten_regeln": {
        "name": "Mahlzeiten-Regeln (nach 18 Uhr, viele kleine Mahlzeiten)",
        "kerngewicht": 0.7,
        "keywords": [
            "nach 18 uhr essen", "spät essen macht dick", "essen vor dem schlafen",
            "viele kleine mahlzeiten", "5 mahlzeiten", "essensfenster",
            "abends essen abnehmen",
        ],
    },
    "uebergewicht_disziplin": {
        "name": "Übergewicht = Disziplinfrage (Leyk-Position)",
        "kerngewicht": 0.6,
        "keywords": [
            "dicke sind faul", "übergewicht disziplin", "keine ausreden dick",
            "willenskraft abnehmen", "disziplin abnehmen", "einfach weniger essen",
        ],
    },
}

# ---------------------------------------------------------------------------
# Suchqueries fuer die YouTube-Claim-Suche.
# Claim-formuliert: so klingen die Videos, die die Falschinfo verbreiten.
# youtube_agent rotiert pro Lauf durch eine Teilmenge (Quota-Budget).
# ---------------------------------------------------------------------------

SUCHQUERIES = [
    "Honig gesünder als Zucker",
    "Süßstoff Krebs gefährlich",
    "Aspartam giftig Wahrheit",
    "Cola Zero ungesund",
    "Frühstück auslassen ungesund",
    "Frühstück wichtigste Mahlzeit",
    "Abnehmen ohne Kaloriendefizit",
    "Kalorien zählen sinnlos",
    "Detox Kur Erfahrung entgiften",
    "Leber entgiften abnehmen",
    "Stoffwechsel ankurbeln Trick",
    "Stoffwechsel eingeschlafen abnehmen",
    "Kohlenhydrate abends machen dick",
    "abends essen macht dick",
    "zu viel Protein schädlich Niere",
    "Proteinshakes ungesund Chemie",
    "Datteln statt Zucker gesund",
    "Zucker ist Gift Droge",
    "Apfelessig abnehmen Trick",
    "5 Kilo in einer Woche abnehmen",
    "Fatburner Lebensmittel Fett verbrennen",
    "Intervallfasten Autophagie Zellreinigung",
    "Bauchfett gezielt verbrennen Übungen",
    "Light Produkte machen dick",
    "E-Nummern Zusatzstoffe gefährlich",
    # Erweiterung 2026-07-04: mehr Claim-Muster aus Chris' Themenwelt + aktuelle Trends
    "Saftkur 7 Tage Erfahrung entgiften",
    "Zitronenwasser morgens abnehmen Trick",
    "Cortisol senken Bauchfett verlieren",
    "Hormone blockieren Abnehmen Frauen",
    "Insulin Trick Fett verbrennen",
    "natürliches Ozempic Berberin abnehmen",
    "Eier Cholesterin gefährlich Herz",
    "Milch ungesund entzündungsfördernd",
    "Samenöle giftig entzündlich Wahrheit",
    "Fruktose Obst macht dick Leber",
    "Mikrowelle zerstört Nährstoffe",
    "Kreatin schädlich Nieren",
    "Süßstoffe zerstören Darmflora",
    "Stoffwechseltyp Test abnehmen",
    "Abnehmen im Schlaf Trick funktioniert",
]


def finde_themen(text):
    """
    Findet alle passenden Themen-Slugs fuer einen Text (Substring-Match
    der Keywords, case-insensitive). Rueckgabe: Liste von Slugs,
    sortiert nach Kerngewicht (wichtigstes zuerst).
    """
    if not text:
        return []
    text_klein = text.lower()
    treffer = []
    for slug, thema in THEMEN.items():
        for kw in thema["keywords"]:
            if kw in text_klein:
                treffer.append(slug)
                break
    treffer.sort(key=lambda s: -THEMEN[s]["kerngewicht"])
    return treffer


def bestes_thema(text):
    """Bestes (kerngewichtigstes) Thema fuer einen Text oder None."""
    themen = finde_themen(text)
    return themen[0] if themen else None


if __name__ == "__main__":
    # Mini-Selbsttest
    print("Themen: %d, Suchqueries: %d" % (len(THEMEN), len(SUCHQUERIES)))
    beispiel = "Süßstoff ist krebserregend? Die Wahrheit über Aspartam und Cola Zero"
    print("Beispiel-Match:", finde_themen(beispiel))
