from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
import datetime
import uuid
from pathlib import Path
from models import BASE_DIR
import os
ALLEGATI_DIR = os.path.join(BASE_DIR, 'data', 'preventivi')
from werkzeug.utils import secure_filename
from sqlalchemy.orm.attributes import flag_modified

ordini_bp = Blueprint('ordini', __name__)

from utils import (
    load_quote, save_quote, get_all_quotes, 
    login_required, role_required, aggiorna_stato_avanzamento, aggiorna_stato_consegna_globale,
    _to_num, _get_ordine_costo_effettivo_netto, _get_netto_ordine, get_indirizzi_cantiere
)
from models import SessionLocal, Preventivo, Ordine


def dashboard_ordini():
    """Pagina che elenca i preventivi con ordini fornitore da gestire."""
    preventivi_con_ordini = []
    tutti_i_preventivi = get_all_quotes()

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p: continue

        if p.get("stato") in ["Bozza", "Inviato", "Chiuso", "Annullato"]:
            continue

        indici_righe_valide = {
            i for i, r in enumerate(p.get("righe", [])) 
            if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"
        }
        
        indici_gia_ordinati = set()
        ordini_fornitore = p.get("ordini_fornitore", [])
        for ordine in ordini_fornitore:
            indici_gia_ordinati.update(ordine.get("indici_righe", []))

        articoli_da_ordinare_count = len(indici_righe_valide - indici_gia_ordinati)
        p["articoli_da_ordinare_count"] = articoli_da_ordinare_count

        articoli_in_attesa_conferma = 0
        ordini_in_attesa = [o for o in ordini_fornitore if not o.get("numero_conferma", "").strip()]
        for ordine in ordini_in_attesa:
            articoli_in_attesa_conferma += len(ordine.get("indici_righe", []))
        p["articoli_in_attesa_conferma"] = articoli_in_attesa_conferma

        if articoli_da_ordinare_count > 0 or articoli_in_attesa_conferma > 0:
            preventivi_con_ordini.append(p)

    return render_template("dashboard_ordini.html", 
        title="Dashboard Ordini Fornitore",
        preventivi=preventivi_con_ordini
    )

@ordini_bp.route("/ordini")
@login_required
def route_dashboard_ordini():
    return dashboard_ordini()

