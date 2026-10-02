# Piano di Implementazione V2 — Gestionale Cerlab

> **Creato:** 28/09/2026 — Sessione 5

---

## Overview

| # | Area | Priorità | Stato |
|---|------|----------|-------|
| **P1** | Revisione tecnica layout di stampa | 🔴 Alta | 🟡 Quasi completo (02/10) |
| **P2** | Tasto "Note Cliente" nella toolbar laterale | 🟡 Media | ✅ Fatto (02/10) |
| **P3** | Test flusso preventivo + CEO + arrotondamenti | 🔴 Alta | ⏳ Da fare |

---

## P1 — Revisione Tecnica Layout di Stampa

> **Obiettivo:** rendere i 4 template di stampa (`stampa.html`, `stampa_semplice.html`, `stampa_edile.html`, `stampa_bolla.html`) **100% affidabili** in produzione su qualsiasi stampante/browser.

### Problemi noti da risolvere

| ID | Problema | File | Gravità |
|----|---------|------|---------|
| S1 | Righe tabella che si spezzano a metà pagina (`page-break-inside`) | tutti | 🔴 |
| S2 | Colori di sfondo delle righe alternate NON stampati di default (browser) | `stampa.html`, `stampa_semplice.html` | 🟡 |
| S3 | Sezione firma + note potrebbe finire su pagina separata dal corpo | tutti | 🔴 |
| S4 | `@bottom-center` con contatore pagina: non supportato da tutti i browser (solo WeasyPrint/Chrome) | tutti | 🟡 |
| S5 | Font Inter caricato da Google Fonts — non disponibile offline/stampa senza internet | tutti | 🟡 |
| S6 | Immagine logo via `url_for` — path relativo che potrebbe rompersi in PDF headless | tutti | 🔴 |
| S7 | Colonna "Articolo" non ha `word-wrap` → testi lunghi escono dal bordo | `stampa.html`, `stampa_semplice.html` | 🟡 |
| S8 | `stampa_bolla.html` non include numero preventivo nel `<title>` | `stampa_bolla.html` | 🟢 |
| S9 | Mancata gestione preventivo con 0 righe o con solo righe vuote | tutti | 🟡 |
| S10 | Numero cliente e tel. aggiunto ma non testato visivamente | tutti | 🟢 |

### Task

- [x] **S-T1** — Aggiungere `word-wrap: break-word` su `td` nelle tabelle articoli
- [x] **S-T2** — Aggiungere `page-break-inside: avoid` su ogni `<tr>` delle tabelle
- [x] **S-T3** — Forzare `-webkit-print-color-adjust: exact` globalmente in `@media print` su tutti i template
- [x] **S-T4** — Sostituire font Google con fallback system font per stampa offline (aggiungere `@media print { body { font-family: 'Helvetica Neue', Arial, sans-serif; } }`)
- [x] **S-T5** — Verificare che `url_for('static', ...)` per il logo funzioni in modalità headless (WeasyPrint) → ok: Chrome/Edge apre l'URL http, WeasyPrint usa `base_url=request.url_root`
- [x] **S-T6** — Aggiungere gestione `{% if p.righe %}...{% else %}<p>Nessun articolo</p>{% endif %}` per preventivi vuoti
- [ ] **S-T7** — Test visivo su Chrome + Firefox dei 4 template con un preventivo reale
- [ ] **S-T8** — Test PDF headless (WeasyPrint) per verificare che logo, pagina e colori appaiano correttamente
- [x] **S-T9** — Allineare header company-details: `stampa_edile.html` mancava KRRH6B9 (ora aggiunto) → verificare
- [ ] **S-T10** *(parziale: regole comuni in `templates/_stampa_print_fixes.html`, incluso da tutti i template di stampa)* — Unificare CSS comune dei template in un eventuale `stampa_base.html` (Jinja2 `extends`) per evitare duplicazioni

---

## P2 — Tasto "Note Cliente" nella Toolbar Laterale

> **Obiettivo:** aggiungere un bottone FAB nella sidebar laterale (accanto a task, allert, notifiche) visibile **solo quando si è su una pagina di un preventivo specifico** (`/editor/<id>`, `/conferma-ordine/<id>`, `/gestione-consegna/<id>`, `/gestione-pagamenti/<id>`, `/editor-fattura/<id>`). Permette di creare, leggere e modificare note libere associate al cliente del preventivo.

