import datetime
import uuid
import re
from functools import wraps
from flask import session, redirect, url_for, flash, request
from models import SessionLocal, Cliente, Preventivo
from jinja2.runtime import Undefined

# ---- FUNZIONI DB E STATI ----
def get_flat_righe_edili(p):
    """
    Versione con retrocompatibilità: gestisce sia la nuova struttura a sezioni 
    che la vecchia lista piatta 'righe_edili'.
    """
    flat_list = []
    if p.get("tipo_preventivo") != "edile":
        return p.get("righe", [])
    
    indice_assoluto = 0
    
    # --- 1. TENTATIVO NUOVA STRUTTURA (Sezioni) ---
    if "sezioni_edili" in p and p["sezioni_edili"]:
        for sezione in p["sezioni_edili"]:
            for riga in sezione.get("righe", []):
                r_copy = riga.copy()
                r_copy["original_index"] = indice_assoluto
                # Campi virtuali per compatibilità
                r_copy["qt"] = "1"
                r_copy["unt"] = "Lav."
                r_copy["tot_prezzo"] = riga.get("prezzo_vendita", "0")
                
                # Calcolo IVA per fatturazione
                prezzo = _to_num(riga.get("prezzo_vendita", 0))
                iva_pct = _to_num(riga.get("iva_pct", 10))
                r_copy["tot_iva_riga"] = f"{(prezzo * iva_pct / 100):.2f}".replace(".", ",")
                
                flat_list.append(r_copy)
                indice_assoluto += 1
                
    # --- 2. TENTATIVO VECCHIA STRUTTURA (Fallback retrocompatibilità) ---
    elif "righe_edili" in p and p["righe_edili"]:
        for riga in p["righe_edili"]:
            r_copy = riga.copy()
            r_copy["original_index"] = indice_assoluto
            r_copy["qt"] = "1"
            r_copy["unt"] = "Lav."
            r_copy["tot_prezzo"] = riga.get("prezzo_vendita", "0")
            
            prezzo = _to_num(riga.get("prezzo_vendita", 0))
            iva_pct = _to_num(riga.get("iva_pct", 10))
            r_copy["tot_iva_riga"] = f"{(prezzo * iva_pct / 100):.2f}".replace(".", ",")
            
            flat_list.append(r_copy)
            indice_assoluto += 1
            

def get_all_quotes(user_role=None, full_name=None): # Rinominato user_name -> username
    """Restituisce un elenco di preventivi, filtrato per venditore se richiesto."""
    quotes = []
    try:
        session = SessionLocal()
        if user_role == 'venditore' and full_name:
            db_quotes = session.query(Preventivo).filter_by(venditore=full_name).all()
        else:
            db_quotes = session.query(Preventivo).all()
            
        for db_quote in db_quotes:
            quotes.append({
                "numero": db_quote.numero, 
                "data": db_quote.data,
                "cliente": db_quote.cliente, 
                "totale": db_quote.totale,
                "stato": db_quote.stato or "Bozza"
            })
    except Exception as e:
        print(f"Errore nel caricare i preventivi dal DB: {e}")
    finally:
        session.close()
    
    quotes.sort(key=lambda x: x.get("numero", ""), reverse=True)
    return quotes
def get_new_quote_id(venditore_sigla):
    if not venditore_sigla: venditore_sigla = "XX"
    now = datetime.datetime.now()
    mesi_map = {1: "GN", 2: "FB", 3: "MR", 4: "AP", 5: "MG", 6: "GU", 7: "LU", 8: "AG", 9: "ST", 10: "OT", 11: "NV", 12: "DC"}
    prefix = "PREV-"; giorno = now.strftime('%d'); mese = mesi_map[now.month]; anno = now.strftime('%y'); ora = now.strftime('%I'); ampm = 'A' if now.strftime('%p') == 'AM' else 'P'; minuti = now.strftime('%M')
    return f"{prefix}{venditore_sigla.upper()}-{giorno}{mese}{anno}{ora}{ampm}{minuti}"
