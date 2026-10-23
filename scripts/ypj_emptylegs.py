# Your Private Jet — lettura automatica degli Empty Leg dal gruppo Telegram
#
# Il programma gira su GitHub Actions (nessun computer da tenere acceso).
# Tutti i dati delicati (chiavi Telegram, numero di telefono, sessione di accesso)
# sono salvati CIFRATI nella cartella secure/. La password di cifratura (YPJ_KEY)
# è custodita solo nelle impostazioni protette del repository (Settings → Secrets).
#
# Comandi:
#   python scripts/ypj_emptylegs.py login    → richiesta codice / accesso (una sola volta)
#   python scripts/ypj_emptylegs.py update   → aggiorna data/emptylegs.csv
#
# Il programma legge soltanto: non scrive nulla nel gruppo.

import asyncio
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from telethon import TelegramClient
from telethon.sessions import StringSession

ROMA = ZoneInfo("Europe/Rome")
NOME_GRUPPO = "Jet Sales Academy"     # basta una parte del nome del gruppo
MESSAGGI_DA_LEGGERE = 800

CONFIG = "secure/config.enc"          # api_id, api_hash, telefono
STATO_LOGIN = "secure/login_state.enc"
SESSIONE = "secure/session.enc"
CODICE = "login/code.enc"             # codice ricevuto su Telegram (cifrato)
RICHIESTA = "login/richiesta.txt"     # file che avvia la richiesta del codice
CSV_VOLI = "data/emptylegs.csv"
CITTA = "data/citta.json"              # città già riconosciute (paese) — si arricchisce da solo
CORREZIONI = "data/correzioni_citta.json"   # eventuali correzioni manuali: {"nome città": "IT"}
VERIFICATE = "data/citta_verificate.json"   # elenco città → area (lo stesso del sito), consultato per primo
EUROPA_MED = "gb,ie,im,je,gg,it,sm,va,fr,mc,ch,li,at,de,cz,pl,hu,sk,gr,hr,si,rs,ba,me,mk,al,xk,bg,ro,md,ua,tr,cy,mt,ee,lv,lt,es,pt,ad,gi,be,nl,lu,dk,no,se,fi,is,ma,tn,dz,eg,il,lb,jo,ae,sa,qa,bh,kw,om"

# Paese → area del sito (codici ISO a 2 lettere)
AREE_PAESI = {
    "UK & Irlanda": "GB IE IM JE GG",
    "Italia": "IT SM VA",
    "Europa Centrale": "FR MC CH LI AT DE CZ PL HU SK",
    "Grecia": "GR",
    "Balcani / EST-EU": "HR SI RS BA ME MK AL XK BG RO MD UA BY TR CY MT EE LV LT",
    "Iberia": "ES PT AD GI",
    "Benelux": "BE NL LU",
    "UAE": "AE",
    "USA": "US",
}
PAESE_AREA = {c: area for area, codici in AREE_PAESI.items() for c in codici.split()}
STATO = "status.txt"

RE_TRATTA = re.compile(r"Tratta\s+(.+?)\s+a\s+bordo\s+(?:del(?:l['’]|lo|la)?|di)\s*(.+)", re.I)
RE_DATA = re.compile(r"Data:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", re.I)
RE_ORA = re.compile(r"(?:Ora|Orario|Partenza|Decollo)[^:\n]*:\s*(\d{1,2})[:.](\d{2})", re.I)
RE_AEREO = re.compile(r"Aereo:\s*(.+?)\s*(?:\((\d+(?:\s*-\s*\d+)?)\s*posti[^)]*\))?\s*$", re.I | re.M)
RE_IMPORTO = re.compile(r"Importo:\s*([\d.,]+)\s*€", re.I)


# ---------------------------------------------------------------- utilità

def adesso():
    return dt.datetime.now(ROMA)


def scrivi_stato(messaggio):
    """Registro leggibile delle ultime operazioni (nessun dato riservato)."""
    righe = []
    if os.path.exists(STATO):
        righe = open(STATO, encoding="utf-8").read().splitlines()
    righe.insert(0, f"{adesso():%d/%m/%Y %H:%M} — {messaggio}")
    with open(STATO, "w", encoding="utf-8") as f:
        f.write("\n".join(righe[:60]) + "\n")
    print(messaggio)


def cifratore():
    chiave = os.environ.get("YPJ_KEY", "").strip()
    if not chiave:
        scrivi_stato("In attesa: manca la password YPJ_KEY nelle impostazioni protette (Settings → Secrets).")
        sys.exit(0)
    return Fernet(chiave.encode())


def leggi(percorso, f):
    return json.loads(f.decrypt(open(percorso, "rb").read()))


def salva(percorso, f, dati):
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "wb") as fh:
        fh.write(f.encrypt(json.dumps(dati).encode()))