@ordini_bp.route("/preventivo/<quote_id>/conferma-ordine")
@login_required
def conferma_ordine(quote_id):
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard"))
    
    # Non salviamo qui gli ID mancanti perché sono già nel DB come UUID validi
    # e la migrazione li ha fixati.

    righe_preventivo = p.get("righe", [])
    tutti_gli_indici_validi = {
        i for i, r in enumerate(righe_preventivo) 
        if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"}

    def _get_shop_cost(riga):
        prezzo_scontato = (_to_num(riga.get("prezzo_catalogo")) * (1 - _to_num(riga.get("s1"))/100) * (1 - _to_num(riga.get("s2"))/100) * (1 - _to_num(riga.get("s3"))/100))
        return prezzo_scontato * _to_num(riga.get("qt", 1))

    def _get_transport_cost(riga):
        trasp_riga = _to_num(riga.get("costo_trasporto", 0))
        qt_riga = _to_num(riga.get("qt", 1))
        unt_riga = riga.get("unt", "").strip().upper()
        if unt_riga == "MQ":
            return trasp_riga * qt_riga
        return trasp_riga

    indici_gia_ordinati = set()
    tutti_gli_ordini = p.get("ordini_fornitore", [])
    ordini_confermati = []
    ordini_in_attesa = []

    for ordine in tutti_gli_ordini:
        items_in_ordine = []
        for item_index in ordine.get("indici_righe", []):
            if 0 <= item_index < len(righe_preventivo):
                riga = righe_preventivo[item_index].copy() 
                riga["original_index"] = item_index
                riga["costo_presunto_articolo"] = _get_shop_cost(riga)
                items_in_ordine.append(riga)
                indici_gia_ordinati.add(item_index)
        
        ordine["articoli"] = items_in_ordine 
        costo_netto_articoli = sum(item["costo_presunto_articolo"] for item in items_in_ordine)
        costo_trasporto_preventivato = sum(_get_transport_cost(item) for item in items_in_ordine)
        
        trasporto_incluso = ordine.get("trasporto_incluso", True) 
        importo_articoli_lordo_salvato = _to_num(ordine.get("importo_articoli"))
        importo_trasporto_lordo_salvato = _to_num(ordine.get("importo_trasporto"))
        importo_totale_lordo_salvato = _to_num(ordine.get("importo")) 
        
        costo_effettivo_articoli_imponibile = 0.0
        costo_effettivo_trasporto_imponibile = 0.0

        if "importo_articoli" in ordine and ordine["importo_articoli"]:
            ordine["importo_articoli_form"] = ordine.get("importo_articoli", "0")
            ordine["importo_trasporto_form"] = ordine.get("importo_trasporto", "0")
            
            if trasporto_incluso:
                costo_effettivo_articoli_imponibile = importo_articoli_lordo_salvato / 1.22
                costo_effettivo_trasporto_imponibile = 0.0 
            else:
                costo_effettivo_articoli_imponibile = importo_articoli_lordo_salvato / 1.22
                if importo_trasporto_lordo_salvato > 0:
                    costo_effettivo_trasporto_imponibile = importo_trasporto_lordo_salvato / 1.22
                else:
                    costo_effettivo_trasporto_imponibile = costo_trasporto_preventivato
        else:
            costo_effettivo_articoli_imponibile = importo_totale_lordo_salvato / 1.22
            costo_effettivo_trasporto_imponibile = costo_trasporto_preventivato 
            ordine["importo_articoli_form"] = ordine.get("importo", "0") 
            ordine["importo_trasporto_form"] = f"{(costo_effettivo_trasporto_imponibile * 1.22):.2f}".replace(".", ",")
            trasporto_incluso = False 

        ordine["trasporto_incluso_flag"] = trasporto_incluso
        costo_totale_effettivo_imponibile = costo_effettivo_articoli_imponibile + costo_effettivo_trasporto_imponibile
        importo_totale_lordo_usato = (costo_effettivo_articoli_imponibile * 1.22) + (costo_effettivo_trasporto_imponibile * 1.22)
        iva_calcolata = importo_totale_lordo_usato - costo_totale_effettivo_imponibile

        ordine["costo_effettivo_articoli_imponibile"] = costo_effettivo_articoli_imponibile
        ordine["costo_effettivo_trasporto_imponibile"] = costo_effettivo_trasporto_imponibile
        ordine["costo_totale_effettivo_imponibile"] = costo_totale_effettivo_imponibile
        ordine["iva_calcolata"] = iva_calcolata
        ordine["costo_netto_articoli"] = costo_netto_articoli
        ordine["costo_trasporto_preventivato"] = costo_trasporto_preventivato
        ordine["costo_totale_preventivato"] = costo_netto_articoli + costo_trasporto_preventivato

        if ordine.get("numero_conferma", "").strip():
            ordini_confermati.append(ordine)
        else:
            ordini_in_attesa.append(ordine)

    indici_non_ordinati = sorted(list(tutti_gli_indici_validi - indici_gia_ordinati))
    righe_non_ordinate = []
    for item_index in indici_non_ordinati:
        riga = righe_preventivo[item_index]
        riga["original_index"] = item_index
        riga["costo_presunto_articolo"] = _get_shop_cost(riga)
        righe_non_ordinate.append(riga)

    totale_presunto_globale = sum(
        _get_shop_cost(r) + _get_transport_cost(r)
        for i, r in enumerate(righe_preventivo) if i in tutti_gli_indici_validi
    )
    totale_effettivo_globale = sum(o.get("costo_totale_effettivo_imponibile", 0) for o in tutti_gli_ordini)

    return render_template("conferma_ordine.html", 
        title="Gestione Ordini", p=p,
        righe_non_ordinate=righe_non_ordinate,
        ordini_confermati=ordini_confermati, 
        ordini_in_attesa=ordini_in_attesa,   
        totale_presunto=totale_presunto_globale,
        totale_effettivo=totale_effettivo_globale
    )

@ordini_bp.route("/preventivo/<quote_id>/salva-ordine", methods=["POST"])
@login_required
def salva_ordine(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    form_data = request.form
    importo_articoli_val = _to_num(form_data.get("importo_articoli"))
    importo_trasporto_val = _to_num(form_data.get("importo_trasporto"))
    importo_totale_val = importo_articoli_val + importo_trasporto_val 
    iva_calcolata = importo_totale_val - (importo_totale_val / 1.22)

    db_session = SessionLocal()
    nuovo_ordine = Ordine(
        ordine_id=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        preventivo_id=quote_id,
        data_ordine=datetime.date.today().strftime('%Y-%m-%d'),
        azienda=form_data.get("azienda"),
        numero_conferma=form_data.get("numero_conferma"),
        importo=f"{importo_totale_val:.2f}".replace(".", ","), 
        importo_articoli=form_data.get("importo_articoli"),
        importo_trasporto=form_data.get("importo_trasporto"),
        iva_ordine=iva_calcolata,
        data_arrivo=form_data.get("data_arrivo"),
        indici_righe=[int(i) for i in form_data.getlist("indici_righe[]")]
    )
    db_session.add(nuovo_ordine)
    db_session.commit()
    db_session.close()

    p = load_quote(quote_id)
    aggiorna_stato_avanzamento(p)
    if form_data.get("numero_conferma"):
        aggiorna_stato_consegna_globale(p)
    save_quote(quote_id, p)
    
    return jsonify({"success": True})

@ordini_bp.route("/preventivo/<quote_id>/modifica-ordine", methods=["POST"])
@login_required
def modifica_ordine(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    form_data = request.form
    ordine_id_da_modificare = form_data.get("ordine_id")
    
    db_session = SessionLocal()
    ordine = db_session.query(Ordine).filter_by(ordine_id=ordine_id_da_modificare).first()
    
    if ordine:
        trasporto_incluso = form_data.get("trasporto_incluso") == 'true'
        importo_articoli_val = _to_num(form_data.get("importo_articoli"))
        importo_trasporto_val = _to_num(form_data.get("importo_trasporto"))
        importo_totale_val = importo_articoli_val + importo_trasporto_val 
        iva_calcolata = importo_totale_val - (importo_totale_val / 1.22)

        ordine.azienda = form_data.get("azienda")
        ordine.numero_conferma = form_data.get("numero_conferma")
        ordine.importo = f"{importo_totale_val:.2f}".replace(".", ",")
        ordine.importo_articoli = form_data.get("importo_articoli")
        ordine.importo_trasporto = form_data.get("importo_trasporto")
        ordine.iva_ordine = iva_calcolata
        ordine.data_arrivo = form_data.get("data_arrivo")
        
        db_session.commit()
        db_session.close()

        p = load_quote(quote_id)
        aggiorna_stato_consegna_globale(p)
        save_quote(quote_id, p)
        flash("Ordine fornitore modificato con successo.")
        return jsonify({"success": True})
    
    db_session.close()
    return jsonify({"success": False, "error": "L'ordine originale non è stato trovato nel DB."})

@ordini_bp.route("/preventivo/<quote_id>/svincola-articolo", methods=["POST"])
@login_required
def svincola_articolo(quote_id):
    data = request.json
    ordine_id_target = data.get("ordine_id")
    item_index = int(data.get("item_index"))

    db_session = SessionLocal()
    ordine = db_session.query(Ordine).filter_by(ordine_id=ordine_id_target).first()
    
    if not ordine:
        db_session.close()
        return jsonify({"success": False, "error": "Ordine non trovato"})

    indici = ordine.indici_righe.copy() if ordine.indici_righe else []
    if item_index in indici:
        indici.remove(item_index)
        ordine.indici_righe = indici
        flag_modified(ordine, "indici_righe")
        db_session.commit()
        db_session.close()
        
        p = load_quote(quote_id)
        save_quote(quote_id, p)
        return jsonify({"success": True})
    
    db_session.close()
    return jsonify({"success": False, "error": "Articolo non trovato nell'ordine"})

@ordini_bp.route("/preventivo/<quote_id>/aggiungi-a-ordine", methods=["POST"])
@login_required
def aggiungi_a_ordine(quote_id):
    form_data = request.form
    target_ordine_id = form_data.get("target_ordine_id")
    indici_da_aggiungere = [int(i) for i in form_data.getlist("indici_righe[]")]

    db_session = SessionLocal()
    ordine = db_session.query(Ordine).filter_by(ordine_id=target_ordine_id).first()
    
    if not ordine:
        db_session.close()
        return jsonify({"success": False, "error": "Ordine di destinazione non trovato"})
    
    indici = ordine.indici_righe.copy() if ordine.indici_righe else []
    nuovi_indici = sorted(list(set(indici + indici_da_aggiungere)))
    ordine.indici_righe = nuovi_indici
    flag_modified(ordine, "indici_righe")
    
    db_session.commit()
    db_session.close()
    
    p = load_quote(quote_id)
    save_quote(quote_id, p)
    return jsonify({"success": True})

@ordini_bp.route("/preventivo/<quote_id>/elimina-ordine", methods=["POST"])
@login_required
def elimina_ordine(quote_id):
    ordine_id_da_eliminare = request.form.get("ordine_id")
    
    db_session = SessionLocal()
    ordine = db_session.query(Ordine).filter_by(ordine_id=ordine_id_da_eliminare).first()
    
    if ordine:
        db_session.delete(ordine)
        db_session.commit()
        db_session.close()
        
        p = load_quote(quote_id)
        save_quote(quote_id, p)
        return jsonify({"success": True})
    
    db_session.close()
    return jsonify({"success": False, "error": "Ordine non trovato"})

@ordini_bp.route("/preventivo/<quote_id>/allega-a-ordine", methods=["POST"])
@login_required
def allega_a_ordine(quote_id):
    """Gestisce l'upload di un allegato per uno specifico ordine fornitore."""
    # NOTA: Questa logica per ora salva i file su disco e in JSON, 
    # andrà adattata se usiamo tabella AllegatiOrdine, ma per ora teniamola invariata, 
    # poiché era salvata nell'ordine. 
    # Aggiungeremo una colonna 'allegati' all'ordine se necessario, 
    # per ora commentata per non crashare dato che manca il DB sync di allegati in models.py
    
    flash("Funzionalità temporaneamente disattivata durante la migrazione al DB.", "error")
    return redirect(request.referrer)