def load_quote(quote_id):
    try:
        session = SessionLocal()
        db_quote = session.query(Preventivo).filter_by(numero=quote_id).first()
        if db_quote:
            return db_quote.to_dict()
    except Exception as e:
        print(f"Errore nel caricare il preventivo {quote_id} dal DB: {e}")
    finally:
        session.close()
    return None
def save_quote(quote_id, data):
    data = aggiorna_stato_pagamento_globale(data)
    try:
        session = SessionLocal()
        db_quote = session.query(Preventivo).filter_by(numero=quote_id).first()
        if not db_quote:
            db_quote = Preventivo(numero=quote_id)
            session.add(db_quote)
            
        db_quote.data = data.get('data', '')
        db_quote.venditore = data.get('venditore', '')
        db_quote.cliente = data.get('cliente', '')
        db_quote.regione = str(data.get('regione', ''))
        db_quote.regione_nome = data.get('regione_nome', '')
        db_quote.indirizzo = data.get('indirizzo', '')
        db_quote.email = data.get('email', '')
        db_quote.telefono = data.get('telefono', '')
        db_quote.referente = data.get('referente', '')
        db_quote.fee_pct = str(data.get('fee_pct', ''))
        db_quote.totale = str(data.get('totale', ''))
        db_quote.comune = data.get('comune', '')
        db_quote.provincia = data.get('provincia', '')
        db_quote.rag_sociale = data.get('rag_sociale', '')
        db_quote.p_iva = data.get('p_iva', '')
        db_quote.cap = data.get('cap', '')
        db_quote.stato = data.get('stato', '')
        db_quote.is_locked = data.get('is_locked', False)
        db_quote.id_cliente = data.get('id_cliente')
        
        db_quote.tot_imponibile_negozio = str(data.get('tot_imponibile_negozio', ''))
        db_quote.tot_imponibile_cliente = str(data.get('tot_imponibile_cliente', ''))
        db_quote.tot_iva = str(data.get('tot_iva', ''))
        db_quote.ricarico_medio_pct = str(data.get('ricarico_medio_pct', ''))
        db_quote.stato_consegna_globale = data.get('stato_consegna_globale', '')
        db_quote.stato_pagamento_globale = data.get('stato_pagamento_globale', '')
        db_quote.stato_fattura = data.get('stato_fattura', '')
        db_quote.data_chiusura = data.get('data_chiusura', '')
        
        db_quote.righe = data.get('righe', [])
        db_quote.imponibili_iva = data.get('imponibili_iva', {})
        db_quote.tot_iva_dettaglio = data.get('tot_iva_dettaglio', {})
        db_quote.storico_pdf = data.get('storico_pdf', [])
        db_quote.pagamenti = data.get('pagamenti', [])
        db_quote.fatture_allegate = data.get('fatture_allegate', [])
        
        session.commit()
    except Exception as e:
        print(f"Errore nel salvare il preventivo {quote_id} nel DB: {e}")
        session.rollback()
    finally:
        session.close()