def client_da(cfg, sessione=""):
    return TelegramClient(StringSession(sessione), int(cfg["api_id"]), cfg["api_hash"],
                          device_model="YPJ Empty Leg (GitHub)", app_version="1.0")


# ---------------------------------------------------------------- riconoscimento automatico delle città

def norm_citta(nome):
    t = unicodedata.normalize("NFD", str(nome or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def carica_json(percorso):
    try:
        return json.load(open(percorso, encoding="utf-8"))
    except Exception:
        return {}


def _nominatim(q, paesi=None):
    parametri = {"q": q, "format": "json", "limit": 1, "addressdetails": 1, "accept-language": "en"}
    if paesi:
        parametri["countrycodes"] = paesi
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(parametri)
    req = urllib.request.Request(url, headers={"User-Agent": "YPJ-EmptyLegs/1.0 (info@yourprivatejet.eu)"})
    time.sleep(1.1)   # regola d'uso del servizio: massimo 1 richiesta al secondo
    risultati = json.load(urllib.request.urlopen(req, timeout=20))
    if not risultati:
        return None
    r = risultati[0]
    return ((r.get("address", {}).get("country_code") or "").upper(), float(r.get("importance") or 0))


def cerca_paese(nome):
    """Chiede a OpenStreetMap in che paese si trova la città (una volta sola per città).
    Confronta il miglior risultato in Europa/Mediterraneo con quello mondiale: se il risultato
    mondiale è molto più importante (es. New York rispetto a un villaggio omonimo) vince quello."""
    try:
        for q in (nome, f"{nome} airport"):
            eu = _nominatim(q, EUROPA_MED)
            mondo = _nominatim(q)
            if eu and mondo:
                return mondo[0] if mondo[1] - eu[1] > 0.2 else eu[0]
            if eu or mondo:
                return (eu or mondo)[0]
    except Exception as e:
        print("Ricerca città non riuscita:", nome, e)
        return None
    return ""


class Citta:
    def __init__(self):
        self.memo = carica_json(CITTA)
        self.correzioni = {norm_citta(k): v.upper() for k, v in carica_json(CORREZIONI).items()}
        self.nuove, self.ignote = 0, set()
        self.verificate = [(" " + norm_citta(c) + " ", a) for c, a in carica_json(VERIFICATE).items()]
        self.verificate.sort(key=lambda x: -len(x[0]))   # prima i nomi più lunghi ("belfast city" prima di "belfast")

    def area_verificata(self, nome):
        testo = " " + norm_citta(nome) + " "
        for chiave, area in self.verificate:
            if chiave in testo:
                return area
        return None

    def paese(self, nome):
        k = norm_citta(nome)
        if not k:
            return ""
        if k in self.correzioni:
            return self.correzioni[k]
        if k not in self.memo:
            codice = cerca_paese(nome)
            if codice is None:          # servizio non raggiungibile: si riproverà al prossimo giro
                return ""
            self.memo[k] = codice
            self.nuove += 1
        return self.memo[k]

    def area_citta(self, citta):
        area = self.area_verificata(citta)
        if not area:
            codice = self.paese(citta)
            area = PAESE_AREA.get(codice)
            if codice == "" and citta:
                self.ignote.add(citta)
        return area

    def area_partenza(self, partenza):
        """Il volo appartiene all'area della città di PARTENZA (criterio scelto per il sito)."""
        return self.area_citta(partenza) or "Altre Tratte"

    def salva(self):
        if self.nuove:
            os.makedirs("data", exist_ok=True)
            with open(CITTA, "w", encoding="utf-8") as fh:
                json.dump(dict(sorted(self.memo.items())), fh, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- estrazione dati

def estrai_volo(testo):
    if not testo or "Importo" not in testo:
        return None
    tratta, data, importo = RE_TRATTA.search(testo), RE_DATA.search(testo), RE_IMPORTO.search(testo)
    if not (tratta and data and importo):
        return None
    g, m, a = data.groups()
    if len(a) == 2:
        a = "20" + a
    try:
        giorno = dt.date(int(a), int(m), int(g))
    except ValueError:
        return None
    rotta = tratta.group(1).strip()
    if " - " in rotta:
        partenza, arrivo = [x.strip() for x in rotta.split(" - ", 1)]
    else:
        partenza, arrivo = rotta, ""
    aereo = RE_AEREO.search(testo)
    ora = RE_ORA.search(testo)
    prezzo = importo.group(1)
    if "," in prezzo and "." not in prezzo:
        prezzo = prezzo.replace(",", ".")
    elif "," in prezzo and "." in prezzo:
        prezzo = prezzo.replace(".", "").replace(",", ".")
    return {
        "giorno": giorno,
        "partenza": partenza,
        "arrivo": arrivo,
        "data": f"{giorno:%d/%m/%Y}",
        "ora": f"{int(ora.group(1))}:{ora.group(2)}" if ora else "",
        "aereo": aereo.group(1).strip() if aereo else tratta.group(2).strip(),
        "posti": aereo.group(2).replace(" ", "") if aereo and aereo.group(2) else "",
        "prezzo": prezzo,
    }


# ---------------------------------------------------------------- accesso (una sola volta)

async def login():
    f = cifratore()
    cfg = leggi(CONFIG, f)

    # Fase 2: il codice è arrivato → accesso
    if os.path.exists(CODICE) and os.path.exists(STATO_LOGIN):
        stato = leggi(STATO_LOGIN, f)
        codice = leggi(CODICE, f)["code"]
        client = client_da(cfg, stato["session"])
        await client.connect()
        try:
            await client.sign_in(phone=cfg["phone"], code=codice, phone_code_hash=stato["hash"])
        except Exception as e:
            scrivi_stato(f"Accesso NON riuscito ({type(e).__name__}). Serve richiedere un nuovo codice.")
            os.remove(CODICE)
            await client.disconnect()
            return
        me = await client.get_me()
        salva(SESSIONE, f, {"session": client.session.save()})
        await client.disconnect()
        os.remove(CODICE)
        os.remove(STATO_LOGIN)
        scrivi_stato(f"Accesso riuscito come {me.first_name or ''}. Lettura automatica attiva.")
        await update()
        return

    # Fase 1: richiesta del codice
    if os.path.exists(RICHIESTA):
        client = client_da(cfg)
        await client.connect()
        try:
            r = await client.send_code_request(cfg["phone"])
        except Exception as e:
            scrivi_stato(f"Richiesta codice NON riuscita ({type(e).__name__}: {e}).")
            await client.disconnect()
            os.remove(RICHIESTA)
            return
        salva(STATO_LOGIN, f, {"session": client.session.save(), "hash": r.phone_code_hash})
        await client.disconnect()
        os.remove(RICHIESTA)
        scrivi_stato("Codice richiesto: Telegram lo ha inviato sull'app. In attesa del codice.")


# ---------------------------------------------------------------- aggiornamento voli

async def update():
    f = cifratore()
    if not os.path.exists(SESSIONE):
        scrivi_stato("In attesa: accesso a Telegram non ancora effettuato.")
        return
    cfg = leggi(CONFIG, f)
    client = client_da(cfg, leggi(SESSIONE, f)["session"])
    await client.connect()
    if not await client.is_user_authorized():
        scrivi_stato("ATTENZIONE: accesso a Telegram scaduto o chiuso da Dispositivi. Serve un nuovo accesso.")
        await client.disconnect()
        return

    gruppo = None
    async for d in client.iter_dialogs():
        if NOME_GRUPPO.lower() in (d.name or "").lower():
            gruppo = d.entity
            break
    if not gruppo:
        scrivi_stato(f"ATTENZIONE: gruppo «{NOME_GRUPPO}» non trovato tra le chat.")
        await client.disconnect()
        return

    oggi = adesso().date()
    voli, visti, letti, scartati = [], set(), 0, 0
    async for msg in client.iter_messages(gruppo, limit=MESSAGGI_DA_LEGGERE):
        letti += 1
        v = estrai_volo(msg.message)
        if not v:
            if msg.message and "Importo" in msg.message:
                scartati += 1
            continue
        if v["giorno"] < oggi:
            continue
        chiave = (v["partenza"].lower(), v["arrivo"].lower(), v["data"], v["aereo"].lower(), v["prezzo"])
        if chiave in visti:          # lo stesso volo è pubblicato in più sezioni
            continue
        visti.add(chiave)
        voli.append(v)
    await client.disconnect()

    voli.sort(key=lambda v: (v["giorno"], v["ora"] or "99", v["partenza"]))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["area", "partenza", "arrivo", "data", "ora", "aereo", "posti", "prezzo"])
    citta = Citta()
    for v in voli:
        # area della città di partenza
        w.writerow([citta.area_partenza(v["partenza"]), v["partenza"], v["arrivo"], v["data"], v["ora"], v["aereo"], v["posti"], v["prezzo"]])
    nuovo = out.getvalue()
    vecchio = open(CSV_VOLI, encoding="utf-8").read() if os.path.exists(CSV_VOLI) else ""
    os.makedirs("data", exist_ok=True)
    citta.salva()
    extra = f" Città nuove riconosciute: {citta.nuove}." if citta.nuove else ""
    if citta.ignote:
        extra += " Città NON riconosciute: " + ", ".join(sorted(citta.ignote)) + "."
    if nuovo != vecchio:
        with open(CSV_VOLI, "w", encoding="utf-8") as fh:
            fh.write(nuovo)
        scrivi_stato(f"Aggiornato: {len(voli)} voli futuri (messaggi letti {letti}, non riconosciuti {scartati}).{extra}")
    else:
        scrivi_stato(f"Controllo eseguito, nessuna novità: {len(voli)} voli futuri.{extra}")


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else "update"
    asyncio.run(login() if comando == "login" else update())
