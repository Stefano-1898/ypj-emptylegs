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


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log.append(traceback.format_exc())
        stato(f"Errore: {type(e).__name__}: {str(e)[:200]}")
        salva_dump()
        sys.exit(0)
