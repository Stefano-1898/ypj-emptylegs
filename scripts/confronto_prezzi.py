# Una tantum: confronta prezzo Telegram (EUR) e prezzo Community per gli stessi voli.
import csv, json, os, re, sys, unicodedata, datetime as dt
from cryptography.fernet import Fernet
f = Fernet(os.environ["YPJ_KEY"].strip().encode())
voli = json.loads(f.decrypt(open("secure/community_voli.enc", "rb").read()))
def n(x):
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
    x = re.sub(r"[^a-z]+", " ", x).strip()
    return {"milano": "milan", "parigi": "paris", "londra": "london", "ginevra": "geneva", "zurigo": "zurich",
            "nizza": "nice", "roma": "rome", "venezia": "venice", "sevilla": "seville", "muenster": "munster",
            "palma mallorca": "palma", "tires": "cascais"}.get(x, x)
tg = list(csv.DictReader(open("data/emptylegs.csv", encoding="utf-8")))
righe = []
for r in tg:
    g, m, a = map(int, r["data"].split("/")); d = dt.date(a, m, g)
    for v in voli:
        if v["date"] == d.isoformat() and n(v["from"]["name"]).split()[0] == n(r["partenza"]).split()[0] \
           and n(v["to"]["name"]).split()[0] == n(r["arrivo"]).split()[0]:
            try:
                q = float(v["price"]) / float(r["prezzo"])
            except Exception:
                q = 0
            righe.append(f'{r["data"]} {r["partenza"]}->{r["arrivo"]} {r["aereo"]} | TG {r["prezzo"]} EUR, posti {r["posti"]}, ora "{r["ora"]}" | COM {v["price"]} ({q:.3f}), {v["aircraft"]}, posti {v["seats"]}, ora {v["time"]}, departsAt {v.get("departsAt")}, free {v.get("free")}')
            break
es = voli[0]
sample = {k: es[k] for k in es if k != "whatsapp"}
ora = dt.datetime.now(dt.timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
open("community/confronto_prezzi.txt", "w", encoding="utf-8").write(
    f"{ora}\nVoli community: {len(voli)}  Telegram: {len(tg)}  Coppie: {len(righe)}\n"
    + "\n".join(righe) + "\n\nEsempio volo community:\n" + json.dumps(sample, ensure_ascii=False, indent=1)
    + "\n\nPaesi partenza: " + json.dumps(__import__("collections").Counter(v["from"].get("country") for v in voli).most_common()) 
    + "\nPrezzi tipo: " + json.dumps(__import__("collections").Counter(type(v["price"]).__name__ for v in voli).most_common()) + "\n")
