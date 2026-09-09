import os

input_file = "gestionale.py"
routes_file = "routes/preventivi.py"

with open(input_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

def get_block(start_line, end_line):
    return "".join(lines[start_line-1:end_line])

# Define the ranges for each route based on decorators to the end of the function
to_move = [
    (1742, 1769), # /preventivo-edile/nuovo/<client_id>
    (1770, 1787), # /preventivo-edile/edit/<quote_id>
    (1788, 1893), # /salva-righe-edili/<quote_id>
    (1894, 1921), # /preventivo/nuovo/<client_id>
    (1922, 1928), # /preventivo/edit/<quote_id>
    (1929, 2169), # /salva-righe/<quote_id>
    (2170, 2226), # /preventivo/<quote_id>/clona
    (2716, 2744), # /preventivo/<quote_id>/sblocca
    (2745, 2763), # /preventivo/<quote_id>/invia
    (2764, 2794), # /preventivo/<quote_id>/conferma
    (2795, 2821), # /preventivo/<quote_id>/annulla
    (3585, 3673)  # /preventivo/analisi/<quote_id>
]

routes_content = """from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
import datetime
import copy

preventivi_bp = Blueprint('preventivi', __name__)

from utils import (
    load_quote, save_quote, load_client, get_new_quote_id, get_all_quotes, 
    login_required, role_required, aggiorna_stato_consegna_globale, 
    aggiorna_stato_pagamento_globale, aggiorna_stato_avanzamento
)
# Importeremo funzioni mancanti da gestionale
from gestionale import (
    money_ui, get_flat_righe_edili, _to_num, _fmt_price, _calculate_profits_from_quote
)
"""

for start, end in to_move:
    block = get_block(start, end)
    # Replace @app.route with @preventivi_bp.route
    block = block.replace("@app.route", "@preventivi_bp.route")
    routes_content += block + "\n"

with open(routes_file, "w", encoding="utf-8") as f:
    f.write(routes_content)

# Delete from bottom to top
to_delete = sorted(to_move, reverse=True)
for start, end in to_delete:
    del lines[start-1:end]

# Insert blueprint registration in gestionale.py right before `if __name__ == "__main__":`
# Let's find the main block
main_idx = -1
for i, line in enumerate(lines):
    if line.startswith('if __name__ == "__main__":'):
        main_idx = i
        break

if main_idx != -1:
    bp_registration = "\n# Registrazione Blueprint Preventivi\nfrom routes.preventivi import preventivi_bp\napp.register_blueprint(preventivi_bp)\n\n"
    lines.insert(main_idx, bp_registration)

with open(input_file, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Estrazione rotte completata con successo!")
