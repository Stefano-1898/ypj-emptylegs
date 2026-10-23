# YPJ Empty Leg

Aggiornamento automatico degli Empty Leg per il sito **Your Private Jet**.

- Un programma su GitHub legge, ogni 2 ore, gli annunci del gruppo Telegram degli Empty Leg
  e salva i voli futuri in [`data/emptylegs.csv`](data/emptylegs.csv), che il sito legge.
- Il programma **legge soltanto**: non scrive nulla nel gruppo.
- Tutti i dati riservati (chiavi Telegram, numero di telefono, accesso) sono salvati **cifrati**
  nella cartella `secure/`. La password di cifratura è custodita solo in
  *Settings → Secrets and variables → Actions* (`YPJ_KEY`).
- L'esito di ogni operazione è registrato in [`status.txt`](status.txt).

**Per fermare tutto in qualsiasi momento:** in Telegram, *Impostazioni → Dispositivi*,
chiudere la sessione "YPJ Empty Leg (GitHub)".
