from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
import datetime
import copy
import json
import os
from pathlib import Path

preventivi_bp = Blueprint('preventivi', __name__)

from utils import (
    load_quote, save_quote, load_client, get_new_quote_id, get_all_quotes, 
    login_required, role_required, aggiorna_stato_consegna_globale, 
    aggiorna_stato_pagamento_globale, aggiorna_stato_avanzamento, get_flat_righe_edili,
    load_margini_config
)

# Costanti necessarie (importate da gestionale o ridefinite)
APP_NAME = "Gestionale Preventivi"
from models import BASE_DIR as _BASE_DIR
DATA_DIR = Path(_BASE_DIR) / "data"
try:
    with open(os.path.join(_BASE_DIR, "data", "comuni.json"), "r", encoding="utf-8") as _f:
        GEO_DATA = json.load(_f)
except FileNotFoundError:
    GEO_DATA = []

@preventivi_bp.route("/preventivo-edile/nuovo/<client_id>")
@login_required
@role_required('amministratore', 'ceo')
def nuovo_preventivo_edile(client_id):
    client_data = load_client(client_id)
    if not client_data:
        flash("Cliente non trovato.")
        return redirect(url_for("dashboard"))

    venditore_sigla = session.get("user_sigla", "XX")
    full_name = session.get("user_name", "Sconosciuto")
    
    # Genera ID con prefisso ED (Edile) per tenerlo separato
    now = datetime.datetime.now()
    new_quote_id = f"EDIL-{venditore_sigla.upper()}-{now.strftime('%d%m%y%H%M')}"
    
    p = EMPTY_STATE.copy()
    p.update(client_data)
    p["numero"] = new_quote_id
    p["tipo_preventivo"] = "edile"
    p["venditore"] = full_name
    p["data"] = now.strftime('%Y-%m-%d')
    # Inizializziamo con una sezione predefinita vuota
    p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": []}] 
    
    save_quote(new_quote_id, p)
    return redirect(url_for("preventivi.editor_preventivo_edile", quote_id=new_quote_id))


@preventivi_bp.route("/preventivo-edile/edit/<quote_id>")
@login_required
@role_required('amministratore', 'ceo')
def editor_preventivo_edile(quote_id):
    p = load_quote(quote_id)
    if p is None: 
        flash(f"Preventivo Edile '{quote_id}' non trovato.")
        return redirect(url_for("dashboard"))
    
    # Migrazione/Inizializzazione per compatibilità con vecchi preventivi
    if "sezioni_edili" not in p:
        if "righe_edili" in p and p["righe_edili"]:
            p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": p["righe_edili"]}]
        else:
            p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": []}]
    
    return render_template("editor_edile.html", title=f"Edile - {quote_id}", p=p, geo_data=GEO_DATA)


