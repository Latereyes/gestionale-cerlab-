from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
import datetime

consegne_bp = Blueprint('consegne', __name__)

from utils import (
    _to_num, get_indirizzi_cantiere,
    load_quote, save_quote, get_all_quotes, 
    login_required, role_required, aggiorna_stato_avanzamento, 
    aggiorna_stato_consegna_globale, get_flat_righe_edili
)
from models import SessionLocal, Preventivo, Bolla



def dashboard_consegne():
    """Mostra i preventivi che hanno articoli da consegnare."""
    preventivi_da_consegnare = []
    tutti_i_preventivi = get_all_quotes()

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p: continue

        if p.get("stato") not in ["Confermato", "Parz. Consegnato"]:
            continue

        ha_articoli_da_consegnare = False
        righe = p.get("righe", [])
        
        for r in righe:
            if not r.get("articolo", "").strip() or r.get("unt", "").strip().upper() == "S":
                continue

            stato_cons = r.get("stato_consegna", "Da Ordinare")
            if stato_cons in ["Pronto", "Parz. Consegnato"]:
                ha_articoli_da_consegnare = True
                break
        
        if ha_articoli_da_consegnare:
            preventivi_da_consegnare.append(p)

    return render_template("dashboard_consegne.html",
                           title="Dashboard Consegne",
                           preventivi=preventivi_da_consegnare)

@consegne_bp.route("/consegne")
@login_required
def route_dashboard_consegne():
    return dashboard_consegne()

@consegne_bp.route("/consegna/<quote_id>")
@login_required
def gestione_consegna(quote_id):
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for('dashboard'))

    righe_preventivo = p.get("righe", [])
    
    ordini_fornitore = p.get("ordini_fornitore", [])

    def is_ordine_completato(ordine):
        return bool(ordine.get("data_arrivo", "").strip())
        
    for riga in righe_preventivo:
        riga["in_ordine_completato"] = False
        
    for ordine in ordini_fornitore:
        if is_ordine_completato(ordine):
            for idx in ordine.get("indici_righe", []):
                if 0 <= idx < len(righe_preventivo):
                    righe_preventivo[idx]["in_ordine_completato"] = True

    bolle = p.get("bolle", [])
    righe_edili = get_flat_righe_edili(p)

    indirizzi = get_indirizzi_cantiere(p.get("id_cliente"))
    return render_template("gestione_consegna.html", 
        title="Gestione Consegna", p=p, 
        righe_edili=righe_edili,
        bolle=bolle, indirizzi_cantiere=indirizzi
    )

@consegne_bp.route("/consegna/<quote_id>/marca-pronto", methods=["POST"])
@login_required
def marca_pronto(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici = [int(i) for i in request.form.getlist("selected_items[]")]
    tipo = request.form.get("tipo", "standard") # 'standard' o 'edile'

    if tipo == "standard":
        righe = p.get("righe", [])
        for i in indici:
            if 0 <= i < len(righe):
                righe[i]["stato_consegna"] = "Pronto"
    elif tipo == "edile":
        righe_edili = p.get("righe_edili", [])
        for i in indici:
            if 0 <= i < len(righe_edili):
                righe_edili[i]["stato_consegna"] = "Pronto"

    aggiorna_stato_consegna_globale(p)
    save_quote(quote_id, p)
    return jsonify({"success": True})


@consegne_bp.route("/consegna/<quote_id>/marca-consegnato", methods=["POST"])
@login_required
def marca_consegnato(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici = [int(i) for i in request.form.getlist("selected_items[]")]
    tipo = request.form.get("tipo", "standard") # 'standard' o 'edile'

    if tipo == "standard":
        righe = p.get("righe", [])
        for i in indici:
            if 0 <= i < len(righe):
                righe[i]["stato_consegna"] = "Consegnato"
    elif tipo == "edile":
        righe_edili = p.get("righe_edili", [])
        for i in indici:
            if 0 <= i < len(righe_edili):
                righe_edili[i]["stato_consegna"] = "Consegnato"

    aggiorna_stato_consegna_globale(p)
    save_quote(quote_id, p)
    return jsonify({"success": True})


@consegne_bp.route("/consegna/<quote_id>/annulla-stato", methods=["POST"])
@login_required
def annulla_stato_consegna(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    item_index = int(request.form.get("item_index"))
    tipo = request.form.get("tipo", "standard")

    if tipo == "standard":
        righe = p.get("righe", [])
        if 0 <= item_index < len(righe):
            in_ordine = any(item_index in o.get("indici_righe", []) for o in p.get("ordini_fornitore", []))
            righe[item_index]["stato_consegna"] = "In Ordine" if in_ordine else "Da Ordinare"
    elif tipo == "edile":
        righe_edili = p.get("righe_edili", [])
        if 0 <= item_index < len(righe_edili):
            righe_edili[item_index]["stato_consegna"] = "Da Ordinare" # L'edile non ha ordini fornitore

    aggiorna_stato_consegna_globale(p)
    save_quote(quote_id, p)
    return jsonify({"success": True})


def get_new_bolla_id(preventivo_data):
    """Genera un ID progressivo per la bolla, specifico per il preventivo."""
    now = datetime.datetime.now()
    year = now.strftime('%Y')
    
    bolle_esistenti = preventivo_data.get("bolle", [])
    if not bolle_esistenti:
        return f"BOLLA-{year}-1"

    max_num = 0
    for bolla in bolle_esistenti:
        try:
            num = int(bolla.get("id", "").split('-')[2])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            continue
    
    return f"BOLLA-{year}-{max_num + 1}"

@consegne_bp.route("/consegna/<quote_id>/crea-bolla", methods=["POST"])
@login_required
def crea_bolla(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        return jsonify({"success": False, "error": "Non disponi delle autorizzazioni per eseguire questa azione."})
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici_righe_bolla = [int(i) for i in request.form.getlist("selected_items[]")]
    indirizzo_cantiere_id = request.form.get("indirizzo_cantiere_id")

    if not indici_righe_bolla:
        return jsonify({"success": False, "error": "Nessun articolo selezionato per la bolla"})

    bolla_id = get_new_bolla_id(p)
    
    db_session = SessionLocal()
    nuova_bolla = Bolla(
        id=bolla_id,
        preventivo_id=quote_id,
        data=datetime.date.today().strftime('%Y-%m-%d'),
        indirizzo_cantiere_id=indirizzo_cantiere_id or "",
        indici_righe=indici_righe_bolla
    )
    db_session.add(nuova_bolla)
    db_session.commit()
    db_session.close()

    p = load_quote(quote_id)
    save_quote(quote_id, p)

    return jsonify({
        "success": True, 
        "next_url": url_for('export_bolla_pdf', quote_id=quote_id, bolla_id=bolla_id)
    })