### Architettura

```
DB: tabella clienti → aggiunta colonna "note" (TEXT)
    ↕
Backend: route GET/POST /api/cliente/<id>/note
    ↕
Frontend: pannello modale laterale in base.html (slide-in dal lato destro)
           attivato dal bottone FAB .note-fab
```

### Struttura dati

La nota è un **testo libero** salvato sul **Cliente** (non sul preventivo), così è visibile da qualsiasi preventivo dello stesso cliente.

```python
# models.py — Cliente
note_interne = Column(Text, default="")   # ← nuova colonna
```

> [!NOTE]
> La colonna va aggiunta anche in `MIGRATIONS` in `models.py` per essere retrocompatibile con DB esistenti.

### Task

- [x] **N-T1** — `models.py`: aggiungere `note_interne = Column(Text, default="")` a `Cliente` + entry in `MIGRATIONS`
- [x] **N-T2** — `gestionale.py`: aggiungere route `GET /api/cliente/<id>/note` → restituisce `{ note: "..." }`
- [x] **N-T3** — `gestionale.py`: aggiungere route `POST /api/cliente/<id>/note` con body `{ note: "..." }` → salva e risponde `{ ok: true }`
- [x] **N-T4** — `base.html`: aggiungere bottone `.note-fab` nel gruppo FAB (solo se `current_quote_id` è definito nel contesto Jinja)
- [x] **N-T5** — `base.html`: creare pannello `#noteClientePanel` (slide-in da destra) con:
  - Header: nome cliente + badge "Note Interne"
  - `<textarea>` per editing note
  - Bottone "Salva" + indicatore "Salvato ✓"
  - Bottone "Chiudi"