def aggiorna_stato_consegna_globale(preventivo_data):
    """
    Ricalcola lo stato di consegna globale.
    """
    stato_preventivo = preventivo_data.get("stato")
    is_edile = preventivo_data.get("tipo_preventivo") == "edile"
    
    if is_edile:
        righe = preventivo_data.get("righe_edili", [])
        if not righe:
            preventivo_data["stato_consegna_globale"] = "N/D"
            return
            
        # Consideriamo "Da Consegnare" se lo stato è nullo
        stati = {r.get("stato_consegna") or "Da Consegnare" for r in righe}
        
        if all(s == "Consegnato" for s in stati):
            preventivo_data["stato_consegna_globale"] = "Completato"
        elif any(s in ["Consegnato", "In Bolla", "Pronto per Consegna"] for s in stati):
            preventivo_data["stato_consegna_globale"] = "Parziale"
        else:
            preventivo_data["stato_consegna_globale"] = "Da Consegnare"
        return

    # 1. Trova tutti gli indici confermati (Per preventivi STANDARD)
    ordini_confermati = [
        o for o in preventivo_data.get("ordini_fornitore", []) 
        if o.get("numero_conferma", "").strip()
    ]
    
    indici_confermati = set()
    for o in ordini_confermati:
        indici_confermati.update(o.get("indici_righe", []))

    # --- INIZIO BLOCCO AGGIUNTO: Controllo stato ordini ---
    
    # 2a. Trova tutti gli indici delle righe valide (con un articolo)
    righe_preventivo = preventivo_data.get("righe", [])
    indici_righe_valide = {
        i for i, r in enumerate(righe_preventivo) 
        if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"
    }

    # 2b. Trova tutti gli indici già ordinati e quelli in attesa di conferma
    indici_gia_ordinati = set()
    articoli_in_attesa_conferma = 0
    ordini_fornitore = preventivo_data.get("ordini_fornitore", [])
    
    for ordine in ordini_fornitore:
        indici_ordine = set(ordine.get("indici_righe", []))
        indici_gia_ordinati.update(indici_ordine)
        # Se l'ordine NON è confermato, conta i suoi articoli
        if not ordine.get("numero_conferma", "").strip():
            articoli_in_attesa_conferma += len(indici_ordine)

    # 2c. Calcola articoli ancora da ordinare
    articoli_da_ordinare_count = len(indici_righe_valide - indici_gia_ordinati)

    # 2d. Definisce lo stato "Tutto Ordinato e Confermato"
    #     Questo corrisponde allo stato "Ordinato" che desideri.
    is_tutto_ordinato_e_confermato = (articoli_da_ordinare_count == 0) and (articoli_in_attesa_conferma == 0)
    # --- FINE BLOCCO AGGIUNTO ---


    # 3. Se lo stato non è attivo OPPURE non ci sono proprio articoli confermati,
    # lo stato di consegna è Non Applicabile. (Logica originale invariata)
    if stato_preventivo in ["Bozza", "Inviato", "Annullato"] or not indici_confermati:
        preventivo_data["stato_consegna_globale"] = "N/D"
        return
        
    # 4. Controlla lo stato di consegna SOLO degli indici confermati (Logica originale invariata)
    stati_righe_confermate = set()
    
    for index in indici_confermati:
        if 0 <= index < len(righe_preventivo):
            riga = righe_preventivo[index]
            # Usa "Da Consegnare" come default se lo stato è vuoto o None
            stati_righe_confermate.add(riga.get("stato_consegna") or "Da Consegnare")

    # 5. Determina lo stato globale in base agli stati raccolti
    
    # Rimuovi None o stringhe vuote se sono finite nel set per errore
    stati_puliti = {s for s in stati_righe_confermate if s}

    # --- INIZIO BLOCCO MODIFICATO ---
    if all(s == "Consegnato" for s in stati_puliti):
        
        # Tutti gli articoli CONFERMATI sono stati consegnati.
        # ORA controlliamo se l'intero stato ordine è "Ordinato".
        if is_tutto_ordinato_e_confermato:
            # Sì, tutti gli articoli del preventivo sono ordinati, confermati E consegnati.
            preventivo_data["stato_consegna_globale"] = "Completato"
        else:
            # No, abbiamo consegnato solo gli articoli confermati, 
            # ma altri sono in attesa (da ordinare o da confermare).
            # Lo stato di consegna è quindi "Parziale".
            preventivo_data["stato_consegna_globale"] = "Parziale"

    elif all(s == "Da Consegnare" for s in stati_puliti):
        # Se TUTTI gli articoli confermati sono "Da Consegnare"
        preventivo_data["stato_consegna_globale"] = "Da Consegnare"
    else:
        # Se c'è un mix (alcuni consegnati, altri in bolla, altri da consegnare)
        preventivo_data["stato_consegna_globale"] = "Parziale"
    # --- FINE BLOCCO MODIFICATO ---
