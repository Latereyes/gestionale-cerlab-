# Gestionale Preventivi — Cerlab

Gestionale web per **Cerlab srls**: preventivi, clienti, ordini fornitori, consegne, fatture, pagamenti e magazzino, usato da tutto l'ufficio attraverso il browser.

Il programma gira su un PC Windows che fa da server per la rete locale. Gli altri PC, e anche i telefoni (via Tailscale), si collegano dal browser all'indirizzo del server.

Versione attuale: **3.1.0** (vedi [`version.txt`](version.txt) e la pagina *Novità* dentro il gestionale).

---

## Funzionalità principali

- **Preventivi**
  - Editor commerciale con prezzi di catalogo, sconti a cascata, ricarico, trasporto e spese d'incasso.
  - Editor dedicato ai **preventivi edili**.
  - Flusso di stati: Bozza → Inviato → Confermato → Chiuso.
  - Clonazione, revisioni e allegati.
  - Copia di sicurezza locale della bozza durante la compilazione.
- **PDF**: preventivi, preventivi edili e bolle di consegna generati con Chrome/Edge in modalità headless, con WeasyPrint come alternativa se il browser non riesce.
- **Clienti**: anagrafica, ricerca rapida, dettaglio cliente con documenti allegati, note e analisi esportabile in Excel.
- **Ordini fornitori e consegne**: conferma ordine per articolo, bolle di consegna (la bolla firmata è obbligatoria per segnare la merce come consegnata).
- **Fatture e pagamenti**: incassi, pagamenti programmati, rettifiche, scadenze e avvisi sui pagamenti scaduti, gestione IVA esente.
- **Magazzino**:
  - Articoli con carico merce e costo medio ponderato.
  - Prenotazione dai preventivi e scarico alla consegna.
  - Correzione o eliminazione dell'ultimo movimento.
- **Dashboard CEO**: statistiche, cashflow ed export Excel (con foglio CALCOLI).
- **Margini e ricarichi** configurabili dall'amministrazione.
- **Collaborazione interna**: chat con allegati, task (anche private), bacheca (tagbox), notifiche e menzioni, pulsante *ADMIN* per segnalare bug e richieste.
- **Gestionale Notifiche** ([`notifiche_client.py`](notifiche_client.py)): piccolo programma per i PC dell'ufficio.
  - Resta nell'area di notifica vicino all'orologio e mostra gli avvisi del gestionale.
  - Permette di rispondere in chat al volo.
  - Trova da solo il server in rete.
- **Telefono**:
  - Interfaccia adattata agli schermi piccoli.
  - Il gestionale si installa come app (PWA) su iOS e Android.
  - Accesso da fuori ufficio tramite Tailscale.
- **Utenti e ruoli**: `amministratore`, `ceo`, `segreteria`, `venditore`. Ogni ruolo vede solo le pagine e i dati di sua competenza.
- **Aggiornamenti automatici**: all'avvio il programma controlla l'ultima release pubblicata su GitHub e propone l'aggiornamento.

## Tecnologie

| Componente | Tecnologia |
|---|---|
| Web app | Python, Flask, Jinja2 |
| Server | Waitress (porta **5001**) |
| Database | SQLite con SQLAlchemy ([`models.py`](models.py)) |
| PDF | Chrome / Edge headless, WeasyPrint come alternativa |
| Excel | pandas, openpyxl |
| Icona nell'area di notifica e finestra di avvio | pystray, Pillow, Tkinter |
| Eseguibile e installer | PyInstaller, Inno Setup |

## Struttura del progetto

```
gestionale.py            Applicazione principale (server Flask, icona nell'area di notifica, aggiornamenti)
models.py                Modelli SQLAlchemy e database SQLite
routes/                  Blueprint Flask: preventivi, ordini, consegne
templates/               Pagine HTML (Jinja2)
static/                  Logo, icone, favicon
data/                    changelog.json (pagina "Novità") e comuni.json
notifiche_client.py      Programma "Gestionale Notifiche" per i PC dell'ufficio
utils.py                 Funzioni di supporto
migrate_v3_installer.py  Migrazione dei vecchi dati JSON verso SQLite (V3)
fix_pagamenti_v2.py      Correzione dei pagamenti, eseguita dall'installer
build.py / build.bat     Aumento della versione e compilazione (PyInstaller + Inno Setup)
crea_installer.iss       Script Inno Setup dell'installer
scripts/                 Script di manutenzione, migrazione e test
requirments/             Dipendenze e guida all'installazione manuale (leggimi.txt)
```

## Installazione (utente finale)

1. Scarica l'installer `setup_gestionale_preventivi_<versione>.exe` dalla pagina [Releases](https://github.com/Latereyes/gestionale-cerlab-/releases) e avvialo sul PC che farà da server.
2. L'installer copia il programma, aggiorna i dati esistenti (migrazione e correzione dei pagamenti) e crea l'icona sul desktop.
3. Avvia **Gestionale**: compare l'icona nell'area di notifica, da cui si possono copiare gli indirizzi della rete locale e di Tailscale.
4. Dagli altri PC apri il browser su `http://<IP-del-server>:5001`.

I dati degli utenti si trovano in `%APPDATA%\GestionalePreventivi`, quindi gli aggiornamenti non li toccano.

## Sviluppo

Requisiti: Windows, Python 3.13 e Chrome o Edge installato (serve per i PDF).

```bat
python -m venv .venv
.venv\Scripts\activate
pip install flask waitress sqlalchemy pandas openpyxl python-dateutil packaging pillow pystray
```

WeasyPrint è facoltativo: richiede anche il runtime GTK (vedi [`requirments/leggimi.txt`](requirments/leggimi.txt)).

Avvio:

- `debug.bat` (equivale a `python gestionale.py --debug`) usa la cartella locale `data/` invece di quella in AppData.
- `test.bat` (equivale a `python gestionale.py`) avvia il programma come nella versione installata.

Poi apri `http://127.0.0.1:5001`.

### Creare una nuova versione

1. Aggiungi le novità in `data/changelog.json`.
2. Lancia `build.bat`. Lo script chiede il tipo di aggiornamento (`major`, `minor` o `patch`) e aggiorna la versione in `version.txt`, `gestionale.py`, `notifiche_client.py` e `crea_installer.iss`. Poi compila `Gestionale.exe`, `GestionaleNotifiche.exe` e l'installer.
3. Pubblica l'installer come nuova Release su GitHub: i gestionali installati la troveranno al successivo avvio.

---

© Cerlab srls — software ad uso interno.
