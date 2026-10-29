# Unisce i voli di Telegram (data/telegram.csv) e della Community (secure/community_voli.enc)
# in un unico elenco senza doppioni: data/emptylegs.csv, il file letto dal sito.
#
# Doppione = stessa data (±1 giorno), stessa città di partenza e di arrivo, stesso tipo di aereo.
# Per i doppioni si tengono i dati della Community (più aggiornati, con orario), completati
# con quelli di Telegram se mancano.
# Area = area della città di PARTENZA (stesso criterio di sempre).

import csv
import datetime as dt
import io
import json
import os
import re
import unicodedata
from zoneinfo import ZoneInfo

ROMA = ZoneInfo("Europe/Rome")
TELEGRAM = "data/telegram.csv"
COMMUNITY = "secure/community_voli.enc"
USCITA = "data/emptylegs_v2.csv"      # nuove aree (USA Est/Ovest, Medio Oriente & Africa) — sito nuovo
USCITA_VECCHIA = "data/emptylegs.csv"  # stesse righe con le aree di prima — sito attuale, finché non viene aggiornato
EMIRATI = ("dubai", "abu dhabi", "sharjah", "ras al khaimah", "al maktoum", "al ain", "fujairah")
STATO = "status.txt"

AREE_PAESI = {
    "UK & Irlanda": "GB IE IM JE GG",
    "Italia": "IT SM VA",
    "Europa Centrale": "FR MC CH LI AT DE CZ PL HU SK DK NO SE FI IS",
    "Grecia": "GR",
    "Balcani / EST-EU": "HR SI RS BA ME MK AL XK BG RO MD UA BY TR CY MT EE LV LT",
    "Iberia": "ES PT AD GI",
    "Benelux": "BE NL LU",
    "Medio Oriente & Africa": "AE SA QA BH KW OM JO LB IL EG MA TN DZ LY SY IQ IR "
                              "ZA KE NG GH SN CI TZ ET MU SC NA BW ZW ZM MZ AO CM GA CV",
}
PAESE_AREA = {c: a for a, cc in AREE_PAESI.items() for c in cc.split()}
NORD_AMERICA = {"US", "CA"}
EST_OVEST = -90.0          # longitudine (circa il Mississippi): a est → USA Est, a ovest → USA Ovest
ALIAS = {"milano": "milan", "parigi": "paris", "londra": "london", "ginevra": "geneva", "zurigo": "zurich",
         "nizza": "nice", "roma": "rome", "venezia": "venice", "firenze": "florence", "napoli": "naples",
         "sevilla": "seville", "siviglia": "seville", "muenster": "munster", "munster": "munster",
         "palma mallorca": "palma", "palma de mallorca": "palma", "tires": "cascais", "koeln": "cologne",
         "koln": "cologne", "muenchen": "munich", "monaco di baviera": "munich", "wien": "vienna",
         "lisboa": "lisbon", "praha": "prague", "bruxelles": "brussels", "tel aviv yafo": "tel aviv"}


def norm(x):
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
    x = re.sub(r"[^a-z]+", " ", x).strip()
    return ALIAS.get(x, x)


def stessa(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a == b or a.split()[0] == b.split()[0])


def stesso_aereo(a, b):
    a, b = norm(a).split(), norm(b).split()
    if not a or not b:
        return True
    # "Citation XLS" e "Citation XLS+" → stesso; "Citation M2" e "Falcon 2000" → diversi
    return a[0] == b[0] and (len(a) < 2 or len(b) < 2 or a[1][:3] == b[1][:3])


def durata_ore(d):
    try:
        h, m = str(d).split(":")[:2]
        return int(h) + int(m) / 60
    except Exception:
        return None


def area_nord_america(lon):
    return "USA Ovest" if (lon is not None and lon < EST_OVEST) else "USA Est"


def area_community(v):
    da, a = v.get("from") or {}, v.get("to") or {}
    paese, lon = (da.get("country") or "").upper(), da.get("lon")
    # Correzione: alcune città hanno coordinate sbagliate (es. Naples in Florida segnata come Napoli).
    # Un volo breve non può attraversare l'Atlantico: in quel caso la partenza è dall'altra parte.
    ore = durata_ore(v.get("duration"))
    lon_a = a.get("lon")
    if lon is not None and lon_a is not None and ore is not None and ore < 6 and (lon > -30) != (lon_a > -30):
        if lon_a < -30:                       # arrivo in America → partenza in realtà in America
            return area_nord_america(lon_a), True
    if paese in NORD_AMERICA:
        return area_nord_america(lon), False
    return PAESE_AREA.get(paese, "Altre Tratte"), False


def scrivi_stato(msg):
    righe = open(STATO, encoding="utf-8").read().splitlines() if os.path.exists(STATO) else []
    righe.insert(0, f"{dt.datetime.now(ROMA):%d/%m/%Y %H:%M} — {msg}")
    open(STATO, "w", encoding="utf-8").write("\n".join(righe[:500]) + "\n")


