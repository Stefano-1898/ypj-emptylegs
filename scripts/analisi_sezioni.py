# Analisi una tantum: in quali sezioni del gruppo Telegram viene pubblicato ogni volo,
# e in che paese si trovano le città di partenza e di arrivo.
# Non modifica il sito né il file dei voli: produce solo data/analisi_sezioni.csv.

import asyncio
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ypj_emptylegs as y  # noqa: E402

try:
    from telethon.tl.functions.messages import GetForumTopicsRequest as Sezioni
except ImportError:
    from telethon.tl.functions.channels import GetForumTopicsRequest as Sezioni

USCITA = "data/analisi_sezioni.csv"
PAESI = "data/citta_paesi.json"   # paese (ISO) di ogni città, usato solo per l'analisi


def sezione_id(msg):
    r = msg.reply_to
    if not r:
        return 1                      # sezione "Generale"
    if getattr(r, "reply_to_top_id", None):
        return r.reply_to_top_id
    if getattr(r, "forum_topic", False):
        return r.reply_to_msg_id
    return 1


async def main():
    f = y.cifratore()
    cfg = y.leggi(y.CONFIG, f)
    client = y.client_da(cfg, y.leggi(y.SESSIONE, f)["session"])
    await client.connect()
    gruppo = None
    async for d in client.iter_dialogs():
        if y.NOME_GRUPPO.lower() in (d.name or "").lower():
            gruppo = d.entity
            break
    try:
        if "channel" in Sezioni.__init__.__code__.co_varnames:
            res = await client(Sezioni(channel=gruppo, offset_date=None, offset_id=0, offset_topic=0, limit=100, q=None))
        else:
            res = await client(Sezioni(peer=gruppo, offset_date=None, offset_id=0, offset_topic=0, limit=100, q=None))
        titoli = {t.id: getattr(t, "title", "?") for t in res.topics}
    except Exception as e:
        titoli = {}
        print("Sezioni non lette:", e)
    titoli.setdefault(1, "Generale")

    oggi = y.adesso().date()
    voli = {}
    async for msg in client.iter_messages(gruppo, limit=1500):
        v = y.estrai_volo(msg.message)
        if not v or v["giorno"] < oggi:
            continue
        k = (v["partenza"], v["arrivo"], v["data"], v["aereo"], v["prezzo"])
        voli.setdefault(k, set()).add(titoli.get(sezione_id(msg), f"sezione {sezione_id(msg)}"))
    await client.disconnect()

    paesi = y.carica_json(PAESI)
    correzioni = {y.norm_citta(k): v for k, v in y.carica_json(y.CORREZIONI).items()}

    def paese(nome):
        k = y.norm_citta(nome)
        if k in correzioni:
            return correzioni[k]
        if k not in paesi:
            paesi[k] = y.cerca_paese(nome) or ""
        return paesi[k]

    righe = []
    for (p, a, d, aereo, prezzo), sezioni in sorted(voli.items(), key=lambda x: (x[0][2], x[0][0])):
        righe.append([p, paese(p), a, paese(a), d, aereo, prezzo, " | ".join(sorted(sezioni))])
    with open(PAESI, "w", encoding="utf-8") as fh:
        import json
        json.dump(dict(sorted(paesi.items())), fh, ensure_ascii=False, indent=1)
    with open(USCITA, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["partenza", "paese_partenza", "arrivo", "paese_arrivo", "data", "aereo", "prezzo", "sezioni_telegram"])
        w.writerows(righe)
    y.scrivi_stato(f"Analisi sezioni completata: {len(righe)} voli, {len(titoli)} sezioni.")


if __name__ == "__main__":
    asyncio.run(main())
