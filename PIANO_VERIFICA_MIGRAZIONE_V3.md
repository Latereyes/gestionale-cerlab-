# Piano di verifica della migrazione JSON → SQLite (Gestionale V3)

Data: 2 ottobre 2026. Documento di sola pianificazione: per scriverlo non è stato modificato nessun file, database o dato. Le uniche operazioni eseguite sono state letture e query SQLite in sola lettura (`mode=ro`).

Sorgente di verità indicata dall'utente: la versione JSON in `C:\Users\andre\Documents\GESTIONALE CERLAB` (cartelle `preventivi\` e `clienti\` nella radice, aggiornate oggi).

---

## 1. Come funziona oggi la migrazione

### 1.1 Chi la lancia

| Punto di ingresso | Dove | Quando |
|---|---|---|
| Installer Inno Setup | `crea_installer.iss`, sezione `[Run]` | A ogni installazione/aggiornamento: `Gestionale.exe --run-migration`, poi `Gestionale.exe --fix-pagamenti` |
| `--run-migration` | `gestionale.py:7213` | Importa `migrate_v3_installer.main()` passando `DATA_DIR`; scrive `migration_installer.log` |
| `--fix-pagamenti` | `gestionale.py:7242` | Esegue `fix_pagamenti_v2.main()`; scrive `fix_pagamenti.log` |
| Avvio automatico | `gestionale.py:862` `_run_auto_migration_if_needed()` | All'avvio, se manca `migration_v3_done.flag` **e** la tabella utenti è vuota **e** esistono JSON |

`build.bat` → `build.py` controlla solo che `migrate_v3_installer.py`, `fix_pagamenti_v2.py` e `models.py` esistano, poi compila PyInstaller e Inno Setup.

### 1.2 Da dove legge e dove scrive

- **Legge** i JSON da `DATA_DIR` = `%APPDATA%\GestionalePreventivi` (in `--debug`: `.\data`).
- **Scrive** nel DB indicato da `models.py`: `DB_PATH = <cartella di models.py>\data\gestionale.db`. Il percorso **non dipende da `DATA_DIR`** e la variabile `GESTIONALE_DB_PATH` che `fix_pagamenti_v2.py` imposta non viene letta da nessuno.
  - In sviluppo: `GESTIONALE CERLAB v3\data\gestionale.db`.
  - Nell'eseguibile PyInstaller (onedir) il modulo `models` sta dentro `{app}\_internal`, quindi il DB finisce in `C:\Program Files (x86)\Gestionale Preventivi\_internal\data\gestionale.db` (dedotto dal codice, da confermare su un PC di prova).

### 1.3 Cosa migra (`migrate_v3_installer.py`)

Clienti, preventivi (con ordini fornitore e bolle estratti dal JSON del preventivo), utenti, tasks, admin tasks, messaggi, tagbox, notifiche, configurazione margini. Ogni record già presente nel DB viene **saltato** (non aggiornato).

Poi `fix_pagamenti_v2.py`: aggiunge un PAY ID ai pagamenti senza id, forza `Saldato` sui preventivi `Chiuso`, e rimette a `Saldato` i `Da Saldare` coperti dai pagamenti.

---

## 2. Problemi già visibili nel codice (da verificare/correggere prima della migrazione vera)

In ordine di gravità.