def aggiorna_stato_pagamento_globale(p):
    """
    Ricalcola il saldo correggendo:
    1. Formati numerici misti (virgola/punto).
    2. Gestione Esente IVA (usa l'imponibile come target).
    3. Supporto specifico per Preventivi Edili.
    """
    def safe_money(val):
        """ Helper interno robusto per leggere formati moneta con simboli """
        if not val: return 0.0
        # Rimuove simboli valuta, percentuali e spazi extra
        s = re.sub(r"[€%\s]", "", str(val))
        if ',' in s:
            # Se c'è la virgola, rimuove il punto delle migliaia e usa la virgola come decimale
            s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except ValueError:
            return 0.0

    if p.get("tipo_preventivo") == "edile":
        # Usiamo l'appiattimento per calcolare i totali globali in modo infallibile
        flat_righe = get_flat_righe_edili(p)
        tot_imp = sum(safe_money(r.get("prezzo_vendita")) for r in flat_righe)
        tot_iva = sum(safe_money(r.get("prezzo_vendita")) * (safe_money(r.get("iva_pct")) / 100) for r in flat_righe)
        
        p["tot_imponibile_cliente"] = f"{tot_imp:.2f}".replace(".", ",")
        p["tot_iva"] = f"{tot_iva:.2f}".replace(".", ",")
        p["totale"] = f"{(tot_imp + tot_iva):.2f}".replace(".", ",")
        
        # Dettaglio per aliquote
        imp_iva_map = {}
        for r in flat_righe:
            k = str(int(safe_money(r.get("iva_pct"))))
            imp_iva_map[k] = imp_iva_map.get(k, 0.0) + safe_money(r.get("prezzo_vendita"))
        p["imponibili_iva"] = {k: f"{v:.2f}".replace(".", ",") for k, v in imp_iva_map.items()}

    # 1. Determina il "Totale Dovuto" (Target)
    if p.get("no_iva") is True:
        # SE ESENTE IVA: Il cliente deve pagare solo l'imponibile!
        # Usiamo tot_imponibile_cliente se esiste, altrimenti fallback su totale
        totale_dovuto = safe_money(p.get("tot_imponibile_cliente", p.get("totale", "0")))
    else:
        # CASO NORMALE: Il cliente paga il totale (inclusa IVA)
        totale_dovuto = safe_money(p.get("totale", "0"))
    
    # 2. Somma i pagamenti effettuati (escludendo quelli ancora programmati/non confermati)
    totale_pagato = 0.0
    for pay in p.get("pagamenti", []):
        if not pay.get("is_scheduled"):
            totale_pagato += safe_money(pay.get("importo", "0"))
        
    # 3. Calcola il rimanente
    da_saldare = totale_dovuto - totale_pagato
    
    # Tolleranza di 0.05€ per arrotondamenti
    if da_saldare <= 0.05:
        da_saldare = 0.0
        nuovo_stato = "Saldato"
    else:
        nuovo_stato = "Da Saldare"
        
    # 4. Scrive i valori corretti nel JSON
    # Formattiamo alla 'italiana' per la visualizzazione
    def to_ita_str(f_val):
        return f"{f_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    p["totale_pagato"] = to_ita_str(totale_pagato)
    p["totale_da_saldare"] = to_ita_str(da_saldare)
    p["stato_pagamento_globale"] = nuovo_stato
    
    return p