@preventivi_bp.route("/salva-righe-edili/<quote_id>", methods=["POST"])
@login_required
@role_required('amministratore', 'ceo')
def salva_righe_edili(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Non trovato"}), 404
    
    form = request.form
    
    # Inizializzazione di sicurezza per prevenire KeyError su vecchi preventivi
    if "sezioni_edili" not in p:
        if "righe_edili" in p:
            p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": p.get("righe_edili", [])}]
        else:
            p["sezioni_edili"] = []

    if form.get("is_locked") != 'true':
        p["data"] = form.get("data", p.get("data"))
        p["referente"] = form.get("referente", p.get("referente"))
        p["riepilogo"] = form.get("riepilogo", p.get("riepilogo", ""))
        p["no_iva"] = True if form.get("no_iva") else False 

    nuove_sezioni = []
    pat = re.compile(r"^s\[(\d+)\](?:\[titolo\]|\[costi_vivi_json\]|\[r\]\[(\d+)\]\[(.+)\])$")
    
    sez_map = {}
    for key, val in form.items():
        m = pat.match(key)
        if m:
            s_idx = int(m.group(1))
            sez_map.setdefault(s_idx, {"titolo": "", "costi_vivi_json": "[]", "righe": {}})
            
            if "[titolo]" in key:
                sez_map[s_idx]["titolo"] = val
            elif "[costi_vivi_json]" in key:
                sez_map[s_idx]["costi_vivi_json"] = val
            else:
                r_idx = int(m.group(2))
                field = m.group(3)
                sez_map[s_idx]["righe"].setdefault(r_idx, {})[field] = val

    if sez_map:
        for s_i in sorted(sez_map.keys()):
            r_list = []
            righe_dic = sez_map[s_i]["righe"]
            for r_i in sorted(righe_dic.keys()):
                r_list.append(righe_dic[r_i])
            nuove_sezioni.append({"titolo": sez_map[s_i]["titolo"], "costi_vivi_json": sez_map[s_i].get("costi_vivi_json", "[]"), "righe": r_list})
        p["sezioni_edili"] = nuove_sezioni

    # 1. Recupera azioni di AGGIUNTA dall'URL (Query String via formaction)
    action_add_section = request.args.get("add_section")
    action_add_row_to = request.args.get("add_row")
    
    # 2. Recupera azioni di ELIMINAZIONE dal corpo del FORM (via JS hidden inputs)
    del_s_idx = form.get("delete_section")
    del_r_idx = form.get("delete_row")
    del_whole_s_idx = form.get("delete_whole_section")

    if action_add_section == "1":
        p["sezioni_edili"].append({"titolo": "Nuova Sezione", "righe": []})
    
    elif action_add_row_to is not None:
        try:
            s_idx = int(action_add_row_to)
            if 0 <= s_idx < len(p["sezioni_edili"]):
                p["sezioni_edili"][s_idx]["righe"].append({
                    "articolo": "", 
                    "prezzo_vendita": "0", 
                    "iva_pct": "10", 
                    "costo_stimato": "0"
                })
        except ValueError:
            pass

    elif del_s_idx is not None and del_r_idx is not None:
        try:
            s_idx = int(del_s_idx)
            r_idx = int(del_r_idx)
            if 0 <= s_idx < len(p["sezioni_edili"]):
                if 0 <= r_idx < len(p["sezioni_edili"][s_idx]["righe"]):
                    p["sezioni_edili"][s_idx]["righe"].pop(r_idx)
        except ValueError:
            pass

    elif del_whole_s_idx is not None:
        try:
            s_idx = int(del_whole_s_idx)
            if 0 <= s_idx < len(p["sezioni_edili"]):
                p["sezioni_edili"].pop(s_idx)
        except ValueError:
            pass
    
    # --- FINE LOGICA CORRETTA AZIONI ---

    # Sincronizzazione dell'elenco piatto righe_edili per ripulire il JSON dai dati eliminati
    flat_righe = []
    for sezione in p.get("sezioni_edili", []):
        for riga in sezione.get("righe", []):
            flat_righe.append(riga)
    p["righe_edili"] = flat_righe
        
    save_quote(quote_id, p)
    if form.get("is_ajax") == "1": return jsonify({"success": True})
    return redirect(url_for("preventivi.editor_preventivo_edile", quote_id=quote_id))


@preventivi_bp.route("/preventivo/nuovo/<client_id>")
@login_required
def nuovo_preventivo(client_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    client_data = load_client(client_id)
    if not client_data:
        flash("Cliente non trovato.")
        return redirect(url_for("dashboard"))

    venditore_sigla = session.get("user_sigla", "XX")
    # Prendiamo sia lo username che il nome completo dalla sessione
    username = session.get("user_id", "sconosciuto")
    full_name = session.get("user_name", "Sconosciuto")
    
    new_quote_id = get_new_quote_id(venditore_sigla)
    p = EMPTY_STATE.copy()
    p.update(client_data)
    p["numero"] = new_quote_id
    p["data"] = datetime.date.today().strftime('%Y-%m-%d')
    # Salviamo lo USERNAME nel campo "venditore"
    p["venditore"] = full_name
    p["righe"] = []
    p["default_iva_switch"] = "22"
    
    save_quote(new_quote_id, p)
    return redirect(url_for("preventivi.editor_preventivo", quote_id=new_quote_id))

@preventivi_bp.route("/preventivo/edit/<quote_id>")
@login_required
def editor_preventivo(quote_id):
    p = load_quote(quote_id)
    if p is None: flash(f"Preventivo '{quote_id}' non trovato."); return redirect(url_for("dashboard"))
    margini_config = load_margini_config()
    return render_template("editor.html", title=f"Modifica {p.get('numero', 'Preventivo')}", app_name=APP_NAME, data_dir=str(DATA_DIR.resolve()), p=p, geo_data=GEO_DATA, margini_config=margini_config)

@preventivi_bp.route("/salva-righe/<quote_id>", methods=["POST"])
@login_required
def salva_righe(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        flash(f"Preventivo '{quote_id}' non trovato.")
        return redirect(url_for("dashboard"))
    
    form = request.form
    iva_selezionata_dal_form = form.get("default-iva-switch", "22")
    header_keys = ["venditore", "numero", "data", "cliente", "regione", "regione_nome", "indirizzo", "comune", "provincia", "email", "telefono", "referente", "fee_pct", "rag_sociale", "p_iva", "codice_univoco" , "cap", "default_iva_switch"]
    for key in header_keys:
        if key in form: p[key] = form.get(key, "")
    p["default_iva_switch"] = iva_selezionata_dal_form    
    p.pop("iva_pct", None)

    # --- MODIFICA CHIAVE PER LA PERSISTENZA DEI DATI ---
    # Non ricostruiamo le righe da zero. Invece, le aggiorniamo.
    righe_esistenti = p.get("righe", [])
    nuove_righe_mappate = {}
    pat = re.compile(r"^r\[(\d+)\]\[(.+)\]$")
    for key, val in form.items():
        m = pat.match(key)
        if m:
            i, field = int(m.group(1)), m.group(2)
            if field == 'spese_incasso' and val:
                # Se riceviamo ancora il vecchio campo, lo trattiamo come 'extra'
                nuove_righe_mappate.setdefault(i, {})['extra'] = val
            else:
                nuove_righe_mappate.setdefault(i, {})[field] = val
    
    righe_aggiornate = []
    num_righe_form = len(nuove_righe_mappate)
    
    for i in range(max(len(righe_esistenti), num_righe_form)):
        # Prendi la riga esistente se c'è, altrimenti un dizionario vuoto
        riga = righe_esistenti[i] if i < len(righe_esistenti) else {}
        # Aggiorna la riga con i nuovi dati dal form, se presenti
        if i in nuove_righe_mappate:
            riga.update(nuove_righe_mappate[i])
        righe_aggiornate.append(riga)

    p["righe"] = righe_aggiornate
    # --- FINE MODIFICA CHIAVE ---

    def _to_num(x, default=0.0):
        if x is None: return float(default)
        s = re.sub(r"[€%\s]", "", str(x));
        if not s: return float(default)
        if "," in s and "." in s: s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
        s = s.replace(",", ".");
        try: return float(s)
        except ValueError: return float(default)
    def _fmt_price(n: float) -> str: return f"{float(n):.2f}".replace(".", ",")
    
    fee_effettiva = _to_num(p.get("fee_pct")) / 100
    if fee_effettiva > 0: fee_effettiva *= 1.166
    
    imponibili_per_iva = {}
    tot_imponibile_negozio_globale = 0.0
    # Rimuoviamo le righe che non hanno più un articolo
    p["righe"] = [r for r in p["righe"] if str(r.get("articolo", "")).strip()]

    for r in p["righe"]:
        qt = _to_num(r.get("qt", 0)); incasso = _to_num(r.get("spese_incasso", 0))
        extra = _to_num(r.get("extra", 0))
        ric = _to_num(r.get("ricarico_pct", 0)) / 100; trasp = _to_num(r.get("costo_trasporto", 0))
        unt = r.get("unt", "").strip().upper(); iva_riga_pct = _to_num(r.get("iva_pct", 22))
        # Variabili che popoleremo nell'if/else
        tot_unit_imponibile = 0.0
        tot_riga_imponibile = 0.0
        tot_riga_negozio = 0.0

        if unt == "S":
            # --- INIZIO BLOCCO MODIFICATO ---
            qt = 1.0 # Forza la quantità a 1
            r["qt"] = "1"
            
            # Leggiamo i valori
            ric = _to_num(r.get("ricarico_pct", 0)) / 100
            prezzo_catalogo_val = _to_num(r.get("prezzo_catalogo"))

            if ric > 0:
                # CASO 1: Ricarico PRESENTE (P.Catalogo è un COSTO)
                costo_negozio = prezzo_catalogo_val
                # Applichiamo fee E ricarico
                prezzo_con_fee_e_ricarico = costo_negozio * (1 + fee_effettiva) * (1 + ric)
                
                tot_unit_imponibile = round(prezzo_con_fee_e_ricarico, 2)
                tot_riga_imponibile = tot_unit_imponibile * qt
                tot_riga_negozio = costo_negozio * qt
                prezzo_con_margini_o_fee = prezzo_con_fee_e_ricarico
            
            else:
                # CASO 2: Ricarico ASSENTE (P.Catalogo è GUADAGNO PURO)
                prezzo_servizio = prezzo_catalogo_val
                # Applichiamo solo la fee (se presente)
                prezzo_con_fee = prezzo_servizio * (1 + fee_effettiva) 
            
                tot_unit_imponibile = round(prezzo_con_fee, 2)
                tot_riga_imponibile = tot_unit_imponibile * qt
                tot_riga_negozio = 0.0 # Costo negozio è zero
                prezzo_con_margini_o_fee = prezzo_con_fee

            # Azzera solo i campi non pertinenti per S
            r["costo_trasporto"] = "0"
            r["extra"] = "0"
            r["spese_incasso"] = "0"
            r["s1"] = "0"
            r["s2"] = "0"
            r["s3"] = "0"
            # --- FINE BLOCCO MODIFICATO ---

        else:
            # CASO 2: È UN ARTICOLO NORMALE (PZ, MQ, ML)
            prezzo_scontato = (_to_num(r.get("prezzo_catalogo")) * (1 - _to_num(r.get("s1"))/100) * (1 - _to_num(r.get("s2"))/100) * (1 - _to_num(r.get("s3"))/100))
            prezzo_con_margini = prezzo_scontato * (1 + fee_effettiva) * (1 + ric)
            trasp_con_margini = trasp * (1 + fee_effettiva) * (1 + ric)
            extra_con_margini = extra * (1 + fee_effettiva) * (1 + ric)
            
            subtotale_unitario = 0
            if unt == "MQ": subtotale_unitario = prezzo_con_margini + trasp_con_margini
            elif unt in ["PZ", "ML"]: subtotale_unitario = prezzo_con_margini + (trasp_con_margini / qt if qt > 0 else 0)
            else: subtotale_unitario = prezzo_con_margini
            
            extra_per_unita_con_margini = (extra_con_margini / qt if qt > 0 else 0)
            tot_unit_imponibile = subtotale_unitario + extra_per_unita_con_margini
            tot_unit_imponibile = round(tot_unit_imponibile, 2)
            tot_riga_imponibile = tot_unit_imponibile * qt

            # Aggiungi questo blocco dentro al ciclo, dopo il calcolo di 'tot_riga_imponibile'
            costo_unitario_negozio = prezzo_scontato
            if unt == "MQ":
                costo_unitario_negozio += trasp
            elif unt in ["PZ", "ML"]:
                costo_unitario_negozio += (trasp / qt if qt > 0 else 0)
            costo_unitario_negozio += (incasso / qt if qt > 0 else 0)

            costo_unitario_negozio += (extra / qt if qt > 0 else 0)
            costo_unitario_negozio = round(costo_unitario_negozio, 2)
            tot_riga_negozio = costo_unitario_negozio * qt
            prezzo_con_margini_o_fee = prezzo_con_margini
        
        tot_imponibile_negozio_globale += tot_riga_negozio
            
        iva_unitaria_val = tot_unit_imponibile * (iva_riga_pct / 100)
        tot_iva_riga_val = tot_riga_imponibile * (iva_riga_pct / 100)

        r["prezzo"] = _fmt_price(prezzo_con_margini_o_fee)
        r["tot_prezzo_unitario"] = _fmt_price(tot_unit_imponibile)
        r["tot_prezzo"] = _fmt_price(tot_riga_imponibile)
        r["iva_pct"] = f"{int(iva_riga_pct)} %"
        r["iva_unitaria"] = _fmt_price(iva_unitaria_val) 
        r["tot_iva_riga"] = _fmt_price(tot_iva_riga_val)

        aliquota_key = str(int(iva_riga_pct))
        imponibili_per_iva.setdefault(aliquota_key, 0.0)
        imponibili_per_iva[aliquota_key] += tot_riga_imponibile

    #  blocco di salvataggio dei totali 
    tot_imponibile_cliente_globale = sum(imponibili_per_iva.values())
    tot_iva_globale = sum(valore * (int(aliquota)/100) for aliquota, valore in imponibili_per_iva.items())

    p["imponibili_iva"] = {k: _fmt_price(v) for k, v in imponibili_per_iva.items()}
    p["tot_iva_dettaglio"] = {k: _fmt_price(v * (int(k)/100)) for k, v in imponibili_per_iva.items()}

    # Salvataggio dei nuovi totali
    p["tot_imponibile_negozio"] = _fmt_price(tot_imponibile_negozio_globale)
    p["tot_imponibile_cliente"] = _fmt_price(tot_imponibile_cliente_globale)
    p["tot_iva"] = _fmt_price(tot_iva_globale)
    p["totale"] = _fmt_price(tot_imponibile_cliente_globale + tot_iva_globale)

    # Calcolo e salvataggio ricarico medio
    totale_guadagno = tot_imponibile_cliente_globale - tot_imponibile_negozio_globale
    if tot_imponibile_negozio_globale > 0:
        ricarico_medio_pct = (totale_guadagno / tot_imponibile_negozio_globale) * 100
    else:
        ricarico_medio_pct = 0.0
    p["ricarico_medio_pct"] = f"{ricarico_medio_pct:.2f}".replace('.', ',') + " %"

    # Rimuoviamo la vecchia chiave per pulizia
    p.pop("tot_imponibile", None)
    
    # --- MODIFICA: Imposta flag no_iva manuale ---
    # Se il preventivo è bloccato (is_locked='true'), i checkbox disabilitati non vengono inviati dal browser.
    # In questo caso NON dobbiamo toccare il valore esistente (altrimenti si resetterebbe a False).
    # Aggiorniamo il valore SOLO se l'editor è sbloccato.
    if form.get("is_locked") != 'true':
        p["no_iva"] = True if form.get("no_iva") else False
    # --- FINE MODIFICA ---

    aggiorna_stato_consegna_globale(p)
    aggiorna_stato_pagamento_globale(p)
    aggiorna_stato_avanzamento(p)
    
    # Gestione eliminazione riga (deve lavorare con la lista aggiornata)
    if request.args.get('delete_row') is not None:
        idx = int(request.args.get('delete_row'))
        if 0 <= idx < len(p["righe"]):
            p["righe"].pop(idx)
        anchor = 'ancora-fine-righe'
# Gestione aggiunta riga
    elif request.args.get('add_row') == '1':
        # --- INIZIO MODIFICA: Leggi l'IVA di default dal form ---
        
        # 1. Leggi il valore dal selettore (es. "22"), con un default di sicurezza
        default_iva_value = iva_selezionata_dal_form
        
        # 2. Crea il dizionario base per la nuova riga
        new_row = {k: "" for k in ["articolo", "unt", "qt", "prezzo_catalogo", "costo_trasporto", "spese_incasso", "s1", "s2", "s3", "ricarico_pct"]}
        
        # 3. Imposta l'iva_pct in base al valore letto, formattandolo
        new_row["iva_pct"] = f"{default_iva_value} %"
        
        # 4. Aggiungi la nuova riga al preventivo
        p["righe"].append(new_row)
        anchor = 'ancora-fine-righe'
        # --- FINE MODIFICA ---
    else: 
        flash("Preventivo Salvato.")
        anchor = 'ancora-fine-righe'
    
    save_quote(quote_id, p)
    
    if request.form.get("is_ajax") == "1": return jsonify({"success": True})
    return redirect(url_for("preventivi.editor_preventivo", quote_id=quote_id, _anchor=anchor))

def _to_num(x, default=0.0):
    if x is None or isinstance(x, Undefined) or str(x).strip() == "": return float(default)
    try:
        s = str(x).strip().replace("€", "").replace("%", "").strip()
        if "," in s and "." in s:
            s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
        s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return float(default)
    

@preventivi_bp.route("/preventivo/<quote_id>/clona")
@login_required
def clona_preventivo(quote_id):
    """
    Crea una copia esatta di un preventivo esistente (Edile o Standard),
    gestendo correttamente la struttura a sezioni.
    """
    # 1. Carica il preventivo originale
    p_originale = load_quote(quote_id)
    if not p_originale:
        return jsonify({"success": False, "error": "Preventivo originale non trovato."})

    # 2. Crea una copia profonda
    p_clonato = copy.deepcopy(p_originale)

    # 3. Genera nuovo ID
    venditore_sigla = session.get("user_sigla", "XX")
    nuovo_id = get_new_quote_id(venditore_sigla)
    
    p_clonato["numero"] = nuovo_id
    p_clonato["data"] = datetime.date.today().strftime('%Y-%m-%d')
    p_clonato["stato"] = "Bozza"
    p_clonato["is_locked"] = False
    
    # 4. Copia esplicita della struttura a sezioni (fondamentale per Edili)
    if "sezioni_edili" in p_originale:
        p_clonato["sezioni_edili"] = copy.deepcopy(p_originale["sezioni_edili"])
    
    # 5. Pulizia dati specifici del vecchio preventivo
    campi_da_rimuovere = [
        "pdf_attivo", "storico_pdf", "pagamenti", "bolle", 
        "fatture_allegate", "ordini_fornitore", "data_conferma", "data_chiusura"
    ]
    for campo in campi_da_rimuovere:
        p_clonato.pop(campo, None)
    
    # Resetta stato consegna righe (sia standard che edili)
    if "righe" in p_clonato:
        for r in p_clonato["righe"]:
            r.pop("stato_consegna", None); r.pop("bolla_id", None); r.pop("data_consegna", None)
            
    if "sezioni_edili" in p_clonato:
        for sez in p_clonato["sezioni_edili"]:
            for r in sez.get("righe", []):
                r.pop("stato_consegna", None); r.pop("bolla_id", None); r.pop("data_consegna", None)

    # 6. Salva
    save_quote(nuovo_id, p_clonato)

    # 7. Restituisci JSON strutturato correttamente
    return jsonify({
        "success": True, 
        "vecchio_id": quote_id, 
        "nuovo_id": nuovo_id,
        "new_url": url_for('preventivi.editor_preventivo_edile', quote_id=nuovo_id) if p_clonato.get("tipo_preventivo") == "edile" else url_for('preventivi.editor_preventivo', quote_id=nuovo_id)
    })


@preventivi_bp.route("/preventivo/<quote_id>/sblocca", methods=["POST"])

@login_required
def sblocca_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        return jsonify({"success": False, "error": "Preventivo non trovato"})

    password = request.json.get("password")
    if not password:
        return jsonify({"success": False, "error": "Password non fornita"})

    users = load_users()
    user = next((u for u in users if u["username"] == session["user_id"]), None)

    if user and check_password_hash(user["password_hash"], password):
        # Password corretta: sblocca, imposta a Bozza E ANNULLA IL PDF ATTIVO
        p["stato"] = "Bozza"
        p["is_locked"] = False
        p.pop("pdf_attivo", None) # <-- MODIFICA CHIAVE: Rimuove il riferimento al PDF attivo

        save_quote(quote_id, p)
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Password errata. Riprova."})
    

@preventivi_bp.route("/preventivo/<quote_id>/invia", methods=["POST"])
@login_required
def invia_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    p["stato"] = "Inviato"
    p["is_locked"] = True
    save_quote(quote_id, p)
    flash("Preventivo impostato come 'Inviato' e bloccato.", "success")
    return redirect(url_for("preventivi.editor_preventivo", quote_id=quote_id))    

# --- File: gestionale.py (intorno alla riga 1680) ---


@preventivi_bp.route("/preventivo/<quote_id>/conferma", methods=["POST"])
@login_required
def conferma_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    p["stato"] = "Confermato"
    p["is_locked"] = True
    p["data_conferma"] = datetime.date.today().strftime('%Y-%m-%d')

    # Se Edile, marca tutto come Pronto per Consegna automaticamente
    if p.get("tipo_preventivo") == "edile":
        for riga in p.get("righe_edili", []):
            if riga.get("stato_consegna") != "Consegnato":
                riga["stato_consegna"] = "Pronto per Consegna"
                riga["data_arrivo_in_house"] = datetime.date.today().strftime('%Y-%m-%d')

    # --- BLOCCO AGGIUNTO ---
    # Aggiorniamo lo stato di pagamento, che passerà a "Da Pagare" se era "Non Definito"
    aggiorna_stato_pagamento_globale(p)


    save_quote(quote_id, p)
    flash("Preventivo confermato e bloccato.", "success")
    return redirect(url_for("preventivi.editor_preventivo", quote_id=quote_id))


@preventivi_bp.route("/preventivo/<quote_id>/annulla", methods=["POST"])
@login_required
def annulla_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    p["stato"] = "Annullato"
    p["is_locked"] = True
    
    # --- RIGA AGGIUNTA ---
    p["data_annullamento"] = datetime.date.today().strftime('%Y-%m-%d')
    # --- FINE RIGA AGGIUNTA ---

    save_quote(quote_id, p)
    flash("Preventivo annullato.", "warning")
    return redirect(url_for("preventivi.editor_preventivo", quote_id=quote_id))

# ===============================================
# === NUOVE ROUTE PER GESTIONE CONSEGNE/BOLLE ===
# ===============================================


@preventivi_bp.route("/preventivo/analisi/<quote_id>")
@login_required
@role_required('amministratore', 'ceo')
def analisi_preventivo(quote_id):
    from gestionale import _calculate_profits_from_quote
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))

    # 1. Calcola Ricavi
    imponibile_cliente = _to_num(p.get("tot_imponibile_cliente"))
    iva_cliente = _to_num(p.get("tot_iva"))
    totale_cliente = _to_num(p.get("totale"))

    # 2. Calcola Costi
    costi_preventivati = _to_num(p.get("tot_imponibile_negozio"))
    
    costi_effettivi_netti = sum(
        _get_ordine_costo_effettivo_netto(o)
        for o in p.get("ordini_fornitore", [])
    )

    # Se è edile, integriamo il costo stimato manuale nei costi effettivi
    if p.get("tipo_preventivo") == "edile":
        costi_effettivi_netti += sum(_to_num(r.get("costo_stimato")) for r in p.get("righe_edili", []))
    
    # Recuperiamo i profitti stimati dal calcolo riga per riga
    profitti = _calculate_profits_from_quote(p)

    # --- NUOVO CALCOLO FEE SEMPLIFICATO ---
    # La fee è calcolata semplicemente come % sull'imponibile cliente totale
    fee_pct = _to_num(p.get("fee_pct"))
    fee_semplice_valore = imponibile_cliente * (fee_pct / 100)
    # --------------------------------------

    # Calcolo Utile Effettivo
    utile_netto_effettivo = imponibile_cliente - costi_effettivi_netti

    # 4. Assembla i dati di analisi
    analisi = {
        'imponibile_cliente': imponibile_cliente,
        'iva_cliente': iva_cliente,
        'totale_cliente': totale_cliente,
        'costi_preventivati': costi_preventivati,
        'costi_effettivi_netti': costi_effettivi_netti if costi_effettivi_netti > 0 else 0.0,
        
        'utile_netto_stimato': profitti.get('profitto', 0.0), 
        'utile_netto_effettivo': utile_netto_effettivo,
        
        # Usiamo il valore calcolato semplicemente
        'fee_versata': fee_semplice_valore, 
        
        'scostamento_costi': 0.0,
        'margine_lordo_pct': 0.0, 
        'utile_netto_effettivo_pct': 0.0, 
        'giorni_per_chiusura': 'N/D'
    }

    # 5. Calcola Redditività e Scostamento
    # Scostamento = Costi Preventivati - Costi Effettivi Netti
    if analisi['costi_effettivi_netti'] > 0: 
        analisi['scostamento_costi'] = analisi['costi_preventivati'] - analisi['costi_effettivi_netti']

    if imponibile_cliente > 0:
        # Margine Lordo % (basato su costo preventivato)
        margine_lordo = imponibile_cliente - costi_preventivati
        analisi['margine_lordo_pct'] = (margine_lordo / imponibile_cliente) * 100

    # Utile Effettivo %
    if imponibile_cliente > 0:
        analisi['utile_netto_effettivo_pct'] = (analisi['utile_netto_effettivo'] / imponibile_cliente) * 100

    # 6. Calcola Tempo Chiusura
    data_conferma_str = p.get("data_conferma")
    data_chiusura_str = p.get("data_chiusura")
    if p.get("stato") == "Chiuso" and data_conferma_str and data_chiusura_str:
        try:
            data_conferma_dt = datetime.datetime.strptime(data_conferma_str, '%Y-%m-%d').date()
            data_chiusura_dt = datetime.datetime.strptime(data_chiusura_str, '%Y-%m-%d').date()
            giorni = (data_chiusura_dt - data_conferma_dt).days
            if giorni >= 0:
                 analisi['giorni_per_chiusura'] = giorni
        except (ValueError, TypeError): pass

    return render_template("analisi_preventivo.html",
        title=f"Analisi Preventivo {p.get('numero')}",
        p=p,
        analisi=analisi
    )

