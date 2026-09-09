import os

input_file = "gestionale.py"
routes_file = "routes/ordini.py"

with open(input_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

def get_block(start_line, end_line):
    return "".join(lines[start_line-1:end_line])

to_move = [
    (3138, 3188), # /ordini (dashboard)
    (1744, 1899), # /preventivo/<quote_id>/conferma-ordine
    (1900, 1947), # /preventivo/<quote_id>/salva-ordine
    (1948, 1996), # /preventivo/<quote_id>/modifica-ordine
    (1997, 2018), # /preventivo/<quote_id>/svincola-articolo
    (2019, 2040), # /preventivo/<quote_id>/aggiungi-a-ordine
    (2041, 2056), # /preventivo/<quote_id>/elimina-ordine
    (2067, 2111), # /preventivo/<quote_id>/allega-a-ordine
]

routes_content = """from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
import datetime
import uuid

ordini_bp = Blueprint('ordini', __name__)

from utils import (
    load_quote, save_quote, get_all_quotes, 
    login_required, role_required, aggiorna_stato_avanzamento, aggiorna_stato_consegna_globale
)
from models import SessionLocal, Preventivo, Ordine

from gestionale import (
    _to_num, _get_ordine_costo_effettivo_netto, _get_netto_ordine, money_ui
)
"""

for start, end in to_move:
    block = get_block(start, end)
    block = block.replace("@app.route", "@ordini_bp.route")
    routes_content += block + "\n"

with open(routes_file, "w", encoding="utf-8") as f:
    f.write(routes_content)

# Delete from bottom to top
to_delete = sorted(to_move, reverse=True)
for start, end in to_delete:
    del lines[start-1:end]

# Insert blueprint registration in gestionale.py right before `if __name__ == "__main__":`
main_idx = -1
for i, line in enumerate(lines):
    if line.startswith('if __name__ == "__main__":'):
        main_idx = i
        break

if main_idx != -1:
    bp_registration = "\n# Registrazione Blueprint Ordini\nfrom routes.ordini import ordini_bp\napp.register_blueprint(ordini_bp)\n\n"
    lines.insert(main_idx, bp_registration)

with open(input_file, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Estrazione rotte ordini completata con successo!")