def aggiorna_stato_avanzamento(preventivo_data):
    """
    Aggiorna lo stato di avanzamento del preventivo ('In Lavorazione', 'Chiuso')
    in base alla presenza di ordini, pagamenti, e allo stato di consegna/saldo.
    """
    stato_attuale = preventivo_data.get("stato")

    # MODIFICA 1: Rimuovi "Chiuso" da questo controllo.
    # Vogliamo che i preventivi chiusi vengano RIVALUTATI.
    if stato_attuale in ["Bozza", "Inviato", "Annullato"]:
        return

    # --- La logica di controllo rimane invariata ---
    is_saldato = preventivo_data.get("stato_pagamento_globale") == "Saldato"
    # MODIFICA 2: "Completato" è la chiave per chiudere
    is_consegnato_completamente = preventivo_data.get("stato_consegna_globale") == "Completato"
    is_fatturato = preventivo_data.get("stato_fattura") == "Fatturato"
    is_no_iva = preventivo_data.get("no_iva") == True
    condizione_fattura_ok = is_fatturato or is_no_iva

    # --- MODIFICA 3: Logica di Chiusura / Riapertura ---
    
    # CASO A: Le condizioni per la chiusura SONO soddisfatte
    if is_saldato and is_consegnato_completamente and condizione_fattura_ok:
        if stato_attuale != "Chiuso":
            # Mettiamo in "Chiuso" solo se non lo era già
            preventivo_data["stato"] = "Chiuso"
            preventivo_data["is_locked"] = True
            if "data_chiusura" not in preventivo_data:
                preventivo_data["data_chiusura"] = datetime.date.today().strftime('%Y-%m-%d')
        return # È chiuso e merita di esserlo.

    # CASO B: Le condizioni per la chiusura NON sono soddisfatte
    else:
        # Se NON merita di essere chiuso, ma è segnato come "Chiuso",
        # dobbiamo riaprilo e impostarlo a "In Lavorazione".
        if stato_attuale == "Chiuso":
            preventivo_data["stato"] = "In Lavorazione"
            preventivo_data["is_locked"] = True # Rimane bloccato
            preventivo_data.pop("data_chiusura", None) # Rimuovi la data di chiusura
            return

    # CASO C: Non è "Chiuso" e non merita di esserlo.
    # Controlla se deve passare da "Confermato" a "In Lavorazione"
    has_ordini = bool(preventivo_data.get("ordini_fornitore"))
    has_pagamenti = bool(preventivo_data.get("pagamenti"))
    if (has_ordini or has_pagamenti) and stato_attuale == "Confermato":
        preventivo_data["stato"] = "In Lavorazione"
        preventivo_data["is_locked"] = True 
        return
  

def get_new_client_id(): return f"CLT-{uuid.uuid4().hex[:6].upper()}"
def load_client(client_id):
    try:
        session = SessionLocal()
        db_client = session.query(Cliente).filter_by(id_cliente=client_id).first()
        if db_client:
            return db_client.to_dict()
    except Exception as e:
        print(f"Errore nel caricare il cliente {client_id} dal DB: {e}")
    finally:
        session.close()
    return None

def save_client(client_id, data):
    try:
        session = SessionLocal()
        db_client = session.query(Cliente).filter_by(id_cliente=client_id).first()
        if not db_client:
            db_client = Cliente(id_cliente=client_id)
            session.add(db_client)
            
        db_client.cliente = data.get('cliente', '')
        db_client.telefono = data.get('telefono', '')
        db_client.email = data.get('email', '')
        db_client.regione_nome = data.get('regione_nome', '')
        db_client.provincia = data.get('provincia', '')
        db_client.comune = data.get('comune', '')
        db_client.cap = data.get('cap', '')
        db_client.indirizzo = data.get('indirizzo', '')
        db_client.p_iva = data.get('p_iva', '')
        db_client.rag_sociale = data.get('rag_sociale', '')
        
        session.commit()
    except Exception as e:
        print(f"Errore nel salvare il cliente {client_id} nel DB: {e}")
        session.rollback()
    finally:
        session.close()