1. **Il DB in produzione può essere cancellato a ogni aggiornamento.** `CurStepChanged` nell'installer fa `DelTree({app}\_internal)`, cioè proprio la cartella dove (vedi 1.2) finisce `gestionale.db`. Subito dopo, `--run-migration` reimporta dai JSON di AppData, che V3 non aggiorna più: il risultato sarebbe tornare all'istantanea JSON e perdere tutto il lavoro fatto in V3. Da confermare su PC di prova; se confermato, il DB va spostato in `DATA_DIR` (AppData) prima di qualunque rilascio.
2. **Campi del preventivo che non esistono nello schema DB**, quindi persi sia dalla migrazione sia da ogni salvataggio V3 (`save_quote`, `gestionale.py:1118`). Presenti nei JSON di origine:
   - `allegati` (104 preventivi): i file restano su disco in `allegati\<numero>\`, ma la lista che l'interfaccia mostra (`gestionale.py:2729-2770`) sparisce.
   - `fatture_per_iva` (74) e `stati_fattura_iva` (94): servono a calcolare `stato_fattura` (`gestionale.py:6168-6210`). Senza di essi, alla prima modifica di una fattura lo stato scende a "In Attesa" e `aggiorna_stato_avanzamento` riapre i `Chiuso` come `In Lavorazione`.
   - `data_annullamento` (208), `pdf_attivo` (309), `indirizzi_cantiere`, `riepilogo`, `default_iva_switch`, `totale_pagato`/`totale_da_saldare` (questi ultimi due vengono ricalcolati, gli altri no).
   - Sui clienti: `codice_univoco` (170), `regione` (183), `indirizzi_cantiere` (3).
3. **La migrazione non aggiorna, salta.** Se un preventivo esiste già nel DB, le modifiche più recenti nei JSON non arrivano. Rieseguirla sopra un DB vecchio non allinea niente: va sempre fatta su un DB vuoto.
4. **I salvataggi V3 ricalcolano gli stati.** `save_quote` chiama `aggiorna_stato_pagamento_globale`, `aggiorna_stato_consegna_globale` e `aggiorna_stato_avanzamento`, che può portare `Chiuso` → `In Lavorazione`. Il confronto va fatto sia subito dopo la migrazione sia dopo un "salva" su un campione.
5. **L'installer copia `data\*` del PC di sviluppo nell'AppData del cliente** senza escludere `gestionale.db`, `migration_v3_done.flag`, `storico_ceo.json`, `config_margini.json`, `admin_tasks.json`, e senza il flag `onlyifdoesntexist`: sovrascrive i file del cliente e può disattivare la migrazione automatica.
6. **Errori silenziosi.** Ordini con `ordine_id` duplicato o bolle senza `id` vengono saltati senza contarli; ordini senza id ricevono un id casuale (2 casi nei dati); i messaggi non hanno controllo duplicati (rieseguire = messaggi doppi); un JSON illeggibile fa saltare il preventivo con un solo rigo di log, nascosto perché l'installer gira con `runhidden`.
7. **`storico_ceo.json` non viene migrato** e V3 non lo usa più: verificare se la modalità CEO V2 lo usava per gli anni passati.
8. **Formati degli importi.** I pagamenti hanno importi con virgola (257), interi (117) e 1 con il punto: `safe_money` legge "1.500" come 1,5 €. Va trovato e controllato a mano.

---

## 3. Fotografia attuale dei dati (letta oggi, sola lettura)

| Copia | Preventivi JSON | Clienti JSON | Note |
|---|---|---|---|
| `GESTIONALE CERLAB\preventivi` + `\clienti` (radice) | 441 | 305 | La più recente (ultima modifica 2 ott 2026). **2 file JSON corrotti**: `PREV-VZ-02ST2609A43.json`, `PREV-VZ-08LU2610A03.json` ("Extra data") |
| `GESTIONALE CERLAB\data\` | 400 | 293 | Copia del 9 settembre |
| `GESTIONALE CERLAB v3\data\` (JSON) | 400 | 293 | Stessa copia del 9 settembre |
| `GESTIONALE CERLAB v3\data\gestionale.db` | 425 preventivi, 296 clienti, 366 ordini, 239 bolle | | DB di sviluppo, già usato in V3 |
| `%APPDATA%\GestionalePreventivi` su questo PC | 132 | 0 | Vecchia installazione, non rilevante |

Confronto tra i 439 JSON leggibili della radice e il DB V3 di sviluppo:

- 41 preventivi solo nei JSON (creati dopo il 9 settembre), 27 solo nel DB (es. `EDIL-FD-1502261912`, `EDIL-ADM-0205261000`: creati in prova su V3 o cancellati in V2).
- Su 398 in comune: **111 con stato diverso**, tra cui 56 `Chiuso` → `In Lavorazione`, 22 `Annullato` → `Inviato`, 9 `Annullato` → `Bozza`, 5 `Inviato` → `Bozza`, 4 `Chiuso` → `Bozza`.
- 142 con `data_conferma` diversa, 59 con stato pagamento diverso, 44 con somma incassi diversa, 23 con totale diverso.

Il DB di sviluppo quindi **non è** una base affidabile: la migrazione vera va rifatta da zero sui JSON più recenti. I casi `→ Bozza` sono in parte spiegati dallo "sblocca" (`gestionale.py:3901`, rimette in Bozza) e dal fatto che il DB è più vecchio; i casi `Chiuso → In Lavorazione` sono coerenti con il punto 2.2.

Distribuzione stati nei JSON di origine: Annullato 221, Chiuso 110, Inviato 64, In Lavorazione 33, Bozza 10, Confermato 1. Stato pagamento: Da Saldare 282, Saldato 157. `data_conferma` presente in 176 preventivi su 439, sempre nel formato `AAAA-MM-GG`.

---

## 4. Cosa confrontare per dimostrare che la migrazione è corretta

Uno script di confronto (da scrivere, in sola lettura su entrambe le parti) legge i JSON di origine e il DB migrato e produce un report CSV/HTML con una riga per differenza. Chiave di confronto: `numero` per i preventivi, `id_cliente` per i clienti, `ordine_id` per gli ordini, `(numero, id)` per le bolle.

### 4.1 Conteggi
- Numero di preventivi, clienti, ordini, bolle, pagamenti, utenti, task, messaggi, tagbox, notifiche, fasce margini: origine = DB.
- Elenco dei record presenti solo da una parte (atteso: zero, più i JSON corrotti spiegati).

### 4.2 Preventivi, campo per campo
- Anagrafica e testata: `data`, `venditore`, `cliente`, `id_cliente`, indirizzo, `p_iva`, `codice_univoco`, `tipo_preventivo`, `no_iva`, `iva_pct`, `fee_pct`.
- Stato: `stato`, `is_locked`, `data_conferma`, `data_chiusura`, `data_annullamento`, `stato_pagamento_globale`, `stato_consegna_globale`, `stato_fattura`.
- Importi: `totale`, `tot_imponibile_cliente`, `tot_imponibile_negozio`, `tot_iva`, `imponibili_iva`, `tot_iva_dettaglio` (confronto numerico con tolleranza 0,01 €, dopo normalizzazione virgola/punto).
- Righe: numero di righe, e per ogni riga articolo, quantità, prezzi, `stato_consegna`; per gli edili `sezioni_edili` e `righe_edili`.
- Campi oggi persi (punto 2.2): il report li elenca separatamente, così si vede quanti preventivi ne sono toccati.

### 4.3 Pagamenti e incassi
- Per ogni preventivo: stessi PAY ID, stesse date, stessi importi, stessi `is_scheduled` e `rectifies_id`.
- Somme: incassato (non programmato), programmato, rettifiche, da saldare.

### 4.4 Ordini fornitore e bolle
- Ordini: `azienda`, `data_ordine`, `numero_conferma`, importi, `iva_ordine`, `data_arrivo`, `indici_righe`, `allegati`, preventivo di appartenenza.
- Bolle: `data`, `indirizzo_cantiere_id`, `indici_righe`.

### 4.5 Allegati su disco
- Per ogni voce di `allegati` (preventivo), `allegati` (ordine), `fatture_allegate`/`fatture_per_iva`, `documenti_anagrafici` (cliente), `storico_pdf`: il file esiste nella cartella dati di destinazione.
- Per ogni file in `allegati\<numero>\` e `allegati\clienti\<id>\`: è referenziato da qualche record (file orfani elencati, non cancellati).
- I PDF `Preventivo_*` e `BOLLA_*` nella cartella `preventivi\` vanno copiati insieme ai JSON.

### 4.6 Clienti
- Tutti i campi del JSON, inclusi `codice_univoco`, `regione`, `indirizzi_cantiere`, documenti e flag `has_*`.
- Ogni preventivo punta a un `id_cliente` esistente.

---

## 5. Come verificare che i numeri tornino (dashboard, incassi, CEO)

Il riferimento sono i numeri che la versione V2 (JSON) mostra oggi, non quelli ricalcolati a mano.

1. **Fotografia V2.** Avviare la V2 in `--debug` su una copia dei dati (vedi sezione 7) e annotare, per gli stessi periodi (anno in corso, mese corrente, mese precedente, un trimestre chiuso):
   - dashboard principale: aperti, in lavorazione, chiusi, totali;
   - dashboard Pagamenti: incassato, da saldare, programmati, elenco preventivi da saldare;
   - dashboard Ordini, Consegne, Fatture, Esenti;
   - modalità CEO: funnel, imponibile per competenza, incassato netto (cassa), in attesa, da saldare, IVA, fee, margini.
   Meglio salvare l'HTML delle pagine o farne screenshot, così il confronto è ripetibile.
2. **Fotografia V3** sugli stessi dati migrati e gli stessi periodi.
3. **Calcolo indipendente** con uno script che somma direttamente dai JSON: incassato = somma pagamenti non programmati per data pagamento nel periodo; da saldare = totale dovuto (imponibile se esente IVA) − incassato, con tolleranza 0,05 €; competenza = `data_conferma` per Confermato/In Lavorazione/Chiuso, altrimenti `data` (stessa regola di `gestionale.py:4165`).
4. Le tre colonne devono coincidere. Ogni differenza va ricondotta a un preventivo specifico prima di andare avanti.

Punti di attenzione specifici:
- **Rettifiche**: la dashboard CEO "analisi" salta i pagamenti con `rectifies_id` (`gestionale.py:4981`), le altre li sommano. Verificare che V2 e V3 trattino le rettifiche allo stesso modo (53 pagamenti coinvolti).
- **Preventivi saldati in V2 senza pagamenti registrati**: la guardia in `aggiorna_stato_pagamento_globale` li considera saldati con incassato = totale; in CEO però l'incasso non ha una data e non entra nel cashflow. Elencarli e decidere.
- **Esenti IVA**: totale dovuto = imponibile; verificare che dashboard Pagamenti e CEO usino la stessa base.
- **Preventivi senza `data_conferma`** (263): per Confermato/In Lavorazione/Chiuso la competenza ricade sulla data del preventivo. Elencare quelli in stato attivo senza data di conferma.

---

## 6. Rischi e casi limite da coprire

| Caso | Cosa può succedere | Come verificarlo |
|---|---|---|
| Preventivi riportati in Bozza | Lo "sblocca" rimette in Bozza; nel DB di sviluppo ci sono 20 casi `→ Bozza` | Report stato per stato; verificare che dopo la migrazione pulita siano zero |
| Chiuso riaperto | Perdita di `stati_fattura_iva` → `stato_fattura` sbagliato → `In Lavorazione` al primo salvataggio | Migrare, poi aprire e salvare un campione di Chiusi e confrontare di nuovo |
| `data_conferma` | Assente in 263 preventivi; V3 la imposta a oggi alla conferma (`gestionale.py:3944`) | Elenco preventivi attivi senza data; nessuna data deve cambiare dopo migrazione e salvataggio |
| JSON corrotti | 2 file oggi; il preventivo non viene migrato | Ripararli a mano su una copia prima della migrazione |
| Ordini senza id / duplicati | Id casuale, o ordine scartato senza avviso | Conteggio ordini origine = DB |
| Importi con il punto | "1.500" letto come 1,5 € | Elenco importi non nel formato atteso |
| Pagamenti senza PAY ID | `fix_pagamenti` li modifica | Confronto prima/dopo il fix |
| Record creati in V3 di prova | 27 preventivi solo nel DB di sviluppo | Decidere: scartarli (DB nuovo) o riportarli |
| Doppio avvio della migrazione | Messaggi duplicati; record vecchi non aggiornati | Sempre su DB vuoto; controllo duplicati messaggi |
| Utenti e password | Hash copiati; se l'installer copia `users.json` dello sviluppo, credenziali sbagliate | Login di prova con ogni ruolo (admin, venditore, segreteria, CEO) |
| Percorsi allegati | Allegati V2 in `DATA_DIR\allegati`, V3 li cerca nello stesso posto | Verifica file per file (4.5) |

---

## 7. Come ripetere la migrazione in sicurezza su copie

Regola: la migrazione non tocca mai i dati originali né l'AppData vero.

1. **Copia congelata della sorgente.** Copiare `GESTIONALE CERLAB\preventivi`, `\clienti`, `\allegati` e i file di `\data` (users, tasks, messages, tagbox, notifications, config_margini, storico_ceo) in una cartella datata, per esempio `D:\migrazione_test\2026-10-02\sorgente\`, e renderla di sola lettura. Calcolare un hash (SHA-256) di ogni file per dimostrare dopo che non è cambiata.
2. **Cartella di lavoro separata**: `...\lavoro\` con la stessa struttura di `DATA_DIR` (copia della sorgente), più un DB vuoto.
3. **Puntare V3 alla copia.** Oggi non si può: `models.py` decide il percorso del DB da solo. Serve una piccola modifica (variabile d'ambiente o parametro, es. `GESTIONALE_DB_PATH`, che `fix_pagamenti_v2.py` già si aspetta) prima di qualunque prova.
4. **Eseguire**: migrazione → fix pagamenti → script di confronto (sezione 4) → avvio V3 in `--debug` sulla copia → fotografia dashboard (sezione 5).
5. **Ripetibilità.** Cancellare `lavoro\` e ripetere dal punto 2: due esecuzioni devono dare lo stesso report. Ogni esecuzione salva log e report in una cartella con data e ora.
6. **Prova installer** su un PC o una macchina virtuale con una V2 installata e i dati copiati: installare V3, aggiornare una seconda volta (per verificare il punto 2.1) e ripetere il confronto.

---

## 8. Ordine di lavoro proposto

1. **Mettere al sicuro il codice.** Le modifiche V3 (35 file modificati e 10 non tracciati) non sono committate: farne un commit su un branch dedicato prima di toccare la migrazione.
2. **Copia congelata dei dati** (7.1), riparazione su copia dei 2 JSON corrotti.
3. **Rendere configurabile il percorso del DB** e spostarlo in `DATA_DIR` (risolve 2.1 e abilita le prove su copia).
4. **Scrivere lo script di confronto** (sezione 4) e lo script di calcolo indipendente dei numeri (sezione 5). Eseguirlo subito sul DB di sviluppo attuale per avere un primo report delle differenze.
5. **Completare lo schema**: aggiungere al DB i campi oggi persi (punto 2.2), con migrazione dello schema idempotente come già fatto in `_apply_schema_migrations`, e aggiornare `migrate_v3_installer.py`, `save_quote` e `to_dict`. In alternativa, una colonna JSON "extra" che conserva tutto ciò che non ha una colonna dedicata, così nessun campo futuro si perde.
6. **Rendere la migrazione verificabile**: contare ordini/bolle saltati, fallire in modo visibile se ci sono errori, non generare id casuali, evitare messaggi duplicati.
7. **Sistemare l'installer**: escludere `gestionale.db`, i flag e i file di stato dalla copia di `data\*`, usare `onlyifdoesntexist` per i file di configurazione, fare un backup della cartella dati prima di `--run-migration`, e mostrare all'utente l'esito (non `runhidden` in caso di errore).
8. **Ciclo di prova su copia** (sezione 7) finché il report è vuoto o ogni differenza è spiegata e accettata.
9. **Prova dell'installer** su macchina di prova, incluso un secondo aggiornamento.
10. **Migrazione vera**: fermare l'uso della V2, ultima copia dei JSON, backup completo di `%APPDATA%\GestionalePreventivi`, installazione V3, report di confronto finale e controllo dashboard/CEO con il CEO stesso. Tenere la V2 e il backup pronti per tornare indietro per un periodo concordato.

---

## 9. Decisioni prese (2 ottobre 2026)

- **Dati veri**: sono sul PC del cliente; la migrazione la deve fare l'installer al momento dell'aggiornamento. Per le prove si usa un backup del cliente ripristinato in `%APPDATA%\GestionalePreventivi` su questo PC.
- **Banco di prova**: si simula il percorso reale del cliente (V2 installata + backup in AppData → installer V3 come aggiornamento). La cartella `GESTIONALE CERLAB` serve solo come riferimento per lo script di confronto, non come sorgente della migrazione.
- **Dati V3 di sviluppo**: sono tutti simulati, nessun preventivo o modifica va importato. Il DB V3 parte sempre vuoto e `data\gestionale.db` di sviluppo non deve mai finire nell'installer.
- **Storico CEO** (`storico_ceo.json`): non serve.
- **Rilasci**: l'aggiornamento automatico installa qualunque nuova release su GitHub, quindi nessuna pubblicazione (passo GitHub di `build.py`) finché la verifica non è chiusa. I commit locali su un branch non attivano aggiornamenti.

## 10. Domande aperte

1. **Dove sono i dati vivi?** La radice `GESTIONALE CERLAB\preventivi` sembra una copia sincronizzata (contiene `desktop.ini`) dal PC del negozio. Il gestionale V2 in uso scrive in `%APPDATA%\GestionalePreventivi` di quale PC? Da lì va fatta la copia finale.
2. **I 27 preventivi presenti solo nel DB V3 di sviluppo** sono prove da buttare o lavoro reale da conservare?
3. **Git**: la cartella V3 è già un repository collegato a `github.com/Latereyes/gestionale-cerlab-`, ma tutto il lavoro V3 recente non è committato. Posso fare un commit su un branch dedicato prima di iniziare le modifiche? Il repository serve collegato al progetto solo se vuoi che lavori anche dal cloud o apra delle PR.
4. **`storico_ceo.json`**: contiene dati storici che la modalità CEO deve continuare a mostrare?
5. **Periodo di convivenza**: V2 e V3 devono girare in parallelo per un po' (con migrazioni ripetute) o si passa in un colpo solo?
6. **Chi conferma i numeri**: chi controlla le dashboard CEO alla fine, e per quali periodi?