def leggi_community(oggi):
    if not os.path.exists(COMMUNITY) or not os.environ.get("YPJ_KEY"):
        return [], "Community non disponibile"
    from cryptography.fernet import Fernet
    f = Fernet(os.environ["YPJ_KEY"].strip().encode())
    voli = json.loads(f.decrypt(open(COMMUNITY, "rb").read()))
    out = []
    for v in voli:
        try:
            g = dt.date.fromisoformat(v["date"])
        except Exception:
            continue
        if g < oggi:
            continue
        out.append(v)
    return out, ""


def main():
    oggi = dt.datetime.now(ROMA).date()
    tg = []
    if os.path.exists(TELEGRAM):
        for r in csv.DictReader(open(TELEGRAM, encoding="utf-8")):
            try:
                g, m, a = map(int, r["data"].split("/"))
                r["_giorno"] = dt.date(a, m, g)
            except Exception:
                continue
            if r["_giorno"] >= oggi:
                tg.append(r)
    com, nota = leggi_community(oggi)

    # coordinate note (dalla Community) per dividere USA Est / Ovest anche i voli di Telegram
    lon_citta = {}
    for v in com:
        for k in ("from", "to"):
            o = v.get(k) or {}
            if (o.get("country") or "").upper() in NORD_AMERICA and o.get("lon") is not None:
                lon_citta.setdefault(norm(o.get("name")), o["lon"])

    usati, righe, doppioni, corretti = set(), [], 0, 0
    for v in com:
        da, a = (v.get("from") or {}).get("name", ""), (v.get("to") or {}).get("name", "")
        g = dt.date.fromisoformat(v["date"])
        area, fix = area_community(v)
        corretti += fix
        riga = {"area": area, "partenza": da, "arrivo": a, "data": f"{g:%d/%m/%Y}", "ora": v.get("time") or "",
                "aereo": v.get("aircraft") or "", "posti": str(v.get("seats") or ""),
                "prezzo": "" if v.get("price") in (None, "") else str(v["price"]), "_giorno": g}
        for i, r in enumerate(tg):
            if i in usati:
                continue
            if abs((g - r["_giorno"]).days) <= 1 and stessa(da, r["partenza"]) and stessa(a, r["arrivo"]) \
                    and stesso_aereo(riga["aereo"], r["aereo"]):
                usati.add(i)
                doppioni += 1
                for k in ("ora", "prezzo", "posti", "aereo"):
                    if not riga[k]:
                        riga[k] = r.get(k, "")
                break
        righe.append(riga)

    for i, r in enumerate(tg):
        if i in usati:
            continue
        area = r.get("area") or "Altre Tratte"
        if area == "UAE":
            area = "Medio Oriente & Africa"
        elif area == "USA":
            area = area_nord_america(lon_citta.get(norm(r["partenza"])))
        righe.append({**{k: r.get(k, "") for k in ("partenza", "arrivo", "data", "ora", "aereo", "posti", "prezzo")},
                      "area": area, "_giorno": r["_giorno"]})

    righe.sort(key=lambda r: (r["_giorno"], r["ora"] or "99", r["partenza"]))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    campi = ["area", "partenza", "arrivo", "data", "ora", "aereo", "posti", "prezzo"]
    w.writerow(campi)
    for r in righe:
        w.writerow([r[k] for k in campi])
    nuovo = out.getvalue()
    out2 = io.StringIO()
    w2 = csv.writer(out2, lineterminator="\n")
    w2.writerow(campi)
    for r in righe:
        a = r["area"]
        if a in ("USA Est", "USA Ovest"):
            a = "USA"
        elif a == "Medio Oriente & Africa":
            a = "UAE" if any(e in norm(r["partenza"]) for e in EMIRATI) else "Altre Tratte"
        w2.writerow([a] + [r[k] for k in campi[1:]])
    open(USCITA_VECCHIA, "w", encoding="utf-8").write(out2.getvalue())
    vecchio = open(USCITA, encoding="utf-8").read() if os.path.exists(USCITA) else ""
    from collections import Counter
    per_area = Counter(r["area"] for r in righe)
    dettaglio = ", ".join(f"{k} {n}" for k, n in per_area.most_common())
    msg = (f"Elenco unico: {len(righe)} voli (Community {len(com)}, Telegram {len(tg)}, doppioni tolti {doppioni}"
           f"{', partenze corrette ' + str(corretti) if corretti else ''}). Per area: {dettaglio}.")
    if nota:
        msg += f" Nota: {nota}."
    if nuovo != vecchio:
        open(USCITA, "w", encoding="utf-8").write(nuovo)
    scrivi_stato(msg)


if __name__ == "__main__":
    main()
