import os

input_file = "gestionale.py"
routes_file = "routes/consegne.py"

with open(input_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

def get_block(start_line, end_line):
    return "".join(lines[start_line-1:end_line])

to_move = [
    (3189, 3247), # /consegne (dashboard)
    (3248, 3294), # /consegna/<quote_id>
    (3295, 3331), # /consegna/<quote_id>/marca-pronto
    (3332, 3383), # /consegna/<quote_id>/marca-consegnato
    (3384, 3453), # /consegna/<quote_id>/annulla-stato
    (3454, 3477), # get_new_bolla_id helper
    (3478, 3517), # /consegna/<quote_id>/crea-bolla
]

routes_content = """from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
import datetime

consegne_bp = Blueprint('consegne', __name__)

from utils import (
    load_quote, save_quote, get_all_quotes, 
    login_required, role_required, aggiorna_stato_avanzamento, 
    aggiorna_stato_consegna_globale, get_flat_righe_edili
)
from models import SessionLocal, Preventivo, Bolla

from gestionale import _to_num, get_indirizzi_cantiere

"""

for start, end in to_move:
    block = get_block(start, end)
    block = block.replace("@app.route", "@consegne_bp.route")
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
    bp_registration = "\n# Registrazione Blueprint Consegne\nfrom routes.consegne import consegne_bp\napp.register_blueprint(consegne_bp)\n\n"
    lines.insert(main_idx, bp_registration)

with open(input_file, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Estrazione rotte consegne completata con successo!")
