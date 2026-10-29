# Accesso alla Community (community.raffaprivatejet.com) e lettura dei voli.
# Fase unica: chiede il codice via email, poi aspetta (max 15 minuti) che il codice
# venga caricato cifrato in community/code.enc, lo inserisce, entra e salva i voli.
# Tutto ciò che contiene dati riservati (email, sessione, contenuto pagine) è cifrato con YPJ_KEY.

import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
import datetime as dt
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright

URL = "https://community.raffaprivatejet.com/voli"
CODICE = "community/code.enc"
STATO = "community/stato.txt"
SESSIONE = "secure/community_session.enc"
DUMP = "secure/community_dump.enc"
CONFIG = "secure/community_config.enc"
ATTESA_MAX = 15 * 60

f = Fernet(os.environ["YPJ_KEY"].strip().encode())
log = []
files = {}
risposte = []


def stato(msg):
    riga = f"{dt.datetime.now(ZoneInfo('Europe/Rome')):%d/%m/%Y %H:%M:%S} — {msg}"
    print(riga, flush=True)
    log.append(riga)
    righe = open(STATO, encoding="utf-8").read().splitlines() if os.path.exists(STATO) else []
    open(STATO, "w", encoding="utf-8").write("\n".join([riga] + righe[:200]) + "\n")


def scatta(page, nome):
    try:
        files[f"{nome}.png"] = page.screenshot(full_page=True)
        files[f"{nome}.html"] = page.content().encode()
        files[f"{nome}.txt"] = page.inner_text("body").encode()
    except Exception as e:
        log.append(f"screenshot {nome} non riuscito: {e}")


def salva_dump():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
        z.writestr("log.txt", "\n".join(log))
        z.writestr("risposte.json", json.dumps(risposte, ensure_ascii=False, indent=1))
    open(DUMP, "wb").write(f.encrypt(buf.getvalue()))


def aspetta_codice():
    inizio = time.time()
    while time.time() - inizio < ATTESA_MAX:
        subprocess.run(["git", "pull", "-q", "--rebase", "origin", "main"], capture_output=True)
        if os.path.exists(CODICE):
            try:
                c = json.loads(f.decrypt(open(CODICE, "rb").read()))
                if c.get("t", 0) >= inizio - 120:
                    return str(c["code"]).strip()
            except Exception as e:
                log.append(f"codice illeggibile: {e}")
        time.sleep(8)
    return None


def visibili(page, sel):
    return [e for e in page.locator(sel).all() if e.is_visible()]


def on_response(resp):
    try:
        ct = resp.headers.get("content-type", "")
        if "json" in ct and len(risposte) < 200:
            body = resp.text()
            risposte.append({"url": resp.url, "status": resp.status, "body": body[:400000]})
    except Exception:
        pass


def main():
    email = json.loads(f.decrypt(open(CONFIG, "rb").read()))["email"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="it-IT", viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(URL, wait_until="networkidle")
        scatta(page, "01_iniziale")

        campo = (visibili(page, "input[type=email]") or visibili(page, "input"))[0]
        campo.fill(email)
        bottone = page.get_by_role("button", name=re.compile("codice|invia|continua", re.I))
        if bottone.count():
            bottone.first.click()
        else:
            campo.press("Enter")
        page.wait_for_timeout(4000)
        scatta(page, "02_codice_richiesto")
        stato("Codice richiesto: controlla l'email e comunica il codice a Claude (attesa max 15 minuti).")
        salva_dump()
        subprocess.run("git add -A && git commit -q -m 'Community: codice richiesto' && git push -q", shell=True)

        codice = aspetta_codice()
        if not codice:
            stato("Nessun codice ricevuto entro 15 minuti: accesso annullato.")
            salva_dump()
            return

        caselle = [e for e in visibili(page, "input") if (e.get_attribute("maxlength") or "") == "1"]
        if len(caselle) >= 4:
            for cifra, casella in zip(codice, caselle):
                casella.fill(cifra)
        else:
            altri = [e for e in visibili(page, "input") if (e.get_attribute("type") or "") != "email"]
            (altri or visibili(page, "input"))[0].fill(codice)
        page.wait_for_timeout(500)
        conferma = page.get_by_role("button", name=re.compile("accedi|entra|verifica|conferma|continua|login", re.I))
        if conferma.count():
            conferma.first.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(6000)
        scatta(page, "03_dopo_codice")

        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(3000)
        for _ in range(60):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(700)
            altri = page.get_by_role("button", name=re.compile("carica|mostra|altri|load more|vedi tutt", re.I))
            if altri.count() and altri.first.is_visible():
                altri.first.click()
                page.wait_for_timeout(1500)
        scatta(page, "04_voli")
        ctx.storage_state(path="/tmp/stato.json")
        open(SESSIONE, "wb").write(f.encrypt(open("/tmp/stato.json", "rb").read()))
        testo = page.inner_text("body")
        stato(f"Accesso eseguito, pagina voli salvata ({len(testo)} caratteri).")
        salva_dump()
        browser.close()


# ------------------------------------------------ controllo automatico (sessione salvata)

def norm(x):
    import unicodedata
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
    x = re.sub(r"[^a-z]+", " ", x).strip()
    alias = {"milano": "milan", "parigi": "paris", "londra": "london", "ginevra": "geneva", "zurigo": "zurich",
             "nizza": "nice", "roma": "rome", "venezia": "venice", "firenze": "florence", "sevilla": "seville",
             "muenster": "munster", "palma mallorca": "palma", "palma de mallorca": "palma", "tires": "cascais"}
    return alias.get(x, x)


def estrai_voli(html):
    pezzi = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    testo = "".join(pezzi).encode().decode("unicode_escape", errors="ignore")
    i = testo.find('"legs":[')
    if i < 0:
        return None
    voli, _ = json.JSONDecoder().raw_decode(testo[i + 7:])
    return voli


def controlla():
    import csv
    if not os.path.exists(SESSIONE):
        stato("Controllo: nessun accesso salvato.")
        return
    open("/tmp/stato.json", "wb").write(f.decrypt(open(SESSIONE, "rb").read()))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="it-IT", storage_state="/tmp/stato.json")
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(3000)
        voli = estrai_voli(page.content())
        if voli is None:
            scatta(page, "controllo_fallito")
            salva_dump()
            stato("Controllo automatico NON riuscito: la community chiede di nuovo il codice (accesso scaduto).")
            browser.close()
            return
        ctx.storage_state(path="/tmp/stato.json")
        open(SESSIONE, "wb").write(f.encrypt(open("/tmp/stato.json", "rb").read()))
        browser.close()
    open("secure/community_voli.enc", "wb").write(f.encrypt(json.dumps(voli, ensure_ascii=False).encode()))
    europa = [v for v in voli if (v.get("from") or {}).get("lon", -999) > -30
              and not (norm(v["from"]["name"]) == "naples" and (v.get("to") or {}).get("lon", 0) < -30)]
    tg = []
    if os.path.exists("data/emptylegs.csv"):
        for r in csv.DictReader(open("data/emptylegs.csv", encoding="utf-8")):
            try:
                g, m, a = map(int, r["data"].split("/"))
                tg.append((dt.date(a, m, g), norm(r["partenza"]), norm(r["arrivo"])))
            except Exception:
                pass
    uguale = lambda a, b: a == b or (a and b and a.split()[0] == b.split()[0])
    nuovi = 0
    lista_nuovi = []
    for v in europa:
        d = dt.date.fromisoformat(v["date"])
        da, a = norm(v["from"]["name"]), norm(v["to"]["name"])
        if not any(abs((d - td).days) <= 1 and uguale(da, tf) and uguale(a, tt) for td, tf, tt in tg):
            nuovi += 1
            lista_nuovi.append(v)
    stato(f"Controllo automatico OK: accesso valido, {len(voli)} voli in community, "
          f"{len(europa)} con partenza Europa/Med/Medio Oriente, di cui {nuovi} non presenti su Telegram.")
    verifica_prezzi(voli)
    distribuzione(lista_nuovi)