- [x] **N-T6** — `gestionale.py`: passare `current_quote_id` e `current_client_id` nel context di `base.html` tramite `g` o `before_request` (leggendo il parametro URL `quote_id`) → fatto con il context processor `inject_current_quote_client`. Nota: la colonna si chiama `note_interne`; la route è `api_note_cliente` (GET/POST in un'unica funzione)
- [x] **N-T7** — Test: aprire pannello, scrivere nota, salvare, ricaricare pagina → nota persiste
- [x] **N-T8** — Test: navigare da preventivo A (cliente X) a preventivo B (cliente Y) → note diverse

### UX del pannello

```
┌─────────────────────────────────────┐
│ 📝 Note — Mario Rossi               │ ← header con nome cliente
│──────────────────────────────────── │
│ ┌─────────────────────────────────┐ │
│ │ Note libere sul cliente...      │ │ ← textarea (min 8 righe)
│ │                                 │ │
│ └─────────────────────────────────┘ │
│                                     │
│  [💾 Salva Note]         ✓ Salvato  │
│                     [✕ Chiudi]      │
└─────────────────────────────────────┘
```

---

## P3 — Test Flusso Preventivo + CEO + Arrotondamenti

> **Obiettivo:** validazione sistematica del sistema con un preventivo reale, verificando arrotondamenti, logica ceo e filtro temporale.

### 3A — Test Flusso Preventivo Completo

| Step | Azione | Cosa verificare |
|------|--------|-----------------|
| 1 | Creare preventivo commerciale con ≥5 righe, IVA mista (22%+10%+4%) | Numero generato correttamente |
| 2 | Calcolo totali | Imponibile = Σ(prezzo × qt); IVA per aliquota; Totale = imponibile + IVA totale |
| 3 | Passare a stato "Inviato" | Badge aggiornato |
| 4 | Passare a stato "Confermato" → `data_conferma` salvata | Verificare che `data_conferma` sia il giorno di oggi |
| 5 | Registrare ordine parziale | Badge Ordini = "Parziale" |
| 6 | Completare ordini | Badge Ordini = "Ordinato" |
| 7 | Registrare consegna parziale | Badge Consegna = "Parziale" |
| 8 | Completare consegne | Badge Consegna = "Consegnato" |
| 9 | Saldare con acconto | Badge Saldo = "Acconto" |
| 10 | Saldare completo | Badge Saldo = "Saldato" |

### 3B — Test Arrotondamenti

> **Scenario critico:** preventivo con quantità decimali e prezzi che generano frazioni di centesimo.

| Caso | Input | Atteso |
|------|-------|--------|
| Prezzo unitario × qt decimale | `€ 12,33 × 3,5` | Imponibile = `€ 43,16` (round half-even) |
| IVA 22% su imponibile decimale | `€ 43,16 × 22%` | IVA = `€ 9,50` |
| Totale = somma righe | più righe con arrotondamenti | Totale ≠ somma dei singoli arrotondamenti (verifica tolleranza ±0.05) |
| Pagamento parziale | Acconto `€ 50,00` su totale `€ 1.234,56` | Residuo = `€ 1.184,56` |

- [ ] **R-T1** — Creare preventivo ad hoc con valori decimali complessi
- [ ] **R-T2** — Verificare che `tot_imponibile_cliente` = somma di tutti i `tot_prezzo` delle righe
- [ ] **R-T3** — Verificare che `totale` = `tot_imponibile_cliente` + `tot_iva`
- [ ] **R-T4** — Verificare che `totale_da_saldare` = `totale` − `totale_pagato` (tolleranza ±0.05 già presente a riga 1195)
- [ ] **R-T5** — Controllare che il PDF stampato mostri gli stessi valori del gestionale

### 3C — Test Modalità CEO con Pagamento in Data Successiva

> **Obiettivo:** verificare che la dashboard CEO attribuisca ogni pagamento al **mese in cui il pagamento è stato effettuato**, indipendentemente dalla data di conferma del preventivo.

**Comportamento attuale — analisi codice:**

Il codice CEO ha **due logiche separate**:

```python
# A. LOGICA COMPETENZA (riga 3751) — usa data_conferma del preventivo
#    → controlla se il preventivo rientra nel periodo selezionato
#    → usata per: Funnel, KPI imponibile, margini, costi

in_periodo = start_date <= p_date <= end_date   # p_date = data_conferma

# B. LOGICA CASSA (riga 3836) — usa la data del singolo pagamento ✅
#    → filtra ogni pagamento per la sua data reale
#    → usata per: cashflow["incassato_netto"], IVA, fee

if start_date <= d_pag <= end_date and not pag.get("is_scheduled"):
    cashflow["incassato_netto"] += val_netto
```

> [!NOTE]
> **La logica di cassa (pagamenti) usa già la data del pagamento** — è già corretta.
> Il problema potenziale è nella logica di competenza (sezione A): se si filtra gennaio, un preventivo confermato a gennaio ma i cui ordini arrivano a febbraio viene comunque contabilizzato nei costi di gennaio.

> [!WARNING]
> **Comportamento da verificare:** `da_saldare_netto` (residuo ancora da incassare) viene calcolato nella sezione A (filtro competenza), non in base alle date dei pagamenti. Questo significa che il "da saldare" appare nel mese della conferma, non nel mese previsto di incasso.

**Decisione dell'utente:** ✅ La data corretta è quella del **singolo pagamento** per tutto ciò che riguarda il cashflow.

**Test da eseguire:**

| # | Setup | Filtro CEO | KPI atteso | Da verificare |
|---|-------|-----------|------------|---------------|
| T1 | Preventivo confermato 15/01, acconto pagato 01/02 | Gennaio | `incassato_netto` = 0 (acconto è di febbraio) | ✅/❌ |
| T2 | Preventivo confermato 15/01, acconto pagato 01/02 | Febbraio | `incassato_netto` include l'acconto | ✅/❌ |
| T3 | Preventivo confermato 15/01, saldo pagato 28/02 | Gennaio | `da_saldare_netto` non dovrebbe comparire | ⚠️ Bug potenziale |
| T4 | Preventivo confermato 15/02, acconto+saldo in febbraio | Febbraio | Tutto visibile e corretto | ✅/❌ |
| T5 | Pagamento `is_scheduled=True` (futuro) | qualsiasi | Appare in `in_attesa_netto`, non in `incassato` | ✅/❌ |

- [ ] **C-T1** — Creare preventivo test: confermarlo con `data_conferma` nel mese precedente
- [ ] **C-T2** — Registrare un pagamento (acconto) con data nel mese corrente
- [ ] **C-T3** — Dashboard CEO → filtro mese precedente → verificare che `incassato_netto` = 0 per quell'acconto (**già corretto nel codice**)
- [ ] **C-T4** — Dashboard CEO → filtro mese corrente → verificare che `incassato_netto` include l'acconto
- [ ] **C-T5** — Verificare `da_saldare_netto`: attualmente calcolato con logica competenza (sezione A). Se il preventivo è confermato a gennaio, il residuo appare a gennaio anche se il saldo arriverà a marzo → **potenziale bug da correggere**
- [ ] **C-T6** — Se C-T5 è un bug: spostare il calcolo di `da_saldare_netto` nella sezione B (logica cassa), usando la data dei pagamenti futuri (`is_scheduled=True`) come data di riferimento per il periodo
- [ ] **C-T7** — Re-test completo dopo eventuale fix di C-T6


---

## P4 — Redesign Dashboard Ordini, Consegne e Pagamenti

> **Obiettivo:** trasformare le 3 dashboard globali da semplici elenchi tabulari a pagine operative ricche di informazioni contestuali, con KPI in testa, stato visivo chiaro e accesso rapido alle azioni prioritarie.

### Stato attuale — problemi identificati

| Dashboard | URL | Problema principale |
|-----------|-----|---------------------|
| [`dashboard_ordini.html`](file:///c:/Users/andre/Documents/GESTIONALE%20CERLAB%20v3/templates/dashboard_ordini.html) | `/ordini` | Solo N° preventivo + data + testo grezzo "X articoli da ordinare". Nessun KPI. Nessuna urgenza visiva. |
| [`dashboard_consegne.html`](file:///c:/Users/andre/Documents/GESTIONALE%20CERLAB%20v3/templates/dashboard_consegne.html) | `/consegne` | Solo N° preventivo + data + "X articoli in attesa". Nessuna barra di progresso, nessun indirizzo visibile. |
| [`dashboard_pagamenti.html`](file:///c:/Users/andre/Documents/GESTIONALE%20CERLAB%20v3/templates/dashboard_pagamenti.html) | `/pagamenti` | Ha più colonne ma badge stato non usa il sistema globale, colori hardcoded, nessun totale aggregato per cliente. |

---

### P4.1 — Dashboard Ordini (`/ordini`)

**Miglioramenti:**

- **KPI strip in cima** — totale preventivi con ordini aperti, totale articoli da ordinare, totale in attesa di conferma
- **Badge stato** — sostituire il testo grezzo con badge semantici (`status-badge`) già usati nel resto del gestionale
- **Numero preventivo abbreviato** — stessa logica `p.numero[:8]+'…'+p.numero[-5:]` già implementata
- **Urgenza visiva** — bordo sinistro colorato se ci sono articoli ancora da ordinare (rosso) vs solo in attesa conferma (arancione) vs ordinato (verde)
- **Colonna fornitore** — mostrare il nome del fornitore degli ordini aperti quando disponibile
- **Token CSS** — sostituire tutti i colori hardcoded (`#dc3545`, `#ff9800`, `#198754`) con variabili CSS

**Task:**
- [ ] **O-T1** — Aggiungere strip KPI sopra la lista (3 card: preventivi attivi, articoli da ordinare, in attesa conferma)
- [ ] **O-T2** — Sostituire testo grezzo stato con `status-badge` semantici (`status-annullato` = da ordinare, `status-parziale` = parziale, `status-confermato` = ordinato)
- [ ] **O-T3** — Aggiungere bordo sinistro colorato per urgenza (`border-left: 4px solid var(--danger)`)
- [ ] **O-T4** — Troncare numero preventivo con tooltip completo
- [ ] **O-T5** — Aggiornare CSS con token CSS del design system (rimuovere colori hardcoded)
- [ ] **O-T6** — Aggiungere colonna "Venditore" per filtrare rapidamente i propri ordini

---

### P4.2 — Dashboard Consegne (`/consegne`)

**Miglioramenti:**

- **KPI strip** — totale preventivi con consegne aperte, totale articoli da consegnare, totale bolla emesse
- **Barra di progresso** — `N consegnati / M totali` visualizzato come progress bar orizzontale invece di testo
- **Indirizzo di consegna** — mostrare in piccolo l'indirizzo cantiere/cliente nella riga (info chiave per il magazzino)
- **Badge stato** — "Parziale" / "Da Consegnare" / "Pronto" con colori semantici
- **Urgenza** — bordo colorato se ci sono articoli pronti ma non ancora consegnati

**Task:**
- [ ] **D-T1** — Aggiungere strip KPI (preventivi aperti, articoli totali da consegnare, bolle emesse)
- [ ] **D-T2** — Sostituire "X articoli in attesa" con barra progresso `<progress>` + testo `N/M`
- [ ] **D-T3** — Aggiungere riga sub-info con indirizzo di consegna (se disponibile nel preventivo)
- [ ] **D-T4** — Badge stato con sistema `status-badge` del design system
- [ ] **D-T5** — Aggiornare CSS con token CSS (rimuovere hardcoded)
- [ ] **D-T6** — Aggiungere backend: verificare che la route `/consegne` passi `articoli_da_consegnare_totale` oltre a `articoli_da_consegnare_count` per poter calcolare la percentuale

---

### P4.3 — Dashboard Pagamenti (`/pagamenti`)

**Miglioramenti:**

- **KPI strip** — totale da incassare (tutti i clienti), totale già incassato, totale scaduto/in allerta
- **Badge stato unificato** — usare `status-badge` del design system al posto di `.status-tag` custom
- **Totale per cliente** — aggiungere riga di subtotale in fondo a ogni card-cliente con somma "Da Saldare"
- **Allerta visiva migliorata** — la riga allerta (bordo sinistro colorato) esiste già ma i colori sono hardcoded → portare a token CSS
- **Colonna "Giorni"** — mostrare quanti giorni sono passati dall'ultimo pagamento (già parzialmente calcolato in backend con `allerta_giorni`)
- **Data leggibile** — `ultimo_pagamento_data` ora mostra `YYYY-MM-DD` grezzo → formattare come `DD/MM/YYYY`
- **Token CSS** — `.total-main`, `.total-paid`, `.total-future`, `.total-due` usano colori hardcoded Bootstrap → portare a token

**Task:**
- [ ] **P-T1** — Aggiungere strip KPI globale (totale da incassare, totale pagato, n° preventivi in allerta)
- [ ] **P-T2** — Sostituire `.status-tag` con `status-badge` del design system
- [ ] **P-T3** — Aggiungere riga subtotale per-cliente in fondo ad ogni card
- [ ] **P-T4** — Formattare `ultimo_pagamento_data` come `DD/MM/YYYY` (o via filtro Jinja2 o via JS)
- [ ] **P-T5** — Aggiungere colonna "Giorni" (giorni dall'ultimo pagamento, con colore semantico)
- [ ] **P-T6** — Portare `.total-*` a token CSS (`var(--accent)`, `var(--success-text)`, `var(--danger-text)`)
- [ ] **P-T7** — Portare bordi allerta a token CSS (`var(--warning)`, `var(--danger)`)

> [!NOTE]
> Per P4.3, il backend nella route `/pagamenti` (riga 4982) già calcola `totale_pagato`, `totale_da_saldare`, `totale_da_incassare`, `ultimo_pagamento_data` e `allerta_giorni` — i dati ci sono, serve solo esporli meglio nell'UI.

---

```
P1 (Stampa) — indipendente, può partire subito
P2 (Note)   — richiede: N-T1 (DB) → N-T2/T3 (backend) → N-T4/T5 (frontend)
P3 (Test)   — indipendente, ma P3C richiede chiarimento logica CEO (C-T6)
```

---

## Stato avanzamento

> Aggiornato 02/10/2026. Anche S10 (tel./email/N. cliente in stampa) risultava già fatto.

| Area | Completato | Totale | % |
|------|-----------|--------|---|
| P1 — Stampa | 7 | 10 | 70% (mancano S-T7 test Chrome+Firefox a vista, S-T8 test WeasyPrint, S-T10 completo) |
| P2 — Note Cliente | 8 | 8 | 100% |
| P3 — Testing | 0 | 15 | 0% |
| P4 — Dashboard Ordini/Consegne/Pagamenti | ~20 | 20 | ✅ fatto il 02/10 (KPI, badge, barre di avanzamento, venditore, giorni, stili comuni in `_workflow_dashboard_styles.html`) |