def find_clients_by_term(search_term):
    found_clients = []
    if not search_term: return found_clients
    term = search_term.lower()
    try:
        session = SessionLocal()
        from sqlalchemy import or_
        db_clients = session.query(Cliente).filter(
            or_(
                Cliente.cliente.ilike(f"%{term}%"),
                Cliente.rag_sociale.ilike(f"%{term}%")
            )
        ).all()
        for c in db_clients:
            found_clients.append(c.to_dict())
    except Exception as e:
        print(f"Errore ricerca clienti dal DB: {e}")
    finally:
        session.close()
    return found_clients

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("login"))
        # NUOVO: Controlla se l'utente deve cambiare password
        if session.get("force_password_reset") and request.endpoint != 'cambia_password':
            flash("Per favore, imposta una nuova password.", "warning")
            return redirect(url_for("cambia_password"))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    """Decorator per limitare l'accesso a ruoli specifici."""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get("user_role") not in roles:
                flash("Accesso non autorizzato.", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return wrapper



import re

def _to_num(x, default=0.0):
    if x is None: return float(default)
    s = re.sub(r"[€%\s]", "", str(x))
    if not s: return float(default)
    if "," in s and "." in s: s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
    s = s.replace(",", ".")
    try: return float(s)
    except ValueError: return float(default)

def _get_ordine_costo_effettivo_netto(ordine):
    importo_articoli_lordo_salvato = _to_num(ordine.get("importo_articoli"))
    importo_trasporto_lordo_salvato = _to_num(ordine.get("importo_trasporto"))
    importo_totale_lordo_salvato = _to_num(ordine.get("importo"))
    
    if "importo_articoli" in ordine and ordine["importo_articoli"]:
        trasporto_incluso = ordine.get("trasporto_incluso", True)
        if trasporto_incluso:
            return importo_articoli_lordo_salvato / 1.22
        else:
            return (importo_articoli_lordo_salvato / 1.22) + (importo_trasporto_lordo_salvato / 1.22)
    else:
        return importo_totale_lordo_salvato / 1.22

def _get_netto_ordine(ordine):
    return _get_ordine_costo_effettivo_netto(ordine)

import json
def get_indirizzi_cantiere(client_id):
    if not client_id:
        return []
    client_data = load_client(client_id)
    if not client_data:
        return []
    return client_data.get("indirizzi_cantiere", [])

from jinja2.runtime import Undefined
def money_ui(value):
    if value is None or isinstance(value, Undefined) or str(value).strip() == "": return ""
    try:
        val = float(value)
        return f"€ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value

from models import BASE_DIR
from pathlib import Path
MARGINI_FILE = Path(BASE_DIR) / "data" / "config_margini.json"

DEFAULT_MARGINI = {
    "fasce": [
        {
            "key": "economici", 
            "descrizione": "Fascia Bassa ", 
            "max_costo": 500, # <-- NUOVO LIMITE
            "pallini": {"verde": 80, "arancione": 70, "rosso": 60}, # <-- Ricarichi più alti
            "regole_colore": {
                "verde_min": 75, "verde_max": 85,        # Target Margine ~43-46%
                "arancione_min1": 65, "arancione_max1": 74,
                "arancione_min2": 86, "arancione_max2": 95
            }
        },
        {
            "key": "standard", 
            "descrizione": "Fascia Standard ", 
            "max_costo": 1500, # <-- NUOVO LIMITE
            "pallini": {"verde": 67, "arancione": 55, "rosso": 45}, # <-- Ricarichi medi (il tuo target 40% margine)
           "regole_colore": {
                "verde_min": 62, "verde_max": 72,        # Target Margine ~38-42%
                "arancione_min1": 55, "arancione_max1": 61,
                "arancione_min2": 73, "arancione_max2": 80
            }
        },
        {
            "key": "costosi", 
            "descrizione": "Fascia Alta ", 
            "max_costo": 999999,
            "pallini": {"verde": 50, "arancione": 40, "rosso": 30}, # <-- Ricarichi più bassi
           "regole_colore": {
                "verde_min": 45, "verde_max": 55,        # Target Margine ~31-35%
                "arancione_min1": 38, "arancione_max1": 44,
                "arancione_min2": 56, "arancione_max2": 65
            }
        }
    ]
}
def log_pdf_event(quote_id, message_type, message):
    """Logs an event related to PDF generation."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{quote_id}] [{message_type.upper()}] {message}\n"
    try:
        with open(PDF_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"ERRORE: Impossibile scrivere nel log PDF: {e}")

def load_margini_config():
    """Carica la configurazione dei margini da file, unendo i default per sicurezza."""
    config = DEFAULT_MARGINI
    if MARGINI_FILE.exists():
        try:
            with MARGINI_FILE.open("r", encoding="utf-8") as f:
                saved_config = json.load(f)
            # Logica di unione per garantire che tutte le chiavi esistano
            if "fasce" in saved_config:
                for i, fascia in enumerate(config["fasce"]):
                    saved_fascia = next((sf for sf in saved_config["fasce"] if sf.get("key") == fascia["key"]), None)
                    if saved_fascia:
                        fascia["max_costo"] = saved_fascia.get("max_costo", fascia["max_costo"])
                        fascia["pallini"] = saved_fascia.get("pallini", fascia["pallini"])
        except (json.JSONDecodeError, IOError):
            return DEFAULT_MARGINI # In caso di errore, torna ai default
    return config