def distribuzione(voli):
    # Riepilogo (solo conteggi) di dove partono i voli Community non presenti su Telegram.
    try:
        from collections import Counter
        paesi = {}
        for nome in ("data/citta_paesi.json", "data/citta.json"):
            if os.path.exists(nome):
                paesi.update({norm(k): v for k, v in json.load(open(nome, encoding="utf-8")).items()})

        def paese(o):
            o = o or {}
            for k in ("country", "countryCode", "country_code", "iso2"):
                if isinstance(o.get(k), str) and o[k].strip():
                    return o[k].strip()
            return paesi.get(norm(o.get("name")), "?")

        per_paese = Counter(paese(v.get("from")) for v in voli)
        per_citta = Counter((v.get("from") or {}).get("name") or "?" for v in voli)
        per_arrivo = Counter(paese(v.get("to")) for v in voli)
        chiavi = sorted({k for v in voli for k in (v.get("from") or {})})
        fmt = lambda c: ", ".join(f"{k} {n}" for k, n in c.most_common())
        stato(f"Distribuzione voli Community non su Telegram ({len(voli)}) — partenza per paese: {fmt(per_paese)} | "
              f"partenza per citta: {fmt(per_citta)} | arrivo per paese: {fmt(per_arrivo)} | campi partenza: {', '.join(chiavi)}")
    except Exception as e:
        stato(f"Distribuzione: errore {type(e).__name__}: {str(e)[:150]}")


def verifica_prezzi(voli):
    # Verifica una tantum: il file scaricato contiene i prezzi?
    try:
        def cerca(o, via=""):
            if isinstance(o, dict):
                for k, val in o.items():
                    p = f"{via}.{k}" if via else k
                    if any(s in k.lower() for s in ("price", "prezzo", "amount", "cost", "eur")) \
                            and isinstance(val, (int, float, str)) and str(val).strip() not in ("", "0"):
                        yield p, val
                    yield from cerca(val, p)
        con, campi, esempio = 0, set(), None
        for v in voli:
            trovati = list(cerca(v))
            if trovati:
                con += 1
                campi.update(k for k, _ in trovati)
                if esempio is None:
                    esempio = (f"{(v.get('from') or {}).get('name')} -> {(v.get('to') or {}).get('name')} "
                               f"{v.get('date')}: " + ", ".join(f"{k}={val}" for k, val in trovati[:3]))
        chiavi = sorted({k for v in voli if isinstance(v, dict) for k in v})
        stato(f"Verifica prezzi: {con} voli su {len(voli)} hanno un prezzo. Campi: {', '.join(sorted(campi)) or 'nessuno'}. "
              f"Esempio: {esempio or '-'}. Campi del volo: {', '.join(chiavi)[:300]}")
    except Exception as e:
        stato(f"Verifica prezzi: errore {type(e).__name__}: {str(e)[:150]}")


if __name__ == "__main__":
    try:
        controlla() if "controlla" in sys.argv else main()
    except Exception as e:
        import traceback
        log.append(traceback.format_exc())
        stato(f"Errore: {type(e).__name__}: {str(e)[:200]}")
        salva_dump()
        sys.exit(0)
